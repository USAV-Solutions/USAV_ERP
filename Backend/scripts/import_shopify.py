import asyncio
from app.core.database import async_session_factory
from app.integrations.shopify.client import ShopifyClient
from app.models import Platform, PlatformSyncStatus
from app.repositories import PlatformListingRepository, ProductVariantRepository
from app.core.config import settings

async def run_import():
    shopify = ShopifyClient(
        shop_url=settings.shopify_shop_url,
        access_token=settings.shopify_access_token.strip(),
        api_version=settings.shopify_api_version,
    )
    conn = await shopify.test_connection()
    if not conn.get("success"):
        print("Connection failed:", conn)
        return

    print("Fetching products from Shopify...")
    products = await shopify.get_all_products()
    print(f"Retrieved {len(products)} variants from Shopify")

    async with async_session_factory() as session:
        listing_repo = PlatformListingRepository(session)
        variant_repo = ProductVariantRepository(session)

        created = 0
        updated = 0
        matched = 0
        unmatched = 0
        errors = []

        for item in products:
            variant_gid = item.get("variant_id")
            if not variant_gid:
                continue

            sku = (item.get("sku") or "").strip()
            price_val = float(item["price"]) if item.get("price") else None
            qty_val = item.get("inventory_quantity")
            listed_title = f"{item.get('product_title', '')} - {item.get('variant_title', '')}".strip(" -")

            # 1. Match ERP variant by SKU
            matched_variant_id = None
            if sku:
                variant = await variant_repo.get_by_sku(sku)
                if variant:
                    matched_variant_id = variant.id
                else:
                    # Fallback: check if an Ecwid listing has this merchant_sku with a variant_id
                    ecwid_listing = await listing_repo.get_by_external_ref(Platform.ECWID, sku)
                    if ecwid_listing and ecwid_listing.variant_id:
                        matched_variant_id = ecwid_listing.variant_id

            if matched_variant_id:
                matched += 1
            else:
                unmatched += 1

            listing_data = {
                "variant_id": matched_variant_id,
                "platform": Platform.SHOPIFY,
                "external_ref_id": variant_gid,
                "merchant_sku": sku or None,
                "listed_name": listed_title or None,
                "listing_price": price_val,
                "listing_quantity": qty_val,
                "sync_status": PlatformSyncStatus.SYNCED if matched_variant_id else PlatformSyncStatus.PENDING,
            }

            try:
                existing = await listing_repo.get_by_external_ref(Platform.SHOPIFY, variant_gid)
                if existing:
                    update_fields = {}
                    if price_val is not None:
                        update_fields["listing_price"] = price_val
                    if qty_val is not None:
                        update_fields["listing_quantity"] = qty_val
                    if listed_title:
                        update_fields["listed_name"] = listed_title
                    if sku:
                        update_fields["merchant_sku"] = sku
                    if existing.variant_id is None and matched_variant_id is not None:
                        update_fields["variant_id"] = matched_variant_id
                        update_fields["sync_status"] = PlatformSyncStatus.SYNCED

                    if update_fields:
                        await listing_repo.update(existing, update_fields)
                    updated += 1
                else:
                    await listing_repo.create(listing_data)
                    created += 1
            except Exception as e:
                msg = f"Failed to save Shopify variant {variant_gid} ({sku}): {e}"
                print(msg)
                errors.append(msg)

        await session.commit()
        print("=== SHOPIFY IMPORT SUMMARY ===")
        print(f"Total Products/Variants in Shopify: {len(products)}")
        print(f"Listings Created in DB: {created}")
        print(f"Listings Updated in DB: {updated}")
        print(f"Auto-matched to ERP Product Variants: {matched}")
        print(f"Unmatched (New/Unlinked): {unmatched}")
        print(f"Errors: {len(errors)}")

if __name__ == "__main__":
    asyncio.run(run_import())
