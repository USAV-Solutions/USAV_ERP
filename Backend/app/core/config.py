"""
Application configuration using pydantic-settings.
Loads from environment variables with .env file support.
"""
from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    
    # Application
    app_name: str = "USAV Inventory API"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: Literal["development", "staging", "production"] = "development"
    
    # Database
    db_host: str = "db"
    db_port: int = 5432
    db_user: str = "postgres"
    db_pass: str = "postgres"
    db_name: str = "inventory_system"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    
    # API
    api_prefix: str = "/api/v1"
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    
    # Authentication & Security
    secret_key: str = "CHANGE-THIS-TO-A-SECURE-SECRET-KEY-IN-PRODUCTION"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24 hours
    
    # SeaTalk OAuth Integration
    seatalk_app_id: str = ""
    seatalk_app_secret: str = ""
    seatalk_redirect_uri: str = "http://localhost:3636/auth/seatalk/callback"
    seatalk_api_base_url: str = "https://openapi.seatalk.io"
    
    # Zoho Integration
    zoho_client_id: str = ""
    zoho_client_secret: str = ""
    zoho_refresh_token: str = ""
    zoho_organization_id: str = ""
    zoho_accounts_url: str = "https://accounts.zoho.com"
    zoho_inventory_api_base: str = "https://www.zohoapis.com/inventory/v1"
    zoho_books_api_base: str = "https://www.zohoapis.com/books/v3"
    zoho_auto_outbound_sync_enabled: bool = False
    zoho_auto_inbound_sync_enabled: bool = False
    zoho_po_cf_tax_id: str = ""
    zoho_po_cf_shipping_fee_id: str = ""
    zoho_po_cf_handling_fee_id: str = ""
    zoho_po_cf_source_id: str = ""
    zoho_po_cf_is_stationery_id: str = ""
    zoho_contact_cf_source_id: str = ""
    zoho_contact_cf_source_api_name: str = "cf_source"
    zoho_contact_tax_exemption_id: str = "5623409000000217703" #TBU
    zoho_contact_tax_authority_id: str = "5623409000000217709" #TBU
    zoho_po_stationery_purchase_account_id: str = ""
    zoho_po_stationery_location_id: str = ""
    zoho_po_stationery_delivery_address: str = ""
    zoho_item_stationery_purchase_account_id: str = ""
    zoho_item_stationery_purchase_account_name: str = "Office Supplies"
    zoho_po_ebay_paid_through_account_id: str = "5623409000001937358"
    
    # Amazon SP-API Integration
    amazon_refresh_token: str = ""
    amazon_client_id: str = ""
    amazon_client_secret: str = ""
    amazon_marketplace_id: str = "ATVPDKIKX0DER"  # US marketplace
    
    # eBay Integration (shared credentials for all stores)
    ebay_sandbox: bool = False
    
    # eBay OAuth Refresh Tokens (per store)
    ebay_app_id: str = ""
    ebay_cert_id: str = ""
    ebay_ru_name: str = ""
    ebay_refresh_token_mekong: str = ""
    ebay_refresh_token_purchasing: str = ""
    ebay_refresh_token_usav: str = ""
    ebay_refresh_token_dragon: str = ""

    ebay_country_dragon: str = "US"
    ebay_currency_usav: str = "USD"
    ebay_currency_dragon: str = "USD"
    ebay_location_usav: str = "16161 Gothard St, Ste A, Huntington Beach, CA"
    ebay_location_dragon: str = "16161 Gothard St, Ste A, Huntington Beach, CA"
    ebay_postal_code_usav: str = "92647"
    ebay_postal_code_dragon: str = "92647"
    ebay_dispatch_time_max_usav: int = 1
    ebay_dispatch_time_max_dragon: int = 1


    ebay_marketplace_id_mekong: str = "EBAY_US"
    ebay_currency_mekong: str = "USD"
    ebay_dispatch_time_max_mekong: int = 1
    ebay_merchant_location_key_mekong: str = "USAV-WAREHOUSE-MK"
    ebay_warehouse_address1_mekong: str = "16161 Gothard St"
    ebay_warehouse_address2_mekong: str = "Unit A"
    ebay_warehouse_city_mekong: str = "Huntington Beach"
    ebay_warehouse_state_mekong: str = "CA"
    ebay_warehouse_country_mekong: str = "US"
    ebay_postal_code_mekong: str = "92647"
    ebay_payment_policy_id_mekong: str = "258875123012"
    ebay_return_policy_id_mekong: str = "258875577012"
    ebay_return_policy_id_no_returns_mekong: str = "258875121012"
    ebay_fulfillment_policy_id_light_mekong: str = "258875552012"
    ebay_fulfillment_policy_id_heavy_mekong: str = "258875382012"
    ebay_fulfillment_policy_id_free_mekong: str = "258875122012"
    ebay_heavy_item_threshold_lbs_mekong: float = 2.0
    
    ebay_marketplace_id_usav: str = "EBAY_US"
    ebay_currency_usav: str = "USD"
    ebay_dispatch_time_max_usav: int = 1
    ebay_merchant_location_key_usav: str = "USAV-WAREHOUSE-HB"
    ebay_warehouse_address1_usav: str = "16161 Gothard St"
    ebay_warehouse_address2_usav: str = "Unit A"
    ebay_warehouse_city_usav: str = "Huntington Beach"
    ebay_warehouse_state_usav: str = "CA"
    ebay_warehouse_postal_code_usav: str = "92647"
    ebay_warehouse_country_usav: str = "US"
    ebay_payment_policy_id_usav: str = "277608353015"
    ebay_return_policy_id_usav: str = "278034901015"
    ebay_return_policy_id_no_returns_usav: str = "277427933015"
    ebay_fulfillment_policy_id_light_usav: str = "277893807015"
    ebay_fulfillment_policy_id_heavy_usav: str = "277702903015"
    ebay_fulfillment_policy_id_free_usav: str = "277893807015"
    ebay_heavy_item_threshold_lbs_usav: float = 2.0
    
    ebay_marketplace_id_dragon: str = "EBAY_US"
    ebay_currency_dragon: str = "USD"
    ebay_dispatch_time_max_dragon: int = 1
    ebay_merchant_location_key_dragon: str = "USAV-WAREHOUSE"
    ebay_warehouse_address1_dragon: str = "16161 Gothard St"
    ebay_warehouse_address2_dragon: str = "Unit A"
    ebay_warehouse_city_dragon: str = "Huntington Beach"
    ebay_warehouse_state_dragon: str = "CA"
    ebay_warehouse_postal_code_dragon: str = "92647"
    ebay_warehouse_country_dragon: str = "US"
    ebay_payment_policy_id_dragon: str = "39594638017"
    ebay_return_policy_id_dragon: str = "236354342017"
    ebay_return_policy_id_no_returns_dragon: str = "39594637017"
    ebay_fulfillment_policy_id_light_dragon: str = "59129340017"
    ebay_fulfillment_policy_id_heavy_dragon: str = "57336855017"
    ebay_fulfillment_policy_id_free_dragon: str = "58364269017"
    ebay_heavy_item_threshold_lbs_dragon: float = 2.0

    # Ecwid Integration
    ecwid_store_id: str = ""
    ecwid_secret: str = ""
    ecwid_api_base_url: str = "https://app.ecwid.com/api/v3"

    # Shopify Integration
    shopify_shop_url: str = ""
    shopify_access_token: str = ""
    shopify_api_version: str = "2024-10"
    shopify_price_sync_enabled: bool = False
    
    # Walmart Integration
    walmart_client_id: str = ""
    walmart_client_secret: str = ""
    walmart_api_base_url: str = "https://marketplace.walmartapis.com"
    
    # Google AISTUDIO
    gemini_api_key: str = ""
    gemini_model_name: str = "gemini-2.5-flash"

    # Product Images
    product_images_path: str = "/mnt/product_images"
    listing_public_base_url: str = ""

    # Tracking status scraper (parcelsapp.com)
    # parcelsapp blocks headless browsers — production runs headed inside a
    # virtual X display (Xvfb via pyvirtualdisplay). Only set True for local
    # debugging where you have a real display.
    tracking_scraper_headless: bool = False
    tracking_scraper_min_delay_seconds: float = 2.0
    tracking_scraper_max_delay_seconds: float = 5.0
    # Consecutive "information has not been found yet" hits before the job pauses.
    tracking_rate_limit_threshold: int = 3
    # Advisory cooldown shown after a rate-limit pause (minutes). Not enforced —
    # resume is gated on a successful probe, not on this timer.
    tracking_cooldown_minutes: int = 30
    # How often auto-probe retries while paused, and its backoff ceiling.
    tracking_auto_probe_interval_minutes: int = 15
    tracking_auto_probe_max_interval_minutes: int = 90
    # Orders checked more recently than this are skipped when (re)building the queue.
    tracking_freshness_hours: int = 6

    # FBA order import (app/modules/fba)
    # Server-side port of the local FBA/ pipeline: merge All-Orders + Fulfilment
    # reports, scrape missing buyer names from Seller Central, feed the result
    # through the existing AMAZON_FBA_CSV ingestion.
    #
    # The buyer-name scraper drives a *persistent* Chromium profile (Amazon needs
    # a logged-in session). That profile lives on a mounted volume — never in the
    # image, never under PLAYWRIGHT_BROWSERS_PATH. See Docs/FBA_Import_Handoff.md.
    fba_chrome_profile_path: str = "/data/fba-profile"
    # Unlike parcelsapp, Amazon serves authenticated Seller Central order pages
    # to a headless browser, so headless is the default (no Xvfb dependency, and
    # it works on nested-container hosts where headed Chrome SIGTRAPs). Set False
    # to force headed-in-Xvfb; the scraper falls back to headless if that fails.
    fba_scraper_headless: bool = True
    # Escape hatch for networks where Chromium's DNS resolver fails but the OS
    # resolver works (some Docker/VPN setups). Passed verbatim as Chromium's
    # --host-resolver-rules, e.g. "MAP * 1.2.3.4". Leave blank in production.
    fba_scraper_host_resolver_rules: str = ""
    fba_scraper_min_delay_seconds: float = 1.0
    fba_scraper_max_delay_seconds: float = 10.0
    # Give up scraping a single order's buyer name after this many page loads.
    fba_scraper_max_attempts_per_order: int = 2

    @model_validator(mode="after")
    def _apply_dev_overrides(self) -> "Settings":
        """
        Apply deterministic development defaults that should not depend on
        external environment file values.
        """
        if self.environment == "development":
            self.seatalk_redirect_uri = "http://localhost:3636/auth/seatalk/callback"
        return self
    
    @computed_field
    @property
    def database_url(self) -> str:
        """Construct the database URL from components."""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"
    
    @computed_field
    @property
    def database_url_sync(self) -> str:
        """Sync database URL for Alembic migrations."""
        return f"postgresql+psycopg2://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
