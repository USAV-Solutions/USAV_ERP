"""
Manual smoke test for the FBA buyer-name scraper.

    docker compose --profile dev exec -e PYTHONPATH=/app -w /app backend-dev \
        python -u misc/fba_scrape_smoke.py --order-id 112-1234567-1234567

With no --order-id it just runs check_auth() and reports whether the mounted
Chromium profile is still logged in to Seller Central.
"""
import argparse
import asyncio

from app.core.config import settings
from app.modules.fba.scraper import FbaBuyerNameScraper, FbaAuthExpired


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--order-id", action="append", default=[], help="Amazon order id (repeatable)")
    parser.add_argument("--headless", action="store_true", help="force headless (will be blocked)")
    args = parser.parse_args()

    print(f"profile: {settings.fba_chrome_profile_path}")
    scraper = FbaBuyerNameScraper(
        profile_path=settings.fba_chrome_profile_path,
        headless=args.headless or settings.fba_scraper_headless,
        host_resolver_rules=settings.fba_scraper_host_resolver_rules,
    )
    await scraper.start()
    try:
        state = await scraper.check_auth()
        print(f"check_auth -> {state}  (url: {scraper._page.url})")
        if state == "signed_out":
            print("Signed out — refresh the profile (see Docs/FBA_Import_Handoff.md).")
            return
        if state == "unverified":
            print("Could not verify (network?) — trying a scrape anyway.")
        for oid in args.order_id:
            try:
                res = await scraper.scrape_buyer_name(oid)
                print(f"  {oid} -> name={res.buyer_name!r}  ({res.detail})")
            except FbaAuthExpired as exc:
                print(f"  {oid} -> AUTH EXPIRED: {exc}")
                break
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())
