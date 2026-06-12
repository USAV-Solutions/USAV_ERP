# Backend\app\integrations\ebay

## What This Folder Does
eBay integration client and API-specific transport/auth/order normalization behaviors.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Editing this folder without checking sibling tests and schema/type contracts.
- Making cross-layer changes here but forgetting migration/frontend alignment.
- Reintroducing duplicated hardcoded eBay timestamp formats; use `EBAY_ISO_DATE_FORMAT` in `client.py` for all eBay ISO datetime string generation.
- Keep `_convert_order` customer enrichment mapping aligned with the normalized contract (`customer_phone`, `customer_source`) so `OrderSyncService` can persist the latest channel context.
- eBay Fulfillment shipping address exposes `addressLine1`/`addressLine2` plus city/state/postal/country; there is no native third street line, so keep normalized `ship_address_line3` unset for eBay orders.
- Listing publish now uses Inventory REST helpers (`put_inventory_item`, `get_offer_by_sku`, `create_offer`, `update_offer`, `publish_offer`) and may recover duplicate-offer create errors by looking up offer by SKU and updating it.
- OAuth refresh scope set must include `sell.inventory.mapping` and `commerce.media` in addition to existing fulfillment/inventory scopes for GraphQL enrich and optional media upload flows.
- GraphQL enrichment now uses Inventory Mapping endpoint (`/commerce/inventory_mapping/v1/graphql`) with start-task + poll-task helpers; timeouts/errors should surface as warnings at route layer, not hard crash manual publish workflows.
- Store defaults now include extended per-store listing config (warehouse address fields, heavy-item threshold, no-returns policy ID, and light/heavy/free fulfillment policy IDs) consumed by inventory publish logic.
- Store defaults policy mapping now prefers `ebay_*_policy_id_<store>` setting names and falls back to legacy `*_profile_id_*` names; missing one of payment/return/fulfillment still triggers "incomplete business policy IDs" errors at route layer.
- Trading XML helpers are still present for compatibility/tests, but eBay listing wizard publish path should not call `AddFixedPriceItem`.
- `_convert_order` now automatically extracts the `tracking_number` and `carrier` from the `fulfillments` array of the eBay REST API order payload, allowing order tracking information to be pulled dynamically during platform sync.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
