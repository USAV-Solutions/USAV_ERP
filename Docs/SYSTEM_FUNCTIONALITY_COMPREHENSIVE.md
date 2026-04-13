# USAV Inventory System - Comprehensive Functionality

Generated: April 10, 2026

## 1. System Purpose and Architecture

USAV Inventory is a hub-and-spoke commerce operations platform. It centralizes product, inventory, order, purchasing, and sync operations in one internal source of truth, then integrates with external channels and services.

Core architecture:
- Hub: FastAPI + PostgreSQL backend that owns product identity, stock state, and workflow status.
- Spokes: External platforms and services (Zoho, eBay stores, Ecwid, Amazon scaffolding).
- Clients: React frontend for operators and admins.
- Infrastructure: Docker Compose deployment with backups, migrations, and health endpoints.

Primary design goals:
- Maintain strict product identity integrity.
- Keep inventory and fulfillment workflows traceable.
- Support multi-channel order ingestion with safe, idempotent sync.
- Provide role-based access and audit-friendly operations.

## 2. Backend Functional Scope

### 2.1 API and Runtime

The backend is an async FastAPI application with:
- Unified API prefix: /api/v1 for core business APIs.
- Additional webhook routes outside /api/v1 for external callback simplicity.
- OpenAPI documentation and ReDoc.
- Root and health endpoints (/ and /health, /health/db).
- Lifespan startup/shutdown hooks for integration listener registration and DB shutdown.

### 2.2 Authentication and Access Control

Authentication and authorization features:
- JWT bearer token login endpoint.
- Password hashing and secure credential verification.
- Role-aware route protection via dependency injection.
- Current role model includes ADMIN, WAREHOUSE_OP, SALES_REP, and SYSTEM_BOT patterns.
- Optional SeaTalk OAuth-based sign-in flow for first-party user onboarding.
- User management APIs for admin workflows (create/update/manage users).

### 2.3 Product Catalog and Identity Model

The catalog uses a two-layer model:
- Product Family: High-level grouping and shared product metadata.
- Product Identity: Engineering-level identity (what the item is).
- Product Variant: Sellable representation (SKU, color, condition, naming, active state).

Key capabilities:
- Deterministic SKU and identity generation logic.
- Lookup management for brands, colors, conditions, and LCI definitions.
- Soft-active variant lifecycle controls.
- Relationship support between base identities and sellable variants.

### 2.4 Bundle and Kit Composition

Composition is supported through bundle component relationships:
- Parent-child identity mapping for bundles and kits.
- Quantity and role semantics (for bill-of-material style handling).
- Validation constraints to prevent invalid graph states.

### 2.5 Platform Listings

Platform listing functionality bridges internal variants to external channels:
- Create, update, and query platform listing records.
- Maintain external reference IDs and listing metadata.
- Track sync status using pending/synced/error states.
- Provide reverse lookup by platform and external ID for order matching.

### 2.6 Inventory Operations

Inventory tracks physical stock units and status transitions.

Core functions:
- Receive stock into the system (single/batch style flows).
- Move inventory by location/bin code.
- Reserve, release, sell, and RMA state transitions.
- Audit and reconcile inventory state.
- Summarize stock by variant and status for operational views.
- Persist cost basis and receiving/sold timestamps for downstream reporting.

### 2.7 Product Image Management

Image handling supports SKU-level and listing-aware media workflows:
- Upload and delete variant images.
- Gallery and thumbnail metadata APIs.
- Thumbnail derivation/backfill utilities.
- Frontend-friendly URLs for image rendering.
- Static-serving compatibility via Nginx path aliasing in production.

### 2.8 Orders Module

The orders module handles external ingestion and internal processing:
- Paginated order list and detailed order views.
- Order status and shipping status updates.
- Sync trigger endpoint for one platform or all configured platforms.
- Sync status dashboard with platform state visibility.
- Sync reset endpoint for stuck/error platform states.

Matching and resolution features:
- Order items begin unmatched when no trusted mapping exists.
- Automatic matching via external identifiers and learned listing links.
- Manual match/confirm/reject workflow for operations teams.
- Match-and-learn behavior can enrich future automatic resolution.

### 2.9 Purchasing Module

Purchasing functionality includes vendor and PO lifecycle management:
- Vendor CRUD.
- Purchase order creation, update, and retrieval.
- Purchase order item add/edit/delete flows.
- Item-to-variant matching workflows.
- Receiving and delivered-state operations.
- Multi-source import tooling (including Zoho and marketplace file/API pathways).
- Total recalculation logic including line totals and extra charges where applicable.

### 2.10 Integrations and External Connectors

Implemented integration patterns:
- eBay connectors for multiple stores with credential-aware client construction.
- Ecwid connector with order retrieval and operational actions.
- Zoho connector for inventory/business object synchronization.
- Amazon connector scaffolding for future full SP-API extension.

Shared integration behavior:
- Standardized client abstraction for platform operations.
- Credential-driven activation (client created only when config is present).
- Normalization of external payloads into internal models.

### 2.11 Zoho Two-Way Sync Engine

Zoho sync is designed for controlled bi-directional processing:
- Outbound sync listeners can be enabled/disabled by settings.
- Inbound webhook handlers can be enabled/disabled by settings.
- Item, contact, and sales order event pipelines are registered through startup hooks.
- Echo-loop prevention and sync-safety mechanisms are built into the integration layer.
- Manual force-sync endpoints are available for controlled operations.

### 2.12 Data Layer and Repository Pattern

Data access follows repository-driven patterns:
- Async SQLAlchemy sessions through dependency injection.
- Shared base repository for generic CRUD and pagination patterns.
- Domain repositories for products, inventory, orders, purchasing, and users.
- Transaction boundaries with explicit commit/rollback behavior in route/service layers.

### 2.13 Background Tasks and Data Utilities

Operational scripts and tasks support system maintenance:
- Data backfills (variant naming, thumbnails, bundle defaults).
- Import scripts for CSV and external dataset migration.
- Cleanup scripts for stale/integrity-sensitive records.
- Reconciliation task support for sync correctness checks.

## 3. Frontend Functional Scope

### 3.1 Application Shell and Access

The frontend is a React + TypeScript SPA with:
- Protected route model and role-based route guards.
- Auth context for user/session state.
- Persistent token/user storage for session continuity.
- Shared layout with navigation and module entry points.

### 3.2 Data Fetching and API Client Behavior

Client communication uses Axios + React Query:
- Centralized endpoint registry.
- Request interceptor for bearer token injection.
- Response interceptor for 401 handling and session reset.
- Query cache strategy with targeted invalidation after mutations.

### 3.3 Functional Pages and Workspaces

Current page-level business capabilities:
- Dashboard: role-aware summary and quick actions.
- Inventory management: variant and stock operations, image management, sync actions.
- Product listings: listing CRUD and platform mapping workflows.
- Orders management: order table, sync controls, item resolution modal workflows.
- Purchasing management: vendors, POs, item matching, receiving/delivery actions.
- Warehouse operations and stock lookup: operational search and updates.
- User management: admin user lifecycle operations.
- Login + SeaTalk callback: credential and SSO entry flows.

### 3.4 UI Components and Operator Productivity

The UI includes reusable operational components:
- Role guards and secure layout wrappers.
- Variant search/autocomplete for matching workflows.
- Resolution and status widgets for order/item handling.
- Dialog-based CRUD patterns for high-speed data entry.
- Data-grid heavy pages for pagination/filtering of large datasets.

## 4. Sync and Workflow Reliability

### 4.1 Safe Sync Principles

Order and integration sync paths implement reliability controls:
- Platform state tracking (idle/syncing/error patterns).
- Controlled sync windowing and repeat-safe ingestion.
- Duplicate prevention through schema constraints and application checks.
- Explicit reset/recovery APIs for operations and support.

### 4.2 Integrity and Deduplication

Data integrity is protected by:
- Unique constraints across identity, variant, and listing mappings.
- External reference mapping rules for cross-platform consistency.
- Transaction-scoped writes in critical workflows.
- Manual correction workflows for edge cases where automatic matching is uncertain.

## 5. Operations, Deployment, and Quality

### 5.1 Deployment and Environments

Deployment model supports local and containerized operation:
- Docker Compose orchestration for backend, frontend, database, and optional tools.
- Alembic migrations for versioned schema evolution.
- Environment-variable-driven connector and feature toggles.
- Health checks for service readiness and availability.

### 5.2 Backups and Recoverability

The project includes structured backup directories and retention-oriented workflows:
- Daily/weekly/monthly backup grouping.
- Operational restore pathways for incident response.

### 5.3 Testing and Validation

Quality controls include:
- API and module tests for core domains.
- Integration parsing tests for external payload normalization.
- Service-level tests for sync behaviors and edge cases.
- Type-checked frontend build pipeline.

## 6. End-to-End Business Outcomes

The system currently delivers:
- Centralized multi-channel commerce operations on a single product and inventory model.
- Controlled synchronization between internal truth and external systems.
- Role-specific operational tooling for sales, warehouse, and admin teams.
- Scalable module boundaries for continued expansion (additional platforms, deeper automation, advanced analytics).

## 7. Known Extensibility Directions

The architecture is already positioned for:
- Full Amazon SP-API production expansion.
- More automated purchase/import normalization.
- Enhanced reconciliation automation and discrepancy workflows.
- Additional reporting and KPI dashboards on top of existing operational data.
