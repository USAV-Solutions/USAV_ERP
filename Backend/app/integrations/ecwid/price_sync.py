"""
Ecwid → Shopify price synchronization engine.

When Ecwid fires a product.updated webhook, this handler:
1. Fetches the latest product data from Ecwid (price, compareToPrice, combinations)
2. Looks up the corresponding ERP variant via PlatformListing (ECWID)
3. Finds the linked Shopify PlatformListing for the same variant_id
4. Pushes the updated price to Shopify via GraphQL
5. Updates sync status in the database
"""
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.entities import Platform, PlatformSyncStatus

logger = logging.getLogger(__name__)


async def sync_ecwid_price_to_shopify(payload: dict) -> None:
    """Handle product.updated webhook and sync price to Shopify."""
    entity_id = str(payload.get("entityId", ""))
    if not entity_id:
        logger.warning("Ecwid price sync: no entityId in payload")
        return

    logger.info("Ecwid price sync: processing product %s", entity_id)

    # Import here to avoid circular imports
    from app.integrations.ecwid.client import EcwidClient
    from app.integrations.shopify.client import ShopifyClient
    from app.repositories.inventory import PlatformListingRepository

    # Initialize clients
    ecwid = EcwidClient(
        store_id=settings.ecwid_store_id,
        access_token=settings.ecwid_secret,
        api_base_url=settings.ecwid_api_base_url,
    )
    shopify = ShopifyClient(
        shop_url=settings.shopify_shop_url,
        access_token=settings.shopify_access_token,
        api_version=settings.shopify_api_version,
    )

    # 1. Fetch latest product data from Ecwid
    product = await ecwid.get_product(entity_id)
    if not product:
        logger.error("Ecwid price sync: could not fetch product %s", entity_id)
        return

    # 2. Build list of SKUs and prices to sync
    # Base product
    items_to_sync = []
    base_sku = product.get("sku")
    base_price = str(product.get("price", ""))
    base_compare = str(product.get("compareToPrice", "")) if product.get("compareToPrice") else None
    ecwid_product_id = str(product.get("id", entity_id))

    if base_sku:
        items_to_sync.append({
            "ecwid_ref": ecwid_product_id,
            "sku": base_sku,
            "price": base_price,
            "compare_at_price": base_compare,
        })

    # Combinations (variants)
    for combo in product.get("combinations", []):
        combo_sku = combo.get("sku")
        combo_price = str(combo.get("price", product.get("price", "")))
        combo_id = str(combo.get("id", ""))
        if combo_sku:
            items_to_sync.append({
                "ecwid_ref": combo_id,
                "sku": combo_sku,
                "price": combo_price,
                "compare_at_price": base_compare,  # Ecwid compareToPrice is product-level
            })

    if not items_to_sync:
        logger.warning("Ecwid price sync: product %s has no SKUs, skipping", entity_id)
        return

    # 3. For each item, find the ERP variant via Ecwid listing, then push to Shopify
    async with async_session_factory() as session:
        listing_repo = PlatformListingRepository(session)
        synced = 0
        skipped = 0
        errors = 0

        for item in items_to_sync:
            try:
                # Find Ecwid listing → get variant_id
                ecwid_listing = await listing_repo.get_by_external_ref(
                    Platform.ECWID, item["ecwid_ref"]
                )
                if not ecwid_listing or not ecwid_listing.variant_id:
                    logger.debug(
                        "Ecwid price sync: no linked ECWID listing for ref=%s (sku=%s), skipping",
                        item["ecwid_ref"], item["sku"],
                    )
                    skipped += 1
                    continue

                variant_id = ecwid_listing.variant_id

                # Find Shopify listing for the same variant
                shopify_listing = await listing_repo.get_by_variant_platform(
                    variant_id, Platform.SHOPIFY
                )
                if not shopify_listing or not shopify_listing.external_ref_id:
                    logger.debug(
                        "Ecwid price sync: no SHOPIFY listing for variant_id=%s (sku=%s), skipping",
                        variant_id, item["sku"],
                    )
                    skipped += 1
                    continue

                # 4. Push price to Shopify
                result = await shopify.update_variant_price(
                    variant_gid=shopify_listing.external_ref_id,
                    price=item["price"],
                    compare_at_price=item["compare_at_price"],
                )

                if result.get("success"):
                    # Update Shopify listing in database
                    shopify_listing.listing_price = float(item["price"]) if item["price"] else None
                    shopify_listing.sync_status = PlatformSyncStatus.SYNCED
                    shopify_listing.last_synced_at = datetime.now(timezone.utc)
                    shopify_listing.sync_error_message = None
                    await session.flush()

                    # Also update the Ecwid listing price for consistency
                    ecwid_listing.listing_price = float(item["price"]) if item["price"] else None
                    ecwid_listing.sync_status = PlatformSyncStatus.SYNCED
                    ecwid_listing.last_synced_at = datetime.now(timezone.utc)
                    await session.flush()

                    synced += 1
                    logger.info(
                        "Ecwid price sync: updated Shopify variant %s to $%s (sku=%s)",
                        shopify_listing.external_ref_id, item["price"], item["sku"],
                    )
                else:
                    shopify_listing.sync_status = PlatformSyncStatus.ERROR
                    shopify_listing.sync_error_message = str(result.get("errors", []))
                    await session.flush()
                    errors += 1
                    logger.error(
                        "Ecwid price sync: Shopify update failed for variant %s: %s",
                        shopify_listing.external_ref_id, result.get("errors"),
                    )

            except Exception as e:
                errors += 1
                logger.exception(
                    "Ecwid price sync: unexpected error for sku=%s: %s",
                    item.get("sku"), e,
                )

        await session.commit()

    logger.info(
        "Ecwid price sync complete for product %s: synced=%d, skipped=%d, errors=%d",
        entity_id, synced, skipped, errors,
    )
