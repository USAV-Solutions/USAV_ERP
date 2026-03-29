"""Deduplicate SKU image folders by exact and near-duplicate matching.

Usage examples:
  python scripts/dedupe_sku_images.py
  python scripts/dedupe_sku_images.py --apply
  python scripts/dedupe_sku_images.py --sku 00031 --sku 00044-P-1-BK --apply
  python scripts/dedupe_sku_images.py --threshold 5 --report dedupe_report.json --apply

Behavior:
- Scans image files under <product_images_path>/sku/<SKU>/ (including listing-* subfolders)
- Removes exact duplicates by SHA256
- Removes near-duplicates by perceptual hash (average hash + Hamming distance)
- Keeps the highest-resolution image in each duplicate cluster
- Dry-run by default; pass --apply to delete files
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image

# Allow importing app settings when script is executed directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}


@dataclass
class ImageInfo:
    path: Path
    width: int
    height: int
    pixels: int
    size_bytes: int
    sha256: str
    ahash: int


@dataclass
class SkuDedupeDetail:
    sku: str
    images_seen: int
    exact_duplicates_removed: int
    near_duplicates_removed: int
    mode: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _average_hash_64(path: Path) -> int:
    with Image.open(path) as img:
        gray = img.convert("L").resize((8, 8), Image.Resampling.LANCZOS)
        pixels = list(gray.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for px in pixels:
        bits = (bits << 1) | (1 if px >= avg else 0)
    return bits


def _hamming_distance_64(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def _load_image_info(path: Path) -> ImageInfo | None:
    try:
        with Image.open(path) as img:
            width, height = img.size
        return ImageInfo(
            path=path,
            width=width,
            height=height,
            pixels=max(width, 1) * max(height, 1),
            size_bytes=path.stat().st_size,
            sha256=_sha256_file(path),
            ahash=_average_hash_64(path),
        )
    except Exception as exc:
        print(f"[WARN] failed reading image {path}: {exc}")
        return None


def _iter_sku_dirs(root: Path, skus: list[str]) -> Iterable[Path]:
    if skus:
        for sku in skus:
            sku_dir = root / sku
            if sku_dir.is_dir():
                yield sku_dir
            else:
                print(f"[WARN] SKU folder not found: {sku_dir}")
        return

    for entry in sorted(root.iterdir()):
        if entry.is_dir():
            yield entry


def _iter_images_under_sku(sku_dir: Path) -> list[Path]:
    images: list[Path] = []
    for path in sku_dir.rglob("*"):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            images.append(path)
    return sorted(images)


def _pick_best(images: list[ImageInfo]) -> ImageInfo:
    return max(images, key=lambda i: (i.pixels, i.width, i.height, i.size_bytes, str(i.path)))


def _cluster_near_duplicates(images: list[ImageInfo], threshold: int) -> list[list[ImageInfo]]:
    clusters: list[list[ImageInfo]] = []
    visited: set[Path] = set()

    for idx, image in enumerate(images):
        if image.path in visited:
            continue

        cluster = [image]
        visited.add(image.path)

        for j in range(idx + 1, len(images)):
            other = images[j]
            if other.path in visited:
                continue

            # Guardrail: only compare similarly-sized images to reduce false positives.
            min_pixels = min(image.pixels, other.pixels)
            max_pixels = max(image.pixels, other.pixels)
            size_ratio = (min_pixels / max_pixels) if max_pixels else 1.0
            if size_ratio < 0.45:
                continue

            if _hamming_distance_64(image.ahash, other.ahash) <= threshold:
                cluster.append(other)
                visited.add(other.path)

        if len(cluster) > 1:
            clusters.append(cluster)

    return clusters


def _delete_paths(paths: list[Path], apply: bool) -> int:
    deleted = 0
    for path in paths:
        if apply:
            try:
                path.unlink(missing_ok=True)
                deleted += 1
            except Exception as exc:
                print(f"[WARN] failed deleting {path}: {exc}")
        else:
            deleted += 1
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate SKU image folders")
    parser.add_argument("--sku", action="append", default=[], help="Specific SKU folder to process (repeatable)")
    parser.add_argument("--threshold", type=int, default=6, help="Near-duplicate Hamming threshold (default: 6)")
    parser.add_argument("--apply", action="store_true", help="Actually delete duplicates (default is dry-run)")
    parser.add_argument("--report", default="", help="Optional JSON report output path")
    args = parser.parse_args()

    sku_root = Path(settings.product_images_path) / "sku"
    if not sku_root.is_dir():
        raise SystemExit(f"SKU image root not found: {sku_root}")

    processed_skus = 0
    processed_images = 0
    exact_duplicates_removed = 0
    near_duplicates_removed = 0
    skipped_or_invalid_images = 0
    details: list[SkuDedupeDetail] = []

    for sku_dir in _iter_sku_dirs(sku_root, args.sku):
        image_paths = _iter_images_under_sku(sku_dir)
        if not image_paths:
            continue

        infos: list[ImageInfo] = []
        for path in image_paths:
            info = _load_image_info(path)
            if info is None:
                skipped_or_invalid_images += 1
                continue
            infos.append(info)

        if not infos:
            continue

        exact_deleted_paths: list[Path] = []
        by_sha: dict[str, list[ImageInfo]] = {}
        for info in infos:
            by_sha.setdefault(info.sha256, []).append(info)

        keep_after_exact: dict[Path, ImageInfo] = {}
        for group in by_sha.values():
            winner = _pick_best(group)
            keep_after_exact[winner.path] = winner
            for info in group:
                if info.path != winner.path:
                    exact_deleted_paths.append(info.path)

        remaining = sorted(keep_after_exact.values(), key=lambda i: str(i.path))
        near_deleted_paths: list[Path] = []
        for cluster in _cluster_near_duplicates(remaining, args.threshold):
            winner = _pick_best(cluster)
            for info in cluster:
                if info.path != winner.path:
                    near_deleted_paths.append(info.path)

        exact_removed = _delete_paths(exact_deleted_paths, args.apply)
        near_removed = _delete_paths(near_deleted_paths, args.apply)

        processed_skus += 1
        processed_images += len(infos)
        exact_duplicates_removed += exact_removed
        near_duplicates_removed += near_removed

        detail = SkuDedupeDetail(
            sku=sku_dir.name,
            images_seen=len(infos),
            exact_duplicates_removed=exact_removed,
            near_duplicates_removed=near_removed,
            mode="apply" if args.apply else "dry-run",
        )
        details.append(detail)
        print(
            f"[INFO] sku={sku_dir.name} images={len(infos)} "
            f"exact_removed={exact_removed} near_removed={near_removed} mode={detail.mode}"
        )

    summary = {
        "dry_run": not args.apply,
        "sku_root": str(sku_root),
        "threshold": args.threshold,
        "processed_skus": processed_skus,
        "processed_images": processed_images,
        "exact_duplicates_removed": exact_duplicates_removed,
        "near_duplicates_removed": near_duplicates_removed,
        "skipped_or_invalid_images": skipped_or_invalid_images,
        "details": [asdict(detail) for detail in details],
    }

    print("[DONE]", json.dumps(summary, indent=2))

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"[INFO] wrote report: {report_path}")


if __name__ == "__main__":
    main()
