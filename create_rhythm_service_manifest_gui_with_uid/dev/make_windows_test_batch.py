#!/usr/bin/env python3
"""
Build the input batch for test_exe_windows_gui.sh.

Writes into --out-dir:
  zips/study_01.zip .. study_03.zip   one synthetic, GDPR-strict DICOM each,
                                      every one with its own StudyInstanceUID
  template.xlsx                       one row per ZIP, retain_after_project
                                      set to yes / no / (empty)
  expected.json                       what the manifest's items must contain

Needs pydicom and openpyxl (use ct_upload_platform/.venv/bin/python).
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RETAIN_VALUES = [("yes", True), ("no", False), ("", None)]
PROTOCOL_ID = "5f6a1e9c-6b1a-4b7e-9c2d-8a1e5f6a1e9c"  # syntactically valid; never sent to a server


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    zips = out / "zips"
    zips.mkdir(parents=True, exist_ok=True)

    fixtures = _load("generate_test_fixtures", HERE / "generate_test_fixtures.py")
    tool = fixtures._load_tool_module()

    import openpyxl

    columns = list(tool.REQUIRED_COLUMNS) + list(getattr(tool, "OPTIONAL_COLUMNS", []))
    if "retain_after_project" not in columns:
        print("ERROR: this tool version has no retain_after_project column", file=sys.stderr)
        return 1

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "metadata"
    ws.append(columns)
    expected = []
    for i, (cell, value) in enumerate(RETAIN_VALUES, start=1):
        name = f"study_{i:02d}.zip"
        fixtures.build_dicom_zip(zips / name)
        row = {
            "filename": name, "site_code": "S001", "protocol_id": PROTOCOL_ID,
            "patient_weight_kg": 20 + i, "patient_age_years": 5 + i,
            "ctdivol_mgy": 3.5, "dlp_mgy_cm": 110, "image_quality": "GOOD",
            "retain_after_project": cell,
        }
        ws.append([row[c] for c in columns])
        expected.append({"filename": name, "retain_after_project": value})
    wb.save(out / "template.xlsx")
    (out / "expected.json").write_text(json.dumps(expected, indent=2))
    print(f"Wrote {len(expected)} studies, template.xlsx and expected.json to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
