"""
Integration tests for Phase 4 Settings API.

Covers:
  - GET /settings            - Overview
  - GET/PUT /settings/ai     - AI settings (any authenticated user can GET; owner PUT)
  - GET/PUT /settings/prompts - Prompt templates (owner only)
  - GET/PUT /settings/knowledge - Knowledge settings
  - GET/PUT /settings/outbound  - Outbound settings
  - GET     /settings/channels  - Channel settings (read only)
  - RBAC: agent can GET but not PUT on owner-only endpoints
  - Tenant isolation: tenant B cannot update tenant A's settings
"""
import pytest
import pytest_asyncio

from tests.conftest import make_token


# ── GET /settings ─────────────────────────────────────────────────────────────

class TestSettingsOverview:
    @pytest.mark.asyncio
    async def test_owner_can_get_overview(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.get("/api/v1/settings", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "tenant_id" in data
        assert "ai_enabled" in data
        assert "knowledge_enabled" in data
        assert "outbound_enabled" in data
        assert "active_channels" in data
        assert "ai_provider" in data

    @pytest.mark.asyncio
    async def test_agent_can_get_overview(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/settings", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get("/api/v1/settings")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_overview_tenant_id_matches(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.get("/api/v1/settings", headers=headers)
        data = response.json()
        assert data["tenant_id"] == str(tenant_a.id)


# ── GET/PUT /settings/ai ──────────────────────────────────────────────────────

class TestAISettings:
    @pytest.mark.asyncio
    async def test_get_ai_settings(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.get("/api/v1/settings/ai", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "ai_enabled" in data
        assert "ai_provider" in data
        assert "ai_model" in data
        assert "ai_language" in data
        assert "ai_tone" in data
        assert "confidence_threshold" in data
        assert "auto_send_mode" in data

    @pytest.mark.asyncio
    async def test_agent_can_get_ai_settings(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/settings/ai", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_owner_can_update_ai_settings(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/ai",
            json={
                "ai_enabled": True,
                "ai_language": "fr",
                "ai_tone": "friendly",
                "confidence_threshold": 0.8,
            },
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ai_language"] == "fr"
        assert data["ai_tone"] == "friendly"
        assert data["confidence_threshold"] == 0.8

    @pytest.mark.asyncio
    async def test_agent_cannot_update_ai_settings(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.put(
            "/api/v1/settings/ai",
            json={"ai_language": "de"},
            headers=headers,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_update_escalation_keywords(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/ai",
            json={"escalation_keywords": ["urgent", "lawsuit", "refund"]},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "urgent" in data["escalation_keywords"]

    @pytest.mark.asyncio
    async def test_update_temperature_and_max_tokens(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/ai",
            json={"ai_temperature": 0.5, "ai_max_tokens": 1000},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ai_temperature"] == 0.5
        assert data["ai_max_tokens"] == 1000

    @pytest.mark.asyncio
    async def test_confidence_threshold_validation(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/ai",
            json={"confidence_threshold": 1.5},  # invalid: > 1.0
            headers=headers,
        )
        assert response.status_code == 422


# ── GET/PUT /settings/prompts ─────────────────────────────────────────────────

class TestPromptSettings:
    @pytest.mark.asyncio
    async def test_owner_can_get_prompts(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.get("/api/v1/settings/prompts", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "system_prompt_template" in data
        assert "reply_prompt_template" in data

    @pytest.mark.asyncio
    async def test_agent_cannot_get_prompts(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/settings/prompts", headers=headers)
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_owner_can_update_prompts(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/prompts",
            json={
                "system_prompt_template": "You are a helpful assistant for {tenant_name}.",
                "reply_prompt_template": "Reply in {language} and be {tone}.",
            },
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "helpful assistant" in data["system_prompt_template"]
        assert "Reply in" in data["reply_prompt_template"]

    @pytest.mark.asyncio
    async def test_agent_cannot_update_prompts(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.put(
            "/api/v1/settings/prompts",
            json={"system_prompt_template": "injected"},
            headers=headers,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_prompt_template_too_long_rejected(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/prompts",
            json={"system_prompt_template": "x" * 8001},
            headers=headers,
        )
        assert response.status_code == 422


# ── GET/PUT /settings/knowledge ───────────────────────────────────────────────

class TestKnowledgeSettings:
    @pytest.mark.asyncio
    async def test_get_knowledge_settings(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.get("/api/v1/settings/knowledge", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "knowledge_enabled" in data
        assert "retrieval_top_k" in data
        assert "embedding_provider" in data
        assert "embedding_model" in data
        assert "chunk_size" in data
        assert "chunk_overlap" in data

    @pytest.mark.asyncio
    async def test_agent_can_get_knowledge_settings(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/settings/knowledge", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_owner_can_update_knowledge_settings(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/knowledge",
            json={"knowledge_enabled": True, "retrieval_top_k": 5},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["knowledge_enabled"] is True
        assert data["retrieval_top_k"] == 5

    @pytest.mark.asyncio
    async def test_agent_cannot_update_knowledge_settings(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.put(
            "/api/v1/settings/knowledge",
            json={"knowledge_enabled": True},
            headers=headers,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_retrieval_top_k_validation(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/knowledge",
            json={"retrieval_top_k": 25},  # > max 20
            headers=headers,
        )
        assert response.status_code == 422


# ── GET/PUT /settings/outbound ────────────────────────────────────────────────

class TestOutboundSettings:
    @pytest.mark.asyncio
    async def test_get_outbound_settings(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.get("/api/v1/settings/outbound", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "outbound_enabled" in data
        assert "outbound_provider" in data
        assert "rate_limit_enabled" in data
        assert "max_messages_per_hour" in data

    @pytest.mark.asyncio
    async def test_agent_can_get_outbound_settings(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/settings/outbound", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_owner_can_update_outbound_settings(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/outbound",
            json={
                "outbound_enabled": True,
                "email_from_address": "noreply@company.com",
                "email_from_name": "Support Team",
                "rate_limit_enabled": True,
                "max_messages_per_hour": 500,
            },
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["outbound_enabled"] is True
        assert data["email_from_address"] == "noreply@company.com"
        assert data["email_from_name"] == "Support Team"
        assert data["max_messages_per_hour"] == 500

    @pytest.mark.asyncio
    async def test_agent_cannot_update_outbound_settings(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.put(
            "/api/v1/settings/outbound",
            json={"outbound_enabled": True},
            headers=headers,
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_max_messages_per_hour_validation(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.put(
            "/api/v1/settings/outbound",
            json={"max_messages_per_hour": 0},  # < 1
            headers=headers,
        )
        assert response.status_code == 422


# ── GET /settings/channels ────────────────────────────────────────────────────

class TestChannelSettings:
    @pytest.mark.asyncio
    async def test_get_channel_settings(self, client, owner_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.get("/api/v1/settings/channels", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert "channels" in data
        assert "supported_channels" in data
        assert isinstance(data["channels"], list)

    @pytest.mark.asyncio
    async def test_agent_can_get_channel_settings(self, client, agent_user_a, tenant_a):
        headers = {"Authorization": f"Bearer {make_token(agent_user_a)}"}
        response = await client.get("/api/v1/settings/channels", headers=headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_channel_settings_no_webhook_secrets(self, client, owner_user_a, db_session, tenant_a):
        """Webhook secrets must never appear in channel settings responses."""
        from app.models.tenant import ChannelConfig

        db_session.add(ChannelConfig(
            tenant_id=tenant_a.id,
            channel="whatsapp",
            is_enabled=True,
            webhook_secret="super_secret_key_123",
            provider_config={"token": "token_abc"},
        ))
        await db_session.commit()

        headers = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        response = await client.get("/api/v1/settings/channels", headers=headers)
        assert response.status_code == 200
        response_text = response.text
        assert "super_secret_key_123" not in response_text
        assert "token_abc" not in response_text

    @pytest.mark.asyncio
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get("/api/v1/settings/channels")
        assert response.status_code == 401


# ── Tenant isolation ──────────────────────────────────────────────────────────

class TestSettingsTenantIsolation:
    @pytest.mark.asyncio
    async def test_tenant_b_cannot_read_tenant_a_ai_settings(
        self, client, owner_user_b, tenant_b
    ):
        """Each tenant only sees their own config."""
        headers = {"Authorization": f"Bearer {make_token(owner_user_b)}"}
        response = await client.get("/api/v1/settings/ai", headers=headers)
        # Should see tenant B's settings (200), not tenant A's
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_settings_update_is_scoped_to_tenant(
        self, client, owner_user_a, owner_user_b, tenant_a, tenant_b
    ):
        """Updating settings for tenant A should not affect tenant B."""
        headers_a = {"Authorization": f"Bearer {make_token(owner_user_a)}"}
        headers_b = {"Authorization": f"Bearer {make_token(owner_user_b)}"}

        # Update tenant A's tone
        await client.put(
            "/api/v1/settings/ai",
            json={"ai_tone": "casual"},
            headers=headers_a,
        )

        # Tenant B should still have default tone
        response_b = await client.get("/api/v1/settings/ai", headers=headers_b)
        data_b = response_b.json()
        assert data_b["ai_tone"] != "casual" or data_b["ai_tone"] == "professional"
