"""
Mock AI provider — deterministic, no external API calls.

Used when:
  - AI_PROVIDER=mock (default)
  - No real API key is configured
  - Running in CI / unit tests

The mock uses simple keyword matching to simulate intent detection and
applies the same policy rules as a real provider would.
"""
import re
import time
from typing import List

from app.ai.base import BaseAIProvider, AIProcessingContext, AIDecisionResult


def _has_word(text: str, words: List[str]) -> bool:
    """Return True if any word in ``words`` appears as a whole word in ``text``."""
    pattern = r"\b(" + "|".join(re.escape(w) for w in words) + r")\b"
    return bool(re.search(pattern, text))

# Intents that are safe for the AI to attempt a draft reply
_SAFE_INTENTS = {"greeting", "faq", "status_inquiry", "general_inquiry"}

# Intents that always require a human agent
_ESCALATION_INTENTS = {"complaint", "refund_request", "legal_threat", "emergency"}

# Canned reply templates keyed by intent
_CANNED_RESPONSES = {
    "greeting": (
        "Hello! Welcome to our support. How can I assist you today?"
    ),
    "status_inquiry": (
        "I can help you check on that. Could you please provide your "
        "order or reference number so I can look it up for you?"
    ),
    "faq": (
        "Great question! Please check our FAQ page for detailed information, "
        "or let me know if you need something more specific."
    ),
    "general_inquiry": (
        "Thank you for reaching out. I'd be happy to help — "
        "could you please share a bit more detail about your question?"
    ),
}

_DEFAULT_REPLY = (
    "Thank you for your message. A member of our support team "
    "will be with you shortly."
)


def _detect_intent(text: str, escalation_keywords: List[str]) -> str:
    """Simple keyword-based intent classifier for mock mode."""
    if not text:
        return "unknown"
    tl = text.lower()

    # Custom escalation keywords from tenant config take highest priority
    if escalation_keywords and _has_word(tl, [kw.lower() for kw in escalation_keywords]):
        return "escalation_keyword_match"

    if _has_word(tl, ["hello", "hi", "hey"]) or "good morning" in tl or "good afternoon" in tl:
        return "greeting"
    if _has_word(tl, ["refund", "billing", "charged"]) or "money back" in tl:
        return "refund_request"
    if _has_word(tl, ["complaint", "angry", "terrible", "awful", "unacceptable", "horrible"]):
        return "complaint"
    if _has_word(tl, ["legal", "lawyer", "sue", "lawsuit", "solicitor"]):
        return "legal_threat"
    if _has_word(tl, ["urgent", "emergency", "asap", "immediately"]) or "help me now" in tl:
        return "emergency"
    if _has_word(tl, ["status", "order", "track", "tracking", "shipped"]) or "where is" in tl:
        return "status_inquiry"
    if _has_word(tl, ["faq", "question", "information"]) or "how do" in tl or "what is" in tl:
        return "faq"
    return "general_inquiry"


class MockAIProvider(BaseAIProvider):
    """
    Deterministic mock AI provider.

    Behaviour:
    - Detects intent via keyword rules (no ML/LLM)
    - Assigns fixed confidence per intent category
    - Generates canned reply drafts for safe intents
    - Applies escalation and auto-send policy from context
    - Phase 3: Incorporates retrieved_chunks into answer when present
    """

    @property
    def provider_name(self) -> str:
        return "mock"

    async def generate_decision(self, context: AIProcessingContext) -> AIDecisionResult:
        start_ms = int(time.monotonic() * 1000)

        intent = _detect_intent(
            context.message_text or "",
            context.escalation_keywords,
        )

        should_escalate = intent in _ESCALATION_INTENTS or intent == "escalation_keyword_match"
        escalation_reason: str | None = None
        if should_escalate:
            escalation_reason = f"Intent '{intent}' requires human agent review"

        # Risk flags
        risk_flags: List[str] = []
        if should_escalate:
            risk_flags.append(f"escalation_intent:{intent}")
        if context.message_text and len(context.message_text) > 1000:
            risk_flags.append("long_message")
        if intent == "unknown":
            risk_flags.append("unrecognised_intent")

        # Confidence: high for well-known intents, lower otherwise
        confidence = 0.9 if (intent in _SAFE_INTENTS or intent in _ESCALATION_INTENTS) else 0.55

        # Build draft reply (only for non-escalating intents)
        answer: str | None = None
        safe_to_auto_send = False

        if not should_escalate:
            base_answer = _CANNED_RESPONSES.get(intent, _DEFAULT_REPLY)

            # Phase 3: enrich answer with retrieved knowledge chunks
            if context.retrieved_chunks:
                kb_snippets = "\n".join(
                    f"  [{i+1}] {chunk.content[:300]}"
                    for i, chunk in enumerate(context.retrieved_chunks[:3])
                )
                answer = (
                    f"{base_answer}\n\n"
                    f"Based on our knowledge base:\n{kb_snippets}"
                )
            else:
                answer = base_answer

            # Honour auto_send_mode policy
            if (
                context.auto_send_mode == "auto"
                and confidence >= context.confidence_threshold
            ):
                safe_to_auto_send = True
            elif context.auto_send_mode == "supervised":
                # Draft is present but not marked safe to auto-send
                safe_to_auto_send = False

        duration_ms = int(time.monotonic() * 1000) - start_ms

        # Phase 3: track which chunks were used
        chunk_ids = [c.chunk_id for c in context.retrieved_chunks]
        rag_note = f"; RAG: {len(chunk_ids)} chunk(s) used" if chunk_ids else ""

        return AIDecisionResult(
            intent=intent,
            answer=answer,
            confidence=confidence,
            should_escalate=should_escalate,
            risk_flags=risk_flags,
            escalation_reason=escalation_reason,
            safe_to_auto_send=safe_to_auto_send,
            processing_notes=f"Mock provider: intent={intent}, mode={context.auto_send_mode}{rag_note}",
            provider_name=self.provider_name,
            model_name="mock-v1",
            processing_duration_ms=duration_ms,
            retrieved_chunk_ids=chunk_ids,
        )

    async def health_check(self) -> bool:
        return True
