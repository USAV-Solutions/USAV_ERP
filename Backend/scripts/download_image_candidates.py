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
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _iter_batches(items: list[dict], batch_size: int) -> list[list[dict]]:
    size = max(1, int(batch_size))
    return [items[i:i + size] for i in range(0, len(items), size)]


def _download_one(
    *,
    request_label: str,
    url: str,
    dst: Path,
    timeout: int,
    retries: int,
    backoff_seconds: float,
) -> tuple[bool, str | None]:
    attempts = max(1, retries + 1)
    last_error: str | None = None

    for attempt in range(1, attempts + 1):
        started_at = time.perf_counter()
        try:
            print(f"[{request_label}] START attempt={attempt}/{attempts} url={url}")
            with requests.get(url, stream=True, timeout=timeout) as resp:
                elapsed_ms = int((time.perf_counter() - started_at) * 1000)
                print(
                    f"[{request_label}] RESPONSE attempt={attempt}/{attempts} "
                    f"status={resp.status_code} elapsed_ms={elapsed_ms}"
                )
                resp.raise_for_status()
                ext = _guess_ext(url, resp.headers.get("content-type"))
                dst = dst.with_suffix(ext)
                dst.parent.mkdir(parents=True, exist_ok=True)
                total_bytes = 0
                with dst.open("wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            total_bytes += len(chunk)
            total_elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            print(
                f"[{request_label}] SUCCESS path={dst} bytes={total_bytes} elapsed_ms={total_elapsed_ms}"
            )
            return True, None
        except Exception as exc:
            last_error = str(exc)
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            print(
                f"[{request_label}] ERROR attempt={attempt}/{attempts} "
                f"elapsed_ms={elapsed_ms} error={last_error}"
            )
            if attempt < attempts:
                time.sleep(backoff_seconds * attempt)

    return False, last_error


def _download_task(job: dict, timeout: int, retries: int, backoff_seconds: float) -> dict:
    request_label = str(job["request_label"])
    ok, err = _download_one(
        request_label=request_label,
        url=str(job["url"]),
        dst=Path(job["base_dst"]),
        timeout=timeout,
        retries=retries,
        backoff_seconds=backoff_seconds,
    )
    return {
        "ok": ok,
        "error": err,
        "sku": job["sku"],
        "platform": job["platform"],
        "external_id": job["external_id"],
        "url": job["url"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Download image candidates into temp platform folders")
    parser.add_argument("--input", required=True, help="Path to JSON file with image_urls entries")
    parser.add_argument("--images-root", default="/mnt/product_images", help="Base image root")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout seconds")
    parser.add_argument("--max-per-task", type=int, default=20, help="Max images downloaded per task")
    parser.add_argument("--batch-size", type=int, default=50, help="Number of URL downloads submitted per batch")
    parser.add_argument("--workers", type=int, default=8, help="Max concurrent download workers per batch")
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
                        jobs: list[dict] = []
                        for row_idx, row in enumerate(rows, start=1):
                            sku = (row.get("sku") or "").strip()
                            platform = _safe_platform(row.get("platform") or "unknown")
                            external_id = (row.get("external_id") or "").strip()
                            urls = row.get("image_urls") or []
                            if not sku or not isinstance(urls, list):
                                continue

                            temp_dir = Path(args.images_root) / "sku" / sku / f"temp-{platform}"
                            for image_idx, url in enumerate(urls[: args.max_per_task], start=1):
                                if not isinstance(url, str) or not url.strip():
                                    continue
                                request_label = f"REQ row={row_idx} sku={sku} idx={image_idx}"
                                jobs.append(
                                    {
                                        "request_label": request_label,
                                        "sku": sku,
                                        "platform": platform,
                                        "external_id": external_id,
                                        "url": url.strip(),
                                        "base_dst": str(temp_dir / f"img-{image_idx - 1}"),
                                    }
                                )

                        print(
                            f"Starting downloads: total_jobs={len(jobs)} batch_size={max(1, args.batch_size)} workers={max(1, args.workers)}"
                        )

                        success = 0
                        failed = 0
                        failed_records: list[dict] = []
                        batches = _iter_batches(jobs, batch_size=args.batch_size)
                        for batch_index, batch in enumerate(batches, start=1):
                            print(f"Batch {batch_index}/{len(batches)} START jobs={len(batch)}")
                            with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
                                futures = [
                                    executor.submit(
                                        _download_task,
                                        job,
                                        args.timeout,
                                        args.retries,
                                        args.backoff_seconds,
                                    )
                                    for job in batch
                                ]

                                for future in as_completed(futures):
                                    result = future.result()
                                    if result["ok"]:
                                        success += 1
                                    else:
                                        failed += 1
                                        failed_records.append(
                                            {
                                                "sku": result["sku"],
                                                "platform": result["platform"],
                                                "external_id": result["external_id"],
                                                "url": result["url"],
                                                "error": result["error"],
                                            }
                                        )
                            print(
                                f"Batch {batch_index}/{len(batches)} DONE cumulative_success={success} cumulative_failed={failed}"
                            )

    print(f"Download complete: success={success} failed={failed}")
    if args.failed_output:
        print(f"Failed URL log: {args.failed_output} ({len(failed_records)} records)")
    if args.retry_input_output:
        print(f"Retry input file: {args.retry_input_output} ({len(failed_records)} failed URLs grouped)")


if __name__ == "__main__":
    main()
