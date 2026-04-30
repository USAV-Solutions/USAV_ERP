# Backend\app\integrations\walmart

## What This Folder Does
Walmart integration client layer and Walmart-specific order synchronization behavior.
The client now performs OAuth client-credentials token exchange against
`/v3/token`, calls `/v3/orders` with cursor pagination, and normalizes Walmart
order payloads into `ExternalOrder`/`ExternalOrderItem` for the shared
OrderSyncService ingestion path.

## Typical Contents
- Python modules, schemas, or support assets scoped to this domain.
- Folder-specific logic that should remain cohesive inside this boundary.

## Common Pitfalls
- Token responses can be wrapped in different envelope shapes (`tokenAPIRes`, `clientCredentialsRes`, or flat JSON); parser must handle all.
- Walmart APIs require request headers like `WM_SEC.ACCESS_TOKEN`, `WM_SVC.NAME`, and a unique `WM_QOS.CORRELATION_ID` per call.
- `list.meta.nextCursor` returns a query fragment that must be appended to `/v3/orders` for pagination.
- Walmart order normalization should map `shippingInfo.phone` and set `customer_source="WALMART_API"` so customer sync captures contact/source metadata.
- Walmart shipping normalization should map `postalAddress.address3` (or `addressLine3`) into normalized `ship_address_line3` when present.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
