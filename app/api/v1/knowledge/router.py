"""
Knowledge Base API — Phase 3.

Endpoints:
  POST   /knowledge/upload          — upload a knowledge file (multipart)
  GET    /knowledge                 — list knowledge files (paginated)
  GET    /knowledge/{file_id}       — get file status + chunk count
  POST   /knowledge/{file_id}/reindex — reset + re-trigger ingestion
"""
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query, status

from app.api.deps import DB, CurrentUser, CurrentTenant, AgentOrOwner, OwnerOnly
from app.core.queue import enqueue_knowledge_ingestion
from app.core.logging import get_logger
from app.core.storage import ALLOWED_EXTENSIONS
from app.models.knowledge import KnowledgeFileStatus
from app.schemas.knowledge import (
    KnowledgeFileResponse,
    KnowledgeFileListResponse,
    KnowledgeUploadResponse,
    KnowledgeReindexResponse,
)
from app.services.knowledge_service import (
    create_knowledge_file,
    get_knowledge_file,
    list_knowledge_files,
    reset_for_reindex,
)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
logger = get_logger(__name__)

_MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


@router.post("/upload", response_model=KnowledgeUploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_knowledge_file(
    db: DB,
    current_user: OwnerOnly,
    current_tenant: CurrentTenant,
    file: UploadFile = File(..., description="Text or PDF file to add to the knowledge base"),
):
    """
    Upload a new knowledge file.

    Supported formats: .txt, .md, .text, .pdf (max 20 MB).
    The file is saved to disk immediately and ingestion is queued asynchronously.
    Poll GET /knowledge/{file_id} to track ingestion status.
    """
    import pathlib
    ext = pathlib.Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty")
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {_MAX_FILE_SIZE // (1024*1024)} MB",
        )

    kf = await create_knowledge_file(
        db=db,
        tenant_id=current_tenant.id,
        original_filename=file.filename or "upload.txt",
        content=content,
        mime_type=file.content_type,
    )

    # Enqueue ingestion (non-blocking; stays pending if queue unavailable)
    await enqueue_knowledge_ingestion(str(kf.id))

    logger.info(
        "knowledge_file_upload_accepted",
        tenant_id=str(current_tenant.id),
        file_id=str(kf.id),
        filename=kf.original_filename,
        user_id=str(current_user.id),
    )

    return KnowledgeUploadResponse(
        file_id=kf.id,
        original_filename=kf.original_filename,
        status=kf.status,
    )


@router.get("", response_model=KnowledgeFileListResponse)
async def list_knowledge(
    db: DB,
    current_user: AgentOrOwner,
    current_tenant: CurrentTenant,
    status_filter: Optional[KnowledgeFileStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    """List knowledge files for the current tenant (paginated)."""
    offset = (page - 1) * page_size
    items = await list_knowledge_files(
        db=db,
        tenant_id=current_tenant.id,
        status=status_filter,
        offset=offset,
        limit=page_size,
    )
    return KnowledgeFileListResponse(
        items=[KnowledgeFileResponse.model_validate(kf) for kf in items],
        total=len(items),  # simple count; full COUNT query deferred to a future phase
        page=page,
        page_size=page_size,
    )


@router.get("/{file_id}", response_model=KnowledgeFileResponse)
async def get_knowledge_file_detail(
    file_id: uuid.UUID,
    db: DB,
    current_user: AgentOrOwner,
    current_tenant: CurrentTenant,
):
    """Get status and metadata for a single knowledge file."""
    kf = await get_knowledge_file(db, current_tenant.id, file_id)
    if kf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found")
    return KnowledgeFileResponse.model_validate(kf)


@router.post("/{file_id}/reindex", response_model=KnowledgeReindexResponse)
async def reindex_knowledge_file(
    file_id: uuid.UUID,
    db: DB,
    current_user: OwnerOnly,
    current_tenant: CurrentTenant,
):
    """
    Reset a knowledge file to pending and re-trigger ingestion.

    Useful after updating source content or changing embedding settings.
    Existing chunks are deleted and replaced during re-ingestion.
    """
    kf = await reset_for_reindex(db, current_tenant.id, file_id)
    if kf is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge file not found")

    await enqueue_knowledge_ingestion(str(kf.id))

    return KnowledgeReindexResponse(
        file_id=kf.id,
        status=kf.status,
    )
