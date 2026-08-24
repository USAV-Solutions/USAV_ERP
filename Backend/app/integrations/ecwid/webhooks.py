"""
Ecwid webhook receiver.

Provides a single ``POST /webhooks/ecwid`` endpoint that instantly returns
``200 OK`` and enqueues the raw webhook payload for background processing.
"""
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.core.config import settings

router = APIRouter(tags=["Ecwid Webhooks"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal queue stub
# ---------------------------------------------------------------------------

_ECWID_WEBHOOK_HANDLERS: dict[str, Any] = {}
"""Registry populated at app startup, maps event_type → async callable."""


def register_ecwid_webhook_handler(event_type: str, handler: Any) -> None:
    """Register an async handler for a given Ecwid event type."""
    _ECWID_WEBHOOK_HANDLERS[event_type] = handler


async def _dispatch_ecwid_webhook(event_type: str, payload: dict) -> None:
    """Route a webhook payload to the appropriate handler (if registered)."""
    handler = _ECWID_WEBHOOK_HANDLERS.get(event_type)
    if handler is None:
        logger.warning("No handler registered for Ecwid eventType=%s", event_type)
        return
    try:
        await handler(payload)
    except Exception:
        logger.exception(
            "Ecwid webhook handler failed | eventType=%s", event_type,
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/webhooks/ecwid")
async def receive_ecwid_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Accept an Ecwid webhook notification.

    Returns ``200 OK`` immediately and schedules background processing.
    """
    try:
        payload: dict = await request.json()
    except Exception:
        logger.warning("Ecwid webhook: invalid JSON body")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    event_type = payload.get("eventType", "unknown")
    logger.debug(
        "[DEBUG.EXTERNAL_API] Ecwid webhook received | eventType=%s keys=%s",
        event_type,
        list(payload.keys()),
    )

    if not settings.shopify_price_sync_enabled:
        logger.debug("[DEBUG.INTERNAL_API] Ecwid webhook ignored because shopify_price_sync_enabled is disabled")
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "auto_sync_disabled"})

    background_tasks.add_task(_dispatch_ecwid_webhook, event_type, payload)

    return JSONResponse(status_code=200, content={"status": "accepted"})
