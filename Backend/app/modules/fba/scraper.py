"""
Seller Central buyer-name scraper (Playwright).

Amazon needs a logged-in session, so this drives a **persistent** Chromium
profile (``launch_persistent_context(user_data_dir=…)``) pointed at a mounted
volume — never the ephemeral context the tracking scraper uses, and never a path
under ``PLAYWRIGHT_BROWSERS_PATH``. Like the tracking scraper it runs headed
inside ``Xvfb`` (``pyvirtualdisplay``); Amazon fingerprints headless too.

``FbaBuyerNameScraper`` owns one browser + display for a whole job.
``BuyerNameScraperProtocol`` is the seam the runner's tests fake.
If the profile's session has expired, ``scrape_buyer_name`` raises
``FbaAuthExpired`` — the runner turns that into a "refresh the profile" warning
(see ``Docs/FBA_Import_Handoff.md``) and finishes the import without names.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

ORDER_URL = "https://sellercentral.amazon.com/orders-v3/order/{order_id}"

_LAUNCH_ARGS = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
_NAV_TIMEOUT_MS = 30_000
_LOGIN_HOST_MARKERS = (
    "/ap/signin",
    "/ap/sso",
    "/ap/mfa",
    "account.amazon.com",
    "signin",
)


class FbaAuthExpired(RuntimeError):
    """The persistent Chromium profile is no longer logged in to Seller Central."""


class FbaScraperUnavailable(RuntimeError):
    """The scraper couldn't even start (e.g. the seeded profile is from a newer
    Chrome than the container's Chromium and Chromium refuses to open it)."""


@dataclass
class BuyerNameResult:
    buyer_name: str = ""
    detail: str = ""


# check_auth() outcomes.
AUTH_LOGGED_IN = "logged_in"
AUTH_SIGNED_OUT = "signed_out"
AUTH_UNVERIFIED = "unverified"  # page wouldn't load — can't tell (network etc.)


class BuyerNameScraperProtocol(Protocol):
    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def check_auth(self) -> str: ...
    async def scrape_buyer_name(self, order_id: str) -> BuyerNameResult: ...


# JS tree-walker fallback — lifted from FBA/main.py.
_BUYER_NAME_JS = r"""() => {
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null, false);
    let node;
    while (node = walker.nextNode()) {
        const val = node.nodeValue;
        if (val && val.toLowerCase().includes('contact buyer')) {
            const parent = node.parentElement;
            if (!parent) continue;
            const sibling = parent.nextElementSibling;
            if (sibling && sibling.tagName === 'A' && sibling.innerText.trim()) {
                return sibling.innerText.trim();
            }
            if (parent.tagName !== 'A') {
                const aTag = parent.querySelector('a');
                if (aTag && aTag.innerText.trim()) return aTag.innerText.trim();
            }
            const m = (parent.innerText || '').match(/contact buyer:?\s*(.+)/i);
            if (m && m[1].trim()) return m[1].trim();
        }
    }
    return "";
}"""


class FbaBuyerNameScraper:
    """One headed persistent-profile Chromium, reused for every order in a job."""

    def __init__(
        self,
        *,
        profile_path: str,
        headless: bool = False,
        host_resolver_rules: str = "",
    ):
        self._profile_path = profile_path
        self._headless = headless
        self._host_resolver_rules = host_resolver_rules
        self._display = None
        self._pw = None
        self._context = None
        self._page = None

    async def __aenter__(self) -> "FbaBuyerNameScraper":
        await self.start()
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.close()

    async def start(self) -> None:
        from playwright.async_api import async_playwright

        profile_dir = Path(self._profile_path)
        profile_dir.mkdir(parents=True, exist_ok=True)
        # A crash / previous host leaves a stale singleton lock that makes
        # launch_persistent_context fail with "Opening in existing browser
        # session". We serialise jobs ourselves (one at a time, and auth-check
        # is blocked while a job runs), so clearing it here is safe.
        for lock in ("SingletonLock", "SingletonSocket", "SingletonCookie"):
            try:
                (profile_dir / lock).unlink(missing_ok=True)
            except OSError:
                pass

        if not self._headless:
            try:
                from pyvirtualdisplay import Display

                self._display = Display(visible=False, size=(1280, 720))
                self._display.start()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Virtual display unavailable (%s); running headless", exc)
                self._headless = True

        args = list(_LAUNCH_ARGS)
        if self._host_resolver_rules:
            args.append(f"--host-resolver-rules={self._host_resolver_rules}")

        self._pw = await async_playwright().start()
        try:
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=self._profile_path,
                headless=self._headless,
                args=args,
                ignore_default_args=["--enable-automation"],
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            if "existing browser session" in msg:
                raise FbaScraperUnavailable(
                    "The Chromium profile is already in use by another browser."
                ) from exc
            # SIGTRAP / TargetClosedError on launch is almost always a profile
            # written by a newer Chrome than this container's Chromium.
            raise FbaScraperUnavailable(
                "Chromium failed to open the profile — it was most likely seeded "
                "from a newer Chrome than the container ships. Re-seed with just "
                "the cookies (Backend/misc/fba_seed_profile.sh, Docs/FBA_Import_Handoff.md §7)."
            ) from exc
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()

    async def close(self) -> None:
        try:
            if self._context is not None:
                await self._context.close()
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
        self._pw = self._context = self._page = None
        self._display = None

    def _looks_like_login(self) -> bool:
        url = (self._page.url or "").lower()
        return any(marker in url for marker in _LOGIN_HOST_MARKERS)

    async def _settle_sso(self) -> None:
        """Click through Amazon's 'Switch accounts' interstitial.

        Seller Central's OpenID flow (``openid.pape.max_auth_age``) can land on
        an account-picker page that just needs the single already-signed-in
        account clicked to continue. If the session is stale the click leads to
        a password prompt instead — which the caller then detects.
        """
        import asyncio

        for _ in range(2):
            if not self._looks_like_login():
                return
            tile = self._page.locator('a[data-name="switch_account_request"]').first
            try:
                if not await tile.is_visible(timeout=2_000):
                    return
            except Exception:  # noqa: BLE001
                return
            try:
                async with self._page.expect_navigation(timeout=_NAV_TIMEOUT_MS):
                    await tile.click()
            except Exception:  # noqa: BLE001
                return
            await asyncio.sleep(1.5)

    async def check_auth(self) -> str:
        """Best-effort probe: is the profile still logged in to Seller Central?

        Returns ``AUTH_LOGGED_IN`` / ``AUTH_SIGNED_OUT`` / ``AUTH_UNVERIFIED``.

        A logged-in session may briefly bounce through ``/ap/sso`` and land back
        on ``sellercentral.amazon.com``; an expired one ends on a sign-in page
        with a visible email/password field. If the page never loads (blocked
        network, timeout) we return ``AUTH_UNVERIFIED`` rather than guessing —
        the import then still tries to scrape and finds out for real.
        """
        import asyncio

        if self._page is None:
            return AUTH_UNVERIFIED
        try:
            await self._page.goto(
                "https://sellercentral.amazon.com/home",
                wait_until="domcontentloaded",
                timeout=_NAV_TIMEOUT_MS,
            )
        except Exception:  # noqa: BLE001
            return AUTH_UNVERIFIED
        # Let any SSO redirect settle, then click through the account picker.
        for _ in range(6):
            if not self._looks_like_login():
                break
            await asyncio.sleep(1.0)
        await self._settle_sso()

        url = (self._page.url or "").lower()
        if self._looks_like_login():
            # We navigated in, let SSO settle, and clicked through the account
            # picker — and Amazon still wants credentials. That's a stale
            # session (a re-auth prompt for openid max_auth_age, or a real
            # sign-out). Either way the profile needs refreshing.
            try:
                has_field = await self._page.locator(
                    "input[type='password'], input[type='email'], input[name='email']"
                ).first.is_visible(timeout=3_000)
            except Exception:  # noqa: BLE001
                has_field = False
            if has_field or "auth_prompt" in url or "switch_account" in url:
                return AUTH_SIGNED_OUT
            return AUTH_UNVERIFIED

        if "sellercentral.amazon.com" in url:
            return AUTH_LOGGED_IN
        return AUTH_UNVERIFIED

    async def scrape_buyer_name(self, order_id: str) -> BuyerNameResult:
        if self._page is None:
            return BuyerNameResult(detail="scraper not started")

        page = self._page
        try:
            await page.goto(
                ORDER_URL.format(order_id=order_id),
                wait_until="domcontentloaded",
                timeout=_NAV_TIMEOUT_MS,
            )
        except Exception as exc:  # noqa: BLE001
            if self._looks_like_login():
                raise FbaAuthExpired("Seller Central redirected to sign-in") from exc
            return BuyerNameResult(detail=f"nav error: {str(exc)[:120]}")

        # Click through the "Switch accounts" interstitial if Seller Central
        # threw one up (openid max_auth_age). If it leads to a password prompt
        # the session is genuinely stale.
        await self._settle_sso()
        if self._looks_like_login():
            raise FbaAuthExpired("Seller Central redirected to sign-in")
        try:
            if await page.locator("input[type='password']").first.is_visible(timeout=1_500):
                raise FbaAuthExpired("Seller Central shows a password prompt")
        except FbaAuthExpired:
            raise
        except Exception:  # noqa: BLE001
            pass

        # Attempt 1 — the buyer-name link id (from the current order page markup).
        for selector in (
            '[data-test-id="buyer-name-with-link"]',
            '[data-test-id="shipping-section-contact-buyer-value"]',
        ):
            try:
                el = await page.wait_for_selector(selector, timeout=4_000)
                if el:
                    name = (await el.inner_text()).strip()
                    if name:
                        return BuyerNameResult(buyer_name=name, detail=f"via {selector}")
            except Exception:  # noqa: BLE001
                pass

        # Attempt 2 — tree-walker text extraction next to "Contact Buyer".
        try:
            await page.wait_for_selector("text=Contact Buyer", timeout=4_000)
            name = (await page.evaluate(_BUYER_NAME_JS) or "").strip()
            if name:
                return BuyerNameResult(buyer_name=name, detail="via tree-walker")
        except Exception:  # noqa: BLE001
            pass

        return BuyerNameResult(detail="buyer name not found on page")
