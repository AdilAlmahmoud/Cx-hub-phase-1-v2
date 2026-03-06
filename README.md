# CX Agent Hub — Phase 4 Backend

Multi-tenant AI-powered customer service platform backend.
Phase 4 adds Outbound Messaging, an Email channel adapter, organized Settings APIs, request
tracing middleware, and final backend hardening on top of the Phase 1+2+3 foundation.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Windows Docker Setup](#windows-docker-setup)
4. [Environment Variables](#environment-variables)
5. [API Documentation](#api-documentation)
6. [Channel Adapter Architecture](#channel-adapter-architecture)
7. [AI Decision Engine](#ai-decision-engine)
8. [Knowledge Base & RAG](#knowledge-base--rag)
9. [Outbound Messaging](#outbound-messaging)
10. [Settings API](#settings-api)
11. [Testing](#testing)
12. [Seed Data](#seed-data)
13. [Phase 1 Deliverables](#phase-1-deliverables)
14. [Phase 2 Deliverables](#phase-2-deliverables)
15. [Phase 3 Deliverables](#phase-3-deliverables)
16. [Phase 4 Deliverables](#phase-4-deliverables)
17. [Deferred to Future Phases](#deferred-to-future-phases)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (future)                        │
└──────────────────────────────┬──────────────────────────────────┘
                               │ REST / JSON  (X-Request-ID traced)
┌──────────────────────────────▼──────────────────────────────────┐
│                      FastAPI Application                         │
│  RequestIDMiddleware → CORSMiddleware                            │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Channel Adapter Layer                                   │    │
│  │  WhatsApp ──┐                                           │    │
│  │  WebChat  ──┼──► UnifiedEvent ──► InboundService        │    │
│  │  SMS      ──┤          │                                │    │
│  │  Email    ──┘  (Phase 4)                                │    │
│  └────────────────────────┼────────────────────────────────┘    │
│                           │ ai_enabled=True                     │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │  AI Job Queue (ARQ / Redis)                              │    │
│  │  create AIJob ──► enqueue ──► Worker picks up           │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Knowledge Base API  (Phase 3)                           │   │
│  │  POST /upload ──► save to disk ──► enqueue ingestion     │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Outbound Messaging API  (Phase 4)                       │   │
│  │  POST /outbound/send ──► create OutboundMessage          │   │
│  │  ──► enqueue delivery ──► Worker delivers via provider   │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Settings API  (Phase 4)                                 │   │
│  │  GET/PUT /settings/{ai,prompts,knowledge,outbound,       │   │
│  │           channels}                                      │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Domain API (tenants / users / customers /               │   │
│  │              conversations / tickets / ai-jobs)           │   │
│  └──────────────────────────────────────────────────────────┘   │
│  Auth (JWT) │ RBAC (owner / agent) │ Multi-tenant isolation      │
└──────────────────────────────┬──────────────────────────────────┘
                               │ SQLAlchemy async
┌──────────────────────────────▼──────────────────────────────────┐
│              PostgreSQL 16 + pgvector extension                  │
│  knowledge_files | knowledge_chunks (vector(1536))               │
│  outbound_messages | outbound_attempts  (Phase 4)                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  AI + Outbound Worker (separate process — ARQ)                  │
│                                                                 │
│  process_ai_job:                                                │
│    embed query ──► retrieve top-k chunks ──► inject into LLM   │
│    AIDecisionEngine ──► AIResult DB                             │
│    [Phase 4] outbound_enabled + safe_to_auto_send?              │
│      ──► create OutboundMessage ──► enqueue delivery            │
│                                                                 │
│  process_knowledge_ingestion:  (Phase 3)                        │
│    extract text ──► chunk ──► embed ──► store vectors in DB     │
│                                                                 │
│  process_outbound_message:  (Phase 4)                           │
│    get_outbound_provider(channel).send(msg)                     │
│    ──► record OutboundAttempt ──► update status                 │
└─────────────────────────────────────────────────────────────────┘
```

**Key principles:**
- **Multi-tenant** — every DB row is scoped to a `tenant_id`; strict isolation enforced at service layer
- **Channel adapter** — each channel normalises its payload to a `UnifiedEvent` before processing
- **Async AI pipeline** — inbound messages enqueue an AI job and return 202 immediately; the worker processes jobs independently
- **Idempotent worker** — re-processing the same job ID is safe; completed jobs are skipped
- **Policy-driven AI** — per-tenant settings (language, tone, confidence threshold, auto-send mode) control AI behaviour
- **RAG (Phase 3)** — query embedding → pgvector cosine similarity → top-k chunks injected into LLM system prompt
- **Outbound delivery (Phase 4)** — provider abstraction (mock + real stubs); AI auto-send + manual agent sends; full delivery audit trail
- **Request tracing (Phase 4)** — `X-Request-ID` header threaded through all requests; surfaced in responses and logs
- **API-first** — paginated responses and clean DTOs ready for a frontend dashboard

---

## Project Structure

```
cx-agent-hub/
├── app/
│   ├── main.py              # FastAPI app + CORS + lifespan (queue init)
│   ├── core/
│   │   ├── config.py        # Settings from environment variables (incl. Phase 2+3)
│   │   ├── database.py      # Async SQLAlchemy engine + pgvector codec registration
│   │   ├── queue.py         # ARQ Redis pool — init/close/enqueue helpers
│   │   ├── security.py      # Password hashing + JWT (stdlib only)
│   │   ├── storage.py       # [Phase 3] File I/O, text extraction, chunking
│   │   └── logging.py       # Structured JSON logging (structlog)
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── tenant.py        # Tenant, TenantConfig (+ AI + knowledge + outbound config), ChannelConfig
│   │   ├── user.py          # User (owner / agent roles)
│   │   ├── customer.py      # Customer (per-tenant, per-channel)
│   │   ├── conversation.py  # Conversation
│   │   ├── ticket.py        # Ticket
│   │   ├── event_log.py     # UnifiedEvent persistence
│   │   ├── ai_job.py        # AIJob (pending→processing→completed|failed)
│   │   ├── ai_result.py     # AIResult (structured AI decision output)
│   │   ├── knowledge.py     # [Phase 3] KnowledgeFile, KnowledgeChunk (vector embeddings)
│   │   └── outbound.py      # [Phase 4] OutboundMessage, OutboundAttempt
│   ├── schemas/             # Pydantic DTOs (request / response)
│   │   ├── ai_job.py
│   │   ├── ai_result.py     # Includes retrieved_chunk_ids
│   │   ├── knowledge.py     # [Phase 3] KnowledgeFileResponse, etc.
│   │   ├── outbound.py      # [Phase 4] OutboundSendRequest, OutboundMessageResponse, etc.
│   │   └── tenant.py        # Includes knowledge + Phase 4 outbound/prompt fields
│   ├── ai/                  # AI provider abstraction layer
│   │   ├── base.py          # AIProcessingContext, AIDecisionResult, BaseAIProvider, RetrievedChunk
│   │   ├── engine.py        # AIDecisionEngine (policy enforcement)
│   │   ├── mock_provider.py # Deterministic mock (keyword-based + RAG snippet injection)
│   │   └── openai_provider.py # [Phase 3] Full OpenAI Chat Completions integration + RAG
│   ├── embeddings/          # [Phase 3] Embedding provider abstraction
│   │   ├── base.py          # BaseEmbeddingProvider ABC
│   │   ├── mock_provider.py # Deterministic mock (SHA-256 seeded unit-length vectors)
│   │   └── openai_provider.py # OpenAI text-embedding-3-small + get_embedding_provider() factory
│   ├── adapters/            # Channel adapter layer
│   │   ├── base.py          # ChannelType enum (whatsapp|webchat|sms|email), UnifiedEvent
│   │   ├── whatsapp.py
│   │   ├── webchat.py
│   │   ├── sms.py
│   │   └── email.py         # [Phase 4] Email inbound adapter (RFC 2822 from parsing, body/subject)
│   ├── outbound/            # [Phase 4] Outbound delivery provider abstraction
│   │   ├── base.py          # BaseOutboundProvider ABC, OutboundResult dataclass
│   │   ├── mock_provider.py # MockOutboundProvider — logs only, always succeeds
│   │   ├── registry.py      # get_outbound_provider(channel) factory (mock or real stubs)
│   │   ├── whatsapp_provider.py  # Real provider stub (Meta Cloud API TODO)
│   │   ├── sms_provider.py       # Real provider stub (Twilio TODO)
│   │   ├── email_provider.py     # Real provider stub (SendGrid TODO)
│   │   └── webchat_provider.py   # Real provider stub (WebSocket TODO)
│   ├── services/            # Business logic
│   │   ├── inbound_service.py
│   │   ├── ai_job_service.py
│   │   ├── knowledge_service.py   # [Phase 3] Ingestion pipeline + vector retrieval
│   │   ├── outbound_service.py    # [Phase 4] create/deliver/list/cancel OutboundMessages
│   │   ├── tenant_service.py
│   │   ├── user_service.py
│   │   ├── customer_service.py
│   │   ├── conversation_service.py
│   │   └── ticket_service.py
│   ├── core/
│   │   ├── config.py        # Settings from env vars (incl. Phase 2+3+4)
│   │   ├── database.py      # Async SQLAlchemy engine + pgvector codec registration
│   │   ├── queue.py         # ARQ Redis pool — init/close/enqueue helpers (incl. Phase 4)
│   │   ├── security.py      # Password hashing + JWT (stdlib only)
│   │   ├── storage.py       # [Phase 3] File I/O, text extraction, chunking
│   │   ├── middleware.py    # [Phase 4] RequestIDMiddleware (X-Request-ID)
│   │   └── logging.py       # Structured JSON logging (structlog)
│   ├── worker/
│   │   ├── main.py          # ARQ WorkerSettings (run: python -m app.worker.main)
│   │   └── tasks.py         # process_ai_job + process_knowledge_ingestion + process_outbound_message
│   └── api/v1/              # REST API routes
│       ├── auth/
│       ├── tenants/
│       ├── users/
│       ├── customers/
│       ├── conversations/
│       ├── tickets/
│       ├── channels/        # Inbound webhooks (WhatsApp, WebChat, SMS, Email [Phase 4])
│       ├── ai_jobs/
│       ├── knowledge/       # [Phase 3] Upload, list, get, reindex
│       ├── outbound/        # [Phase 4] Send, list, get, cancel, attempts
│       └── settings/        # [Phase 4] AI, prompts, knowledge, outbound, channels settings
├── migrations/              # Alembic migrations
│   └── versions/
│       ├── 001_initial_schema.py
│       ├── 002_phase2_ai_tables.py
│       ├── 003_phase3_knowledge.py  # knowledge_files, knowledge_chunks, pgvector
│       └── 004_phase4_outbound.py   # [Phase 4] outbound_messages, outbound_attempts, TenantConfig cols
├── tests/
│   ├── unit/
│   │   ├── test_adapters.py    # WhatsApp, WebChat, SMS, Email adapters + contract tests
│   │   ├── test_security.py
│   │   ├── test_ai_engine.py
│   │   ├── test_ai_worker.py
│   │   ├── test_knowledge.py   # [Phase 3] chunking, extraction, embeddings, ingestion, RAG
│   │   └── test_outbound.py    # [Phase 4] Mock provider, registry, create/deliver/cancel service
│   └── integration/
│       ├── test_health.py
│       ├── test_auth.py
│       ├── test_inbound_channels.py
│       ├── test_tenant_isolation.py
│       ├── test_ai_jobs.py
│       ├── test_knowledge_api.py   # [Phase 3] Upload, list, reindex, RBAC, isolation, AI+RAG
│       ├── test_outbound_api.py    # [Phase 4] Send, list, get, cancel, RBAC, tenant isolation
│       └── test_settings_api.py   # [Phase 4] GET/PUT all settings sections, RBAC, isolation
├── scripts/
│   └── seed.py
├── data/
│   └── knowledge/           # [Phase 3] Mounted Docker volume for uploaded knowledge files
├── Dockerfile
├── docker-compose.yml       # pgvector image + knowledge_data volume + Phase 4 env vars
├── .env.example
└── requirements.txt
```

---

## Windows Docker Setup

### Prerequisites

- **Windows 10/11** (64-bit)
- **Docker Desktop for Windows** — [Download here](https://docs.docker.com/desktop/install/windows-install/)
  - Enable WSL 2 backend (recommended) or Hyper-V
- **Git for Windows** — [Download here](https://git-scm.com/download/win)

### Step 1 — Clone the repository

Open **PowerShell** or **Command Prompt**:

```powershell
git clone <repo-url> cx-agent-hub
cd cx-agent-hub
```

### Step 2 — Create environment file

```powershell
copy .env.example .env
```

Open `.env` in Notepad (or any editor) and set at minimum:

```env
SECRET_KEY=<generate with: python -c "import secrets; print(secrets.token_hex(32))">
POSTGRES_PASSWORD=<a strong password>
DATABASE_URL=postgresql+asyncpg://cxhub:<POSTGRES_PASSWORD>@db:5432/cxhub
```

> **Security note:** Never commit `.env` to version control.

### Step 3 — Start all services

```powershell
docker compose up --build
```

Docker Desktop will:
1. Build the FastAPI + worker image
2. Start PostgreSQL with **pgvector** extension (port `5432`)
3. Start Redis (port `6379`)
4. Run Alembic migrations automatically (Phase 1–4 tables including `knowledge_files`, `knowledge_chunks`, `outbound_messages`, `outbound_attempts`, and `vector(1536)` column)
5. Seed the demo tenant
6. Start the FastAPI API on port `8000`
7. Start the AI + Outbound worker process (polls Redis for AI jobs, knowledge ingestion, and outbound delivery)

> First startup may take 2–3 minutes while Docker pulls images and builds.

### Step 4 — Verify the API is running

```powershell
# Health check
Invoke-WebRequest -Uri http://localhost:8000/health | Select-Object -ExpandProperty Content

# Interactive API docs
Start-Process "http://localhost:8000/docs"
```

### Step 5 — Log in with the demo account

```powershell
$body = '{"email":"owner@demo-corp.com","password":"DemoPass123!","tenant_slug":"demo-corp"}'
Invoke-WebRequest -Uri http://localhost:8000/api/v1/auth/login `
  -Method POST -ContentType "application/json" -Body $body |
  Select-Object -ExpandProperty Content
```

### Step 6 — Enable AI + Knowledge Base

```powershell
# Replace <TOKEN> with the JWT from the login response
$headers = @{ Authorization = "Bearer <TOKEN>"; "Content-Type" = "application/json" }
$body = '{"ai_enabled": true, "knowledge_enabled": true, "retrieval_top_k": 3, "auto_send_mode": "supervised"}'
Invoke-WebRequest -Uri http://localhost:8000/api/v1/tenants/me/config `
  -Method PUT -Headers $headers -Body $body |
  Select-Object -ExpandProperty Content
```

### Step 7 — Upload a knowledge file

```powershell
# Upload a .txt knowledge file
$headers_no_ct = @{ Authorization = "Bearer <TOKEN>" }
$filePath = "C:\path\to\your\knowledge.txt"
$fileBytes = [System.IO.File]::ReadAllBytes($filePath)
$boundary = "----FormBoundary$(Get-Random)"
$bodyLines = @(
    "--$boundary",
    'Content-Disposition: form-data; name="file"; filename="knowledge.txt"',
    "Content-Type: text/plain",
    "",
    [System.Text.Encoding]::UTF8.GetString($fileBytes),
    "--$boundary--"
)
$bodyContent = $bodyLines -join "`r`n"
Invoke-WebRequest -Uri http://localhost:8000/api/v1/knowledge/upload `
  -Method POST `
  -Headers @{ Authorization = "Bearer <TOKEN>"; "Content-Type" = "multipart/form-data; boundary=$boundary" } `
  -Body ([System.Text.Encoding]::UTF8.GetBytes($bodyContent)) |
  Select-Object -ExpandProperty Content
# Returns: {"file_id": "...", "status": "pending", "original_filename": "knowledge.txt", ...}
# The worker ingests it asynchronously (extract → chunk → embed → store)
```

### Step 8 — Send a message and check AI result with RAG

```powershell
# Send inbound message (worker will retrieve knowledge chunks and include them in the AI reply)
$body = '{"from":"+15551234567","type":"text","text":{"body":"Hello I need help"},"message_id":"test-001"}'
$resp = Invoke-WebRequest -Uri http://localhost:8000/api/v1/inbound/whatsapp/demo-corp `
  -Method POST -ContentType "application/json" -Body $body |
  Select-Object -ExpandProperty Content
$jobId = ($resp | ConvertFrom-Json).ai_job_id

# Check AI job result (includes retrieved_chunk_ids when RAG was used)
Invoke-WebRequest -Uri "http://localhost:8000/api/v1/ai/jobs/$jobId/result" `
  -Headers $headers | Select-Object -ExpandProperty Content
```

### Useful Docker commands

```powershell
# View API logs
docker compose logs api --follow

# View AI worker logs
docker compose logs worker --follow

# Stop all services
docker compose down

# Stop and remove volumes (wipes database, Redis, and knowledge files)
docker compose down -v

# Re-run migrations only
docker compose run --rm migrate

# Re-run seed only
docker compose run --rm seed

# Run tests inside container
docker compose run --rm api python -m pytest tests/ -v
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | random | JWT signing key — **change in production** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `480` | Token lifetime (8 hours) |
| `DATABASE_URL` | see below | Full async DB URL |
| `POSTGRES_USER` | `cxhub` | PostgreSQL username |
| `POSTGRES_PASSWORD` | `cxhub_pass` | PostgreSQL password |
| `POSTGRES_DB` | `cxhub` | Database name |
| `DEBUG` | `false` | Enable SQLAlchemy query logging |
| `ENVIRONMENT` | `production` | Environment label |
| `LOG_LEVEL` | `INFO` | Logging verbosity |
| `LOG_FORMAT` | `json` | `json` or `console` |
| `CORS_ORIGINS` | localhost:3000,5173 | Comma-separated allowed origins |
| `API_PORT` | `8000` | Host port for the API |
| **Phase 2** | | |
| `REDIS_URL` | `redis://redis:6379` | Redis connection URL for the job queue |
| `AI_QUEUE_ENABLED` | `true` | Set `false` to disable queue (jobs stay pending) |
| `AI_PROVIDER` | `mock` | AI provider: `mock` or `openai` |
| `OPENAI_API_KEY` | _(none)_ | OpenAI key (required if `AI_PROVIDER=openai`) |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI chat model name |
| `AI_MAX_RETRIES` | `3` | Max retry attempts per AI job |
| `AI_JOB_TIMEOUT_SECONDS` | `300` | Worker job timeout |
| **Phase 3** | | |
| `KNOWLEDGE_STORAGE_PATH` | `./data/knowledge` | Local filesystem path for uploaded files (mount as Docker volume) |
| `EMBEDDING_PROVIDER` | `mock` | Embedding provider: `mock` or `openai` |
| `OPENAI_EMBEDDING_MODEL` | `text-embedding-3-small` | OpenAI embedding model |
| `EMBEDDING_DIMENSIONS` | `1536` | Vector dimensions (must match the model) |
| `KNOWLEDGE_CHUNK_SIZE` | `1000` | Max characters per knowledge chunk |
| `KNOWLEDGE_CHUNK_OVERLAP` | `100` | Overlap characters between consecutive chunks |
| **Phase 4** | | |
| `OUTBOUND_PROVIDER` | `mock` | Outbound delivery provider: `mock` (logs only) or `real` (channel-specific stubs) |
| `OUTBOUND_MAX_ATTEMPTS` | `3` | Max delivery attempts per outbound message |

---

## API Documentation

When the server is running, full interactive documentation is at:

- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`
- **OpenAPI JSON:** `http://localhost:8000/openapi.json`

### Key endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/health` | None | Service health check |
| `POST` | `/api/v1/auth/login` | None | Authenticate and get JWT |
| `GET` | `/api/v1/auth/me` | Bearer | Current user info |
| `GET` | `/api/v1/tenants` | owner | List all tenants |
| `GET` | `/api/v1/tenants/me` | any | Current tenant details |
| `PUT` | `/api/v1/tenants/me/config` | owner | Update tenant config (AI policy + knowledge settings) |
| `GET` | `/api/v1/users` | agent+ | List users in tenant |
| `POST` | `/api/v1/users` | owner | Create user |
| `GET` | `/api/v1/customers` | agent+ | List customers (paginated) |
| `GET` | `/api/v1/conversations` | agent+ | List conversations |
| `GET` | `/api/v1/conversations/{id}/events` | agent+ | Conversation message history |
| `GET` | `/api/v1/tickets` | agent+ | List tickets (paginated, filterable) |
| `PATCH` | `/api/v1/tickets/{id}` | agent+ | Update ticket |
| `GET` | `/api/v1/tickets/{id}/ai-result` | agent+ | AI decision result for a ticket |
| `POST` | `/api/v1/inbound/whatsapp/{slug}` | None | Receive WhatsApp message |
| `POST` | `/api/v1/inbound/webchat/{slug}` | None | Receive web chat message |
| `POST` | `/api/v1/inbound/sms/{slug}` | None | Receive SMS message |
| `GET` | `/api/v1/ai/jobs` | agent+ | List AI jobs |
| `GET` | `/api/v1/ai/jobs/{id}` | agent+ | Get AI job status |
| `GET` | `/api/v1/ai/jobs/{id}/result` | agent+ | Get AI decision result (includes `retrieved_chunk_ids`) |
| `POST` | `/api/v1/ai/jobs/{id}/retry` | agent+ | Retry a failed AI job |
| **Phase 3** | | | |
| `POST` | `/api/v1/knowledge/upload` | owner | Upload a knowledge file (.txt, .md, .pdf) — returns 202 |
| `GET` | `/api/v1/knowledge` | agent+ | List knowledge files (paginated, filterable by status) |
| `GET` | `/api/v1/knowledge/{id}` | agent+ | Get knowledge file details |
| `POST` | `/api/v1/knowledge/{id}/reindex` | owner | Re-trigger ingestion for a knowledge file |
| **Phase 4** | | | |
| `POST` | `/api/v1/inbound/email/{slug}` | None | Receive inbound email (normalised via EmailAdapter) |
| `POST` | `/api/v1/outbound/send` | agent+ | Queue a manual outbound message (returns 202) |
| `GET` | `/api/v1/outbound` | agent+ | List outbound messages (paginated; filter by conversation/ticket/status) |
| `GET` | `/api/v1/outbound/{id}` | agent+ | Get outbound message detail (with delivery attempts) |
| `GET` | `/api/v1/outbound/{id}/attempts` | agent+ | List delivery attempts for a message |
| `POST` | `/api/v1/outbound/{id}/cancel` | agent+ | Cancel a pending outbound message |
| `GET` | `/api/v1/settings` | any | Settings overview (all categories summary) |
| `GET` | `/api/v1/settings/ai` | any | Get AI/LLM settings |
| `PUT` | `/api/v1/settings/ai` | owner | Update AI/LLM settings |
| `GET` | `/api/v1/settings/prompts` | owner | Get prompt template settings |
| `PUT` | `/api/v1/settings/prompts` | owner | Update prompt templates (null = revert to built-in default) |
| `GET` | `/api/v1/settings/knowledge` | any | Get knowledge/RAG settings |
| `PUT` | `/api/v1/settings/knowledge` | owner | Update knowledge/RAG settings |
| `GET` | `/api/v1/settings/outbound` | any | Get outbound messaging settings |
| `PUT` | `/api/v1/settings/outbound` | owner | Update outbound messaging settings |
| `GET` | `/api/v1/settings/channels` | any | Get channel configuration (enabled/disabled; no secrets) |

All list endpoints support `?page=1&page_size=20` pagination.

---

## Channel Adapter Architecture

Each inbound channel has a dedicated **adapter** that normalises the raw webhook payload into a `UnifiedEvent`:

```python
class UnifiedEvent(BaseModel):
    event_id: str
    tenant_id: str
    channel: ChannelType   # whatsapp | webchat | sms | email
    external_user_identifier: str
    message_text: str | None
    timestamp: datetime
    raw_payload: dict | None
    metadata: dict | None
```

**Available adapters:**

| Adapter | Endpoint | External identifier | Notes |
|---|---|---|---|
| WhatsApp | `POST /inbound/whatsapp/{slug}` | Phone number | `from`, `text.body`, `interactive` button replies |
| WebChat | `POST /inbound/webchat/{slug}` | `session_id` | `message` or `text` field |
| SMS | `POST /inbound/sms/{slug}` | Phone number | `body`, `text`, or `message` field |
| Email | `POST /inbound/email/{slug}` | Sender email | RFC 2822 `from` parsing; `body`/`text`/`html_body`; `subject` as fallback; thread metadata |

**Email adapter metadata fields:** `message_id`, `subject`, `from_raw`, `to`, `in_reply_to`, `thread_id`, `has_attachments`

To add a new channel (e.g. Telegram):

1. Create `app/adapters/telegram.py` subclassing `BaseChannelAdapter`
2. Implement the `normalize()` method
3. Add a `ChannelType.telegram` enum value
4. Register it in `app/api/v1/channels/router.py`

---

## AI Decision Engine

### Overview

When a tenant has `ai_enabled=True`, every inbound message triggers:

1. **AIJob creation** (status: `pending`) — persisted in DB before the queue call
2. **Enqueue** via ARQ to Redis — fire-and-forget; inbound response is not blocked
3. **Worker picks up** the job, optionally retrieves RAG chunks (Phase 3), then runs `AIDecisionEngine.process(context)`
4. **AIResult persisted** — structured decision output stored in DB

```
Inbound message
      |
      v
InboundService.process()
      |  ai_enabled=True
      +---> create AIJob (pending) --> commit --> enqueue_ai_job()
      |                                               |
      |                                          Redis queue       <-- 202 returned immediately
      |                                               |
      +-----------------------------------------------> Worker
                                                       |
                                               [Phase 3] knowledge_enabled=True?
                                               embed query --> retrieve top-k chunks
                                                       |
                                               AIDecisionEngine (inject chunks into context)
                                                       |
                                               MockAIProvider / OpenAIProvider
                                                       |
                                               AIResult persisted (with retrieved_chunk_ids)
                                               AIJob --> completed
                                               [Phase 4] outbound_enabled + safe_to_auto_send?
                                               --> create OutboundMessage --> enqueue delivery
```

### AI Provider abstraction

All providers implement `BaseAIProvider`:

```python
class BaseAIProvider(ABC):
    @abstractmethod
    async def generate_decision(self, context: AIProcessingContext) -> AIDecisionResult: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
```

### OpenAI Provider (Phase 3)

Set `AI_PROVIDER=openai` and `OPENAI_API_KEY=sk-...` to enable real LLM integration.

The provider:
- Calls `client.chat.completions.create` with `response_format={"type": "json_object"}`
- Injects retrieved knowledge chunks into the system prompt (up to 5 excerpts)
- Returns structured JSON with `intent`, `answer`, `confidence`, `should_escalate`, `risk_flags`

### Mock Provider (default)

The built-in mock provider (`AI_PROVIDER=mock`) uses keyword matching to classify intent and
applies the same policy rules as a real provider. No API key is needed. It is deterministic
and suitable for CI, development, and demo purposes.

**Intent categories:**

| Intent | Escalates? | Example trigger |
|---|---|---|
| `greeting` | No | "Hello", "Hi", "Good morning" |
| `faq` | No | "How do I", "What is" |
| `status_inquiry` | No | "Order status", "Where is my" |
| `general_inquiry` | No | (default for unrecognised safe messages) |
| `complaint` | Yes | "Terrible", "Awful", "Unacceptable" |
| `refund_request` | Yes | "Refund", "Money back", "Billing" |
| `legal_threat` | Yes | "Sue", "Lawyer", "Lawsuit" |
| `emergency` | Yes | "Urgent", "ASAP", "Emergency" |
| `escalation_keyword_match` | Yes | Any custom keyword from tenant config |

### Tenant AI Policy

Configure per-tenant AI behaviour via `PUT /api/v1/tenants/me/config`:

| Field | Default | Description |
|---|---|---|
| `ai_enabled` | `false` | Enable AI processing for inbound messages |
| `ai_language` | `"en"` | Language for AI reply drafts (ISO 639-1) |
| `ai_tone` | `"professional"` | Tone for AI-generated replies |
| `confidence_threshold` | `0.7` | Minimum confidence for `safe_to_auto_send=True` |
| `auto_send_mode` | `"off"` | `"off"` / `"supervised"` / `"auto"` |
| `escalation_keywords` | `null` | List of keywords that always trigger escalation |
| `handoff_message_template` | `null` | Template sent when handing off to human agent |
| `knowledge_enabled` | `false` | **[Phase 3]** Enable RAG retrieval for AI jobs |
| `retrieval_top_k` | `3` | **[Phase 3]** Number of knowledge chunks to inject (1–20) |

**auto_send_mode values:**

| Mode | Behaviour |
|---|---|
| `"off"` | AI processes and drafts a reply, but `safe_to_auto_send` is always `false` |
| `"supervised"` | Draft is present; human reviews before sending |
| `"auto"` | `safe_to_auto_send=true` when `confidence >= confidence_threshold` (not escalating) |

### AIResult fields

| Field | Description |
|---|---|
| `intent` | Detected intent label |
| `answer` | Draft reply candidate |
| `confidence` | Provider confidence score (0.0–1.0) |
| `should_escalate` | True if a human agent must handle this |
| `risk_flags` | List of risk indicators |
| `escalation_reason` | Human-readable reason for escalation |
| `safe_to_auto_send` | True if policy allows automatic sending |
| `processing_notes` | Provider debug notes |
| `provider_name` | AI provider used (`"mock"`, `"openai"`, ...) |
| `model_name` | Model version identifier |
| `processing_duration_ms` | Processing time in milliseconds |
| `retrieved_chunk_ids` | **[Phase 3]** IDs of knowledge chunks used in the answer |

---

## Knowledge Base & RAG

### Overview

Phase 3 adds a full **Retrieval-Augmented Generation (RAG)** pipeline:

```
Owner uploads file
        |
        v
POST /api/v1/knowledge/upload
        |
        +---> save bytes to disk (content-hash filename)
        +---> create KnowledgeFile record (status=pending)
        +---> enqueue process_knowledge_ingestion job (202 returned immediately)
                        |
                Worker picks up:
                        |
                1. extract_text()    (.txt/.md read directly; .pdf via pypdf)
                2. chunk_text()      (character-level, configurable size + overlap)
                3. embed_batch()     (OpenAI text-embedding-3-small or mock)
                4. delete old chunks (safe re-ingestion)
                5. insert new KnowledgeChunks with vector(1536) embeddings
                6. KnowledgeFile.status = "ready"

On each inbound AI job (knowledge_enabled=True):
        |
        +---> embed_text(message_text)      (same embedding provider)
        +---> retrieve_similar_chunks()     (pgvector <=> cosine distance, top-k)
        +---> attach RetrievedChunk list to AIProcessingContext
        +---> LLM system prompt includes [Excerpt 1], [Excerpt 2], ... from KB
        +---> AIResult.retrieved_chunk_ids = [chunk_uuid, ...]
```

### Knowledge file lifecycle

```
pending --> ingesting --> ready
                    \--> failed (error_message stored)
```

Re-ingest a failed or outdated file via `POST /knowledge/{id}/reindex`.

### Embedding provider

| `EMBEDDING_PROVIDER` | Description |
|---|---|
| `mock` (default) | Deterministic 1536-dim unit vectors (SHA-256 seeded). No API key needed. Suitable for tests and development. |
| `openai` | Calls OpenAI `embeddings.create` API. Requires `OPENAI_API_KEY`. Supports batching. |

### Supported file types

| Extension | MIME type | Extraction method |
|---|---|---|
| `.txt` / `.md` / `.text` | `text/plain`, `text/markdown` | Read as UTF-8 |
| `.pdf` | `application/pdf` | pypdf (pure Python, no system deps) |

Maximum upload size: **20 MB** per file.

### Tenant isolation

All knowledge data is scoped to `tenant_id`. Tenants cannot see or access each other's files.
The IVFFlat index on `knowledge_chunks.embedding` ensures fast ANN search per tenant at scale.

---

## Outbound Messaging

### Overview

Phase 4 adds a complete outbound delivery pipeline:

```
Agent sends message (POST /outbound/send)   OR   AI auto-send (outbound_enabled + safe_to_auto_send)
         |                                                  |
         +--------------------------------------------------+
         |
         v
create OutboundMessage (status=pending) --> commit --> enqueue_outbound_message()
                                                              |
                                                        Redis queue  <-- 202 returned immediately
                                                              |
                                                      Worker picks up:
                                                              |
                                              get_outbound_provider(channel).send(msg)
                                                              |
                                              record OutboundAttempt (success | failure)
                                                              |
                                              update OutboundMessage.status
                                              --> delivered | pending (retry) | failed
```

### Outbound message lifecycle

```
pending → sending → delivered
                \→ pending   (retry, attempt_count < max_attempts)
                \→ failed    (attempt_count >= max_attempts)
cancelled        (abandoned before first send)
```

### Provider abstraction

All delivery providers implement `BaseOutboundProvider`:

```python
class BaseOutboundProvider(ABC):
    @property @abstractmethod
    def provider_name(self) -> str: ...    # "mock", "twilio", "sendgrid", ...
    @property @abstractmethod
    def channel(self) -> str: ...          # "whatsapp", "sms", "email", "webchat"

    @abstractmethod
    async def send(self, message: OutboundMessage) -> OutboundResult: ...
    @abstractmethod
    async def health_check(self) -> bool: ...
```

### Provider modes

| `OUTBOUND_PROVIDER` | Behaviour |
|---|---|
| `mock` (default) | `MockOutboundProvider` handles all channels — logs via structlog, always returns success. No real API calls. Suitable for development, CI, and demos. |
| `real` | Routes to channel-specific stubs (WhatsApp → Meta Cloud API, SMS → Twilio, Email → SendGrid, WebChat → stub). Each stub returns `provider_not_configured` until real credentials are added. |

### AI auto-send

When `outbound_enabled=True` on `TenantConfig`, after every successful AI job, if `decision.safe_to_auto_send=True`:

1. Loads the `Conversation` and `Customer` linked to the job
2. Creates an `OutboundMessage` (is_ai_generated=True)
3. Enqueues `process_outbound_message` for async delivery
4. This step is **non-fatal** — a failure here does not affect the already-persisted AIResult

Set `auto_send_mode="auto"` and `outbound_enabled=True` together for fully automated AI replies.

---

## Settings API

Phase 4 provides organized settings endpoints for each configuration domain. All settings are scoped to the current tenant and backed by `TenantConfig`.

| Section | Endpoint | Readable by | Writable by |
|---|---|---|---|
| Overview | `GET /settings` | any | — |
| AI/LLM | `GET/PUT /settings/ai` | any / owner | owner |
| Prompt templates | `GET/PUT /settings/prompts` | owner | owner |
| Knowledge/RAG | `GET/PUT /settings/knowledge` | any / owner | owner |
| Outbound | `GET/PUT /settings/outbound` | any / owner | owner |
| Channels | `GET /settings/channels` | any | — (use `/channels` API to configure) |

**Read-only fields** (surfaced from env vars, not stored in DB): `ai_provider`, `ai_model`, `embedding_provider`, `embedding_model`, `chunk_size`, `chunk_overlap`

**Prompt templates:** Setting a template to `null` reverts to the built-in default prompt (controlled by owner only).

**Security:** Channel settings never expose `webhook_secret` or provider credentials.

---

## Testing

```bash
# All tests (289 tests, 1 skipped)
python -m pytest tests/ -v

# Unit tests only
python -m pytest tests/unit/ -v

# Integration tests (uses in-memory SQLite)
python -m pytest tests/integration/ -v

# With coverage report
python -m pytest tests/ --cov=app --cov-report=term-missing
```

**Test coverage includes:**

*Unit tests:*
- Channel adapter normalisation (WhatsApp, WebChat, SMS, Email)
- Email adapter: RFC 2822 `from` parsing, body/text/html_body/subject fallbacks, metadata, timestamps
- JWT creation and validation
- Password hashing and verification
- AI intent detection (all intent categories + custom keywords)
- Mock AI provider (all auto_send_mode combinations)
- AI decision engine (policy enforcement, provider error propagation)
- Worker task (idempotency, retry logic, result persistence)
- **[Phase 3]** `chunk_text` — empty, single chunk, overlap, boundary splitting
- **[Phase 3]** `extract_text` — .txt, .md, unsupported extension, missing file
- **[Phase 3]** Mock embedding provider — determinism, unit length, batch, health check
- **[Phase 3]** `get_embedding_provider` factory — defaults to mock
- **[Phase 3]** Ingestion pipeline — full flow, already-ready skips, not-found, bad path → failed
- **[Phase 3]** AI engine with RAG — chunks injected into answer, escalation ignores RAG, chunk_ids tracked
- **[Phase 3]** Knowledge retrieval fallback — graceful empty list on SQLite (no pgvector)
- **[Phase 3]** Knowledge worker task — `_process_knowledge_ingestion_inner` success and not-found paths
- **[Phase 4]** `OutboundResult` dataclass, `MockOutboundProvider` send + health_check
- **[Phase 4]** `get_outbound_provider` registry — mock mode all channels, unknown channel fallback, lowercasing
- **[Phase 4]** `create_outbound_message` — pending status, default max_attempts, AI generated flag
- **[Phase 4]** `deliver_outbound_message` — success → delivered, idempotency skip, not-found, max_attempts exceeded
- **[Phase 4]** `deliver_outbound_message` — attempt record creation (status=success, provider=mock)
- **[Phase 4]** `cancel_outbound_message` — cancels pending, no-op on delivered, wrong tenant → None

*Integration tests:*
- Multi-tenant data isolation (customers, conversations, tickets, users, AI jobs)
- RBAC enforcement (agent vs owner)
- Inbound channel pipeline (entity creation, conversation reuse)
- AI job creation when `ai_enabled=True`
- Worker processing → AIResult in DB
- AI Jobs API (list, get, result, retry)
- Ticket AI result sub-resource
- Cross-tenant AI job isolation
- Health/system endpoints
- Authentication flows
- **[Phase 3]** Knowledge upload (owner only, 202 accepted)
- **[Phase 3]** Unsupported extension → 415; empty file → 400
- **[Phase 3]** Knowledge list and get detail (agent can read)
- **[Phase 3]** Reindex (owner only, resets to pending)
- **[Phase 3]** Tenant isolation (tenant B cannot see/access tenant A's files)
- **[Phase 3]** AI job completes with `knowledge_enabled=True` (RAG fallback on SQLite)
- **[Phase 3]** Tenant config `knowledge_enabled` + `retrieval_top_k` CRUD + validation
- **[Phase 4]** POST /outbound/send — agent/owner 202, unauthenticated 401, wrong-tenant conv 404
- **[Phase 4]** POST /outbound/send — email channel with subject field
- **[Phase 4]** GET /outbound — empty list, tenant isolation, conversation filter
- **[Phase 4]** GET /outbound/{id} — detail + attempts; wrong tenant → 404
- **[Phase 4]** POST /outbound/{id}/cancel — cancels pending; non-existent → 404
- **[Phase 4]** Settings overview — all tenants see own settings only
- **[Phase 4]** GET/PUT /settings/ai — agent can GET; only owner can PUT; validation (confidence 0-1, temp 0-2)
- **[Phase 4]** GET/PUT /settings/prompts — owner only; agent → 403; too-long template → 422
- **[Phase 4]** GET/PUT /settings/knowledge — agent read; owner write; top_k > 20 → 422
- **[Phase 4]** GET/PUT /settings/outbound — agent read; owner write; max_messages_per_hour < 1 → 422
- **[Phase 4]** GET /settings/channels — webhook secrets never exposed in response
- **[Phase 4]** Settings tenant isolation — update tenant A does not affect tenant B

---

## Seed Data

The seed script creates a demo tenant with two users:

| Role | Email | Password |
|---|---|---|
| owner | `owner@demo-corp.com` | `DemoPass123!` |
| agent | `agent@demo-corp.com` | `AgentPass123!` |

Tenant slug: `demo-corp`
Enabled channels: `whatsapp`, `webchat`, `sms`
AI enabled: `false` by default — enable via `PUT /api/v1/tenants/me/config`

To re-run the seed manually:
```bash
# In Docker
docker compose run --rm seed

# Locally (requires DATABASE_URL to be set)
python -m scripts.seed
```

---

## Phase 1 Deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | Backend project structure | ✅ |
| 2 | Docker environment (Dockerfile + docker-compose.yml) | ✅ |
| 3 | PostgreSQL database | ✅ |
| 4 | Database migrations (Alembic) | ✅ |
| 5 | Multi-tenant schema (Tenant, TenantConfig, ChannelConfig) | ✅ |
| 6 | Channel adapter architecture (WhatsApp, WebChat, SMS) | ✅ |
| 7 | Unified inbound message handling pipeline | ✅ |
| 8 | Authentication foundation (JWT) | ✅ |
| 9 | RBAC roles (owner, agent) | ✅ |
| 10 | Environment variable management (.env.example) | ✅ |
| 11 | Structured JSON logging (structlog) | ✅ |
| 12 | Health endpoint (`/health`) | ✅ |
| 13 | OpenAPI documentation (`/docs`, `/redoc`) | ✅ |
| 14 | Demo tenant seed data | ✅ |
| 15 | README with Windows Docker setup | ✅ |
| 16 | Tenant isolation tests | ✅ |
| 17 | Channel adapter normalisation tests | ✅ |

---

## Phase 2 Deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | Redis job queue (ARQ) — `app/core/queue.py` | ✅ |
| 2 | ARQ worker process — `app/worker/main.py`, `app/worker/tasks.py` | ✅ |
| 3 | AIJob model + lifecycle (pending→processing→completed\|failed) | ✅ |
| 4 | AIResult model — structured AI decision persistence | ✅ |
| 5 | Database migration 002 (ai_jobs, ai_results, AI policy columns) | ✅ |
| 6 | AI provider abstraction (`BaseAIProvider`, `AIProcessingContext`, `AIDecisionResult`) | ✅ |
| 7 | Mock AI provider — deterministic keyword-based engine, no API key | ✅ |
| 8 | AI decision engine with tenant policy enforcement | ✅ |
| 9 | Inbound pipeline integration — AI job created + enqueued on `ai_enabled=True` | ✅ |
| 10 | Tenant AI configuration (language, tone, threshold, auto_send_mode, keywords) | ✅ |
| 11 | Structured logging for all AI job events | ✅ |
| 12 | AI Jobs API (`/ai/jobs` — list, get, result, retry) | ✅ |
| 13 | Ticket AI result sub-resource (`/tickets/{id}/ai-result`) | ✅ |
| 14 | Worker service in docker-compose.yml | ✅ |
| 15 | Idempotent worker task (safe to re-run, retry tracking) | ✅ |
| 16 | Unit tests — AI engine, mock provider, worker task | ✅ |
| 17 | Integration tests — AI job pipeline, API endpoints, tenant isolation | ✅ |
| 18 | README updated for Phase 2 | ✅ |

---

## Phase 3 Deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | `KnowledgeFile` + `KnowledgeChunk` models (`app/models/knowledge.py`) | ✅ |
| 2 | Alembic migration 003 — `knowledge_files`, `knowledge_chunks`, pgvector extension, IVFFlat index | ✅ |
| 3 | File storage utilities — `save_upload`, `delete_file`, `extract_text`, `chunk_text` (`app/core/storage.py`) | ✅ |
| 4 | Embedding provider abstraction — `BaseEmbeddingProvider`, `MockEmbeddingProvider`, `OpenAIEmbeddingProvider` | ✅ |
| 5 | `get_embedding_provider()` factory — env-driven, defaults to mock | ✅ |
| 6 | Knowledge service — `create_knowledge_file`, `ingest_knowledge_file`, `retrieve_similar_chunks` | ✅ |
| 7 | pgvector cosine similarity retrieval with graceful SQLite fallback | ✅ |
| 8 | Knowledge ingestion ARQ task — `process_knowledge_ingestion` | ✅ |
| 9 | Knowledge API router — upload, list, get, reindex (`app/api/v1/knowledge/router.py`) | ✅ |
| 10 | RBAC on knowledge endpoints (owner=upload/reindex, agent=read) | ✅ |
| 11 | 20 MB file size limit + extension allowlist (.txt, .md, .pdf) | ✅ |
| 12 | Tenant-scoped knowledge isolation (FK + query filter) | ✅ |
| 13 | RAG integration in AI worker — embed query → top-k retrieval → inject into `AIProcessingContext` | ✅ |
| 14 | RAG non-blocking — retrieval failure is caught and logged; AI job continues | ✅ |
| 15 | `AIProcessingContext.retrieved_chunks` + `AIDecisionResult.retrieved_chunk_ids` | ✅ |
| 16 | `AIResult.retrieved_chunk_ids` persisted in DB | ✅ |
| 17 | OpenAI provider — full Chat Completions API with RAG prompt injection | ✅ |
| 18 | Mock provider updated to incorporate retrieved chunks into answer | ✅ |
| 19 | `TenantConfig.knowledge_enabled` + `TenantConfig.retrieval_top_k` | ✅ |
| 20 | Docker: pgvector image, `knowledge_data` volume, Phase 3 env vars | ✅ |
| 21 | `.env.example` updated with Phase 3 variables | ✅ |
| 22 | Unit tests for all Phase 3 components (51 new tests) | ✅ |
| 23 | Integration tests for Knowledge API, RBAC, tenant isolation, AI+RAG | ✅ |
| 24 | README updated for Phase 3 | ✅ |

---

## Phase 4 Deliverables

| # | Deliverable | Status |
|---|---|---|
| 1 | `OutboundMessage` + `OutboundAttempt` models (`app/models/outbound.py`) | ✅ |
| 2 | Alembic migration 004 — `outbound_messages`, `outbound_attempts`, Phase 4 TenantConfig columns | ✅ |
| 3 | Outbound provider abstraction — `BaseOutboundProvider` ABC, `OutboundResult` dataclass | ✅ |
| 4 | `MockOutboundProvider` — logs via structlog, always returns success, safe for all channels | ✅ |
| 5 | Real provider stubs — WhatsApp, SMS, Email, WebChat (return `provider_not_configured`; TODOs for real APIs) | ✅ |
| 6 | `get_outbound_provider(channel)` factory — env-driven, defaults to mock | ✅ |
| 7 | `outbound_service.py` — `create_outbound_message`, `deliver_outbound_message` (with retry), `cancel_outbound_message`, list/get | ✅ |
| 8 | `process_outbound_message` ARQ worker task — testable inner function pattern | ✅ |
| 9 | AI auto-send integration in `process_ai_job` — non-fatal, triggered when `outbound_enabled + safe_to_auto_send` | ✅ |
| 10 | Outbound API router — POST /send, GET list (paginated+filtered), GET detail+attempts, POST cancel | ✅ |
| 11 | RBAC on outbound endpoints — agent+owner can send; unauthenticated → 401 | ✅ |
| 12 | Tenant isolation on outbound — cross-tenant conversation → 404 | ✅ |
| 13 | Email inbound adapter (`app/adapters/email.py`) — RFC 2822 from parsing, body/text/html_body fallback, thread metadata | ✅ |
| 14 | `ChannelType.email` added to adapter base enum | ✅ |
| 15 | `POST /inbound/email/{slug}` endpoint | ✅ |
| 16 | Settings API router (`app/api/v1/settings/`) — overview + ai/prompts/knowledge/outbound/channels sections | ✅ |
| 17 | Prompt template fields in TenantConfig (`system_prompt_template`, `reply_prompt_template`) | ✅ |
| 18 | Phase 4 TenantConfig fields — `ai_temperature`, `ai_max_tokens`, `outbound_enabled`, `outbound_provider`, `email_from_*`, `rate_limit_enabled`, `max_messages_per_hour` | ✅ |
| 19 | Webhook secrets excluded from all API responses | ✅ |
| 20 | `RequestIDMiddleware` — reuse client `X-Request-ID` or generate UUID4; stored on `request.state` and echoed in response headers | ✅ |
| 21 | CORS updated to expose `X-Request-ID` | ✅ |
| 22 | Enhanced `/health` endpoint — checks DB (`SELECT 1`) and Redis pool; returns `"ok"` or `"degraded"` with per-check details | ✅ |
| 23 | `enqueue_outbound_message()` in `app/core/queue.py` | ✅ |
| 24 | `docker-compose.yml` updated with Phase 4 env vars (`OUTBOUND_PROVIDER`, `OUTBOUND_MAX_ATTEMPTS`) | ✅ |
| 25 | `.env.example` updated with Phase 4 variables | ✅ |
| 26 | Unit tests — outbound provider, registry, service (create/deliver/cancel/idempotency) | ✅ |
| 27 | Unit tests — email adapter (all normalization cases + cross-adapter contract) | ✅ |
| 28 | Integration tests — outbound API (send, list, get, cancel, RBAC, tenant isolation) | ✅ |
| 29 | Integration tests — settings API (all sections, RBAC, validation, tenant isolation) | ✅ |
| 30 | Full test suite — 289 passed, 1 skipped | ✅ |
| 31 | README updated for Phase 4 | ✅ |

---

## Deferred to Future Phases

| Feature | Notes |
|---|---|
| Real WhatsApp outbound provider | Plug in Meta Cloud API — stub exists in `app/outbound/whatsapp_provider.py` |
| Real SMS outbound provider | Plug in Twilio/Vonage — stub exists in `app/outbound/sms_provider.py` |
| Real Email outbound provider | Plug in SendGrid/Mailgun — stub exists in `app/outbound/email_provider.py` |
| Frontend UI | Consumes existing REST APIs (pagination + DTOs ready) |
| Webhook signature verification | Per-channel HMAC validation (secret stored in ChannelConfig, excluded from responses) |
| Rate limiting enforcement | `rate_limit_enabled` + `max_messages_per_hour` stored in TenantConfig; enforcement logic deferred |
| Audit log | Track all state changes with actor |
| Analytics API | Aggregated metrics per tenant |
| Voice channel | IVR / telephony integration |
| WebSocket push | Real-time dashboard updates |
| Enterprise secret manager | Vault / AWS Secrets Manager for provider credentials |
