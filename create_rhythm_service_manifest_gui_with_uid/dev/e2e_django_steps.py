"""
Django-side steps for test_exe_automated_upload.sh, run inside the live
`web` container via `manage.py shell < this_file`. Not shipped to partners.

Reads its mode and parameters from environment variables (piped-stdin
`manage.py shell` scripts don't get argv) and prints machine-parseable
`KEY=value` lines the orchestrating shell script greps for.

Modes (E2E_MODE):
  setup   — create a real CTProtocol (+ scanner + test user) tagged with
            E2E_TAG, in the live DB. Prints PROTOCOL_ID/SCANNER_ID/
            SITE_CODE/USERNAME/PASSWORD.
  drive   — force-login as that user and drive the *real* Automated
            Upload flow (validate-manifest -> chunked/init -> chunk ->
            complete) with the manifest/ZIP the .exe produced, poll the
            real Celery worker to completion, and verify the result
            matches what Manual Exam Entry would produce. Prints
            RESULT=PASS or RESULT=FAIL: <reason>.
  cleanup — delete every DB row and Orthanc study tagged with E2E_TAG.
            Self-contained: safe to run even if `drive` never ran or
            failed early, so the orchestrator can call it unconditionally
            on exit.
"""

import hashlib
import json
import os
import time

MODE = os.environ["E2E_MODE"]
TAG = os.environ["E2E_TAG"]


def _protocol_name():
    return f"e2e-exe-test {TAG}"


def _username():
    return f"e2eexe_{TAG}"


def setup():
    from django.contrib.auth.models import User
    from uploads.models import CTManufacturer, CTProtocol, CTScannerModel, CTScannerProfile, UserProfile

    site_code = "S001"
    mfr, _ = CTManufacturer.objects.get_or_create(name=f"e2e-exe-test mfr {TAG}", defaults={"is_active": True})
    model, _ = CTScannerModel.objects.get_or_create(manufacturer=mfr, name=f"e2e-exe-test scanner {TAG}", defaults={"is_active": True})
    scanner = CTScannerProfile.objects.create(
        manufacturer=mfr, scanner_model=model, detector_rows="256",
        site_code=site_code, created_by=_username(),
    )
    protocol = CTProtocol.objects.create(
        scanner=scanner,
        site_code=site_code,
        protocol_type="PEDIATRIC_HEAD",
        anatomical_region="Head",
        clinical_indication="Trauma",
        contrast="Non-contrast",
        examination_group="Group 4",
        age_group="30 kg - 50 kg",
        protocol_name=_protocol_name(),
    )
    password = "TestPass123!"
    user, _ = User.objects.get_or_create(username=_username(), defaults={"is_active": True})
    user.set_password(password)
    user.save()
    UserProfile.objects.update_or_create(user=user, defaults={"institution": "E2E Test", "site_code": site_code})

    print(f"PROTOCOL_ID={protocol.pk}")
    print(f"SCANNER_ID={scanner.pk}")
    print(f"SITE_CODE={site_code}")
    print(f"USERNAME={user.username}")
    print(f"PASSWORD={password}")


def drive():
    from django.test import Client
    from uploads.models import CTExamination, CTProtocol, StudyMapping, UploadJob

    username = os.environ["E2E_USERNAME"]
    manifest_path = os.environ["E2E_MANIFEST_PATH"]
    zip_path = os.environ["E2E_ZIP_PATH"]
    protocol_id = os.environ["E2E_PROTOCOL_ID"]
    scanner_id = os.environ["E2E_SCANNER_ID"]

    # Prints RESULT=FAIL and returns (not sys.exit()) — this runs inside
    # `manage.py shell`'s exec(), and the orchestrator determines pass/fail
    # by grepping stdout for RESULT=, not by this process's exit code.
    class _Bail(Exception):
        pass

    def fail(reason):
        print(f"RESULT=FAIL: {reason}")
        raise _Bail(reason)

    try:
        _drive(username, manifest_path, zip_path, protocol_id, scanner_id, fail)
    except _Bail:
        return


def _drive(username, manifest_path, zip_path, protocol_id, scanner_id, fail):
    from django.contrib.auth.models import User
    from django.test import Client
    from uploads.models import CTExamination, CTProtocol, StudyMapping, UploadJob

    try:
        user = User.objects.get(username=username)
    except User.DoesNotExist:
        fail(f"setup user {username!r} not found — did the setup step run?")

    with open(manifest_path, "r") as f:
        manifest = json.load(f)
    with open(zip_path, "rb") as f:
        zip_bytes = f.read()

    client = Client(SERVER_NAME="localhost")
    client.force_login(user)

    resp = client.get("/automated-upload/")
    if resp.status_code != 200:
        fail(f"GET /automated-upload/ -> {resp.status_code}")

    resp = client.post(
        "/api/v1/uploads/validate-manifest/",
        data=json.dumps({"manifest": manifest}),
        content_type="application/json",
    )
    body = resp.json()
    print(f"validate-manifest: {resp.status_code} {body}")
    if resp.status_code != 200 or not body.get("valid") or body.get("schema_version") != "v2":
        fail(f"manifest produced by the .exe did not validate: {body}")

    item = manifest["items"][0]
    resp = client.post(
        "/api/v1/uploads/chunked/init/",
        data=json.dumps({
            "filename": item["filename"], "total_size": len(zip_bytes),
            "chunk_size": 10 * 1024 * 1024, "batch": manifest.get("batch", ""),
            "manifest_item": item,
        }),
        content_type="application/json",
    )
    print(f"chunked/init: {resp.status_code} {resp.json()}")
    if resp.status_code != 201:
        fail(f"chunked/init failed: {resp.content}")
    session = resp.json()

    chunk_hash = hashlib.sha256(zip_bytes).hexdigest()
    resp = client.post(
        f"/api/v1/uploads/chunked/{session['session_id']}/chunk/?chunk_number=0&chunk_hash={chunk_hash}",
        data=zip_bytes, content_type="application/octet-stream",
    )
    print(f"chunk 0: {resp.status_code} {resp.json()}")
    if resp.status_code not in (200, 202):
        fail(f"chunk upload failed: {resp.content}")

    resp = client.post(
        f"/api/v1/uploads/chunked/{session['session_id']}/complete/",
        data=json.dumps({"file_hash": chunk_hash}), content_type="application/json",
    )
    print(f"complete: {resp.status_code} {resp.json()}")
    if resp.status_code != 200:
        fail(f"complete failed: {resp.content}")
    job_id = resp.json()["job_id"]

    job = None
    for _ in range(30):
        job = UploadJob.objects.get(id=job_id)
        if job.status in ("COMPLETE", "PARTIAL", "FAILED"):
            break
        time.sleep(1)
    print(f"job status: {job.status} error_report={job.error_report}")
    if job.status != "COMPLETE":
        fail(f"job did not complete: {job.status} {job.error_report}")

    exam = CTExamination.objects.filter(upload_job=job).first()
    if exam is None:
        fail("no CTExamination created for this job")
    protocol = CTProtocol.objects.get(pk=protocol_id)

    checks = [
        ("exam.protocol_id", str(exam.protocol_id), protocol_id),
        ("exam.scanner_id", str(exam.scanner_id), scanner_id),
        ("exam.anatomical_region", exam.anatomical_region, protocol.anatomical_region),
        ("exam.clinical_indication", exam.clinical_indication, protocol.clinical_indication),
        ("exam.contrast", exam.contrast, protocol.contrast),
        ("exam.protocol_type", exam.protocol_type, protocol.protocol_type),
        ("exam.examination_group", exam.examination_group, protocol.examination_group),
    ]
    mismatches = [f"{name}: got {got!r}, expected {expected!r}" for name, got, expected in checks if got != expected]
    if mismatches:
        fail("CTExamination does not match the protocol: " + "; ".join(mismatches))

    mapping = StudyMapping.objects.filter(upload_job=job).first()
    if mapping is None:
        fail("no StudyMapping created for this job")
    if not mapping.orthanc_study_id:
        fail("StudyMapping.orthanc_study_id is empty — Orthanc push did not record a study id")

    import requests
    from django.conf import settings
    r = requests.get(
        f"{settings.ORTHANC_BASE_URL}/dicom-web/studies/{mapping.orthanc_study_id}/series",
        auth=(settings.ORTHANC_USERNAME, settings.ORTHANC_PASSWORD), timeout=10,
    )
    if r.status_code != 200:
        fail(f"Orthanc DICOMweb lookup for {mapping.orthanc_study_id} -> {r.status_code}")

    print(f"rhythm_pseudo_id: {exam.rhythm_pseudo_id}")
    print(f"orthanc_study_id: {mapping.orthanc_study_id}")
    print("RESULT=PASS")


def cleanup():
    from django.contrib.auth.models import User
    from uploads.models import (
        CTExamination, CTManufacturer, CTProtocol, CTScannerModel,
        CTScannerProfile, StudyMapping, UploadJob,
    )

    mappings = StudyMapping.objects.filter(upload_job__uploader_id=_username())
    orthanc_study_ids = list(mappings.values_list("orthanc_study_id", flat=True))

    UploadJob.objects.filter(uploader_id=_username()).delete()
    CTExamination.objects.filter(created_by=_username()).delete()
    mappings.delete()
    CTProtocol.objects.filter(protocol_name=_protocol_name()).delete()
    CTScannerProfile.objects.filter(created_by=_username()).delete()
    CTScannerModel.objects.filter(name=f"e2e-exe-test scanner {TAG}").delete()
    CTManufacturer.objects.filter(name=f"e2e-exe-test mfr {TAG}").delete()
    User.objects.filter(username=_username()).delete()

    if orthanc_study_ids:
        import requests
        from django.conf import settings
        for study_uid in orthanc_study_ids:
            if not study_uid:
                continue
            r = requests.post(
                f"{settings.ORTHANC_BASE_URL}/tools/find",
                json={"Level": "Study", "Query": {"StudyInstanceUID": study_uid}},
                auth=(settings.ORTHANC_USERNAME, settings.ORTHANC_PASSWORD), timeout=10,
            )
            for oid in r.json() if r.status_code == 200 else []:
                requests.delete(
                    f"{settings.ORTHANC_BASE_URL}/studies/{oid}",
                    auth=(settings.ORTHANC_USERNAME, settings.ORTHANC_PASSWORD), timeout=10,
                )
    print("CLEANUP=DONE")


{"setup": setup, "drive": drive, "cleanup": cleanup}[MODE]()
