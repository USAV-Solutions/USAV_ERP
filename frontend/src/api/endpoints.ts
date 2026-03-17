// Auth endpoints
export const AUTH = {
  LOGIN: '/token',
  ME: '/users/me',
}

// Inventory endpoints
export const INVENTORY = {
  AUDIT: (sku: string) => `/inventory/audit/${sku}`,
  RECEIVE: '/inventory/receive',
  MOVE: '/inventory/move',
  LOOKUP: '/inventory/lookup',
}

// Catalog endpoints
export const CATALOG = {
  FAMILIES: '/families',
  FAMILY: (id: number) => `/families/${id}`,
  IDENTITIES: '/identities',
  IDENTITY: (id: number) => `/identities/${id}`,
  VARIANTS: '/variants',
  VARIANT: (id: number) => `/variants/${id}`,
  VARIANT_SEARCH: '/variants/search',
  BUNDLES: '/bundles',
  BUNDLE: (id: number) => `/bundles/${id}`,
}

// Lookup endpoints
export const LOOKUPS = {
  BRANDS: '/brands',
  BRAND: (id: number) => `/brands/${id}`,
  COLORS: '/colors',
  COLOR: (id: number) => `/colors/${id}`,
  CONDITIONS: '/conditions',
  CONDITION: (id: number) => `/conditions/${id}`,
  LCI_DEFINITIONS: '/lci-definitions',
  LCI_DEFINITION: (id: number) => `/lci-definitions/${id}`,
}

// Listing endpoints
export const LISTINGS = {
  LIST: '/listings',
  LISTING: (id: number) => `/listings/${id}`,
  BY_PLATFORM_REF: (platform: string, refId: string) => `/listings/platform/${platform}/ref/${refId}`,
  PENDING: '/listings/pending',
  ERRORS: '/listings/errors',
  MARK_SYNCED: (id: number) => `/listings/${id}/mark-synced`,
  MARK_ERROR: (id: number) => `/listings/${id}/mark-error`,
}

// Product Image endpoints
export const IMAGES = {
  SKU_IMAGES: (sku: string) => `/images/${sku}`,
  THUMBNAIL: (sku: string) => `/images/${sku}/thumbnail`,
  FILE: (sku: string, filename: string) => `/images/${sku}/file/${filename}`,
  UPLOAD: (sku: string) => `/images/${sku}/upload`,
  DELETE_FILE: (sku: string, listing: number, filename: string) => `/images/${sku}/listing/${listing}/file/${filename}`,
  CLEAR_LISTING: (sku: string, listing: number) => `/images/${sku}/listing/${listing}/clear`,
  BATCH_THUMBNAILS: '/images/batch/thumbnails',
  DEBUG_BACKFILL: '/images/debug/backfill-thumbnails',
  DEBUG_COUNTERS: '/images/debug/counters',
}

export const ZOHO = {
  SYNC_ITEMS: '/zoho/sync/items',
  SYNC_SINGLE_ITEM: (variantId: number) => `/zoho/sync/items/${variantId}`,
  SYNC_READINESS: '/zoho/sync/readiness',
  SYNC_ITEMS_START: '/zoho/sync/items/start',
  SYNC_ITEMS_PROGRESS: '/zoho/sync/items/progress',
  SYNC_ITEMS_STOP: '/zoho/sync/items/stop',
}

// Force-sync (two-way Zoho sync engine) endpoints
export const SYNC = {
  ITEM: (variantId: number) => `/sync/items/${variantId}`,
  ORDER: (orderId: number) => `/sync/orders/${orderId}`,
  PURCHASE: (poId: number) => `/sync/purchases/${poId}`,
  PURCHASES: '/sync/purchases',
  CUSTOMER: (customerId: number) => `/sync/customers/${customerId}`,
}

// Order endpoints – matches Backend routes.py prefix /orders
export const ORDERS = {
  // CRUD
  LIST: '/orders',
  ORDER: (id: number) => `/orders/${id}`,
  DELETE: (id: number) => `/orders/${id}`,
  UPDATE_STATUS: (id: number) => `/orders/${id}`,
  UPDATE_SHIPPING: (id: number) => `/orders/${id}/shipping`,

  // Sync
  SYNC: '/orders/sync',
  SYNC_RANGE: '/orders/sync/range',
  SYNC_STATUS: '/orders/sync/status',
  SYNC_RESET: (platform: string) => `/orders/sync/${platform}/reset`,

  // SKU Resolution
  MATCH_ITEM: (itemId: number) => `/orders/items/${itemId}/match`,
  CONFIRM_ITEM: (itemId: number) => `/orders/items/${itemId}/confirm`,
  REJECT_ITEM: (itemId: number) => `/orders/items/${itemId}/reject`,
}

// Purchasing endpoints
export const PURCHASING = {
  VENDORS: '/vendors',
  VENDOR: (id: number) => `/vendors/${id}`,
  PURCHASES: '/purchases',
  PURCHASE: (id: number) => `/purchases/${id}`,
  PURCHASE_ITEMS: (id: number) => `/purchases/${id}/items`,
  PURCHASE_ITEM: (itemId: number) => `/purchases/items/${itemId}`,
  IMPORT_ZOHO: '/purchases/import/zoho',
  IMPORT_ZOHO_RANDOM_ONE: '/purchases/import/zoho/random-one',
  IMPORT_PURCHASE_FILE: '/purchases/import/file',
  IMPORT_GOODWILL_CSV: '/purchases/import/goodwill-csv',
  MATCH_ITEM: (itemId: number) => `/purchases/items/${itemId}/match`,
  MARK_DELIVERED: (id: number) => `/purchases/${id}/mark-delivered`,
}
