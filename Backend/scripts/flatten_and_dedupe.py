#!/usr/bin/env python
# pyright: reportMissingImports=false
"""Flatten and deduplicate SKU image folders using perceptual hash.

Input layout per SKU:
    {images_root}/sku/{sku}/temp-*/img-*.jpg

Output layout per SKU:
    {images_root}/sku/{sku}/img-{n}.jpg

Duplicate rule:
  pHash hamming distance <= threshold (default: 5)
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def _iter_image_files(root: Path) -> list[Path]:
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    return [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts]


def _require_deps():
    try:
        from PIL import Image  # noqa: F401
        import imagehash  # noqa: F401
    except Exception as exc:
        raise SystemExit(
            "Missing dependencies for dedupe. Install: pip install pillow imagehash"
        ) from exc


def _compute_phash(path: Path):
    from PIL import Image
    import imagehash

    with Image.open(path) as img:
        return imagehash.phash(img)


def _is_duplicate(existing_hashes, candidate_hash, threshold: int) -> bool:
    for h in existing_hashes:
        if (h - candidate_hash) <= threshold:
            return True
    return False


def main() -> None:
    _require_deps()

    parser = argparse.ArgumentParser(description="Flatten and dedupe temp platform image folders")
    parser.add_argument("--images-root", default="/mnt/product_images", help="Base image root")
    parser.add_argument("--threshold", type=int, default=5, help="pHash hamming distance threshold")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not mutate files")
    args = parser.parse_args()

    root = Path(args.images_root)
    if not root.exists():
        raise SystemExit(f"Images root not found: {root}")

    sku_root = root / "sku"
    if not sku_root.exists() or not sku_root.is_dir():
        raise SystemExit(f"SKU namespace root not found: {sku_root}")

    sku_dirs = [p for p in sku_root.iterdir() if p.is_dir()]
    total_kept = 0
    total_deleted = 0

    for sku_dir in sorted(sku_dirs):
        temp_dirs = [p for p in sku_dir.iterdir() if p.is_dir() and p.name.startswith("temp-")]
        if not temp_dirs:
            continue

        candidates = []
        for td in temp_dirs:
            candidates.extend(_iter_image_files(td))

        if not candidates:
            continue

        kept_files: list[Path] = []
        kept_hashes = []

        for path in sorted(candidates):
            try:
                h = _compute_phash(path)
            except Exception:
                # Skip unreadable/broken images.
                continue

            if _is_duplicate(kept_hashes, h, threshold=args.threshold):
                total_deleted += 1
                if not args.dry_run:
                    path.unlink(missing_ok=True)
                continue

            kept_hashes.append(h)
            kept_files.append(path)

        # Move kept files to flattened sku root.
        for i, src in enumerate(kept_files):
            dst = sku_dir / f"img-{i}{src.suffix.lower()}"
            total_kept += 1
            if args.dry_run:
                continue
            if dst.exists():
                dst.unlink()
            shutil.move(str(src), str(dst))

        # Remove now-empty temp directories.
        if not args.dry_run:
            for td in temp_dirs:
                try:
                    td.rmdir()
                except OSError:
                    # If non-empty due to unreadable leftovers, remove recursively.
                    shutil.rmtree(td, ignore_errors=True)

    print(f"Flatten/dedupe complete: kept={total_kept} removed_duplicates={total_deleted}")


if __name__ == "__main__":
    main()
