"""
Pull product images from eBay/Ecwid using listing IDs stored in the database.

Output path format (required):
    /mnt/product_images/sku/{variant_sku}/
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import quote, urlparse

import httpx
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

# Allow running as a script: python scripts/image_getting.py
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_ROOT = SCRIPT_DIR.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.entities import Platform, PlatformListing, ProductVariant


EBAY_BROWSE_API_URL = "https://api.ebay.com/buy/browse/v1/item"
EBAY_OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"

VALID_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}


@dataclass(frozen=True)
class ListingTask:
    listing_id: int
    variant_id: int
    variant_sku: str
    platform: Platform
    external_ref_id: str


class EbayTokenManager:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, float]] = {}

    async def get_token(self, client: httpx.AsyncClient, account_key: str) -> str | None:
        cached = self._cache.get(account_key)
        now = time.time()
        if cached and cached[1] > now:
            return cached[0]

        refresh_token = self._get_refresh_token(account_key)
        if not refresh_token:
            print(f"[WARN] Missing eBay refresh token for account={account_key}")
            return None

        if not settings.ebay_app_id or not settings.ebay_cert_id:
            print("[WARN] Missing eBay app credentials (ebay_app_id / ebay_cert_id)")
            return None

        basic = base64.b64encode(f"{settings.ebay_app_id}:{settings.ebay_cert_id}".encode("utf-8")).decode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {basic}",
        }
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": "https://api.ebay.com/oauth/api_scope",
        }

        print(f"[REQ] eBay OAuth refresh account={account_key}")
        response = await client.post(EBAY_OAUTH_URL, data=payload, headers=headers)
        print(f"[RES] eBay OAuth refresh account={account_key} status={response.status_code}")

        if response.status_code != 200:
            print(f"[WARN] eBay OAuth refresh failed account={account_key} body={response.text[:300]}")
            return None

        data = response.json()
        token = data.get("access_token")
        if not token:
            print(f"[WARN] eBay OAuth response missing access_token for account={account_key}")
            return None

        expires_in = int(data.get("expires_in", 7200))
        self._cache[account_key] = (token, now + max(60, expires_in - 120))
        return token

    @staticmethod
    def _get_refresh_token(account_key: str) -> str:
        mapping = {
            "USAV": settings.ebay_refresh_token_usav,
            "MEKONG": settings.ebay_refresh_token_mekong,
            "DRAGON": settings.ebay_refresh_token_dragon,
        }
        return mapping.get(account_key, "")


def infer_ebay_account(platform: Platform) -> str:
    if platform == Platform.EBAY_MEKONG:
        return "MEKONG"
    if platform == Platform.EBAY_DRAGON:
        return "DRAGON"
    return "USAV"


def normalize_ebay_browse_item_id(external_ref_id: str) -> str:
    value = external_ref_id.strip()
    if value.startswith("v1|"):
        return value
    if value.isdigit():
        return f"v1|{value}|0"
    return value


def dedupe_keep_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)


def detect_image_ext(image_url: str) -> str:
    path = urlparse(image_url).path or ""
    ext = os.path.splitext(path)[1].lower()
    if ext in VALID_IMAGE_EXTENSIONS:
        return ext
    return ".jpg"


async def fetch_db_tasks(session: AsyncSession, limit: int | None, variant_sku: str | None) -> list[ListingTask]:
    stmt: Select = (
        select(
            PlatformListing.id,
            PlatformListing.variant_id,
            PlatformListing.platform,
            PlatformListing.external_ref_id,
            ProductVariant.full_sku,
        )
        .join(ProductVariant, ProductVariant.id == PlatformListing.variant_id)
        .where(PlatformListing.platform.in_([Platform.EBAY_MEKONG, Platform.EBAY_USAV, Platform.EBAY_DRAGON, Platform.ECWID]))
        .where(PlatformListing.external_ref_id.is_not(None))
        .where(PlatformListing.external_ref_id != "")
        .where(ProductVariant.full_sku.is_not(None))
        .order_by(PlatformListing.id.asc())
    )

    if variant_sku:
        stmt = stmt.where(ProductVariant.full_sku == variant_sku)
    if limit and limit > 0:
        stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).all()
    tasks: list[ListingTask] = []
    for listing_id, variant_id, platform, external_ref_id, full_sku in rows:
        if not full_sku:
            continue
        tasks.append(
            ListingTask(
                listing_id=int(listing_id),
                variant_id=int(variant_id),
                variant_sku=str(full_sku),
                platform=platform,
                external_ref_id=str(external_ref_id),
            )
        )
    return tasks


async def fetch_ebay_images(client: httpx.AsyncClient, token_mgr: EbayTokenManager, task: ListingTask) -> list[str]:
    account_key = infer_ebay_account(task.platform)
    token = await token_mgr.get_token(client, account_key)
    if not token:
        return []

    browse_item_id = normalize_ebay_browse_item_id(task.external_ref_id)
    url = f"{EBAY_BROWSE_API_URL}/{quote(browse_item_id, safe='|')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    print(f"[REQ] eBay listing_id={task.listing_id} platform={task.platform.value} browse_item_id={browse_item_id}")
    response = await client.get(url, headers=headers)
    print(f"[RES] eBay listing_id={task.listing_id} status={response.status_code}")

    if response.status_code != 200:
        print(f"[WARN] eBay fetch failed listing_id={task.listing_id} body={response.text[:300]}")
        return []

    payload = response.json()
    urls: list[str] = []
    image = payload.get("image") or {}
    primary = image.get("imageUrl")
    if isinstance(primary, str) and primary:
        urls.append(primary)

    additional = payload.get("additionalImages") or []
    for img in additional:
        if isinstance(img, dict):
            u = img.get("imageUrl")
            if isinstance(u, str) and u:
                urls.append(u)

    return dedupe_keep_order(urls)


async def fetch_ecwid_images(client: httpx.AsyncClient, task: ListingTask) -> list[str]:
    if not settings.ecwid_store_id or not settings.ecwid_secret:
        print("[WARN] Missing Ecwid credentials (ecwid_store_id / ecwid_secret)")
        return []

    headers = {
        "Authorization": f"Bearer {settings.ecwid_secret}",
        "Content-Type": "application/json",
    }

    search_candidates = dedupe_keep_order([task.external_ref_id.strip(), task.variant_sku.strip()])

    for sku in search_candidates:
        if not sku:
            continue

        url = f"{settings.ecwid_api_base_url}/{settings.ecwid_store_id}/products?sku={quote(sku)}"
        print(f"[REQ] Ecwid listing_id={task.listing_id} sku={sku}")
        response = await client.get(url, headers=headers)
        print(f"[RES] Ecwid listing_id={task.listing_id} sku={sku} status={response.status_code}")

        if response.status_code != 200:
            print(f"[WARN] Ecwid fetch failed listing_id={task.listing_id} body={response.text[:300]}")
            return []

        payload = response.json()
        items = payload.get("items") or []
        if not items:
            continue

        item = items[0]
        urls: list[str] = []
        primary = item.get("imageUrl")
        if isinstance(primary, str) and primary:
            urls.append(primary)

        gallery = item.get("galleryImages") or []
        for img in gallery:
            if isinstance(img, dict):
                u = img.get("url") or img.get("imageUrl")
                if isinstance(u, str) and u:
                    urls.append(u)

        return dedupe_keep_order(urls)

    return []


async def download_image(client: httpx.AsyncClient, image_url: str, dest_path: Path) -> bool:
    try:
        print(f"[REQ] Download {image_url}")
        response = await client.get(image_url, follow_redirects=True)
        print(f"[RES] Download status={response.status_code} url={image_url}")
        if response.status_code != 200:
            return False

        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(response.content)
        return True
    except Exception as exc:
        print(f"[WARN] Download failed url={image_url} error={exc}")
        return False


def build_variant_dir(variant_sku: str) -> Path:
    # Required destination layout: /mnt/product_images/sku/{variant_sku}
    return Path(settings.product_images_path) / "sku" / sanitize_filename(variant_sku)


async def process_listing(client: httpx.AsyncClient, token_mgr: EbayTokenManager, task: ListingTask) -> tuple[int, int]:
    image_urls: list[str] = []
    if task.platform in {Platform.EBAY_MEKONG, Platform.EBAY_USAV, Platform.EBAY_DRAGON}:
        image_urls = await fetch_ebay_images(client, token_mgr, task)
    elif task.platform == Platform.ECWID:
        image_urls = await fetch_ecwid_images(client, task)

    if not image_urls:
        print(f"[INFO] listing_id={task.listing_id} variant={task.variant_sku} no images found")
        return (0, 1)

    variant_dir = build_variant_dir(task.variant_sku)
    saved = 0
    for idx, image_url in enumerate(image_urls, start=1):
        ext = detect_image_ext(image_url)
        filename = sanitize_filename(f"listing-{task.listing_id}-{task.platform.value.lower()}-{idx}{ext}")
        destination = variant_dir / filename
        ok = await download_image(client, image_url, destination)
        if ok:
            saved += 1
            print(f"[SAVE] {destination}")

    print(
        f"[DONE] listing_id={task.listing_id} variant={task.variant_sku} "
        f"platform={task.platform.value} saved={saved}/{len(image_urls)}"
    )
    return (saved, 0)


async def run(limit: int | None, variant_sku: str | None) -> None:
    print("=== Image Pull Start ===")
    print(f"Target root: {Path(settings.product_images_path) / 'sku'}")

    async with async_session_factory() as db:
        tasks = await fetch_db_tasks(db, limit=limit, variant_sku=variant_sku)

    print(f"Found {len(tasks)} listing(s) from DB")
    if not tasks:
        print("No eligible listings found.")
        return

    token_mgr = EbayTokenManager()
    total_saved = 0
    total_failed = 0
    started = time.time()

    timeout = httpx.Timeout(30.0, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for task in tasks:
            print(
                f"\n[LISTING] id={task.listing_id} variant={task.variant_sku} "
                f"platform={task.platform.value} external_ref_id={task.external_ref_id}"
            )
            saved, failed = await process_listing(client, token_mgr, task)
            total_saved += saved
            total_failed += failed
            await asyncio.sleep(0.1)

    duration = time.time() - started
    print("\n=== Image Pull Complete ===")
    print(f"Listings processed: {len(tasks)}")
    print(f"Images saved: {total_saved}")
    print(f"Listings with no images/errors: {total_failed}")
    print(f"Duration: {duration:.2f}s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pull images for eBay/Ecwid listings from DB")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of DB listings to process")
    parser.add_argument("--variant-sku", type=str, default=None, help="Process only one variant SKU")
    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_args()
    asyncio.run(run(limit=cli_args.limit, variant_sku=cli_args.variant_sku))
