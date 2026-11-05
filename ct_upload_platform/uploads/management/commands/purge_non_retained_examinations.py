"""
End-of-project deletion of examinations without retention consent.

The Data Transfer Agreement requires deleting, at the end of the Grant
Agreement, every study the patient did not authorise for retention. Studies
marked DELETE and studies with no declaration at all are both deleted; only
studies explicitly marked RETAIN are kept.

For each examination to delete, this command removes every copy:
  * the study in Orthanc (all series and images),
  * StudyMapping / Image / Annotation rows, and the Patient row once unused,
  * the CTExamination row,
  * the UploadJob row (unless another examination still uses it),
  * the uploaded archive, its extracted copy and any Manual Entry study-set
    file, and the matching ChunkedUpload session row.
It then writes a STUDY_PURGED AuditLog entry (not attached to any job, so it
survives) and a per-site CSV report listing every repository study ID.

Safety:
  * Without --execute it only prints what would be deleted (dry run).
  * --execute also requires --expected-count N, the number shown by the dry
    run, so a changed or mistyped selection never deletes anything.
  * If Orthanc refuses a deletion, that examination is left untouched in the
    database and reported as FAILED, so it can be retried.

Usage:
  python manage.py purge_non_retained_examinations                 # dry run
  python manage.py purge_non_retained_examinations --site S001     # dry run, one site
  python manage.py purge_non_retained_examinations --execute --expected-count 42
"""

from __future__ import annotations

import csv
import os
import shutil
import uuid
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from uploads.models import (
    RETENTION_RETAIN,
    AuditLog,
    ChunkedUpload,
    CTExamination,
    Patient,
    StudyMapping,
)
from uploads.orthanc_client import OrthancQueryError, get_client


def _allowed_roots() -> list[Path]:
    roots = [settings.MEDIA_ROOT, settings.RAW_DATA_DIR, settings.PROCESSED_DATA_DIR]
    return [Path(r).resolve() for r in roots if r]


def _is_inside_allowed_root(path: Path) -> bool:
    """Only ever delete files inside the platform's own data directories,
    whatever path a database row happens to contain."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    return any(resolved == root or root in resolved.parents for root in _allowed_roots())


def _remove_path(path_str: str, removed: list[str]) -> None:
    if not path_str:
        return
    path = Path(path_str)
    if not path.exists() or not _is_inside_allowed_root(path):
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()
    removed.append(str(path))


class Command(BaseCommand):
    help = (
        "Delete every examination without retention consent (marked DELETE or "
        "not declared) from Orthanc, the database and disk. Dry run unless "
        "--execute --expected-count N is given."
    )

    def add_arguments(self, parser) -> None:
        parser.add_argument("--site", help="Limit to one site code, e.g. S001.")
        parser.add_argument("--execute", action="store_true", help="Actually delete (default: dry run).")
        parser.add_argument(
            "--expected-count", type=int,
            help="Required with --execute: the number of examinations the dry run reported.",
        )
        parser.add_argument(
            "--report-dir",
            help="Where to write per-site CSV reports (default: backups/purge_reports/<timestamp>/).",
        )
        parser.add_argument("--actor", default="system", help="Name recorded in the audit log.")

    def handle(self, *args, **options) -> None:
        qs = CTExamination.objects.exclude(retention_consent=RETENTION_RETAIN).select_related("upload_job")
        if options["site"]:
            qs = qs.filter(site_code__iexact=options["site"])
        exams = list(qs.order_by("site_code", "rhythm_pseudo_id"))
        retained = CTExamination.objects.filter(retention_consent=RETENTION_RETAIN)
        if options["site"]:
            retained = retained.filter(site_code__iexact=options["site"])

        by_site = Counter(e.site_code or "?" for e in exams)
        undeclared = sum(1 for e in exams if not e.retention_consent)
        self.stdout.write(f"Examinations to delete: {len(exams)} "
                          f"({len(exams) - undeclared} marked DELETE, {undeclared} not declared)")
        self.stdout.write(f"Examinations retained:  {retained.count()}")
        for site, n in sorted(by_site.items()):
            self.stdout.write(f"  {site}: {n}")

        if not options["execute"]:
            for e in exams:
                self.stdout.write(f"  would delete {e.rhythm_pseudo_id or e.pk} "
                                  f"[{e.site_code or '?'}] ({e.retention_consent or 'NOT_DECLARED'})")
            self.stdout.write(self.style.WARNING(
                f"Dry run: nothing deleted. To delete, re-run with "
                f"--execute --expected-count {len(exams)}"))
            return

        if options["expected_count"] is None:
            raise CommandError("--execute requires --expected-count (the number from the dry run).")
        if options["expected_count"] != len(exams):
            raise CommandError(
                f"--expected-count {options['expected_count']} does not match the "
                f"{len(exams)} examinations currently selected. Nothing deleted; run the dry run again."
            )

        report_dir = Path(options["report_dir"] or (
            Path(settings.BASE_DIR) / "backups" / "purge_reports" / timezone.now().strftime("%Y%m%d_%H%M%S")
        ))
        report_dir.mkdir(parents=True, exist_ok=True)

        orthanc = get_client()
        rows_by_site: dict[str, list[dict]] = {}
        failures = 0
        for exam in exams:
            row = self._purge_one(exam, orthanc, options["actor"])
            failures += row["result"] != "DELETED"
            rows_by_site.setdefault(exam.site_code or "UNKNOWN", []).append(row)

        for site, rows in rows_by_site.items():
            with open(report_dir / f"{site}.csv", "w", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

        self.stdout.write(f"Reports written to {report_dir}")
        if failures:
            raise CommandError(f"{failures} examination(s) could not be deleted; see the reports and re-run.")
        self.stdout.write(self.style.SUCCESS(f"Deleted {len(exams)} examination(s)."))

    def _purge_one(self, exam: CTExamination, orthanc, actor: str) -> dict:
        rid = exam.rhythm_pseudo_id
        job = exam.upload_job
        row = {
            "repository_study_id": rid or str(exam.pk),
            "site_code": exam.site_code,
            "retention_consent": exam.retention_consent or "NOT_DECLARED",
            "orthanc_studies_deleted": 0,
            "files_removed": 0,
            "result": "",
            "error": "",
            "deleted_at": "",
        }

        # Studies belonging to this examination. v2 keys the Patient by the
        # repository ID; a job's mappings count only when no other
        # examination shares that job.
        job_is_exclusive = bool(job) and not job.examinations.exclude(pk=exam.pk).exists()
        cond = Q(patient__pseudo_id=rid) if rid else Q(pk__in=[])
        if job_is_exclusive:
            cond |= Q(upload_job=job)
        mappings = list(StudyMapping.objects.filter(cond).select_related("patient"))

        # 1) Orthanc first: if it fails, keep the DB rows so a re-run can retry.
        try:
            for m in mappings:
                if m.orthanc_study_id and orthanc.delete_study(m.orthanc_study_id):
                    row["orthanc_studies_deleted"] += 1
        except OrthancQueryError as exc:
            row["result"] = "FAILED"
            row["error"] = f"Orthanc: {exc}"
            self.stderr.write(f"  FAILED {row['repository_study_id']}: {row['error']}")
            return row

        # 2) Files on disk.
        removed: list[str] = []
        if exam.study_set_file:
            _remove_path(exam.study_set_file.path, removed)
        if job_is_exclusive:
            _remove_path(job.tar_temp_path, removed)
            _remove_path(str(Path(settings.PROCESSED_DATA_DIR) / str(job.id)), removed)
        row["files_removed"] = len(removed)

        # 3) Database, atomically, plus a surviving audit record.
        with transaction.atomic():
            patient_ids = {m.patient_id for m in mappings}
            StudyMapping.objects.filter(pk__in=[m.pk for m in mappings]).delete()  # cascades Image/Annotation
            Patient.objects.filter(pk__in=patient_ids, study_mappings__isnull=True).delete()
            if rid:
                Patient.objects.filter(pseudo_id=rid, study_mappings__isnull=True).delete()
            session_id = _session_id(job.tar_temp_path) if job_is_exclusive else ""
            if session_id:
                ChunkedUpload.objects.filter(id=session_id).delete()
            exam.delete()
            if job_is_exclusive:
                job.delete()  # also removes that job's own audit rows
            AuditLog.objects.create(
                upload_job=None,
                event_type="STUDY_PURGED",
                actor_id=actor,
                detail={
                    "repository_study_id": rid,
                    "site_code": row["site_code"],
                    "retention_consent": row["retention_consent"],
                    "orthanc_studies_deleted": row["orthanc_studies_deleted"],
                    "files_removed": row["files_removed"],
                },
            )
        row["result"] = "DELETED"
        row["deleted_at"] = timezone.now().isoformat()
        return row


def _session_id(archive_path: str) -> str:
    """Chunked uploads are assembled as raw_data/<uploader>/<session_id>.<ext>.
    Returns the session UUID, or '' when the archive name is not one."""
    name = os.path.basename(archive_path or "")
    for ext in (".tar.gz", ".tar.bz2"):
        if name.endswith(ext):
            name = name[: -len(ext)]
            break
    else:
        name = os.path.splitext(name)[0]
    try:
        return str(uuid.UUID(name))
    except ValueError:
        return ""
