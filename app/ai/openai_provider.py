"""
OpenAI GPT provider — Phase 3 full implementation.

Generates structured AI decisions using the OpenAI Chat Completions API.
When retrieved_chunks are present in the context, they are injected into the
system prompt so the LLM can ground its answer in tenant knowledge.

Configure via:
  AI_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  OPENAI_MODEL=gpt-4o-mini   (default)
"""
import json
import time
from typing import List, Optional

from app.ai.base import BaseAIProvider, AIProcessingContext, AIDecisionResult, RetrievedChunk
from app.core.logging import get_logger

logger = get_logger(__name__)

# System prompt template injected before every request.
_SYSTEM_PROMPT_TEMPLATE = """\
You are a customer service AI assistant for a business.
Respond ONLY with valid JSON — no markdown, no extra text.

Tone: {tone}
Language: {language}

{kb_section}

Your task: analyse the customer message and return a JSON object with exactly these fields:
{{
  "intent": "<one of: greeting, faq, status_inquiry, general_inquiry, complaint, refund_request, legal_threat, emergency, unknown>",
  "answer": "<draft reply for the customer, or null if escalation is required>",
  "confidence": <float 0.0-1.0>,
  "should_escalate": <true|false>,
  "escalation_reason": "<reason string or null>",
  "risk_flags": ["<optional flag strings>"]
}}

Rules:
- should_escalate=true for: complaint, refund_request, legal_threat, emergency
- answer must be null when should_escalate=true
- confidence reflects how certain you are of the intent and the quality of the answer
- risk_flags may include items like "escalation_intent:<intent>", "long_message", etc.
- Reply in the language specified above ({language})
"""

_KB_SECTION_TEMPLATE = """\
--- Relevant Knowledge Base Context ---
Use the following excerpts from the business knowledge base to inform your answer.
Do NOT fabricate information not present here.

{chunks}
--- End Knowledge Base Context ---
"""


def _build_system_prompt(context: AIProcessingContext) -> str:
    kb_section = ""
    if context.retrieved_chunks:
        chunk_texts = "\n\n".join(
            f"[Excerpt {i+1}]\n{chunk.content}"
            for i, chunk in enumerate(context.retrieved_chunks[:5])
        )
        kb_section = _KB_SECTION_TEMPLATE.format(chunks=chunk_texts)

    return _SYSTEM_PROMPT_TEMPLATE.format(
        tone=context.ai_tone,
        language=context.ai_language,
        kb_section=kb_section,
    )


def _build_messages(context: AIProcessingContext) -> List[dict]:
    """Build the messages array for the Chat Completions API."""
    messages = [{"role": "system", "content": _build_system_prompt(context)}]

    # Include recent conversation history (last 6 turns to keep prompt short)
    for msg in context.conversation_history[-6:]:
        role = "user" if msg.direction == "inbound" else "assistant"
        if msg.message_text:
            messages.append({"role": role, "content": msg.message_text})

    # The current message
    if context.message_text:
        messages.append({"role": "user", "content": context.message_text})

    return messages


def _parse_response(
    raw: str,
    context: AIProcessingContext,
    provider_name: str,
    model_name: str,
    duration_ms: int,
) -> AIDecisionResult:
    """Parse the JSON response from the LLM into an AIDecisionResult."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"OpenAI returned non-JSON response: {exc}\nRaw: {raw[:500]}") from exc

    intent = str(data.get("intent", "general_inquiry"))
    should_escalate = bool(data.get("should_escalate", False))
    confidence = max(0.0, min(1.0, float(data.get("confidence", 0.7))))
    answer: Optional[str] = data.get("answer") if not should_escalate else None
    escalation_reason: Optional[str] = data.get("escalation_reason")
    risk_flags: List[str] = list(data.get("risk_flags", []))

    # Ensure escalating results have no answer
    if should_escalate:
        answer = None

    # Apply safe_to_auto_send policy (engine also enforces this, but compute here for consistency)
    safe_to_auto_send = (
        not should_escalate
        and context.auto_send_mode == "auto"
        and confidence >= context.confidence_threshold
    )

    chunk_ids = [c.chunk_id for c in context.retrieved_chunks]

    return AIDecisionResult(
        intent=intent,
        answer=answer,
        confidence=confidence,
        should_escalate=should_escalate,
        risk_flags=risk_flags,
        escalation_reason=escalation_reason,
        safe_to_auto_send=safe_to_auto_send,
        processing_notes=f"OpenAI model={model_name}; RAG chunks={len(chunk_ids)}",
        provider_name=provider_name,
        model_name=model_name,
        processing_duration_ms=duration_ms,
        retrieved_chunk_ids=chunk_ids,
    )


class OpenAIProvider(BaseAIProvider):
    """
    Full OpenAI GPT provider using the Chat Completions API.

    Configure via: AI_PROVIDER=openai, OPENAI_API_KEY=sk-...

    Phase 3: Supports RAG context injection via context.retrieved_chunks.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self._api_key = api_key
        self._model = model
        self._client = None  # lazy initialised

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise RuntimeError(
                    "openai package is required. Install with: pip install openai"
                ) from exc
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    @property
    def provider_name(self) -> str:
        return "openai"

    async def generate_decision(self, context: AIProcessingContext) -> AIDecisionResult:
        start_ms = int(time.monotonic() * 1000)
        client = self._get_client()
        messages = _build_messages(context)

        logger.info(
            "openai_request",
            ai_job_id=context.ai_job_id,
            model=self._model,
            rag_chunks=len(context.retrieved_chunks),
        )

        response = await client.chat.completions.create(
            model=self._model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.2,  # low temperature for consistent structured output
            max_tokens=512,
        )

        raw_content = response.choices[0].message.content or ""
        duration_ms = int(time.monotonic() * 1000) - start_ms

        result = _parse_response(
            raw=raw_content,
            context=context,
            provider_name=self.provider_name,
            model_name=self._model,
            duration_ms=duration_ms,
        )

        logger.info(
            "openai_response",
            ai_job_id=context.ai_job_id,
            intent=result.intent,
            confidence=result.confidence,
            should_escalate=result.should_escalate,
            duration_ms=duration_ms,
        )
        return result

    async def health_check(self) -> bool:
        try:
            client = self._get_client()
            # Minimal test — list models to confirm connectivity
            await client.models.list()
            return True
        except Exception as exc:
            logger.warning("openai_health_check_failed", error=str(exc))
            return False
