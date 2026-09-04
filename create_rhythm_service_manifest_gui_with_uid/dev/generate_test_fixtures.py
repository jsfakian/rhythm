#!/usr/bin/env python3
"""
Build synthetic test fixtures for build_windows_exe.sh's smoke test and
test_exe_automated_upload.sh's end-to-end pipeline test:
  - one GDPR-strict-compliant DICOM file, zipped (no PatientID/PatientName/
    StudyDate — matches the "remove" directive the real anonymization tool
    uses, same fixture style as ct_upload_platform's own test suite)
  - one Excel metadata template, using the *real* required columns imported
    directly from the manifest tool script (so this can't silently drift
    out of sync with it)

By default site_code/protocol_id are throwaway values, enough to prove the
.exe runs and produces a schema-valid manifest (build_windows_exe.sh's use
case). Pass --protocol-id/--site-code to reference a real, already
registered CTProtocol instead, when the manifest this produces needs to
actually be accepted by the live server (test_exe_automated_upload.sh's
use case).

Not shipped to partners.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import uuid
import zipfile
from pathlib import Path

# build_windows_exe.sh copies this file flat into its work dir, alongside
# (not below) the tool script — so this looks one level up only when run
# from its committed location in dev/, and next to it otherwise.
_CANDIDATES = [
    Path(__file__).resolve().parent / "create_rhythm_server_assigned_manifest_gui_with_uid.py",
    Path(__file__).resolve().parent.parent / "create_rhythm_server_assigned_manifest_gui_with_uid.py",
]
TOOL_SCRIPT = next((p for p in _CANDIDATES if p.is_file()), _CANDIDATES[0])


def _load_tool_module():
    spec = importlib.util.spec_from_file_location("rhythm_manifest_tool", TOOL_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_dicom_zip(zip_path: Path) -> None:
    from pydicom.dataset import Dataset, FileDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid

    meta = Dataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(str(zip_path), {}, file_meta=meta, preamble=b"\0" * 128)
    # Older pydicom (2.x, the newest the build image's Python 3.7 can
    # install) writes Implicit VR by default unless these are set
    # explicitly, regardless of what file_meta.TransferSyntaxUID declares
    # — producing a file whose header and encoding disagree. pydicom's own
    # reader tolerates that (auto-detects and warns), but Orthanc's
    # stricter STOW-RS parser correctly rejects it with 400. Newer pydicom
    # (3.x, what ct_upload_platform itself runs) infers this from
    # file_meta automatically, which is why this only surfaced once a
    # synthetic file generated here was actually pushed to a real Orthanc.
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    # Deliberately no PatientID/PatientName/StudyDate.

    dcm_path = zip_path.with_suffix(".dcm")
    ds.save_as(str(dcm_path))
    with zipfile.ZipFile(zip_path, "w") as z:
        z.write(dcm_path, arcname="slice.dcm")
    dcm_path.unlink()


def build_template_xlsx(
    xlsx_path: Path, columns: list[str], zip_filename: str, site_code: str, protocol_id: str
) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(columns)

    row = {
        "filename": zip_filename,
        "site_code": site_code,
        "protocol_id": protocol_id,
        "patient_weight_kg": 28.0,
        "patient_age_years": 8.0,
        "ctdivol_mgy": 18.4,
        "dlp_mgy_cm": 320.5,
        "image_quality": "Acceptable",
    }
    ws.append([row.get(col, "") for col in columns])
    wb.save(xlsx_path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True, help="Directory to write template.xlsx and zips/ into.")
    ap.add_argument("--site-code", default="S001", help="site_code to put in the template row.")
    ap.add_argument(
        "--protocol-id", default=None,
        help="protocol_id to put in the template row (default: a random UUID, for build_windows_exe.sh's "
             "purposes only — it never reaches a real server). Pass a real registered CTProtocol's id "
             "for an end-to-end test the server will actually accept.",
    )
    ap.add_argument("--zip-filename", default="smoke_test_study.zip")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    zips_dir = out_dir / "zips"
    (out_dir / "out").mkdir(parents=True, exist_ok=True)
    zips_dir.mkdir(parents=True, exist_ok=True)

    tool = _load_tool_module()

    protocol_id = args.protocol_id or str(uuid.uuid4())
    build_dicom_zip(zips_dir / args.zip_filename)
    build_template_xlsx(out_dir / "template.xlsx", tool.REQUIRED_COLUMNS, args.zip_filename, args.site_code, protocol_id)

    print(f"Wrote {zips_dir / args.zip_filename}")
    print(f"Wrote {out_dir / 'template.xlsx'} (site_code={args.site_code}, protocol_id={protocol_id})")


if __name__ == "__main__":
    sys.exit(main())
