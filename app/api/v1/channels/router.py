"""
Channel Inbound Endpoints.

These endpoints receive raw payloads from external channel providers
(or test clients in Phase 1) and route them through the channel adapter
layer into unified internal events.

URL pattern: /api/v1/inbound/{channel}/{tenant_slug}
Using tenant_slug in the URL allows webhook registration per channel
without needing auth headers.
"""
from typing import Any
from fastapi import APIRouter, HTTPException, status, Path

from app.api.deps import DB
from app.adapters.whatsapp import WhatsAppAdapter
from app.adapters.webchat import WebChatAdapter
from app.adapters.sms import SMSAdapter
from app.adapters.email import EmailAdapter
from app.services.inbound_service import inbound_service
from app.services.tenant_service import tenant_service
from app.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/inbound", tags=["Inbound Channels"])

_adapters = {
    "whatsapp": WhatsAppAdapter(),
    "webchat": WebChatAdapter(),
    "sms": SMSAdapter(),
    "email": EmailAdapter(),
}


async def _handle_inbound(channel: str, tenant_slug: str, payload: dict[str, Any], db) -> dict:
    adapter = _adapters.get(channel)
    if not adapter:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown channel: {channel}")

    tenant = await tenant_service.get_by_slug(db, tenant_slug)
    if not tenant or not tenant.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    if not adapter.validate_payload(payload):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid payload for channel")

    event = adapter.normalize(str(tenant.id), payload)
    logger.info("inbound_event_normalized", channel=channel, tenant_slug=tenant_slug, external_id=event.external_user_identifier)

    result = await inbound_service.process(db, event)
    return {"status": "accepted", **result}


@router.post("/whatsapp/{tenant_slug}", status_code=status.HTTP_202_ACCEPTED)
async def inbound_whatsapp(
    tenant_slug: str = Path(..., description="Tenant slug used for webhook routing"),
    payload: dict[str, Any] = {},
    db: DB = None,
):
    """Receive a WhatsApp inbound message and process it."""
    return await _handle_inbound("whatsapp", tenant_slug, payload, db)


@router.post("/webchat/{tenant_slug}", status_code=status.HTTP_202_ACCEPTED)
async def inbound_webchat(
    tenant_slug: str = Path(..., description="Tenant slug used for widget routing"),
    payload: dict[str, Any] = {},
    db: DB = None,
):
    """Receive a web chat widget message and process it."""
    return await _handle_inbound("webchat", tenant_slug, payload, db)


@router.post("/sms/{tenant_slug}", status_code=status.HTTP_202_ACCEPTED)
async def inbound_sms(
    tenant_slug: str = Path(..., description="Tenant slug used for webhook routing"),
    payload: dict[str, Any] = {},
    db: DB = None,
):
    """Receive an SMS inbound message and process it."""
    return await _handle_inbound("sms", tenant_slug, payload, db)


@router.post("/email/{tenant_slug}", status_code=status.HTTP_202_ACCEPTED)
async def inbound_email(
    tenant_slug: str = Path(..., description="Tenant slug used for webhook routing"),
    payload: dict[str, Any] = {},
    db: DB = None,
):
    """
    Receive an inbound email and process it.

    Compatible with inbound parse webhooks from providers such as
    SendGrid, Mailgun, Postmark, or AWS SES SNS.
    Payload must contain at least a 'from' field.
    """
    return await _handle_inbound("email", tenant_slug, payload, db)
