"""
Zoho Inventory webhook receiver.

Provides a single ``POST /webhooks/zoho`` endpoint that instantly returns
``200 OK`` and enqueues the raw webhook payload for background processing.

The actual fan-out (item / contact / salesorder inbound sync) is handled
by the background workers defined in Phase 3 & 4.  This module is
deliberately thin – its only job is to accept the call and enqueue.
"""
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.core.config import settings

router = APIRouter(tags=["Zoho Webhooks"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal queue stubd
# ---------------------------------------------------------------------------
# Phase 3/4 will replace this with a real Redis / ARQ broker push.
# For now we use FastAPI ``BackgroundTasks`` as a lightweight stand-in so
# the endpoint shape is production-ready.

_WEBHOOK_HANDLERS: dict[str, Any] = {}
"""Registry populated at app startup, maps event_type → async callable."""


def register_webhook_handler(event_type: str, handler: Any) -> None:
    """Register an async handler for a given Zoho event type."""
    _WEBHOOK_HANDLERS[event_type] = handler


async def _dispatch_webhook(event_type: str, payload: dict) -> None:
    """Route a webhook payload to the appropriate handler (if registered)."""
    handler = _WEBHOOK_HANDLERS.get(event_type)
    if handler is None:
        logger.warning("No handler registered for Zoho event_type=%s", event_type)
        return
    try:
        await handler(payload)
    except Exception:
        logger.exception(
            "Zoho webhook handler failed | event_type=%s", event_type,
        )


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/webhooks/zoho")
async def receive_zoho_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """
    Accept a Zoho Inventory webhook notification.

    Returns ``200 OK`` immediately and schedules background processing.
    """
    try:
        payload: dict = await request.json()
    except Exception:
        logger.warning("Zoho webhook: invalid JSON body")
        return JSONResponse(status_code=200, content={"status": "ignored"})

    event_type = payload.get("event_type", "unknown")
    logger.debug(
        "[DEBUG.EXTERNAL_API] Zoho webhook received | event_type=%s keys=%s",
        event_type,
        list(payload.keys()),
    )

    if not settings.zoho_auto_inbound_sync_enabled:
        logger.debug("[DEBUG.INTERNAL_API] Zoho webhook ignored because auto inbound sync is disabled")
        return JSONResponse(status_code=200, content={"status": "ignored", "reason": "auto_inbound_disabled"})

    background_tasks.add_task(_dispatch_webhook, event_type, payload)

    return JSONResponse(status_code=200, content={"status": "accepted"})
