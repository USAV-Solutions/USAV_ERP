/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SEATALK_APP_ID?: string
  readonly VITE_SEATALK_REDIRECT_URI?: string
  readonly VITE_DISABLE_PRODUCT_IMAGES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
