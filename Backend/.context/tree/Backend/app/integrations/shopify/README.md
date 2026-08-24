# Backend\app\integrations\shopify

## What This Folder Does
Shopify GraphQL Admin API integration client for product/variant catalog queries, inventory/price updates, and connection testing.

## Typical Contents
- `client.py`: `ShopifyClient` implementing async GraphQL operations (`test_connection`, `get_all_products`, `get_variant_by_id`, `update_variant_price`).
- `__init__.py`: Exports `ShopifyClient`.

## Common Pitfalls
- `ShopifyClient` uses GraphQL Admin API (`/admin/api/{version}/graphql.json`) with an Admin API access token (`X-Shopify-Access-Token`).
- Rate limiting: Shopify uses leaky-bucket query cost budgeting (429 handling with retry and artificial delay).
- Does not subclass `BasePlatformClient` as it is currently scoped for price sync and catalog listing import rather than generic order polling.

## Child Folders
- (No child folders)

## Agent Navigation Hint
- Read this file first.
- Then open only the child folder docs needed for your current task.
