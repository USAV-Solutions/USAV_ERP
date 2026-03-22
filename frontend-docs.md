# USAV Inventory – Frontend Documentation

---

## 1. FRONTEND ARCHITECTURE & STATE FLOW

### Tech Stack

| Layer | Technology | Version |
|---|---|---|
| **Framework** | React | 18.2 |
| **Language** | TypeScript | 5.3 |
| **Build Tool** | Vite | 5.0 |
| **UI Library** | Material UI (MUI) | 5.15 |
| **Data Grid** | MUI X Data Grid | 6.19 |
| **Styling** | Emotion (`@emotion/react`, `@emotion/styled`) | 11.11 |
| **Server-State** | TanStack React Query | 5.17 |
| **HTTP Client** | Axios | 1.6 |
| **Routing** | React Router DOM | 6.21 |

### Global State Management

The application does **not** use Redux, Zustand, or similar global stores. Instead, state is managed through two complementary patterns:

1. **React Context (Auth only)** – A single `AuthContext` (provided by `AuthProvider` in `useAuth.tsx`) holds the current user object, authentication status, and role-checking helpers. It persists the JWT and user payload in `localStorage`.
2. **TanStack React Query (server-state)** – All API data (inventory, orders, listings, users, sync status) is fetched and cached using React Query. Query keys are carefully structured to allow targeted invalidation after mutations. The default stale time is 5 minutes with a single retry.

There is no client-side form library; local `useState` hooks manage form state within dialogs and pages.

### Routing Strategy

React Router v6 with nested `<Route>` declarations inside `App.tsx`. Two route groups exist:

- **Public routes** – `/login` and `/auth/seatalk/callback`.
- **Protected routes** – Wrapped in a `RoleGuard` that checks authentication and the user's role (`ADMIN`, `WAREHOUSE_OP`, `SALES_REP`). A shared `Layout` component (sidebar + top bar) wraps all protected routes via `<Outlet />`.

Route access is role-gated at multiple levels: the outer guard ensures login, while inner `RoleGuard` wrappers restrict specific routes (e.g., `/admin/users` is `ADMIN`-only).

### Backend / API Interaction

All HTTP communication flows through a central Axios instance (`axiosClient.ts`):

- **Base URL:** `/api/v1` – during development, Vite proxies this to the backend container (`usav_backend_dev:8080`); in production, Nginx proxies it to the `backend:8080` service.
- **Authentication:** A request interceptor attaches the `Bearer` JWT from `localStorage`. A response interceptor catches 401 errors, clears stored credentials, and redirects to `/login`.
- **Endpoint registry:** All API paths are centralized in `endpoints.ts` as named constant objects (`AUTH`, `INVENTORY`, `CATALOG`, `LOOKUPS`, `LISTINGS`, `IMAGES`, `ZOHO`, `SYNC`, `ORDERS`, `PURCHASING`).
- **Service functions:** Domain-specific wrapper files (`api/orders.ts`, `api/sync.ts`, `api/purchasing.ts`) provide typed async functions consumed by React Query hooks in pages/components.

---

## 2. DIRECTORY STRUCTURE

```
frontend/
├── index.html                          # HTML shell – mounts #root, loads Google Fonts Roboto
├── package.json                        # Dependencies & scripts (dev, build, preview)
├── vite.config.ts                      # Vite config – React plugin, dev proxy to backend
├── tsconfig.json                       # TypeScript config – strict mode, path alias @/*
├── tsconfig.node.json                  # Separate TS config for vite.config.ts
├── nginx.conf                          # Production Nginx – SPA fallback, API proxy, image serving
├── Dockerfile                          # Production multi-stage build (Node → Nginx)
├── Dockerfile.dev                      # Development container with hot-reload
│
└── src/
    ├── main.tsx                        # Entry point – providers (QueryClient, Router, Theme, Auth)
    ├── App.tsx                         # Route definitions & role-based guards
    ├── theme.ts                        # MUI theme customization (palette, typography)
    │
    ├── api/                            # HTTP / API layer
    │   ├── axiosClient.ts              # Configured Axios instance (interceptors, base URL)
    │   ├── endpoints.ts                # Centralized API endpoint path constants
    │   ├── orders.ts                   # Order CRUD, sync, & SKU resolution API functions
    │   ├── purchasing.ts               # Vendor / Purchase Order / Receiving API functions
    │   └── sync.ts                     # Force-sync (two-way Zoho) API functions
    │
    ├── types/                          # TypeScript interfaces & type aliases
    │   ├── auth.ts                     # User, AuthResponse, LoginCredentials, UserRole
    │   ├── inventory.ts                # Product, Variant, Listing, Lookup types
    │   ├── orders.ts                   # Order, OrderItem, Sync, Integration types
    │   └── purchasing.ts               # Vendor / Purchase Order / Receive payload types
    │
    ├── hooks/                          # Custom React hooks
    │   ├── useAuth.tsx                 # AuthContext provider + useAuth consumer hook
    │   └── useScanner.ts              # Barcode scanner keyboard-input detection hook
    │
    ├── components/                     # Reusable UI components
    │   ├── common/
    │   │   ├── Layout.tsx              # App shell: sidebar nav, top bar, user menu, <Outlet />
    │   │   ├── SeaTalkLoginButton.tsx  # SeaTalk OAuth SDK button with loading overlay
    │   │   └── VariantSearchAutocomplete.tsx # Shared SKU search Autocomplete used by matching flows
    │   ├── guards/
    │   │   └── RoleGuard.tsx           # Auth + role gate (redirects or renders children/Outlet)
    │   ├── inventory/
    │   │   ├── CreateProductDialog.tsx # Add-variant dialog for existing Product/Kit identities
    │   │   ├── CreateStockDialog.tsx   # Dialog to add an inventory stock item to a variant
    │   │   ├── ImageGalleryModal.tsx   # SKU image gallery with carousel & thumbnail strip
    │   │   ├── ProductThumbnail.tsx    # Lazy-loaded thumbnail with skeleton + error fallback
    │   │   └── VariantImageDialog.tsx  # Upload/delete/manage variant images (drag-drop + preview)
    │   └── orders/
    │       ├── AdminDateRangeSync.tsx  # Admin dialog for historical date-range order sync
    │       ├── OrderItemsPanel.tsx     # Expandable panel showing line items + match workflow
    │       ├── OrderSyncButton.tsx     # Button/dialog to trigger incremental order sync
    │       ├── ResolutionModal.tsx     # Full order detail dialog with SKU resolution actions
    │       └── StatusBadge.tsx         # Colored MUI Chip for order/item status enums
    │
    └── pages/                          # Route-level page components
        ├── Dashboard.tsx               # Welcome banner + role-filtered quick-action cards
        ├── Login.tsx                   # Username/password form + SeaTalk SSO button
        ├── SeaTalkCallback.tsx         # OAuth callback – exchanges code for JWT
        ├── WarehouseOps.tsx            # SKU stock lookup + Create Stock button
        ├── InventoryManagement.tsx     # Variant catalog: list/grouped views, Zoho sync, CRUD
        ├── ProductListings.tsx         # Platform listings: filter/group by family, CRUD, delete
        ├── OrdersManagement.tsx        # Orders table: sync status, filters, expand items, Zoho sync
        ├── PurchasingManagement.tsx    # Vendors + PO list/detail, item matching, mark delivered
        ├── StockLookup.tsx             # Simple SKU audit lookup (DataGrid)
        └── UserManagement.tsx          # Admin CRUD for users: create, edit, password, delete
```

---

## 3. FILE-BY-FILE DOCUMENTATION

---

### `index.html` (Path: `/frontend/index.html`)
* **Purpose:** The single-page application HTML shell. Serves as the static entry point for Vite.
* **Dependencies & Props:** Loads Google Fonts (Roboto) via CDN. References `/src/main.tsx` as the module entry.
* **Mechanism / Render Logic:** Provides the `<div id="root">` mount point. Sets viewport meta, charset, and page title ("USAV Inventory System").

---

### `package.json` (Path: `/frontend/package.json`)
* **Purpose:** Project manifest defining dependencies, dev dependencies, and npm scripts.
* **Dependencies & Props:** Key runtime deps: React 18, MUI 5, React Query 5, Axios, React Router 6. Dev deps: Vite 5, TypeScript 5, `@vitejs/plugin-react`.
* **Mechanism / Render Logic:** Scripts: `dev` (Vite dev server on port 3636), `build` (TypeScript check + Vite build), `build:no-check` (skip TS check), `preview`, `check` (type-only validation).

---

### `vite.config.ts` (Path: `/frontend/vite.config.ts`)
* **Purpose:** Vite build and dev-server configuration.
* **Dependencies & Props:** Uses `@vitejs/plugin-react`.
* **Mechanism / Render Logic:** Dev server runs on port 3636 (`0.0.0.0`). Proxies all `/api` requests to `http://usav_backend_dev:8080` (the Docker backend service) during development.

---

### `tsconfig.json` (Path: `/frontend/tsconfig.json`)
* **Purpose:** TypeScript compiler configuration for the `src/` directory.
* **Dependencies & Props:** References `tsconfig.node.json` for Vite config.
* **Mechanism / Render Logic:** Targets ES2020 with `react-jsx` transform. Enables strict mode, no unused locals/params. Defines path alias `@/*` → `src/*`. Uses bundler module resolution.

---

### `tsconfig.node.json` (Path: `/frontend/tsconfig.node.json`)
* **Purpose:** Separate TypeScript configuration scoped to `vite.config.ts`.
* **Dependencies & Props:** Marked as `composite` for project references.
* **Mechanism / Render Logic:** Uses ESNext module resolution with synthetic default imports enabled.

---

### `nginx.conf` (Path: `/frontend/nginx.conf`)
* **Purpose:** Production Nginx configuration for the frontend container.
* **Dependencies & Props:** Serves built static files from `/usr/share/nginx/html`. Proxies to `backend:8080`.
* **Mechanism / Render Logic:** Key behaviors: (1) API requests (`/api/`) are reverse-proxied to the backend with WebSocket upgrade headers. This includes image upload requests such as `POST /api/v1/images/{sku}/upload`. (2) `client_max_body_size 50m` allows larger multipart image uploads. (3) `/health` is proxied to the backend health check. (4) `/product-images/` is served directly from a mounted host path (`/mnt/product_images/`) for high-performance static image delivery after files are stored. (5) Image API metadata/file endpoints under `/api/v1/images/` are proxied to backend routes. (6) SPA fallback (`try_files $uri /index.html`). (7) Static assets are cached for 1 year with immutable headers. Gzip compression is enabled.

---

### `main.tsx` (Path: `/frontend/src/main.tsx`)
* **Purpose:** Application entry point. Sets up the React tree with all global providers.
* **Dependencies & Props:** Imports `QueryClientProvider` (React Query), `BrowserRouter` (routing), `ThemeProvider` + `CssBaseline` (MUI), `AuthProvider` (auth context).
* **Mechanism / Render Logic:** Creates a `QueryClient` with a 5-minute stale time and 1 retry. Wraps `<App />` in provider hierarchy: `QueryClientProvider` → `BrowserRouter` → `ThemeProvider` → `AuthProvider`. Renders into `#root` via `createRoot` with `StrictMode`.

---

### `App.tsx` (Path: `/frontend/src/App.tsx`)
* **Purpose:** Top-level route configuration and navigation structure.
* **Dependencies & Props:** Uses `useAuth` hook for `isAuthenticated`. Imports all page components and the `Layout`/`RoleGuard` wrappers.
* **Mechanism / Render Logic:** Defines the full route tree:
  - `/login` – renders `Login` if not authenticated, redirects to `/` if already logged in.
  - `/auth/seatalk/callback` – SeaTalk OAuth callback handler.
  - All other routes are nested under a `RoleGuard` + `Layout` wrapper that requires authentication.
  - `/` – Dashboard (all roles).
  - `/warehouse/ops` – WarehouseOps (ADMIN, WAREHOUSE_OP).
  - `/catalog/inventory` – InventoryManagement (ADMIN, SALES_REP).
  - `/catalog/listings` – ProductListings (ADMIN, SALES_REP).
  - `/orders` – OrdersManagement (ADMIN, SALES_REP, WAREHOUSE_OP).
  - `/purchasing` – PurchasingManagement (ADMIN, SALES_REP, WAREHOUSE_OP).
  - `/admin/users` – UserManagement (ADMIN only).
  - `*` – Catch-all redirect to `/`.

---

### `theme.ts` (Path: `/frontend/src/theme.ts`)
* **Purpose:** MUI theme customization.
* **Dependencies & Props:** Uses `createTheme` from MUI.
* **Mechanism / Render Logic:** Light mode palette with standard Material colors (primary blue `#1976d2`, secondary pink `#dc004e`, green/amber/red for success/warning/error). Background default is light grey (`#f5f5f5`). Typography uses Roboto. Buttons have `textTransform: 'none'` (no uppercase).

---

### `axiosClient.ts` (Path: `/frontend/src/api/axiosClient.ts`)
* **Purpose:** Configured Axios HTTP client shared across the entire application.
* **Dependencies & Props:** Axios library. No component dependencies.
* **Mechanism / Render Logic:** Base URL is `/api/v1`. **Request interceptor:** reads `access_token` from `localStorage` and attaches it as a `Bearer` Authorization header. **Response interceptor:** on 401 responses, clears stored credentials (`access_token`, `user`) and redirects to `/login`. All API service functions import this instance.

---

### `endpoints.ts` (Path: `/frontend/src/api/endpoints.ts`)
* **Purpose:** Centralized registry of all backend API endpoint paths.
* **Dependencies & Props:** Pure constants — no dependencies.
* **Mechanism / Render Logic:** Exports named constant objects, each containing static paths or parameterized path-builder functions:
  - `AUTH` – `/token`, `/users/me`.
  - `INVENTORY` – audit, receive, move, lookup.
  - `CATALOG` – families, identities, variants (CRUD + search), bundles.
  - `LOOKUPS` – brands, colors, conditions, LCI definitions.
  - `LISTINGS` – list, CRUD, platform-ref lookups, pending/error filters, sync-status marking.
  - `IMAGES` – per-SKU images, thumbnails, batch thumbnails, debug backfill/counters.
  - `ZOHO` – item sync, readiness check, progress/start/stop for background sync job.
  - `SYNC` – force-sync endpoints for items, orders, purchases, and customers (two-way Zoho engine).
  - `ORDERS` – CRUD, shipping-status update endpoint (`/orders/{id}/shipping`), sync/sync-range/sync-status/reset, SKU resolution (match/confirm/reject).
  - `PURCHASING` – vendors, purchases, add PO line items (`/purchases/{id}/items`), delete PO line items (`/purchases/items/{item_id}`), Zoho import (`/purchases/import/zoho`), item matching, and mark-delivered endpoints.

---

### `purchasing.ts` (Path: `/frontend/src/api/purchasing.ts`)
* **Purpose:** Typed API service functions for Vendor and Purchase Order workflows.
* **Dependencies & Props:** Imports `axiosClient`, `PURCHASING` endpoints, and purchasing types from `types/purchasing.ts`.
* **Mechanism / Render Logic:** Exports async functions for listing/creating/updating vendors, listing/creating/getting purchase orders (including paged listing), adding PO line items, matching PO items to variants, deleting PO items, marking POs delivered with receipt payloads, and importing purchasing data from Zoho.

---

### `TablePaginationWithPageJump.tsx` (Path: `/frontend/src/components/common/TablePaginationWithPageJump.tsx`)
* **Purpose:** Reusable table pagination control with direct page selection.
* **Dependencies & Props:** Wraps MUI `TablePagination`; accepts `count`, `page`, `rowsPerPage`, `rowsPerPageOptions`, and page/row change handlers.
* **Mechanism / Render Logic:** Combines standard pagination controls with a `Page` number input and `Go` action (also supports Enter key).

---

### `VariantSearchAutocomplete.tsx` (Path: `/frontend/src/components/common/VariantSearchAutocomplete.tsx`)
* **Purpose:** Shared SKU search + selection component used by manual item matching workflows.
* **Dependencies & Props:** Uses MUI `Autocomplete`, React Query, `searchVariants`, and `useDebouncedValue`.
* **Mechanism / Render Logic:** Maintains independent selected value and text input states, debounces search text, queries `GET /variants/search`, and renders SKU/name rich options. This keeps order-item and purchasing-item matching interactions visually and behaviorally consistent.

---

### `purchasing.ts` (Path: `/frontend/src/types/purchasing.ts`)
* **Purpose:** TypeScript interfaces mirroring backend purchasing schemas.
* **Dependencies & Props:** None – pure type declarations.
* **Mechanism / Render Logic:** Defines vendor, purchase order, purchase order item (including optional `variant_sku` display field), delivery status enums, reusable PO item create payload, item-match request, receipt payload, mark-delivered response types, and Zoho purchasing import response types.

---

### `orders.ts` (Path: `/frontend/src/api/orders.ts`)
* **Purpose:** Typed API service functions for the Orders module.
* **Dependencies & Props:** Imports `axiosClient`, `ORDERS` and `CATALOG` endpoints, and order/variant types from `types/orders.ts`.
* **Mechanism / Render Logic:** Exports async functions organized into three groups:
  1. **Order CRUD** – `listOrders` (with query-string filters for skip, limit, platform, status, item_status, search), `getOrder`, `updateOrderStatus`, `updateShippingStatus`.
  2. **Sync** – `syncOrders` (incremental), `syncOrdersRange` (admin date-range), `getSyncStatus`, `resetSyncState`.
  3. **SKU Resolution** – `matchItem`, `confirmItem`, `rejectItem` (POST to items endpoints).
  4. **Variant Search** – `searchVariants` calls `GET /variants/search?q=...` for the resolution autocomplete.

---

### `sync.ts` (Path: `/frontend/src/api/sync.ts`)
* **Purpose:** API wrappers for the two-way Zoho force-sync engine.
* **Dependencies & Props:** Imports `axiosClient` and `SYNC` endpoints.
* **Mechanism / Render Logic:** Four functions (`forceSyncItem`, `forceSyncOrder`, `forceSyncPurchase`, `forceSyncCustomer`) each POST to the corresponding endpoint and return a `ForceSyncResponse` with `{ status: 'queued', entity, id }`.

---

### `auth.ts` (Path: `/frontend/src/types/auth.ts`)
* **Purpose:** TypeScript type definitions for authentication entities.
* **Dependencies & Props:** None – pure type declarations.
* **Mechanism / Render Logic:** Exports: `UserRole` (union: `'ADMIN' | 'WAREHOUSE_OP' | 'SALES_REP'`), `User` (id, username, role, is_active), `AuthResponse` (access_token, token_type), `LoginCredentials` (username, password).

---

### `inventory.ts` (Path: `/frontend/src/types/inventory.ts`)
* **Purpose:** TypeScript interfaces for the inventory and catalog domain.
* **Dependencies & Props:** None – pure type declarations.
* **Mechanism / Render Logic:** Comprehensive type coverage:
  - **Enums as unions:** `ZohoSyncStatus`, `ProductType`, `ItemCondition`, `ItemStatus`, `Platform`, `PlatformSyncStatus`.
  - **Lookup types:** `Brand`, `Color`, `Condition`, `LCIDefinition`.
  - **Product hierarchy:** `ProductFamily` → `ProductIdentity` → `Variant`.
  - **Inventory:** `InventoryItem`, `InventoryAudit`.
  - **Extended UI types:** `InventoryListItem`, `GroupedInventoryItem`, `CreateProductFormData`.
  - **Bundle:** `BundleComponent`.
  - **Listings:** `PlatformListing`, `PlatformListingCreate`, `PlatformListingUpdate`.

---

### `orders.ts` (Path: `/frontend/src/types/orders.ts`)
* **Purpose:** TypeScript interfaces mirroring the backend Pydantic schemas for orders and sync.
* **Dependencies & Props:** None – pure type declarations.
* **Mechanism / Render Logic:** Defines:
  - **Enums:** `OrderPlatform` (7 values including ZOHO, MANUAL), `OrderStatus` (9 states), `ShippingStatus` (6 fulfilment states), `OrderItemStatus` (5 states), `IntegrationSyncStatus`, `ZohoSyncStatus`.
  - **Order items:** `OrderItemBrief`, `OrderItemDetail`, `VariantSearchResult`, `OrderItemMatchRequest`, `OrderItemConfirmRequest`.
  - **Order headers:** `OrderBrief` (list row, includes `shipping_status`), `OrderDetail` (full record with address, financials, items, and `shipping_status`), `OrderListResponse` (paginated), `OrderStatusUpdate`, `ShippingStatusUpdate`.
  - **Sync:** `IntegrationStateResponse`, `SyncRequest`, `SyncRangeRequest`, `SyncResponse`, `SyncStatusResponse`.

---

### `useAuth.tsx` (Path: `/frontend/src/hooks/useAuth.tsx`)
* **Purpose:** Authentication context provider and consumer hook. The single source of truth for auth state.
* **Dependencies & Props:** Uses React Context API, `localStorage`, and Axios (direct, not `axiosClient`) for the login POST.
* **Mechanism / Render Logic:**
  - **`AuthProvider`**: On mount, checks `localStorage` for an existing token/user pair. Exposes `login` (sends form-encoded credentials to `/api/v1/auth/token`, decodes the JWT to extract user info), `loginWithToken` (for SeaTalk SSO flow), `logout` (clears storage), and `hasRole` (checks role membership).
  - **JWT decoding**: A helper `decodeToken` parses the JWT payload (base64url) to extract `sub`, `role`, and `username`.
  - **`useAuth` hook**: Consumes the context with a guard that throws if used outside the provider.

---

### `useScanner.ts` (Path: `/frontend/src/hooks/useScanner.ts`)
* **Purpose:** Custom hook for detecting barcode scanner input.
* **Dependencies & Props:** Uses `useEffect`, `useCallback`, `useRef`. Accepts `onScan` callback, configurable `minLength` (default 3) and `maxDelay` (default 50ms).
* **Mechanism / Render Logic:** Barcode scanners emulate rapid keyboard input followed by Enter. The hook listens for `keydown` events globally. Characters arriving within `maxDelay` ms are buffered; on Enter, if the buffer meets `minLength`, `onScan` is called with the accumulated string. Returns a `clearBuffer` function.

---

### `Layout.tsx` (Path: `/frontend/src/components/common/Layout.tsx`)
* **Purpose:** Application shell for all authenticated pages. Provides persistent navigation sidebar and top app bar.
* **Dependencies & Props:** Uses `useAuth` (for user info, logout, role filtering), `useNavigate`, `useLocation` from React Router. No external props — it renders `<Outlet />` for child routes.
* **Mechanism / Render Logic:**
  - **Sidebar (240px drawer):** Contains the "USAV Inventory" branding and a navigation list. Nav items are role-filtered (e.g., User Management only visible to ADMIN). Each item highlights when its path matches the current location. On mobile, the drawer is a toggleable temporary drawer; on desktop, it is permanently visible.
  - **Top bar:** Displays the current page title (derived from nav items), a user avatar button that opens a dropdown menu showing username/role and a Logout action.
  - **Main content area:** Renders `<Outlet />` with padding, offset by the toolbar height and drawer width.
  - **Navigation items:** Dashboard, Warehouse Operations, Inventory Management, Product Listings, Orders, User Management.

---

### `SeaTalkLoginButton.tsx` (Path: `/frontend/src/components/common/SeaTalkLoginButton.tsx`)
* **Purpose:** Renders a SeaTalk OAuth login button using the SeaTalk auth SDK.
* **Dependencies & Props:** Accepts optional props: `size` (`'small' | 'medium' | 'large'`), `theme` (`'light' | 'dark'`), `copywriting` (button label), `align`. Reads `VITE_SEATALK_APP_ID` and `VITE_SEATALK_REDIRECT_URI` from environment variables.
* **Mechanism / Render Logic:**
  - Dynamically loads the SeaTalk auth SDK script (`auth.js` from CDN) on first mount.
  - Injects a hidden `#seatalk_login_app_info` div with OAuth parameters (app ID, redirect URI, response type, random state).
  - Renders a `#seatalk_login_button` div that the SDK populates with its styled button.
  - Uses a `MutationObserver` + safety timeout (6 seconds) to detect when the SDK finishes rendering, showing a loading spinner in the interim.
  - If env vars are missing, renders nothing.

---

### `RoleGuard.tsx` (Path: `/frontend/src/components/guards/RoleGuard.tsx`)
* **Purpose:** Route protection component that enforces authentication and role-based access control.
* **Dependencies & Props:** Accepts `allowedRoles: UserRole[]` and optional `children`. Uses `useAuth` for auth state.
* **Mechanism / Render Logic:**
  - While auth is loading, shows a centered `CircularProgress` spinner.
  - If not authenticated, redirects to `/login`.
  - If authenticated but role not in `allowedRoles`, redirects to `/` (dashboard).
  - If authorized, renders `children` (when used as a wrapper) or `<Outlet />` (when used as a route element).

---

### `CreateProductDialog.tsx` (Path: `/frontend/src/components/inventory/CreateProductDialog.tsx`)
* **Purpose:** Focused dialog for adding a new variant to an existing parent product/kit identity.
* **Dependencies & Props:** Accepts `open: boolean`, `onClose: () => void`, and optional `onCreated?: (fullSku: string) => void`. Uses React Query for colors, conditions, identities, families, and variants.
* **Mechanism / Render Logic:**
  - Parent selector uses Autocomplete over existing identities (restricted to Product and Kit).
  - Optional variant-name edit updates the parent family base_name before creating the variant.
  - Color and condition selectors are optional.
  - Condition normalization: U/Used is treated as default and omitted from variant payload.
  - **SKU preview** calculated live from current selections.
  - Existing variants for the selected parent are displayed as chips for quick duplicate awareness.
  - Mutation flow: optional family-name update, then create variant under selected identity.
  - On successful variant creation, emits `onCreated(full_sku)` so the parent page can immediately open image management for that new SKU.
  - Form state resets on dialog open and close.

---

### `CreateStockDialog.tsx` (Path: `/frontend/src/components/inventory/CreateStockDialog.tsx`)
* **Purpose:** Dialog for creating a new physical stock/inventory item against an existing variant.
* **Dependencies & Props:** Accepts `open`, `onClose`, optional `onSuccess`. Fetches variants, identities, and families via React Query.
* **Mechanism / Render Logic:**
  - **Variant selection:** Autocomplete searching enhanced variants (SKU + product name).
  - **Form fields:** Serial number (optional), location code (warehouse location), cost basis (number), status dropdown (AVAILABLE / RESERVED / SOLD / RMA / DAMAGED with color-coded dots), notes (multiline).
  - **Submit:** Posts to `/inventory` with the form payload.
  - On success, invalidates the `['inventory']` query cache and calls `onSuccess`.

---

### `ImageGalleryModal.tsx` (Path: `/frontend/src/components/inventory/ImageGalleryModal.tsx`)
* **Purpose:** Full-screen image gallery modal for viewing all product images associated with a SKU.
* **Dependencies & Props:** Accepts `open`, `onClose`, `sku`. Fetches images via `GET /images/{sku}`.
* **Mechanism / Render Logic:**
  - Fetches a `SkuImagesResponse` containing image URLs and metadata (listing name, total count).
  - **Main viewer:** Large centered image with left/right chevron navigation buttons.
  - **Thumbnail strip:** Clickable thumbnail grid below the main image, with a blue border highlighting the selected image.
  - **Keyboard navigation:** Left/Right arrow keys cycle through images.
  - Loading state shows a spinner; error/empty state shows a message.

---

### `VariantImageDialog.tsx` (Path: `/frontend/src/components/inventory/VariantImageDialog.tsx`)
* **Purpose:** Interactive image management modal for a single SKU, supporting upload, preview, and deletion.
* **Dependencies & Props:** Accepts `open`, `onClose`, `sku`. Uses React Query and mutations against image endpoints.
* **Mechanism / Render Logic:**
  - Upload flow uses backend endpoint `POST /images/{sku}/upload` with multipart `files[]` and `listing_index`.
  - Supports drag-drop and file-picker upload, with client-side validation (JPG/PNG/WEBP, 10 MB max each).
  - Displays current images in a selectable grid and a full-size preview area with arrow navigation.
  - Per-image delete uses `DELETE /images/{sku}/listing/{listing_index}/file/{filename}`.
  - On upload/delete success, invalidates `['sku-images', sku]` and `['variants']` caches so thumbnails refresh.

---

### `ProductThumbnail.tsx` (Path: `/frontend/src/components/inventory/ProductThumbnail.tsx`)
* **Purpose:** Compact thumbnail image component for product variants, used in table rows.
* **Dependencies & Props:** Accepts `sku`, optional `thumbnailUrl`, `size` (px, default 40), optional `onClick`. Falls back to `/api/v1/images/{sku}/thumbnail` if no URL provided.
* **Mechanism / Render Logic:**
  - Shows a `Skeleton` placeholder while the image loads.
  - On load success, fades the image in (opacity transition).
  - On error, shows a grey box with an `ImageNotSupported` icon.
  - Handles `img.complete` edge case (cached images that fire no load event).
  - Resets error/loaded state when the URL changes.

---

### `AdminDateRangeSync.tsx` (Path: `/frontend/src/components/orders/AdminDateRangeSync.tsx`)
* **Purpose:** Admin-only dialog for syncing orders within a custom historical date range.
* **Dependencies & Props:** No props. Uses `syncOrdersRange` from `api/orders.ts`. Invalidates `['orders']` and `['syncStatus']` caches on success.
* **Mechanism / Render Logic:**
  - **Trigger:** "Range Sync" outlined button.
  - **Dialog form:** Platform dropdown (All / Ecwid / eBay variants / Amazon), start datetime picker, end datetime picker.
  - **Validation:** Ensures start < end before enabling the submit button.
  - **Warning alert** clarifies this bypasses normal sync locks but safely skips duplicates.
  - **Results display:** Per-platform list with success/error icons and stats (new orders, auto-matched, skipped).

---

### `OrderItemsPanel.tsx` (Path: `/frontend/src/components/orders/OrderItemsPanel.tsx`)
* **Purpose:** Expandable inline panel showing an order's line items with SKU resolution actions. Renders inside a collapsed table row on the Orders page.
* **Dependencies & Props:** Accepts `orderId: number`. Fetches full `OrderDetail` via `getOrder`.
* **Mechanism / Render Logic:**
  - Shows a mini header (customer name, email, item count).
  - **Items table** with columns: Item Name, Ext SKU, Qty, Unit, Total, Status (`StatusBadge`), Variant SKU (Chip), Actions.
  - **`ItemRow` sub-component** handles per-item actions:
    - **UNMATCHED items:** "Match to variant" icon button opens an inline `VariantSearchAutocomplete` search bar backed by `GET /variants/search?q=...`. User selects a variant and clicks "Match".
    - **MATCHED items:** "Confirm match" (green check) and "Reject match" (red unlink) buttons.
  - All mutations invalidate the order, orders list, and sync status queries.
  - Matching notes are displayed below applicable rows.

---

### `OrderSyncButton.tsx` (Path: `/frontend/src/components/orders/OrderSyncButton.tsx`)
* **Purpose:** Button + dialog for triggering incremental order sync from platform APIs.
* **Dependencies & Props:** No props. Calls `syncOrders` from `api/orders.ts`.
* **Mechanism / Render Logic:**
  - **Trigger:** "Sync Orders" contained button with a Sync icon.
  - **Dialog:** Platform selector (same options as AdminDateRangeSync). Info alert explaining incremental sync behavior.
  - **Execution:** POSTs to `/orders/sync` with optional platform filter.
  - **Results:** Shows per-platform success/error list with new order counts, auto-matched counts, and skipped duplicates.
  - Invalidates orders and sync-status caches on success.

---

### `ResolutionModal.tsx` (Path: `/frontend/src/components/orders/ResolutionModal.tsx`)
* **Purpose:** Full order detail dialog with comprehensive SKU resolution actions. An alternative to the inline `OrderItemsPanel`.
* **Dependencies & Props:** Accepts `orderId: number | null` and `onClose`. Fetches `OrderDetail`.
* **Mechanism / Render Logic:**
  - **`OrderHeaderSection`** sub-component displays: customer info, shipping address, financial summary (subtotal/tax/shipping/total), order status badge, tracking info, processing notes, and error messages.
  - **Line items table** with the same columns as `OrderItemsPanel`.
  - **`ItemRow`** sub-component: UNMATCHED items get a manual variant ID text field + "Learn for auto-match" checkbox. MATCHED items get confirm/reject buttons. This variant uses a numeric Variant ID input rather than the Autocomplete used in `OrderItemsPanel`.
  - Platform labels are mapped from codes to human-readable names.

---

### `StatusBadge.tsx` (Path: `/frontend/src/components/orders/StatusBadge.tsx`)
* **Purpose:** Reusable MUI `Chip` component that renders a color-coded badge for order and item status values.
* **Dependencies & Props:** Accepts `status` (OrderStatus or OrderItemStatus), optional `size`, optional `itemLevel` boolean to switch between order-level and item-level color maps.
* **Mechanism / Render Logic:**
  - **Order statuses:** PENDING (warning), PROCESSING (primary), READY_TO_SHIP (info), SHIPPED/DELIVERED (success), CANCELLED/REFUNDED (default), ON_HOLD (warning), ERROR (error).
  - **Item statuses:** UNMATCHED (error), MATCHED (info), ALLOCATED (primary), SHIPPED (success), CANCELLED (default).
  - Falls back to a plain chip with the raw status string if the status is not in the config.

---

### `Dashboard.tsx` (Path: `/frontend/src/pages/Dashboard.tsx`)
* **Purpose:** Landing page after login. Shows a welcome banner and role-appropriate quick-action navigation cards.
* **Dependencies & Props:** Uses `useAuth` (for user, role check) and `useNavigate`.
* **Mechanism / Render Logic:**
  - **Welcome banner:** Gradient blue Paper showing the username and a role badge (Administrator / Warehouse Operator / Sales Representative) with corresponding colors.
  - **Quick action cards:** Grid of clickable cards filtered by the user's role. Each card has an icon (in a colored circle), title, and description. Available actions: Warehouse Operations, Inventory Management, Product Listings, User Management.
  - Cards have a hover animation (translateY, elevated shadow, colored border).

---

### `Login.tsx` (Path: `/frontend/src/pages/Login.tsx`)
* **Purpose:** Authentication page with dual login methods.
* **Dependencies & Props:** Uses `useAuth` (login function), `useNavigate`, and the `SeaTalkLoginButton` component.
* **Mechanism / Render Logic:**
  - Centered card layout with a lock icon and "USAV Inventory" branding.
  - **Username/password form:** Standard text inputs with submit button. On submit, calls `auth.login()` which sends form-encoded credentials to the backend OAuth2 endpoint.
  - **Divider** with "OR" text.
  - **SeaTalk SSO button:** Renders the `SeaTalkLoginButton` component for enterprise SSO login.
  - Error messages from failed login attempts are shown in an alert banner.

---

### `SeaTalkCallback.tsx` (Path: `/frontend/src/pages/SeaTalkCallback.tsx`)
* **Purpose:** OAuth callback handler for the SeaTalk SSO flow.
* **Dependencies & Props:** Uses `useSearchParams`, `useNavigate`, `useAuth` (loginWithToken).
* **Mechanism / Render Logic:**
  - Reads `code`, `state`, and `error` from URL search params.
  - If an error param is present, displays a failure message with a link back to login.
  - If a code is present, exchanges it via `GET /api/v1/auth/seatalk/callback?code=...&state=...` to get a JWT.
  - On success, calls `loginWithToken(access_token)` and navigates to `/`.
  - Uses a `useRef` guard (`hasExchanged`) to prevent double-execution in React 18 StrictMode.
  - Shows a spinner with "Completing SeaTalk login..." while the exchange is in progress.

---

### `WarehouseOps.tsx` (Path: `/frontend/src/pages/WarehouseOps.tsx`)
* **Purpose:** Warehouse operations page for stock lookup and creation.
* **Dependencies & Props:** Uses `useQuery` for inventory audit lookup, `useAuth` for role checks, and the `CreateStockDialog` component.
* **Mechanism / Render Logic:**
  - **Header:** Page title + "Create Stock" button (visible to ADMIN and WAREHOUSE_OP roles).
  - **Search bar:** Text field where Enter triggers a `GET /inventory/audit/{sku}` query.
  - **Results table:** MUI X `DataGrid` displaying inventory items with columns: Serial Number, Location, Status (color-coded badge), Received date. Paginated (10/25/50 rows).
  - **Notifications:** Success/error Snackbar feedback after stock creation.
  - **Create Stock Dialog:** Opens `CreateStockDialog`; on success, shows a notification with the created item's serial number or ID.

---

### `InventoryManagement.tsx` (Path: `/frontend/src/pages/InventoryManagement.tsx`)
* **Purpose:** The primary inventory catalog page. Lists all product variants with search, view modes, Zoho sync, and product creation.
* **Dependencies & Props:** Fetches variants, identities, and families via React Query. Uses `CreateProductDialog`, `ProductThumbnail`, `ImageGalleryModal`, and `VariantImageDialog` components.
* **Mechanism / Render Logic:**
  - **Header actions (ADMIN only):** "Sync All to Zoho" (triggers readiness check first, then bulk sync), "Backfill Thumbnails" (runs debug endpoint to populate missing thumbnails), "Add Variant" (opens `CreateProductDialog`).
  - Newly created variants can immediately open `VariantImageDialog` via the `CreateProductDialog` `onCreated` callback.
  - **Search bar + view toggle:** Text search filters by name, SKU, variant name, UPIS-H, or brand. Toggle between **list view** (flat table of all variants) and **grouped view** (rows grouped by product family, expandable).
  - **Server page aggregation:** Variants, identities, and families are fetched across all API pages (skip/limit loop) to avoid 1000-row truncation issues in type/search mapping.
  - **Filter/sort controls:** Type, condition, sync status, active/inactive, brand text filter, per-view sort fields, sort direction, and reset action.
  - **List view columns:** Image (thumbnail), Full SKU, Name, Type (chip), Parent UPIS-H, Color, Condition, Zoho Status (chip), Actions.
  - **Per-variant actions:** `Manage Images`, `Sync to Zoho`, plus admin-only `Edit` and `Delete` actions.
  - **Edit action (ADMIN):** Opens a dialog to update all mutable variant fields: `variant_name`, `color_code`, `condition_code`, and `is_active`.
  - **Delete action (ADMIN):** Soft-delete behavior; the variant is inactivated and archived (SKU moved to `D-{old_sku}`), rather than hard-removed.
  - **Grouped view:** Collapsible rows by product family (name, brand, variant count). Expanded rows include family summary chips (active/inactive counts and type breakdown) plus nested variant table/actions.
  - **Zoho sync features:** Single-variant sync, bulk sync (batch POST), readiness check dialog (shows checked/ready/blocked/warning counts + per-item detail table).
  - **Data enrichment:** Variants are enriched with identity and family data by joining across three parallel queries using `useMemo`.
  - **Pagination:** Client-side with MUI `TablePagination` (10/25/50/100 rows).

---

### `ProductListings.tsx` (Path: `/frontend/src/pages/ProductListings.tsx`)
* **Purpose:** Manages product listings across multiple e-commerce platforms (Amazon, eBay stores, Ecwid).
* **Dependencies & Props:** Fetches listings, variants, identities, and families via React Query. Contains the `CreateListingDialog` sub-component.
* **Mechanism / Render Logic:**
  - **Header:** "Product Listings" title + "Add Listing" button (ADMIN/SALES_REP).
  - **Filter bar:** Text search (SKU, name, external ref), Platform dropdown, Status dropdown (Synced/Pending/Error), Refresh button.
  - **Table (grouped by product family):** Collapsible rows showing family name, brand, and listing count. Expanded view shows a nested table with: SKU, Platform (chip), Listed Name, External Ref ID, Price, Sync Status (icon + colored chip with tooltip for error messages), Last Synced date, Delete action (ADMIN only).
  - **`CreateListingDialog`** sub-component: Form with variant Autocomplete, platform dropdown, external ref ID, listed name, description (multiline), and listing price. Posts to `LISTINGS.LIST`.
  - **Delete:** Confirmation dialog (`confirm()`) calls `DELETE /listings/{id}`.
  - **Pagination:** Client-side over the grouped family list.

---

### `OrdersManagement.tsx` (Path: `/frontend/src/pages/OrdersManagement.tsx`)
* **Purpose:** The main orders management page. Displays sync status, filterable order list, expandable order items, and Zoho sync capabilities.
* **Dependencies & Props:** Uses `listOrders`, `getSyncStatus`, `updateOrderStatus`, `updateShippingStatus` from `api/orders.ts`, `forceSyncOrder` from `api/sync.ts`. Composes `OrderSyncButton`, `AdminDateRangeSync`, and `OrderItemsPanel` components. Sync status auto-refreshes every 15 seconds.
* **Mechanism / Render Logic:**
  - **Header actions:** Refresh button, Admin Date-Range Sync (ADMIN), "Sync matched to Zoho" bulk button (ADMIN), Order Sync Button.
  - **Summary cards:** Total Orders, Unmatched Items (red), Matched Items (blue), Platforms (chip list with status-based coloring).
  - **Platform error alerts:** Auto-displayed warning banners for any platform in ERROR state.
  - **Filter bar:** Search (order ID / customer name), Platform dropdown, Order Status dropdown, Item Status dropdown, Reset button.
  - **Orders table** (server-paginated):
    - Columns: Expand toggle, Order # (external number), Platform (chip), Customer, Unmatched count (red chip if > 0), Total amount, Shipping Status (inline dropdown for direct status updates), Zoho Sync status (chip), Ordered date, Zoho sync button (ADMIN, triggers `forceSyncOrder`).
    - **Expandable rows:** Clicking a row expands to show `OrderItemsPanel` with full line-item details and match/confirm/reject actions.
  - **Inline status update:** Shipping status updates use a dedicated mutation (`PATCH /orders/{id}/shipping`) with its own loading state and feedback message that indicates Zoho sync is queued.
  - **Pagination UX:** Uses shared `TablePaginationWithPageJump` for rows-per-page and direct page jump.
  - **Bulk Zoho sync dialog:** Fetches all orders (up to 2000), filters to those with 0 unmatched items, and sequentially queues each for Zoho sync. Shows a progress bar, success/fail counts, and error messages.
  - **Feedback:** Snackbar notifications for force-sync success/failure.

---

### `PurchasingManagement.tsx` (Path: `/frontend/src/pages/PurchasingManagement.tsx`)
* **Purpose:** Main purchasing workspace for vendors and purchase orders.
* **Dependencies & Props:** Uses React Query + `api/purchasing.ts` and role checks from `useAuth`.
* **Mechanism / Render Logic:**
  - **Vendor actions in Create PO:** Vendor is selected via searchable autocomplete; users can create a new vendor directly from typed input using a Create Vendor action beside the search bar.
  - **PO actions:** Create PO dialog includes PO number, vendor search/create, dates, total, tax, shipping, handling, currency, and notes.
  - **PO list/detail:** Supports paged loading and expanded/collapsible table rows for line-item visibility.
  - **Date sorting:** Purchasing list supports date sort direction (`Newest first` / `Oldest first`) driven by server-side query parameters.
  - **Date filter:** Purchasing list supports date-range filtering (`From` / `To`) on order date with a clear-filter action.
  - **Pagination:** Uses shared `TablePaginationWithPageJump` with server-side `skip/limit` loading and direct page jump.
  - **PO unmatched count:** Main PO rows include an `Unmatched` count chip showing number of `UNMATCHED` line items.
  - **Line-item actions column:** Expanded PO line-item table exposes visible per-row actions to avoid relying on hidden gestures.
  - **Line-item creation:** Expanded PO section uses an Add New Item toggle; the inline Add Line form appears only when requested for that PO. Quantity and unit price are entered, and total price is auto-calculated as quantity × unit price.
  - **Immutable line-item total:** Edit and create flows treat total price as derived/read-only to keep totals consistent.
  - **Line-item total row:** Expanded line-items table displays a summary row showing the summed line-item total.
  - **Zoho import:** Includes bulk import trigger for vendors + purchase orders from Zoho with progress and result feedback.
  - **Purchase file import:** Header action **Import Purchase** opens source selection for `Goodwill`, `Amazon`, or `AliExpress`, then uploads the source-appropriate file type (`CSV` for Goodwill/Amazon, `JSON` for AliExpress).
  - **Amazon import exclusion rule:** Rows with `Account User = Dragonhn` are skipped during Purchasing import because they are treated as personal purchases.
  - **Random Zoho import test:** Header action **Import 1 Random PO** imports exactly one random purchase order from Zoho for quick import validation and displays selected PO metadata in feedback.
  - **PO force-sync:** Supports per-purchase force-sync to Zoho via `forceSyncPurchase`.
  - **Item matching:** Per-line-item Match action on `UNMATCHED` rows opens an inline search bar (same `VariantSearchAutocomplete` used by Order resolution), allowing SKU/name search and one-click match.
  - **Matched display detail:** In line-item rows, a matched item shows a smaller italic subline under the item name containing the matched in-database variant name.
  - **Item external view link:** Per-line-item eye icon opens `purchase_item_link` in a new tab; if no link exists, the eye action is disabled and rendered as inactive/grey.
  - **Unmatch action:** Matched items show a red unlink action (chain with slash) that resets the item back to `UNMATCHED`.
  - **Item delete:** Per-line-item Delete icon opens a confirmation dialog and calls `DELETE /purchases/items/{item_id}` (disabled for `RECEIVED` rows).
  - **Long-press edit:** Existing long-press edit prompt remains available for updating item fields and manual SKU correction.
  - **Mark delivered:** Admin/Warehouse action opens a receive dialog where each PO item receives quantity, optional serial numbers, and location code. Submitting calls `/purchases/{id}/mark-delivered`.
  - **Feedback:** Mutation results shown via Snackbar and query invalidation refreshes PO/vendor data.

---

### `StockLookup.tsx` (Path: `/frontend/src/pages/StockLookup.tsx`)
* **Purpose:** Simple standalone stock lookup page (appears to be an earlier/simpler version of the warehouse ops search).
* **Dependencies & Props:** Uses React Query and `axiosClient` for inventory audit lookups. Uses MUI X `DataGrid`.
* **Mechanism / Render Logic:**
  - Text input for SKU search (Enter to submit).
  - Fetches `GET /inventory/audit/{sku}` and displays results in a DataGrid with Serial Number, Location, Status (color-coded), and Received date columns.
  - Simpler than `WarehouseOps.tsx` (no stock creation, no notifications).

---

### `UserManagement.tsx` (Path: `/frontend/src/pages/UserManagement.tsx`)
* **Purpose:** Admin-only page for full CRUD management of system users.
* **Dependencies & Props:** Uses React Query and `axiosClient` directly (endpoints: `/auth/users`, `/auth/users/{id}`, `/auth/users/{id}/activate`, `/auth/users/{id}/deactivate`).
* **Mechanism / Render Logic:**
  - **Users table:** Columns: Username, Full Name, Email, SeaTalk ID (chip if linked), Role (colored chip), Active Status (toggle icon button), Last Login, Actions (Edit / Change Password / Delete icon buttons).
  - **Create/Edit dialog:** Form with username (disabled on edit), full name, email, password (only on create), role dropdown (Administrator / Warehouse Op / Sales Rep), active toggle switch.
  - **Change password dialog:** Single password field with 8-character minimum requirement.
  - **Delete dialog:** Confirmation before deletion.
  - **Toggle active:** Calls activate/deactivate endpoints; changes icon color between green check and grey cancel.
  - **Mutations:** Separate mutations for create, update, change password, delete, and toggle active, all invalidating the `['users']` cache.
  - **Notifications:** Success/error Snackbar for all operations.

---

*Document generated: 2026-03-16*
