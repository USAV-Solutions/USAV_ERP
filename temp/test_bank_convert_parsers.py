#!/usr/bin/env python3
"""Quick validation script for bank-convert parsers against sample PDFs."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTIL_PATH = ROOT / "Backend" / "app" / "modules" / "accounting" / "bank_convert_utils.py"

SAMPLES: dict[str, Path] = {
    "boa_v1": ROOT / "temp" / "sample_BoA.pdf",
    "boa_v2": ROOT / "temp" / "sample_BoA2.pdf",
    "boa_v3": ROOT / "temp" / "sample_BoA3.pdf",
    "amazon": ROOT / "temp" / "sample_amazon.pdf",
    "apple": ROOT / "temp" / "sample_apple.pdf",
    "chase": ROOT / "temp" / "sample_chase.pdf",
}


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("bank_convert_utils", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    try:
        module = load_module(UTIL_PATH)
    except ModuleNotFoundError as exc:
        print(f"ERROR: missing dependency: {exc}")
        print("Install backend parser deps first (example: pandas, pdfplumber).")
        return 2

    parsers = getattr(module, "BANK_CONVERT_PARSERS", {})
    failed = False

    print("Bank parser validation start")
    for format_type, sample_path in SAMPLES.items():
        if format_type not in parsers:
            print(f"FAIL {format_type}: parser missing")
            failed = True
            continue
        if not sample_path.exists():
            print(f"FAIL {format_type}: sample file missing at {sample_path}")
            failed = True
            continue

        try:
            pdf_bytes = sample_path.read_bytes()
            dataframe = parsers[format_type](pdf_bytes)
            row_count = len(dataframe)
            columns = ", ".join(list(dataframe.columns))
            print(f"PASS {format_type}: rows={row_count} cols=[{columns}]")
        except Exception as exc:
            print(f"FAIL {format_type}: {type(exc).__name__}: {exc}")
            failed = True

    if failed:
        print("Validation result: FAIL")
        return 1

    print("Validation result: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
