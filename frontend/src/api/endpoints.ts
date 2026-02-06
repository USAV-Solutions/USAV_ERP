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

// Order endpoints
export const ORDERS = {
  LIST: '/orders',
  ORDER: (id: number) => `/orders/${id}`,
  SUMMARY: '/orders/summary',
  SYNC: (platform: string) => `/orders/sync/${platform}`,
  UNMATCHED_ITEMS: '/orders/items/unmatched',
  MATCH_ITEM: (itemId: number) => `/orders/items/${itemId}/match`,
  ALLOCATE_ITEM: (itemId: number) => `/orders/items/${itemId}/allocate`,
  PROCESS: (orderId: number) => `/orders/${orderId}/process`,
  READY_TO_SHIP: (orderId: number) => `/orders/${orderId}/ready-to-ship`,
  SHIP: (orderId: number) => `/orders/${orderId}/ship`,
  CANCEL: (orderId: number) => `/orders/${orderId}/cancel`,
}
