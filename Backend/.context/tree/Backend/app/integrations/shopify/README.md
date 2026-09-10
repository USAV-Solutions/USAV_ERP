# Backend\app\integrations\shopify

## What This Folder Does
Shopify GraphQL Admin API integration client for product/variant catalog queries, inventory/price updates, connection testing, and sales order ingestion.

## Typical Contents
- `client.py`: `ShopifyClient` implementing `BasePlatformClient` with async GraphQL operations (`test_connection`, `get_all_products`, `get_variant_by_id`, `update_variant_price`, `fetch_orders`, `get_order`).
- `__init__.py`: Exports `ShopifyClient`.

## Common Pitfalls
- `ShopifyClient` uses GraphQL Admin API (`/admin/api/{version}/graphql.json`) with an Admin API access token (`X-Shopify-Access-Token`).
- Rate limiting: Shopify uses leaky-bucket query cost budgeting (429 handling with retry and artificial delay).
- Subclasses `BasePlatformClient` to support both price synchronization and orders domain API sync (`fetch_orders`, `get_order`). When querying orders, Shopify requires the `read_orders` scope and defaults to open orders unless `status:any` is included in the query string.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
