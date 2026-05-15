from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException

from app.modules.inventory.routes import listings
from app.models import Platform


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


def test_resolve_listing_defaults_prefers_variant_name_and_ecwid_max_price():
    variant = SimpleNamespace(
        variant_name="Variant Preferred Title",
        full_sku="SKU-123",
        thumbnail_url=None,
        color_code="Black",
        condition_code=SimpleNamespace(value="USED"),
        identity=SimpleNamespace(
            identity_name="Identity Name",
            family=SimpleNamespace(
                base_name="Family Base Name",
                description="Family Description",
                brand=SimpleNamespace(name="Brand Name"),
            ),
            dimension_length=None,
            dimension_width=None,
            dimension_height=None,
            weight=None,
        ),
        listings=[
            SimpleNamespace(
                platform=Platform.EBAY_USAV,
                listed_name="Old eBay Title",
                listed_description="Old eBay Description",
                listing_price=12.5,
                listing_quantity=3,
                upc="123",
                listing_condition="USED",
                platform_metadata={},
            ),
            SimpleNamespace(
                platform=Platform.ECWID,
                listed_name="Ecwid 1",
                listed_description="Ecwid Desc 1",
                listing_price=22.0,
                listing_quantity=1,
                upc=None,
                listing_condition=None,
                platform_metadata={},
            ),
            SimpleNamespace(
                platform=Platform.ECWID,
                listed_name="Ecwid 2",
                listed_description="Ecwid Desc 2",
                listing_price=31.0,
                listing_quantity=1,
                upc=None,
                listing_condition=None,
                platform_metadata={},
            ),
        ],
    )

    defaults = listings._resolve_listing_defaults(variant, Platform.EBAY_USAV)
    assert defaults["title"] == "Variant Preferred Title"
    assert defaults["price"] == 31.0


def test_build_gemini_prompt_templates_match_expected_patterns():
    description_prompt = listings._build_gemini_description_prompt(
        title="My Product",
        description="Original text",
        condition_name="Used",
    )
    package_prompt = listings._build_gemini_package_prompt(title="My Product")

    assert "You are an AI assistant for creating eBay listings." in description_prompt
    assert "Return ONLY the formatted HTML." in description_prompt
    assert "Based on 'My Product', estimate weight (lb, oz)" in package_prompt
    assert "Return JSON:" in package_prompt


def test_resolve_offer_policy_ids_supports_threshold_free_and_no_returns():
    store_defaults = {
        "payment_profile_id": "pay-1",
        "return_profile_id": "ret-1",
        "return_policy_id_no_returns": "ret-none",
        "fulfillment_policy_id_light": "ful-light",
        "fulfillment_policy_id_heavy": "ful-heavy",
        "fulfillment_policy_id_free": "ful-free",
        "heavy_item_threshold_lbs": 2.0,
    }

    light = listings._resolve_offer_policy_ids(
        store_defaults=store_defaults,
        weight_lbs=1.5,
        is_free_shipping=False,
        use_no_returns_policy=False,
    )
    assert light["fulfillment_policy_id"] == "ful-light"
    assert light["return_policy_id"] == "ret-1"

    heavy = listings._resolve_offer_policy_ids(
        store_defaults=store_defaults,
        weight_lbs=2.5,
        is_free_shipping=False,
        use_no_returns_policy=False,
    )
    assert heavy["fulfillment_policy_id"] == "ful-heavy"

    free_no_returns = listings._resolve_offer_policy_ids(
        store_defaults=store_defaults,
        weight_lbs=3.0,
        is_free_shipping=True,
        use_no_returns_policy=True,
    )
    assert free_no_returns["fulfillment_policy_id"] == "ful-free"
    assert free_no_returns["return_policy_id"] == "ret-none"
