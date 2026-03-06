"""Pydantic schemas for the Knowledge Base API — Phase 3."""
import uuid
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel

from app.models.knowledge import KnowledgeFileStatus


class KnowledgeFileResponse(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    original_filename: str
    file_size: Optional[int]
    mime_type: Optional[str]
    status: KnowledgeFileStatus
    error_message: Optional[str] = None
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeFileListResponse(BaseModel):
    items: List[KnowledgeFileResponse]
    total: int
    page: int
    page_size: int


class KnowledgeUploadResponse(BaseModel):
    """Returned immediately after a file is accepted for ingestion."""
    file_id: uuid.UUID
    original_filename: str
    status: KnowledgeFileStatus
    message: str = "File accepted; ingestion has been queued."


class KnowledgeReindexResponse(BaseModel):
    file_id: uuid.UUID
    status: KnowledgeFileStatus
    message: str = "File reset to pending; re-ingestion has been queued."


class KnowledgeChunkResult(BaseModel):
    """A knowledge chunk returned by the RAG retrieval service."""
    chunk_id: str
    knowledge_file_id: str
    content: str
    chunk_index: int = 0
    similarity_score: float = 0.0
