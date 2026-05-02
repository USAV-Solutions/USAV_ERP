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
- AddFixedPriceItem publish XML is strict: always include `DispatchTimeMax`, `ListingDuration=GTC`, nested `PrimaryCategory.CategoryID`, `SellerProfiles`, `PictureDetails.PictureURL`, and `ItemSpecifics.NameValueList`; missing any of these causes parser/validation failures.
- `Item.Description` is wrapped as CDATA in the XML builder to protect embedded HTML; avoid changing this to plain escaped text for listing payloads.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
