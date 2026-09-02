"""
parcelsapp.com tracking-status scraper (Playwright).

parcelsapp renders nothing server-side: the page fires a background call to
``/api/v2/parcels`` and builds the result from that JSON. Their anti-bot layer
replies ``{"error": "RELOAD"}`` to headless / automated browsers and never
returns data — which is why an earlier headless version only ever produced
"unknown". So this scraper:

* runs a **headed** Chromium inside a virtual X display (``pyvirtualdisplay`` →
  ``Xvfb``), with ``playwright-stealth`` applied,
* intercepts the ``/api/v2/parcels`` response and classifies from that JSON
  (falling back to the DOM if the API shape ever changes).

``TrackingScraper`` owns one browser + display for the lifetime of a job.
``ScraperProtocol`` is the seam the runner's tests fake.

Requires: ``playwright`` + Chromium (``playwright install chromium``),
``playwright-stealth``, ``pyvirtualdisplay``, and the ``Xvfb`` + ``xauth``
binaries (installed by the Dockerfile).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

logger = logging.getLogger(__name__)

# ── Result vocabulary ────────────────────────────────────────────────────────
DELIVERED = "DELIVERED"
SHIPPING = "SHIPPING"
PENDING = "PENDING"          # parcelsapp "label created" / pre-transit
NOT_FOUND = "NOT_FOUND"
UNKNOWN = "UNKNOWN"
ERROR = "ERROR"
RATE_LIMITED = "RATE_LIMITED"
SKIPPED_TBA = "SKIPPED_TBA"

# Statuses safe to persist / stamp ``tracking_last_checked_at`` for.
PERSISTABLE = frozenset({DELIVERED, SHIPPING, PENDING})

PARCELSAPP_TRACKING_URL = "https://parcelsapp.com/en/tracking/{number}"
_API_PATH = "/api/v2/parcels"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled"]

_NAV_TIMEOUT_MS = 25_000
_API_POLL_SECONDS = 30      # how long to wait for a non-RELOAD API payload
_API_POLL_STEP = 1.5

_RATE_LIMIT_MARKER = "information has not been found yet"
_TRANSIT_CODES = {"transit", "pickup", "expired", "undelivered", "alert", "exception"}


@dataclass
class ScrapeResult:
    status: str
    detail: str = ""


def parcelsapp_url(tracking_number: str) -> str:
    return PARCELSAPP_TRACKING_URL.format(number=(tracking_number or "").strip())


class ScraperProtocol(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def scrape(self, tracking_number: str) -> ScrapeResult: ...


# ── Classification ──────────────────────────────────────────────────────────
def classify_api(body: Any) -> ScrapeResult:
    """Map a ``/api/v2/parcels`` JSON body to a ScrapeResult."""
    if not isinstance(body, dict):
        return ScrapeResult(UNKNOWN, "unexpected API response")

    err = str(body.get("error") or "").upper()
    if err == "RELOAD":
        return ScrapeResult(RATE_LIMITED, "anti-bot challenge (RELOAD)")
    if err:  # NO_DATA / NOT_FOUND / anything else
        return ScrapeResult(NOT_FOUND, f"API: {err}")

    states = body.get("states") or []
    top = str(body.get("status") or "").strip().lower()
    # Carrier event text can contain non-breaking spaces — normalise before matching.
    latest = re.sub(r"\s+", " ", str(states[0].get("status") if states else "")).strip().lower()
    detail = f"{top or '?'} · {latest[:90]}" if latest else (top or "no status")

    # Pre-transit: a label exists but the carrier has not scanned the parcel.
    # parcelsapp sometimes still reports status "transit" here, so this wins.
    label_only = any(
        k in latest
        for k in (
            "label created", "awaiting item", "pre-shipment", "pre-transit",
            "shipment information", "billing information", "order created",
            "order processed", "ready for ups",
        )
    )

    if "delivered" in latest and "not delivered" not in latest and not latest.startswith(
        ("no authorized", "attempted", "notice left", "delivery attempted")
    ):
        return ScrapeResult(DELIVERED, detail)
    if top == "delivered":
        return ScrapeResult(DELIVERED, detail)
    if top == "archive":
        return ScrapeResult(DELIVERED if "deliver" in latest else SHIPPING, detail)
    if label_only:
        return ScrapeResult(PENDING, detail)
    if top in _TRANSIT_CODES:
        return ScrapeResult(SHIPPING, detail)
    if top in ("pending", ""):
        if not states:
            return ScrapeResult(NOT_FOUND, "no tracking events yet")
        return ScrapeResult(SHIPPING, detail)
    if top == "notfound":
        return ScrapeResult(NOT_FOUND, detail)
    return ScrapeResult(SHIPPING, detail)  # has data, unrecognised code → assume moving


def _classify_dom(text: str) -> ScrapeResult:
    """Fallback: classify from the latest-event DOM text (old behaviour)."""
    text = text.lower()
    if _RATE_LIMIT_MARKER in text:
        return ScrapeResult(RATE_LIMITED, "DOM: not found yet")
    if "label created" in text:
        return ScrapeResult(PENDING, text[:90])
    if "delivered" in text and not any(
        w in text for w in ("center", "post office", "usps", "ups", "fed ex")
    ):
        return ScrapeResult(DELIVERED, text[:90])
    return ScrapeResult(SHIPPING, text[:90])


class TrackingScraper:
    """A single headed Chromium + virtual display, reused for every order in a job."""

    def __init__(self, *, headless: bool = False):
        # ``headless`` is honoured for local debugging, but parcelsapp blocks it —
        # production always runs headed inside the virtual display.
        self._headless = headless
        self._display = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def __aenter__(self) -> "TrackingScraper":
        await self.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        if not self._headless:
            try:
                from pyvirtualdisplay import Display

                self._display = Display(visible=False, size=(1280, 720))
                self._display.start()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Virtual display unavailable (%s); running headless", exc)
                self._headless = True

        try:
            from playwright_stealth import Stealth
        except ImportError:
            Stealth = None
            logger.warning("playwright-stealth not installed — parcelsapp may block requests")

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=self._headless, args=_LAUNCH_ARGS
        )
        # Ephemeral context — parcelsapp needs no login, so nothing persists.
        # A future integration that DOES need a persistent session (e.g. Amazon
        # FBA) must use launch_persistent_context(user_data_dir=...) pointed at
        # its OWN mounted volume — never a path under PLAYWRIGHT_BROWSERS_PATH
        # (which `playwright install` manages) and never baked into the image.
        self._context = await self._browser.new_context(user_agent=_USER_AGENT)
        self._page = await self._context.new_page()
        if Stealth is not None:
            try:
                await Stealth().apply_stealth_async(self._page)
            except Exception:  # noqa: BLE001
                pass

    async def close(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    await closer.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            if self._pw is not None:
                await self._pw.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self._display is not None:
                self._display.stop()
        except Exception:  # noqa: BLE001
            pass
        self._pw = self._browser = self._context = self._page = None
        self._display = None

    async def scrape(self, tracking_number: str) -> ScrapeResult:
        import asyncio

        tn = (tracking_number or "").strip()
        if not tn:
            return ScrapeResult(UNKNOWN, "empty tracking number")
        if tn.upper().startswith("TBA"):
            return ScrapeResult(SKIPPED_TBA, "Amazon TBA")
        if self._page is None:
            return ScrapeResult(ERROR, "scraper not started")

        page = self._page
        payloads: list[dict] = []
        saw_reload = False

        async def _on_response(resp):
            nonlocal saw_reload
            if _API_PATH not in resp.url:
                return
            try:
                body = await resp.json()
            except Exception:  # noqa: BLE001
                return
            if isinstance(body, dict) and str(body.get("error")).upper() == "RELOAD":
                saw_reload = True
            else:
                payloads.append(body)

        page.on("response", _on_response)
        try:
            try:
                await page.goto(
                    parcelsapp_url(tn),
                    wait_until="domcontentloaded",
                    timeout=_NAV_TIMEOUT_MS,
                )
            except Exception:  # noqa: BLE001 — classify from whatever loads
                pass

            waited = 0.0
            while waited < _API_POLL_SECONDS and not payloads:
                await asyncio.sleep(_API_POLL_STEP)
                waited += _API_POLL_STEP

            if payloads:
                return classify_api(payloads[-1])
            if saw_reload:
                return ScrapeResult(RATE_LIMITED, "anti-bot challenge (RELOAD, no data)")

            # API never answered — fall back to the DOM.
            try:
                locator = page.locator(".event-content strong").first
                await locator.wait_for(timeout=5_000)
                return _classify_dom(await locator.inner_text())
            except Exception:  # noqa: BLE001
                body_text = (await page.locator("body").inner_text()).lower()
                if _RATE_LIMIT_MARKER in body_text:
                    return ScrapeResult(RATE_LIMITED, "DOM marker")
                if "not found" in body_text:
                    return ScrapeResult(NOT_FOUND, "DOM: not found")
                return ScrapeResult(UNKNOWN, "no API response and no DOM result")
        except Exception as exc:  # noqa: BLE001
            return ScrapeResult(ERROR, str(exc)[:200])
        finally:
            page.remove_listener("response", _on_response)
