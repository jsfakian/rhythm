#!/usr/bin/env python3
"""
Build synthetic test fixtures for build_windows_exe.sh's smoke test:
  - one GDPR-strict-compliant DICOM file, zipped (no PatientID/PatientName/
    StudyDate — matches the "remove" directive the real anonymization tool
    uses, same fixture style as ct_upload_platform's own test suite)
  - one Excel metadata template, using the *real* required columns imported
    directly from the manifest tool script (so this can't silently drift
    out of sync with it)

Not shipped to partners — used only by build_windows_exe.sh to prove a
freshly built .exe actually runs and produces a schema-valid manifest,
not just that it exists.
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


def build_template_xlsx(xlsx_path: Path, columns: list[str], zip_filename: str) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(columns)

    row = {
        "filename": zip_filename,
        "site_code": "S001",
        "protocol_id": str(uuid.uuid4()),
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
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    zips_dir = out_dir / "zips"
    (out_dir / "out").mkdir(parents=True, exist_ok=True)
    zips_dir.mkdir(parents=True, exist_ok=True)

    tool = _load_tool_module()

    zip_filename = "smoke_test_study.zip"
    build_dicom_zip(zips_dir / zip_filename)
    build_template_xlsx(out_dir / "template.xlsx", tool.REQUIRED_COLUMNS, zip_filename)

    print(f"Wrote {zips_dir / zip_filename}")
    print(f"Wrote {out_dir / 'template.xlsx'}")


if __name__ == "__main__":
    sys.exit(main())
