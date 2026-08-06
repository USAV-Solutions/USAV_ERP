#!/usr/bin/env python3
"""
Daily Automated Tasks Script
Runs the required synchronization endpoints automatically.
Should be executed via cron daily.
"""

import os
import sys
import time
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Try to import dotenv if available, to load environment variables from Backend/.env
try:
    from dotenv import load_dotenv
    # Find Backend root directory assuming script is in Backend/scripts
    backend_dir = Path(__file__).resolve().parent.parent
    load_dotenv(backend_dir / ".env")
except ImportError:
    pass

import httpx

# Configuration
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD")
LOG_DIR = Path(__file__).resolve().parent.parent / "logs" / "daily_tasks"

def setup_logging():
    """Set up rotating log handler: keeps logs for 7 days."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "daily_sync.log"
    
    logger = logging.getLogger("DailyTasks")
    logger.setLevel(logging.INFO)
    
    # TimedRotatingFileHandler rotates at midnight, keeps 7 backups
    handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8"
    )
    
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # Also log to stdout
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

def get_auth_headers(logger, client: httpx.Client) -> dict:
    """Login and get JWT token."""
    if not ADMIN_USERNAME or not ADMIN_PASSWORD:
        logger.error("ADMIN_USERNAME and ADMIN_PASSWORD environment variables are not set in .env! Cannot authenticate.")
        sys.exit(1)
        
    logger.info("Authenticating with API...")
    login_url = f"{API_BASE_URL}/auth/login/access-token"
    
    data = {
        "username": ADMIN_USERNAME,
        "password": ADMIN_PASSWORD,
    }
    
    try:
        response = client.post(login_url, data=data, timeout=10.0)
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            logger.error("No access token found in response.")
            sys.exit(1)
        logger.info("Authentication successful.")
        return {"Authorization": f"Bearer {token}"}
    except Exception as e:
        logger.error(f"Failed to authenticate: {e}")
        if isinstance(e, httpx.HTTPStatusError):
            logger.error(f"Response details: {e.response.text}")
        sys.exit(1)

def run_tasks():
    logger = setup_logging()
    logger.info("=== Starting Daily Automated Tasks ===")
    
    now = datetime.now(timezone.utc)
    ten_days_ago = now - timedelta(days=10)
    
    # ISO formats
    since_iso = ten_days_ago.isoformat()
    until_iso = now.isoformat()
    
    # Date strings (YYYY-MM-DD)
    date_from = ten_days_ago.date().isoformat()
    date_to = now.date().isoformat()

    # Create the client with a long timeout for intensive tasks
    with httpx.Client(base_url=API_BASE_URL, timeout=300.0) as client:
        headers = get_auth_headers(logger, client)
        
        # 1. Sync Sale Orders
        logger.info(f"Task 1/3: Syncing Sale Orders from {since_iso} to {until_iso}")
        try:
            res = client.post(
                "/orders/sync/range",
                headers=headers,
                json={"since": since_iso, "until": until_iso}
            )
            res.raise_for_status()
            logger.info(f"Sale Orders Sync Success: {res.json()}")
        except Exception as e:
            logger.error(f"Sale Orders Sync Failed: {e}")
            if isinstance(e, httpx.HTTPStatusError):
                logger.error(f"Response: {e.response.text}")

        # 2. Import Purchase Orders from Zoho
        logger.info(f"Task 2/3: Importing Purchase Orders from Zoho ({date_from} to {date_to})")
        try:
            res = client.post(
                "/purchases/import/zoho",
                headers=headers,
                params={
                    "order_date_from": date_from,
                    "order_date_to": date_to,
                }
            )
            res.raise_for_status()
            logger.info(f"Purchase Orders Import Success: {res.json()}")
        except Exception as e:
            logger.error(f"Purchase Orders Import Failed: {e}")
            if isinstance(e, httpx.HTTPStatusError):
                logger.error(f"Response: {e.response.text}")

        # 3. Backfill Zoho Delivery Status
        logger.info(f"Task 3/3: Backfilling Delivery Status ({date_from} to {date_to})")
        try:
            res = client.post(
                "/purchases/backfill-delivery-status",
                headers=headers,
                params={
                    "receive_date_from": date_from,
                    "receive_date_to": date_to,
                }
            )
            res.raise_for_status()
            logger.info(f"Delivery Status Backfill Success: {res.json()}")
        except Exception as e:
            logger.error(f"Delivery Status Backfill Failed: {e}")
            if isinstance(e, httpx.HTTPStatusError):
                logger.error(f"Response: {e.response.text}")

    logger.info("=== Daily Automated Tasks Completed ===")

if __name__ == "__main__":
    run_tasks()
