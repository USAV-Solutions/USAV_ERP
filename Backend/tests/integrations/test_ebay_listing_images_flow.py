from pathlib import Path

from fastapi import HTTPException

from app.modules.inventory.routes import listings


def test_collect_available_sku_images_includes_listing_and_flat(tmp_path):
    sku = "SKU-123"
    root = tmp_path / "sku" / sku
    (root / "listing-0").mkdir(parents=True, exist_ok=True)
    (root / "listing-1").mkdir(parents=True, exist_ok=True)
    (root / "listing-0" / "img-0.jpg").write_bytes(b"x")
    (root / "listing-1" / "img-9.png").write_bytes(b"x")
    (root / "flat.webp").write_bytes(b"x")

    old_path = listings.settings.product_images_path
    listings.settings.product_images_path = str(tmp_path)
    try:
        images = listings._collect_available_sku_images(sku)
    finally:
        listings.settings.product_images_path = old_path

    image_ids = {img.image_id for img in images}
    assert "listing-0/img-0.jpg" in image_ids
    assert "listing-1/img-9.png" in image_ids
    assert "flat.webp" in image_ids


def test_resolve_image_file_path_blocks_traversal(tmp_path):
    sku = "SKU-999"
    root = tmp_path / "sku" / sku / "listing-0"
    root.mkdir(parents=True, exist_ok=True)
    (root / "img-0.jpg").write_bytes(b"x")

    old_path = listings.settings.product_images_path
    listings.settings.product_images_path = str(tmp_path)
    try:
        resolved = listings._resolve_image_file_path(sku, "listing-0/img-0.jpg")
        assert resolved == (root / "img-0.jpg").resolve()

        try:
            listings._resolve_image_file_path(sku, "../etc/passwd")
        except HTTPException as exc:
            assert exc.status_code == 400
        else:
            raise AssertionError("Expected HTTPException for traversal image_id")
    finally:
        listings.settings.product_images_path = old_path
