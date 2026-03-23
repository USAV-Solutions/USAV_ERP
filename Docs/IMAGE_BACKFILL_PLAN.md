# USAV Image Backfill Architecture and Implementation Plan

## Scope
Populate, deduplicate, and link product images for listing-backed SKUs after full catalog import.

## Preflight (before delete/rebuild)
Run a quick sanity check for mount path, SKU namespace, and DB thumbnail baseline.

```bash
python scripts/preflight_image_reset.py --images-root /mnt/product_images --create-sku-root --check-db
```

If you want to enforce empty `sku` namespace before starting a fresh pull:

```bash
python scripts/preflight_image_reset.py --images-root /mnt/product_images --require-empty-sku-root
```

## Canonical storage decision
After the reset, use SKU namespace only:
- Filesystem: `/mnt/product_images/sku/{sku}/...`
- URL: `/product-images/sku/{sku}/{filename}`

Keep backend `product_images_path=/mnt/product_images` and let code append `/sku`.

## Phase 1: Task generation from DB
Use the database once to extract immutable scraping targets.

Command:

```bash
python scripts/generate_image_tasks.py --output scripts/image_tasks.json --format json
```

Output schema:

```json
{
  "sku": "00002-BK",
  "platform": "AMAZON",
  "external_id": "B00005T3NH",
  "variant_id": 123,
  "listing_id": 456
}
```

Optional filters:
- `--platforms AMAZON,ECWID,EBAY_USAV`
- `--include-inactive`
- `--limit 500`

## Phase 2: URL extraction (fetchers)
Run platform-specific fetchers that read `scripts/image_tasks.json` and produce URL candidates.

Recommended output file format for the downloader:

```json
[
  {
    "sku": "00002-BK",
    "platform": "AMAZON",
    "external_id": "B00005T3NH",
    "image_urls": ["https://...", "https://..."]
  }
]
```

Implementation recommendation:
- Stream A (APIs): eBay Browse API + Ecwid Product API
- Stream B (Stealth): Playwright for Amazon with jittered delay and rotating user agent/proxy if needed

Current implementation command:

```bash
python scripts/build_image_url_candidates.py --input scripts/image_tasks.json --output scripts/image_url_candidates.json --include-platform-metadata --fetch-ecwid --fetch-ebay --delay-ms 100 --progress-every 25
```

Amazon fallback extractor (best-effort HTML scraping):

```bash
python scripts/fetch_amazon_image_urls.py --input scripts/image_tasks.json --output scripts/image_url_candidates_amazon.json --delay-min-ms 250 --delay-max-ms 850
```

If you run both commands, merge results into a single candidate file before download.

Notes:
- Metadata extraction reads `platform_listing.platform_metadata` first when enabled.
- Ecwid/eBay API enrichment is optional and controlled by flags.
- Amazon robust extraction is still recommended via Playwright stream for higher success rate.

## Phase 3: Download to temporary platform folders
Download candidate URLs into per-platform temporary directories.

Command:

```bash
python scripts/download_image_candidates.py --input scripts/image_url_candidates.json --images-root /mnt/product_images --retries 2 --backoff-seconds 0.5 --failed-output scripts/image_failed_urls.jsonl --retry-input-output scripts/image_retry_input.json
```

Retry-only rerun:

```bash
python scripts/download_image_candidates.py --input scripts/image_retry_input.json --images-root /mnt/product_images --retries 2 --backoff-seconds 0.5 --failed-output scripts/image_failed_urls_retry.jsonl --retry-input-output scripts/image_retry_input_next.json
```

Temporary layout:
- `/mnt/product_images/sku/{sku}/temp-amazon/img-{n}.jpg`
- `/mnt/product_images/sku/{sku}/temp-ecwid/img-{n}.jpg`
- `/mnt/product_images/sku/{sku}/temp-ebay_usav/img-{n}.jpg`

## Phase 4: Visual dedupe and flatten
Use pHash dedupe and flatten each SKU folder.

Install deps once:

```bash
pip install pillow imagehash
```

Dry run:

```bash
python scripts/flatten_and_dedupe.py --images-root /mnt/product_images --threshold 5 --dry-run
```

Apply:

```bash
python scripts/flatten_and_dedupe.py --images-root /mnt/product_images --threshold 5
```

Final layout:
- `/mnt/product_images/sku/{sku}/img-0.jpg`
- `/mnt/product_images/sku/{sku}/img-1.jpg`

## Phase 5: Sync thumbnails to DB
Set `product_variant.thumbnail_url` to the flattened primary image path.

Dry run:

```bash
python scripts/sync_thumbnails_to_db.py --images-root /mnt/product_images --dry-run
```

Apply:

```bash
python scripts/sync_thumbnails_to_db.py --images-root /mnt/product_images
```

DB linkage rule:
- `thumbnail_url = /product-images/sku/{sku}/{img-file}`
- matched by `product_variant.full_sku = {sku}`

## Operational sequence
1. Generate tasks once.
2. Run fetchers in batches (per platform), writing URL candidate files.
3. Download candidates into temp folders.
4. Run dedupe/flatten once all downloads complete.
5. Sync thumbnail paths to DB.
6. Optionally run existing thumbnail backfill endpoint for consistency checks.

## Safety and observability
- Keep fetchers decoupled from DB.
- Use dry-run options for dedupe and DB sync.
- Use downloader retries and write failed URLs to a JSONL manifest for retry batches.
- Track counts at each stage: task count, URL count, downloaded files, deduped files, updated variants.
- Keep failed URL logs for retry batches.

## Post-run verification
After sync, validate filesystem and DB coverage:

```bash
python scripts/verify_image_rebuild.py --images-root /mnt/product_images --active-only
```
