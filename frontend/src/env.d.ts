/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SEATALK_APP_ID?: string
  readonly VITE_SEATALK_REDIRECT_URI?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}