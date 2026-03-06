"""
AI Provider abstraction layer.

Defines the common contract for all AI providers:
  - RetrievedChunk      — a knowledge chunk retrieved via RAG
  - AIProcessingContext — input to the AI engine (message + tenant policy + RAG context)
  - AIDecisionResult    — structured output from the AI engine
  - BaseAIProvider      — abstract base that every provider must implement
"""
from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, Field


class ConversationMessage(BaseModel):
    """A single message in conversation history passed to the AI provider."""
    direction: str          # "inbound" | "outbound"
    message_text: Optional[str]
    timestamp: datetime
    channel: str


class RetrievedChunk(BaseModel):
    """A knowledge chunk retrieved from the tenant knowledge base via RAG."""
    chunk_id: str
    knowledge_file_id: str
    content: str
    chunk_index: int = 0
    similarity_score: float = Field(default=0.0, ge=0.0, le=1.0)


class AIProcessingContext(BaseModel):
    """
    Full context handed to the AI provider for a single processing run.
    Includes the triggering message, conversation history, tenant-level AI
    policy, and optionally knowledge chunks retrieved via RAG.
    """
    # Job / entity identifiers
    ai_job_id: str
    tenant_id: str
    ticket_id: str
    conversation_id: str

    # Message being processed
    message_text: Optional[str]
    channel: str

    # Conversation history (recent messages, oldest first)
    conversation_history: List[ConversationMessage] = []

    # ── Tenant AI policy (from TenantConfig) ──────────────────────────────────
    ai_language: str = "en"
    ai_tone: str = "professional"
    confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    # "off"        → AI processes, safe_to_auto_send always False
    # "supervised" → safe_to_auto_send may be True but human still reviews
    # "auto"       → safe_to_auto_send True if confidence >= threshold
    auto_send_mode: str = "off"
    escalation_keywords: List[str] = []
    handoff_message_template: Optional[str] = None

    # ── Phase 3: RAG context ──────────────────────────────────────────────────
    # Knowledge chunks retrieved from the tenant knowledge base.
    # Empty when knowledge_enabled=False or when no relevant chunks are found.
    retrieved_chunks: List[RetrievedChunk] = []


class AIDecisionResult(BaseModel):
    """
    Structured output produced by an AI provider for one inbound message.
    This is the contract persisted in ai_results and used for ticket policy.
    """
    intent: str                           # detected intent label
    answer: Optional[str]                 # draft reply candidate (may be None if escalating)
    confidence: float = Field(ge=0.0, le=1.0)
    should_escalate: bool
    risk_flags: List[str] = []           # e.g. ["escalation_intent:refund", "long_message"]
    escalation_reason: Optional[str] = None
    safe_to_auto_send: bool              # True only when policy + confidence both allow it
    processing_notes: Optional[str] = None

    # Provider metadata
    provider_name: str
    model_name: Optional[str] = None
    processing_duration_ms: int = 0

    # ── Phase 3: RAG metadata ─────────────────────────────────────────────────
    # IDs of knowledge chunks that were used to generate this decision.
    retrieved_chunk_ids: List[str] = []


class BaseAIProvider(ABC):
    """Abstract base class for all AI providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Short identifier for this provider, e.g. 'mock', 'openai'."""
        ...

    @abstractmethod
    async def generate_decision(self, context: AIProcessingContext) -> AIDecisionResult:
        """
        Process the context and return a structured AI decision.
        Must be implemented by every concrete provider.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and ready."""
        ...
