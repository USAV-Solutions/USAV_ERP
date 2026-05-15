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


def test_normalize_public_picture_urls_supports_absolute_and_relative_product_images():
    old_base = listings.settings.listing_public_base_url
    listings.settings.listing_public_base_url = "https://cdn.example.com"
    try:
        urls = listings._normalize_public_picture_urls(
            [
                "https://img.example.com/a.jpg",
                "/product-images/sku/SKU-1/listing-0/img-0.jpg",
            ]
        )
    finally:
        listings.settings.listing_public_base_url = old_base

    assert urls == [
        "https://img.example.com/a.jpg",
        "https://cdn.example.com/product-images/sku/SKU-1/listing-0/img-0.jpg",
    ]


def test_normalize_public_picture_urls_rejects_non_http_url():
    try:
        listings._normalize_public_picture_urls(["file:///tmp/a.jpg"])
    except HTTPException as exc:
        assert exc.status_code == 400
    else:
        raise AssertionError("Expected HTTPException for non-http picture URL")


def test_to_inventory_aspects_merges_duplicate_names():
    aspects = listings._to_inventory_aspects(
        [
            {"Name": "Brand", "Value": ["Acme"]},
            {"Name": "Brand", "Value": ["Acme", "USAV"]},
            {"Name": "Color", "Value": ["Black"]},
        ]
    )
    assert aspects == {
        "Brand": ["Acme", "USAV"],
        "Color": ["Black"],
    }
