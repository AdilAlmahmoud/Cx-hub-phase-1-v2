import uuid
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class EventLogResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: Optional[uuid.UUID]
    channel: str
    external_user_identifier: str
    message_text: Optional[str]
    event_timestamp: datetime
    direction: str
    event_metadata: Optional[dict]
    created_at: datetime

    model_config = {"from_attributes": True}
