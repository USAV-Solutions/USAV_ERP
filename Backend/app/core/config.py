"""
Application configuration using pydantic-settings.
Loads from environment variables with .env file support.
"""
from functools import lru_cache
from typing import Literal

from pydantic import PostgresDsn, computed_field
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
    
    # Amazon SP-API Integration
    amazon_refresh_token: str = ""
    amazon_client_id: str = ""
    amazon_client_secret: str = ""
    amazon_marketplace_id: str = "ATVPDKIKX0DER"  # US marketplace
    
    # eBay Integration (shared credentials for all stores)
    ebay_app_id: str = ""
    ebay_cert_id: str = ""
    ebay_ru_name: str = ""
    ebay_sandbox: bool = False
    
    # eBay OAuth Refresh Tokens (per store)
    ebay_refresh_token_mekong: str = ""
    ebay_refresh_token_usav: str = ""
    ebay_refresh_token_dragon: str = ""
    
    # Ecwid Integration
    ecwid_store_id: str = ""
    ecwid_secret: str = ""
    ecwid_api_base_url: str = "https://app.ecwid.com/api/v3"
    
    # Walmart Integration
    walmart_client_id: str = ""
    walmart_client_secret: str = ""
    walmart_api_base_url: str = "https://marketplace.walmartapis.com"
    
    # Product Images
    product_images_path: str = "/mnt/product_images"
    
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
