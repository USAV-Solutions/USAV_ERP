# Implementation Changelog

## Overview

This document outlines all the changes implemented to improve the USAV Inventory Management System, including database restructuring, API enhancements, and frontend UI improvements.

---

## Table of Contents

1. [Database Changes](#database-changes)
2. [Backend API Changes](#backend-api-changes)
3. [Frontend UI Changes](#frontend-ui-changes)
4. [Port Configuration Changes](#port-configuration-changes)
5. [How to Run](#how-to-run)

---

## Database Changes

### New Lookup Tables

Four new lookup tables were added to provide standardized values across the system:

#### 1. Brand Table
- **Purpose**: Store brand/manufacturer information
- **Columns**: `id`, `name` (unique), `created_at`, `updated_at`
- **Default Data**: "Unknown", "USAV"

#### 2. Color Table
- **Purpose**: Store color options for products
- **Columns**: `id`, `name` (unique), `hex_code` (optional), `created_at`, `updated_at`
- **Default Data**: "Black", "White", "Silver", "Red", "Blue", "Green"

#### 3. Condition Table
- **Purpose**: Store product condition options
- **Columns**: `id`, `name` (unique), `description` (optional), `created_at`, `updated_at`
- **Default Data**: "New", "Refurbished", "Used", "Open Box"

#### 4. LCI Definition Table
- **Purpose**: Store LCI (Label Code Identifier) definitions
- **Columns**: `id`, `code` (unique), `description`, `created_at`, `updated_at`
- **Default Data**: LCI-001 through LCI-006 with descriptions

### ProductFamily Table Updates

The `product_family` table was enhanced with new columns:

| Column | Type | Description |
|--------|------|-------------|
| `brand_id` | Integer (FK) | Reference to Brand table |
| `dimensions_length` | Numeric(10,2) | Product length |
| `dimensions_width` | Numeric(10,2) | Product width |
| `dimensions_height` | Numeric(10,2) | Product height |
| `dimensions_unit` | String(10) | Unit of measurement (in, cm, etc.) |
| `weight_value` | Numeric(10,3) | Product weight |
| `weight_unit` | String(10) | Weight unit (lb, kg, oz, etc.) |
| `kit_included_products` | JSON | For Kit type - list of included product IDs |

### IdentityType Enum Changes

The `identity_type` enum was updated:
- **Renamed**: `Base` → `Product` (clearer naming)
- **Removed**: `Service` type (not needed for inventory)
- **Current Values**: `Product`, `Part`, `Bundle`, `Kit`

### Migration File

**File**: `migrations/versions/20260129_000000_0003_add_lookup_tables.py`

This migration:
- Creates all new lookup tables
- Adds new columns to `product_family`
- Seeds default data for all lookup tables
- Handles rollback/downgrade properly

---

## Backend API Changes

### Update 2026-03-16: Zoho Purchase Order Charge Mapping (Import + Export)

- Enhanced Zoho Purchase Order import mapping to persist PO-level charges into local fields:
	- `tax_amount`
	- `shipping_amount`
	- `handling_amount`
- Import parsing now supports both legacy and sandbox style payloads with fallbacks:
	- Tax from `cf_tax` custom field, then `tax_total`, then summed line-item tax values.
	- Shipping from `cf_shipping_fee` custom field.
	- Handling from `cf_handling_fee` custom field.
	- Legacy fallback: when shipping/handling custom fields are missing, `adjustment` is treated as shipping.
- Outbound PO sync payload now includes:
	- `custom_fields` for `cf_tax`, `cf_shipping_fee`, and `cf_handling_fee`.
	- `adjustment` set to `tax + shipping + handling`.
	- `adjustment_description` set to `Shipping Fee + Tax + Handling Fee`.
- Added optional configuration keys for explicit Zoho custom field IDs:
	- `zoho_po_cf_tax_id`
	- `zoho_po_cf_shipping_fee_id`
	- `zoho_po_cf_handling_fee_id`
- Added test-focused import endpoint `POST /api/v1/purchases/import/zoho/random-one` to import a single random Zoho Purchase Order from a chosen source page.

### New Lookup Endpoints

**Base Path**: `/api/v1`

#### Brands API
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/brands` | List all brands |
| GET | `/brands/{id}` | Get brand by ID |
| POST | `/brands` | Create new brand |
| PUT | `/brands/{id}` | Update brand |
| DELETE | `/brands/{id}` | Delete brand |

#### Colors API
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/colors` | List all colors |
| GET | `/colors/{id}` | Get color by ID |
| POST | `/colors` | Create new color |
| PUT | `/colors/{id}` | Update color |
| DELETE | `/colors/{id}` | Delete color |

#### Conditions API
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/conditions` | List all conditions |
| GET | `/conditions/{id}` | Get condition by ID |
| POST | `/conditions` | Create new condition |
| PUT | `/conditions/{id}` | Update condition |
| DELETE | `/conditions/{id}` | Delete condition |

#### LCI Definitions API
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/lci-definitions` | List all LCI definitions |
| GET | `/lci-definitions/{id}` | Get LCI definition by ID |
| POST | `/lci-definitions` | Create new LCI definition |
| PUT | `/lci-definitions/{id}` | Update LCI definition |
| DELETE | `/lci-definitions/{id}` | Delete LCI definition |

### New Files Created

| File | Purpose |
|------|---------|
| `app/schemas/lookups.py` | Pydantic schemas for lookup tables |
| `app/api/routes/lookups.py` | API route handlers for lookups |

### Updated Files

| File | Changes |
|------|---------|
| `app/models/entities.py` | Added Brand, Color, Condition, LCIDefinition models |
| `app/models/__init__.py` | Added exports for new models |
| `app/schemas/__init__.py` | Added lookup schema exports |
| `app/schemas/families.py` | Added new fields (brand, dimensions, weight, kit products) |
| `app/api/__init__.py` | Registered lookup routers |

---

## Frontend UI Changes

### Update 2026-03-16: Purchasing PO Creation + Line Item Entry Improvements

- Added inline purchase-order line item creation in expanded PO rows.
- New line-item total is auto-calculated (`quantity * unit_price`) and treated as read-only in both create and edit flows.
- Added line-item summary row that shows the summed line-item total per PO.
- Removed separate Add Vendor header action; vendor creation is now integrated into Create PO using searchable vendor input with one-click create from typed value.
- Moved the Create Vendor action to the right side of the vendor search field for faster access while creating a PO.
- Extended Create PO form with `tax_amount`, `shipping_amount`, and `handling_amount` inputs.
- Added per-PO **Add New Item** toggles so inline line-item create forms stay hidden until requested.
- Added Purchasing header action **Import 1 Random PO** that triggers test-focused import of a single random Zoho purchase order.
- Added server-side pagination to Purchasing list (MUI `TablePagination`, aligned with Orders/Inventory page behavior).
- Added reusable frontend pagination component `TablePaginationWithPageJump` and applied it to Orders + Purchasing pages.
- Added direct page-number jump (`Page` input + `Go`) to Orders + Purchasing list pagination.
- Added `Unmatched` item count chip per purchase-order row in Purchasing list (aligned with Order list visibility pattern).

### Update 2026-03-16: Purchasing Line-Item Matching + Delete Actions

- Added visible per-line-item actions in Purchasing expanded rows (instead of relying only on long-press).
- Added a Match action for `UNMATCHED` purchase items that opens an inline search/match row.
- Reused `VariantSearchAutocomplete` so Purchasing item matching behavior is consistent with Order item matching.
- Added a visible Delete action with confirmation dialog for purchase items (`RECEIVED` items remain protected).
- Kept long-press edit flow in place for full item field editing.

### Removed Pages

The following pages were removed in favor of a unified inventory management approach:

- ❌ `pages/ProductIdentities.tsx` - Replaced by InventoryManagement
- ❌ `pages/VariantManager.tsx` - Replaced by InventoryManagement

### New Pages

#### Inventory Management (`pages/InventoryManagement.tsx`)

A unified page that combines product identity and variant management with the following features:

**Features:**
- **List View**: Flat list of all product identities
- **Grouped View**: Products grouped by parent (ProductFamily) with expandable rows
- **Search**: Filter products by name or SKU
- **Pagination**: Navigate through large datasets
- **Type Filtering**: (Ready for implementation)
- **Create Product Button**: Opens the create product dialog

**View Modes:**
1. **List View** (Default): Shows all products in a flat table
2. **Grouped View**: Toggle with "Group by Parent" button to see products organized by their parent ProductFamily

### New Components

#### Create Product Dialog (`components/inventory/CreateProductDialog.tsx`)

A dynamic form for creating new products with type-specific fields:

**Common Fields (All Types):**
- Identity Type (Product, Part, Bundle, Kit)
- Name
- Description
- Product Family (optional)
- Color (searchable dropdown with add-new)
- Condition (searchable dropdown with add-new)

**Product Type Specific:**
- Brand (searchable dropdown with add-new)
- Dimensions (Length, Width, Height, Unit)
- Weight (Value, Unit)

**Bundle Type Specific:**
- Bundle Components (select from existing products)

**Kit Type Specific:**
- Brand
- Dimensions
- Weight
- Kit Included Products

**Dialog Features:**
- Searchable autocomplete dropdowns
- Add new option inline (e.g., "+ Add New Brand")
- Dynamic field display based on selected type
- Form validation
- Loading states

### Updated Files

| File | Changes |
|------|---------|
| `App.tsx` | Updated routes - removed old pages, added InventoryManagement |
| `components/common/Layout.tsx` | Updated navigation links |
| `types/inventory.ts` | Added lookup types (Brand, Color, Condition, LCIDefinition) |
| `api/endpoints.ts` | Added LOOKUPS endpoints object |

---

## Port Configuration Changes

### Updated Ports

| Service | Old Port | New Port |
|---------|----------|----------|
| Backend (Production) | 8000 | **8080** |
| Backend (Development) | 8000 | **8080** |
| Frontend (Production) | 3000 | **3636** |
| Frontend (Development) | 3000 | **3636** |
| Database | 5432 | 5432 (unchanged) |
| pgAdmin | 5050 | 5050 (unchanged) |

### Files Updated for Port Changes

| File | Changes |
|------|---------|
| `docker-compose.yml` | Updated all port mappings and health checks |
| `Backend/Dockerfile` | Updated EXPOSE, healthcheck, and CMD |
| `frontend/Dockerfile` | Updated EXPOSE, healthcheck, and CMD |
| `frontend/Dockerfile.dev` | Updated EXPOSE |
| `frontend/vite.config.ts` | Updated server.port and proxy target |

---

## How to Run

### Prerequisites

- Docker and Docker Compose installed
- Ports 8080, 3636, and 5432 available

### Production Mode

```bash
# Start all services (database, backend, frontend)
docker-compose up -d

# Run database migrations (first time or after schema changes)
docker-compose --profile migrate up migrations

# View logs
docker-compose logs -f
```

### Development Mode (with hot reload)

```bash
# Start database + development backend + development frontend
docker-compose --profile dev up -d

# This enables:
# - Backend hot reload (code changes auto-restart)
# - Frontend hot reload (Vite HMR)
```

### Access Points

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3636 |
| Backend API | http://localhost:8080/api/v1 |
| API Docs (Swagger) | http://localhost:8080/docs |
| API Docs (ReDoc) | http://localhost:8080/redoc |
| pgAdmin (if enabled) | http://localhost:5050 |

### Optional: pgAdmin (Database UI)

```bash
# Start with pgAdmin
docker-compose --profile tools up -d
```

### Environment Variables

Create a `.env` file in the root directory:

```env
# Database
DB_USER=postgres
DB_PASS=your_secure_password
DB_NAME=inventory_system

# Zoho Integration (optional)
ZOHO_CLIENT_ID=
ZOHO_CLIENT_SECRET=
ZOHO_REFRESH_TOKEN=
ZOHO_ORGANIZATION_ID=

# pgAdmin (optional)
PGADMIN_EMAIL=admin@example.com
PGADMIN_PASSWORD=admin
```

---

## Summary of Changes

### Files Created
- `Backend/app/schemas/lookups.py`
- `Backend/app/api/routes/lookups.py`
- `Backend/migrations/versions/20260129_000000_0003_add_lookup_tables.py`
- `frontend/src/pages/InventoryManagement.tsx`
- `frontend/src/components/inventory/CreateProductDialog.tsx`
- `IMPLEMENTATION_CHANGELOG.md` (this file)

### Files Modified
- `Backend/app/models/entities.py`
- `Backend/app/models/__init__.py`
- `Backend/app/schemas/__init__.py`
- `Backend/app/schemas/families.py`
- `Backend/app/api/__init__.py`
- `Backend/Dockerfile`
- `frontend/src/App.tsx`
- `frontend/src/components/common/Layout.tsx`
- `frontend/src/types/inventory.ts`
- `frontend/src/api/endpoints.ts`
- `frontend/Dockerfile`
- `frontend/Dockerfile.dev`
- `frontend/vite.config.ts`
- `docker-compose.yml`

### Files Deleted
- `frontend/src/pages/ProductIdentities.tsx`
- `frontend/src/pages/VariantManager.tsx`
