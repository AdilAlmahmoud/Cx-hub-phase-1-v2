"""
Local filesystem storage for tenant knowledge files.

Files are stored at:  {KNOWLEDGE_STORAGE_PATH}/{tenant_id}/{filename}

The storage path is configurable via KNOWLEDGE_STORAGE_PATH and should be
mounted as a Docker volume so uploads survive container restarts.

Supported text-extraction formats:
  - .txt / .md / .text  — read directly as UTF-8
  - .pdf                — extracted with pypdf
"""
import hashlib
import io
import os
import uuid
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Allowed MIME types for knowledge file upload
ALLOWED_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "application/pdf",
    "application/octet-stream",  # fallback for files without detected MIME
}

ALLOWED_EXTENSIONS = {".txt", ".md", ".text", ".pdf"}


def _tenant_dir(tenant_id: uuid.UUID) -> Path:
    return Path(settings.KNOWLEDGE_STORAGE_PATH) / str(tenant_id)


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_upload(tenant_id: uuid.UUID, original_filename: str, content: bytes) -> str:
    """
    Persist the raw upload bytes to disk under the tenant directory.

    Returns the absolute file path (string) so it can be stored in the DB.
    The stored filename is a content-hash + original extension to avoid collisions.
    """
    ext = Path(original_filename).suffix.lower() or ".txt"
    content_hash = hashlib.sha256(content).hexdigest()[:16]
    stored_name = f"{content_hash}{ext}"

    tenant_dir = _tenant_dir(tenant_id)
    _ensure_dir(tenant_dir)

    file_path = tenant_dir / stored_name
    file_path.write_bytes(content)

    logger.info(
        "knowledge_file_saved",
        tenant_id=str(tenant_id),
        original_filename=original_filename,
        stored_path=str(file_path),
        size_bytes=len(content),
    )
    return str(file_path)


def delete_file(file_path: str) -> None:
    """Remove a file from disk (best-effort; logs errors instead of raising)."""
    try:
        p = Path(file_path)
        if p.exists():
            p.unlink()
    except Exception as exc:
        logger.warning("knowledge_file_delete_failed", path=file_path, error=str(exc))


def extract_text(file_path: str, mime_type: Optional[str] = None) -> str:
    """
    Extract plain text from a file on disk.

    Raises ValueError if the file type is unsupported.
    Raises FileNotFoundError if the file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Knowledge file not found: {file_path}")

    ext = path.suffix.lower()

    if ext in (".txt", ".md", ".text"):
        return path.read_text(encoding="utf-8", errors="replace")

    if ext == ".pdf" or (mime_type and "pdf" in mime_type):
        return _extract_pdf_text(path)

    raise ValueError(f"Unsupported file extension '{ext}' for text extraction")


def _extract_pdf_text(path: Path) -> str:
    """Extract text from a PDF using pypdf (pure Python, no system deps)."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("pypdf is required for PDF extraction; install pypdf") from exc

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n".join(pages)


def chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    """
    Split *text* into overlapping character-level chunks.

    Each chunk is at most *chunk_size* characters.  Consecutive chunks share
    *overlap* characters with the previous chunk so context is not lost at
    boundaries.  Chunks are split on whitespace when possible to avoid
    mid-word breaks.
    """
    if not text or not text.strip():
        return []

    chunks: list[str] = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + chunk_size, length)

        # Try to break on the last whitespace within the window
        if end < length:
            last_ws = text.rfind(" ", start, end)
            if last_ws > start:
                end = last_ws

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        # If we reached the end of the text, stop.
        if end >= length:
            break

        next_start = end - overlap
        if next_start <= start:
            # Safety: always advance to avoid infinite loop
            next_start = start + max(1, chunk_size - overlap)
        start = next_start

    return chunks
