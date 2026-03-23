#!/usr/bin/env python
"""Best-effort Amazon image URL extractor from product pages.

Reads task JSON rows and outputs downloader-ready URL candidates for AMAZON rows.
This is a lightweight fallback while a full Playwright-based extractor is pending.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

import requests


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_IMAGE_RE = re.compile(r"https://[^\"'\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^\"'\s]*)?", re.IGNORECASE)
_ASIN_RE = re.compile(r"^[A-Z0-9]{10}$")


def _clean_asin(value: str) -> str:
    token = (value or "").strip().upper()
    if _ASIN_RE.match(token):
        return token

    # Handle forms like B0XXXXXXX|... or URL snippets with /dp/{asin}
    dp_match = re.search(r"/dp/([A-Z0-9]{10})", token)
    if dp_match:
        return dp_match.group(1)

    token_match = re.search(r"([A-Z0-9]{10})", token)
    if token_match:
        return token_match.group(1)

    return ""


def _extract_image_urls(html: str) -> list[str]:
    urls = sorted(set(_IMAGE_RE.findall(html)))
    filtered = []
    for url in urls:
        lower = url.lower()
        # Filter obvious non-product media assets/noise.
        if any(skip in lower for skip in ("sprite", "icon", "logo", "nav-", "spinner")):
            continue
        filtered.append(url)
    return filtered


def _fetch_page(asin: str, timeout: int) -> str | None:
    url = f"https://www.amazon.com/dp/{asin}"
    headers = {
        "User-Agent": random.choice(_USER_AGENTS),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return None
        return resp.text
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract Amazon image URLs from task list")
    parser.add_argument("--input", required=True, help="Task JSON input path")
    parser.add_argument("--output", required=True, help="Downloader-ready output JSON")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout in seconds")
    parser.add_argument("--max-per-asin", type=int, default=20, help="Max URLs to keep per ASIN")
    parser.add_argument("--delay-min-ms", type=int, default=250, help="Min jitter delay between requests")
    parser.add_argument("--delay-max-ms", type=int, default=850, help="Max jitter delay between requests")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of AMAZON tasks")
    args = parser.parse_args()

    rows = json.loads(Path(args.input).read_text(encoding="utf-8"))
    amazon_rows = [r for r in rows if (r.get("platform") or "").upper() == "AMAZON"]
    if args.limit is not None:
        amazon_rows = amazon_rows[: args.limit]

    output_rows = []
    success = 0
    failed = 0

    for row in amazon_rows:
        sku = (row.get("sku") or "").strip()
        external_id = (row.get("external_id") or "").strip()
        asin = _clean_asin(external_id)

        if not sku or not asin:
            failed += 1
            continue

        html = _fetch_page(asin=asin, timeout=args.timeout)
        if not html:
            failed += 1
            continue

        urls = _extract_image_urls(html)[: args.max_per_asin]
        if not urls:
            failed += 1
            continue

        output_rows.append(
            {
                "sku": sku,
                "platform": "AMAZON",
                "external_id": external_id,
                "image_urls": urls,
            }
        )
        success += 1

        delay_ms = random.randint(max(0, args.delay_min_ms), max(args.delay_min_ms, args.delay_max_ms))
        time.sleep(delay_ms / 1000.0)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(output_rows, indent=2), encoding="utf-8")

    print(f"Amazon tasks processed: {len(amazon_rows)}")
    print(f"Rows with URLs: {success}")
    print(f"Rows failed/no URLs: {failed}")
    print(f"Wrote: {output_path}")


if __name__ == "__main__":
    main()
