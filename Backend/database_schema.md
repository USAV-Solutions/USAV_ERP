# Database Schema Overview

This document summarizes the current **application-level database schema** defined by SQLAlchemy models in:
- `Backend/app/models/user.py`
- `Backend/app/models/entities.py`
- `Backend/app/models/purchasing.py`
- `Backend/app/modules/orders/models.py`

Scope is the operational domain used by the app runtime: users, catalog/inventory, listings, purchasing, and sales orders.

## 1) Brief Documentation

### Core domain groups
- **Identity & Catalog**: `product_family` -> `product_identity` -> `product_variant`
- **Inventory**: `inventory_item` tracks physical units by `variant_id`
- **External Listing**: `platform_listing` maps internal variants to channel listings
- **Sales Orders**: `orders` + `order_item` + `customer`
- **Purchasing**: `vendor` + `purchase_order` + `purchase_order_item`
- **Sync Runtime**: `integration_state` stores per-platform sync cursor/state
- **Security**: `users` for RBAC login/auth

### Important modeling notes
- `orders` uses `(platform, external_order_id)` unique constraint for idempotent imports.
- `order_item` keeps both `platform_listing_id` and `variant_id` to support matching workflows and fast querying.
- `platform_listing.external_ref_id` is unique per platform when not null (partial unique index).
- `product_variant.full_sku` is globally unique for sellable SKU identity.
- `purchase_order.po_number` is unique for purchasing lifecycle tracking.
- `integration_state.platform_name` is unique: one sync-state row per platform.

## 2) Mermaid ER Diagram (Live Code)

[https://mermaid.live](https://mermaid.live):

```mermaid
erDiagram
    users {
        bigint id PK
        string username UK
        string email
        string role
        bool is_active
    }

    brand {
        bigint id PK
        string name UK
    }

    color {
        bigint id PK
        string name
        string code UK
    }

    condition {
        bigint id PK
        string name
        string code UK
    }

    product_family {
        int product_id PK
        string family_code UK
        string base_name
        bigint brand_id FK
    }

    lci_definition {
        bigint id PK
        int product_id FK
        int lci_index
        string component_name
    }

    product_identity {
        bigint id PK
        int product_id FK
        string type
        int lci
        string generated_upis_h UK
        string hex_signature
        decimal dimension_length
        decimal dimension_width
        decimal dimension_height
        decimal weight
    }

    product_variant {
        bigint id PK
        bigint identity_id FK
        string full_sku UK
        string color_code
        string condition_code
        string variant_name
        string zoho_item_id
        bool is_active
    }

    bundle_component {
        bigint id PK
        bigint parent_identity_id FK
        bigint child_identity_id FK
        int quantity_required
        string role
    }

    platform_listing {
        bigint id PK
        bigint variant_id FK
        string platform
        string external_ref_id
        string merchant_sku
        decimal listing_price
        int listing_quantity
        string sync_status
    }

    inventory_item {
        bigint id PK
        string serial_number UK
        bigint variant_id FK
        string status
        string location_code
        decimal cost_basis
    }

    customer {
        bigint id PK
        string name
        string email
        string source
        bool is_active
    }

    orders {
        bigint id PK
        string platform
        string source
        string external_order_id
        bigint customer_id FK
        string status
        string shipping_status
        decimal subtotal_amount
        decimal tax_amount
        decimal shipping_amount
        decimal total_amount
        string tracking_number
    }

    order_item {
        bigint id PK
        bigint order_id FK
        bigint platform_listing_id FK
        bigint variant_id FK
        bigint allocated_inventory_id FK
        string external_sku
        string status
        int quantity
        decimal unit_price
        decimal total_price
    }

    vendor {
        bigint id PK
        string name UK
        string email
        bool is_active
    }

    purchase_order {
        bigint id PK
        string po_number UK
        bigint vendor_id FK
        string deliver_status
        date order_date
        decimal total_amount
        decimal tax_amount
        decimal shipping_amount
        string source
        string tracking_number
    }

    purchase_order_item {
        bigint id PK
        bigint purchase_order_id FK
        bigint variant_id FK
        string external_item_id
        string status
        int quantity
        decimal unit_price
        decimal total_price
    }

    integration_state {
        bigint id PK
        string platform_name UK
        datetime last_successful_sync
        string current_status
    }

    brand ||--o{ product_family : has
    product_family ||--o{ lci_definition : defines
    product_family ||--o{ product_identity : owns
    product_identity ||--o{ product_variant : has
    product_identity ||--o{ bundle_component : parent_of
    product_identity ||--o{ bundle_component : child_of
    product_variant ||--o{ platform_listing : listed_as
    product_variant ||--o{ inventory_item : stocked_as

    customer ||--o{ orders : places
    orders ||--o{ order_item : contains
    platform_listing ||--o{ order_item : matched_by
    product_variant ||--o{ order_item : resolved_to
    inventory_item ||--o{ order_item : allocated_item

    vendor ||--o{ purchase_order : owns
    purchase_order ||--o{ purchase_order_item : contains
    product_variant ||--o{ purchase_order_item : references
```
