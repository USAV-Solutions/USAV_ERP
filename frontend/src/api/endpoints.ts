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
  IDENTITY_SEARCH: '/identities/search',
  IDENTITY: (id: number) => `/identities/${id}`,
  VARIANTS: '/variants',
  EXPORT_ZOHO_ITEMS_CSV: '/variants/export/zoho-import.csv',
  VARIANT: (id: number) => `/variants/${id}`,
  CONVERT_VARIANT_TO_KIT: (id: number) => `/variants/${id}/convert-to-kit`,
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
  IMPORT_CSV: '/listings/import/csv',
  LISTING: (id: number) => `/listings/${id}`,
  BY_PLATFORM_REF: (platform: string, refId: string) => `/listings/platform/${platform}/ref/${refId}`,
  PENDING: '/listings/pending',
  ERRORS: '/listings/errors',
  MARK_SYNCED: (id: number) => `/listings/${id}/mark-synced`,
  MARK_ERROR: (id: number) => `/listings/${id}/mark-error`,
  SYNC: (id: number) => `/listings/${id}/sync`,
  MATCH: (id: number) => `/listings/${id}/match`,
  UNMATCH: (id: number) => `/listings/${id}/unmatch`,
}

export const EBAY_LISTING = {
  ACCOUNTS: '/listings/ebay/accounts',
  CATEGORY_SUGGESTIONS: '/listings/ebay/categories',
  CATEGORY_ASPECTS: (categoryId: string) => `/listings/ebay/categories/${categoryId}/aspects`,
  VALID_CONDITIONS: (categoryId: string) => `/listings/ebay/categories/${categoryId}/conditions`,
  PUBLISH: '/listings/ebay/publish',
  VERIFY: '/listings/ebay/verify',
  AI_SHORTEN_TITLE: '/listings/ebay/ai/shorten-title',
  AI_GENERATE_DESC: '/listings/ebay/ai/generate-description',
  AI_SUGGEST_DETAILS: '/listings/ebay/ai/suggest-details',
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
  RELINK_ITEM_IDS_BY_SKU: '/zoho/sync/items/relink-by-sku',
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
  ORDER_ITEMS: (id: number) => `/orders/${id}/items`,
  ORDER_ITEM: (itemId: number) => `/orders/items/${itemId}`,
  DELETE: (id: number) => `/orders/${id}`,
  UPDATE_STATUS: (id: number) => `/orders/${id}`,
  UPDATE_SHIPPING: (id: number) => `/orders/${id}/shipping`,

  // Sync
  SYNC: '/orders/sync',
  SYNC_RANGE: '/orders/sync/range',
  SYNC_REFRESH_MATCHING: '/orders/sync/refresh-matching',
  SYNC_STATUS: '/orders/sync/status',
  SYNC_RESET: (platform: string) => `/orders/sync/${platform}/reset`,
  IMPORT_API: '/orders/import/api',
  IMPORT_FILE: '/orders/import/file',
  IMPORT_TRACKING_LINK: '/orders/import/tracking-link',

  // SKU Resolution
  MATCH_ITEM: (itemId: number) => `/orders/items/${itemId}/match`,
  CONFIRM_ITEM: (itemId: number) => `/orders/items/${itemId}/confirm`,
  REJECT_ITEM: (itemId: number) => `/orders/items/${itemId}/reject`,

  // Physical Barcode Scans
  SCANS: '/orders/scans',
}

export const RETURNS = {
  LIST: '/returns',
  RECORD: (id: number) => `/returns/${id}`,
  REMATCH_RECORD: (id: number) => `/returns/${id}/rematch`,
  ZOHO_SYNC_RECORD: (id: number) => `/returns/${id}/zoho/sync`,
  SYNC: '/returns/sync',
  SYNC_RANGE: '/returns/sync/range',
  SYNC_STATUS: '/returns/sync/status',
  IMPORT_AMAZON_CSV: '/returns/import-amazon-csv',
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
  BACKFILL_DELIVERY_STATUS: '/purchases/backfill-delivery-status',
  IMPORT_PURCHASE_FILE: '/purchases/import/file',
  IMPORT_EBAY: '/purchases/import/ebay',
  IMPORT_GOODWILL_SHIPPED_CSV: '/purchases/import/goodwill-csv',
  MATCH_ITEM: (itemId: number) => `/purchases/items/${itemId}/match`,
  MARK_DELIVERED: (id: number) => `/purchases/${id}/mark-delivered`,
}

export const ACCOUNTING = {
  PURCHASE_ORDER_REPORTS: '/accounting/reports/purchase-orders',
  PURCHASE_ORDER_REPORTS_EXPORT: '/accounting/reports/purchase-orders/export',
  PURCHASE_ORDER_REPORT_FILTER_OPTIONS: '/accounting/reports/purchase-orders/filter-options',
  SALES_ORDER_REPORTS: '/accounting/reports/sales-orders',
  SALES_ORDER_REPORTS_EXPORT: '/accounting/reports/sales-orders/export',
  SALES_ORDER_REPORT_FILTER_OPTIONS: '/accounting/reports/sales-orders/filter-options',
}

export const BEST_SELLING_DASHBOARD = {
  SUMMARY: '/dashboard/best-selling/summary',
  PRODUCTS: '/dashboard/best-selling/products',
  TRENDS: '/dashboard/best-selling/trends',
  PLATFORM_BREAKDOWN: '/dashboard/best-selling/platform-breakdown',
  PRODUCT: (sku: string) => `/dashboard/best-selling/products/${encodeURIComponent(sku)}`,
}
