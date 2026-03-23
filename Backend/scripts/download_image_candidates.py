#!/usr/bin/env python
"""Download image candidates from URL task files.

Input JSON schema:
[
  {
    "sku": "00002-BK",
    "platform": "AMAZON",
    "external_id": "B00005T3NH",
    "image_urls": ["https://...", "https://..."]
  }
]

Temporary output layout:
    {images_root}/sku/{sku}/temp-{platform}/img-{n}.jpg
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

import requests


def _safe_platform(platform: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", platform.strip().lower()) or "unknown"


def _guess_ext(url: str, content_type: str | None) -> str:
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".webp"):
        if path.endswith(ext):
            return ext
    if content_type:
        ct = content_type.lower()
        if "png" in ct:
            return ".png"
        if "webp" in ct:
            return ".webp"
    return ".jpg"


def _download_one(url: str, dst: Path, timeout: int, retries: int, backoff_seconds: float) -> tuple[bool, str | None]:
    attempts = max(1, retries + 1)
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        try:
            with requests.get(url, stream=True, timeout=timeout) as resp:
                resp.raise_for_status()
                ext = _guess_ext(url, resp.headers.get("content-type"))
                dst = dst.with_suffix(ext)
                dst.parent.mkdir(parents=True, exist_ok=True)
                with dst.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
            return True, None
        except Exception as exc:
            last_error = str(exc)
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)

    return False, last_error


def main() -> None:
    parser = argparse.ArgumentParser(description="Download image candidates into temp platform folders")
    parser.add_argument("--input", required=True, help="Path to JSON file with image_urls entries")
    parser.add_argument("--images-root", default="/mnt/product_images", help="Base image root")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds")
    parser.add_argument("--max-per-task", type=int, default=20, help="Max images downloaded per task")
    parser.add_argument("--retries", type=int, default=2, help="Retries per URL after initial attempt")
    parser.add_argument("--backoff-seconds", type=float, default=0.5, help="Base backoff delay between retries")
    parser.add_argument(
        "--failed-output",
        default=None,
        help="Optional JSONL file path for failed URL records",
    )
    parser.add_argument(
        "--retry-input-output",
        default=None,
        help="Optional JSON file path to emit failed URLs as next-run input payload",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    rows = json.loads(input_path.read_text(encoding="utf-8"))

    success = 0
    failed = 0
    failed_records: list[dict] = []
    for row in rows:
        sku = (row.get("sku") or "").strip()
        platform = _safe_platform(row.get("platform") or "unknown")
        external_id = (row.get("external_id") or "").strip()
        urls = row.get("image_urls") or []
        if not sku or not isinstance(urls, list):
            continue

        temp_dir = Path(args.images_root) / "sku" / sku / f"temp-{platform}"
        for i, url in enumerate(urls[: args.max_per_task]):
            if not isinstance(url, str) or not url.strip():
                continue
            base_dst = temp_dir / f"img-{i}"
            clean_url = url.strip()
            ok, err = _download_one(
                clean_url,
                base_dst,
                timeout=args.timeout,
                retries=args.retries,
                backoff_seconds=args.backoff_seconds,
            )
            if ok:
                success += 1
            else:
                failed += 1
                failed_records.append(
                    {
                        "sku": sku,
                        "platform": platform,
                        "external_id": external_id,
                        "url": clean_url,
                        "error": err,
                    }
                )

    if args.failed_output:
        failed_output_path = Path(args.failed_output)
        failed_output_path.parent.mkdir(parents=True, exist_ok=True)
        with failed_output_path.open("w", encoding="utf-8") as f:
            for record in failed_records:
                f.write(json.dumps(record) + "\n")

    if args.retry_input_output:
        grouped: dict[tuple[str, str, str], list[str]] = defaultdict(list)
        for record in failed_records:
            key = (
                record.get("sku") or "",
                record.get("platform") or "unknown",
                record.get("external_id") or "",
            )
            grouped[key].append(record.get("url") or "")

        retry_rows = []
        for (sku, platform, external_id), image_urls in sorted(grouped.items()):
            deduped_urls = sorted({u for u in image_urls if u})
            if not sku or not deduped_urls:
                continue
            retry_rows.append(
                {
                    "sku": sku,
                    "platform": platform.upper(),
                    "external_id": external_id,
                    "image_urls": deduped_urls,
                }
            )

        retry_input_path = Path(args.retry_input_output)
        retry_input_path.parent.mkdir(parents=True, exist_ok=True)
        retry_input_path.write_text(json.dumps(retry_rows, indent=2), encoding="utf-8")

    print(f"Download complete: success={success} failed={failed}")
    if args.failed_output:
        print(f"Failed URL log: {args.failed_output} ({len(failed_records)} records)")
    if args.retry_input_output:
        print(f"Retry input file: {args.retry_input_output} ({len(failed_records)} failed URLs grouped)")


if __name__ == "__main__":
    main()
