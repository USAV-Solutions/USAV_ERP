# USAV System Expansion Plan: Inventory to Modular Monolith

**Objective:** Expand the current Inventory System to handle Order Management (OMS), External Integrations (Amazon, eBay, Zoho), and future modules (CRM, Repair) without splitting into complex microservices.

**Architecture Strategy:** **Modular Monolith** with **Split Runtime**.

* **One Codebase:** All logic stays in the `Backend/` folder.
* **Two Runtimes:**
1. **API Service:** Handles fast user requests (Dashboard, Frontend).
2. **Worker Service:** Handles slow background tasks (Syncing Orders, Pushing to Zoho).

**Status:** ✅ **IMPLEMENTED** (February 5, 2026)

---

## 1. Final Directory Structure

```text
Backend/
├── app/
│   ├── main.py                # API Entrypoint
│   ├── worker.py              # Worker Entrypoint ✅
│   │
│   ├── core/                  # Shared Config, Database, Security
│   │   ├── config.py          # Settings with Amazon/eBay/Zoho credentials
│   │   ├── database.py        # Async SQLAlchemy setup
│   │   └── security.py        # JWT & password hashing
│   │
│   ├── api/                   # Auth routes only (auth module)
│   │   ├── __init__.py        # Main API router combining all modules
│   │   └── routes/
│   │       ├── __init__.py    # Auth exports only
│   │       └── auth.py        # Authentication endpoints
│   │
│   ├── schemas/               # Re-exports for backward compatibility
│   │   ├── __init__.py        # Re-exports from modules for backward compat
│   │   └── auth.py            # Auth schemas (stay here)
│   │
│   ├── modules/               # INTERNAL DOMAINS (New Modular Structure) ✅
│   │   ├── inventory/         # Product Families, Identities, Variants ✅ MIGRATED
│   │   │   ├── __init__.py    # Module exports
│   │   │   ├── models.py      # Re-exports from entities (still shared)
│   │   │   ├── routes/        # ✅ ACTUAL ROUTE FILES (moved from api/routes)
│   │   │   │   ├── __init__.py
│   │   │   │   ├── families.py
│   │   │   │   ├── identities.py
│   │   │   │   ├── variants.py
│   │   │   │   ├── bundles.py
│   │   │   │   ├── listings.py
│   │   │   │   ├── inventory.py
│   │   │   │   └── lookups.py
│   │   │   └── schemas/       # ✅ ACTUAL SCHEMA FILES (moved from app/schemas)
│   │   │       ├── __init__.py
│   │   │       ├── pagination.py
│   │   │       ├── families.py
│   │   │       ├── identities.py
│   │   │       ├── variants.py
│   │   │       ├── bundles.py
│   │   │       ├── listings.py
│   │   │       ├── inventory.py
│   │   │       └── lookups.py
│   │   │
│   │   └── orders/            # Order Processing & Matching ✅ NEW
│   │       ├── __init__.py
│   │       ├── models.py      # Order, OrderItem tables
│   │       ├── schemas.py     # Pydantic schemas
│   │       ├── routes.py      # API endpoints
│   │       └── services.py    # Business logic (matching, allocation)
│   │
│   └── integrations/          # EXTERNAL ADAPTERS ✅ NEW
│       ├── base.py            # Abstract interface for all platforms
│       ├── amazon/            # SP-API Client (skeleton)
│       │   └── client.py
│       ├── ebay/              # Trading API Client (skeleton)
│       │   └── client.py
│       └── zoho/              # Inventory/Books Sync
│           └── client.py
│
├── migrations/
│   └── versions/
│       ├── ...existing migrations...
│       └── 20260205_000000_0005_add_orders.py  # ✅ NEW
│
└── requirements.txt
```

---

## 2. Implementation Checklist

### Phase 1: The "Great Refactor" (Code Reorganization) ✅ COMPLETE

- [x] **Create Domain Folders:**
  - `Backend/app/modules/inventory`
  - `Backend/app/modules/orders`
  - `Backend/app/integrations/amazon`
  - `Backend/app/integrations/ebay`
  - `Backend/app/integrations/zoho`

- [x] **Create Module Structure:**
  - Created `modules/__init__.py` with module documentation
  - Created `modules/inventory/` with ACTUAL files (not re-exports)
  - Created `modules/orders/` with new order management code

- [x] **File Migration (Completed):**
  - Moved `app/api/routes/*.py` → `app/modules/inventory/routes/*.py`
  - Moved `app/schemas/*.py` → `app/modules/inventory/schemas/*.py`
  - Updated all imports to use new module paths
  - Kept `app/api/routes/auth.py` in place (auth module)
  - Kept `app/schemas/auth.py` in place (auth module)

- [x] **Backward Compatibility:** 
  - `app/schemas/__init__.py` re-exports from `modules/inventory/schemas`
  - `app/api/__init__.py` imports routes from `modules/inventory/routes`
  - Existing code using `from app.schemas import ...` still works

### Phase 2: Database Expansion (Schema Updates) ✅ COMPLETE

- [x] **Define Order Models (`app/modules/orders/models.py`):**
  - `Order`: platform, external_order_id, customer info, shipping address, financials, status
  - `OrderItem`: links to Order, external SKU/ASIN, variant_id, allocated_inventory_id
  - Enums: `OrderPlatform`, `OrderStatus`, `OrderItemStatus`

- [x] **Generate Migration:**
  - Created: `migrations/versions/20260205_000000_0005_add_orders.py`
  - Tables: `order`, `order_item`
  - Indexes for efficient querying

- [x] **To Apply Schema:**
  ```bash
  docker compose --profile migrate up
  # OR inside container:
  alembic upgrade head
  ```

### Phase 3: The "Split Runtime" (Docker & Worker) ✅ COMPLETE

- [x] **Create Worker Script (`Backend/app/worker.py`):**
  - Async event loop with configurable intervals
  - Platform client initialization
  - Order sync from external platforms
  - Stock sync to platforms
  - Health checks

- [x] **Update `docker-compose.yml`:**
  - Added `worker` service (production profile)
  - Added `worker-dev` service (dev profile)
  - Same Docker image, different entrypoint
  - Environment variables for all platform credentials

- [x] **Deploy & Verify:**
  ```bash
  # Development (with hot reload)
  docker compose --profile dev up -d
  
  # Production
  docker compose --profile prod up -d
  
  # Check worker logs
  docker compose logs -f worker
  ```

### Phase 4: The Integration Layer ✅ COMPLETE (Skeleton)

- [x] **Base Interface (`app/integrations/base.py`):**
  - `BasePlatformClient` abstract class
  - `ExternalOrder` / `ExternalOrderItem` dataclasses
  - `StockUpdate` / `StockUpdateResult` dataclasses
  - `PlatformClientFactory` for client instantiation

- [x] **Amazon Client (`app/integrations/amazon/client.py`):**
  - SP-API skeleton with authentication flow
  - Methods: `fetch_orders()`, `update_stock()`, `update_tracking()`
  - TODO: Implement actual API calls with `python-amazon-sp-api`

- [x] **eBay Client (`app/integrations/ebay/client.py`):**
  - Fulfillment API skeleton
  - Multi-store support (MEKONG, USAV, DRAGON)
  - TODO: Implement actual API calls

- [x] **Zoho Client (`app/integrations/zoho/client.py`):**
  - Full implementation with OAuth token refresh
  - Methods: `create_item()`, `update_item()`, `sync_item()`, `update_stock()`

### Phase 5: Business Logic (Order Matching) ✅ COMPLETE

- [x] **`OrderService` (`app/modules/orders/services.py`):**
  - `create_order()` - Create order with items
  - `process_incoming_order()` - Create + auto-match
  - `auto_match_sku()` - Multi-strategy SKU matching:
    1. By ASIN via `platform_listing.external_ref_id`
    2. By platform item ID via listings
    3. By SKU directly to `product_variant.full_sku`
  - `match_sku_manually()` - Manual SKU assignment
  - `allocate_inventory()` - Reserve inventory items
  - `get_order_summary()` - Dashboard statistics

- [x] **Order API Endpoints (`app/modules/orders/routes.py`):**
  - `GET /api/v1/orders` - List with filtering
  - `POST /api/v1/orders` - Create new order
  - `GET /api/v1/orders/summary` - Dashboard stats
  - `GET /api/v1/orders/{id}` - Get order with items
  - `PATCH /api/v1/orders/{id}` - Update order
  - `POST /api/v1/orders/{id}/process` - Mark processing
  - `POST /api/v1/orders/{id}/ready-to-ship` - Mark ready
  - `POST /api/v1/orders/{id}/ship` - Ship with tracking
  - `POST /api/v1/orders/{id}/cancel` - Cancel + release inventory
  - `GET /api/v1/orders/items/unmatched` - Items needing matching
  - `POST /api/v1/orders/items/{id}/match` - Manual SKU match
  - `POST /api/v1/orders/items/{id}/allocate` - Allocate inventory

---

## 3. Configuration Updates

### New Environment Variables

Add to `.env` file:

```env
# Amazon SP-API
AMAZON_REFRESH_TOKEN=
AMAZON_CLIENT_ID=
AMAZON_CLIENT_SECRET=

# eBay (per store)
EBAY_MEKONG_APP_ID=
EBAY_MEKONG_CERT_ID=
EBAY_MEKONG_USER_TOKEN=

EBAY_USAV_APP_ID=
EBAY_USAV_CERT_ID=
EBAY_USAV_USER_TOKEN=

EBAY_DRAGON_APP_ID=
EBAY_DRAGON_CERT_ID=
EBAY_DRAGON_USER_TOKEN=

# Zoho (existing)
ZOHO_CLIENT_ID=
ZOHO_CLIENT_SECRET=
ZOHO_REFRESH_TOKEN=
ZOHO_ORGANIZATION_ID=
```

---

## 4. Data Flow Diagram (Current State)

```
┌─────────────────────────────────────────────────────────────────┐
│                     EXTERNAL PLATFORMS                          │
│  ┌─────────┐    ┌───────────┐    ┌───────────┐    ┌──────────┐ │
│  │ Amazon  │    │eBay Mekong│    │ eBay USAV │    │eBay Dragon│ │
│  └────┬────┘    └─────┬─────┘    └─────┬─────┘    └─────┬────┘ │
└───────┼───────────────┼────────────────┼────────────────┼──────┘
        │               │                │                │
        └───────────────┴────────┬───────┴────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │    WORKER SERVICE       │
                    │ (Background Process)    │
                    │ • Fetch Orders          │
                    │ • Auto-match SKUs       │
                    │ • Push Stock Levels     │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │     POSTGRES DB         │
                    │ • order                 │
                    │ • order_item            │
                    │ • product_variant       │
                    │ • platform_listing      │
                    │ • inventory_item        │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │     API SERVICE         │
                    │ • REST Endpoints        │
                    │ • Order Management      │
                    │ • Manual Matching       │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │   REACT FRONTEND        │
                    │ • Dashboard             │
                    │ • Order List            │
                    │ • SKU Matching UI       │
                    └─────────────────────────┘
```

---

## 5. Next Steps (Future Work)

### Immediate (After deployment):
1. [ ] Implement actual Amazon SP-API calls in `amazon/client.py`
2. [ ] Implement actual eBay API calls in `ebay/client.py`
3. [ ] Add frontend pages for Order Management
4. [ ] Add WebSocket for real-time order notifications

### Short-term:
1. [ ] Add `repairs` module for service ticket tracking
2. [ ] Add automated inventory allocation based on FIFO
3. [ ] Add order batching for multi-item shipments

### Long-term:
1. [ ] Add `crm` module for customer management
2. [ ] Add reporting/analytics module
3. [ ] Add automated repricing integration

---

## 6. Testing

### Run Tests
```bash
# Inside container
pytest tests/ -v

# Specific test file
pytest tests/test_orders.py -v
```

### Manual Testing
```bash
# Create an order
curl -X POST http://localhost:8080/api/v1/orders \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "MANUAL",
    "external_order_id": "TEST-001",
    "total_amount": 99.99,
    "items": [
      {
        "item_name": "Test Product",
        "quantity": 1,
        "unit_price": 99.99,
        "external_sku": "00845-Product"
      }
    ]
  }'

# Get order summary
curl http://localhost:8080/api/v1/orders/summary

# List unmatched items
curl http://localhost:8080/api/v1/orders/items/unmatched
```

---

**Implementation completed by:** GitHub Copilot  
**Date:** February 5, 2026