# CX Agent Hub — Phase 2 Backend

Multi-tenant AI-powered customer service platform backend.
Phase 2 adds the asynchronous AI decision engine, Redis job queue, and structured AI result
persistence on top of the Phase 1 multi-tenant foundation.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Windows Docker Setup](#windows-docker-setup)
4. [Environment Variables](#environment-variables)
5. [API Documentation](#api-documentation)
6. [Channel Adapter Architecture](#channel-adapter-architecture)
7. [AI Decision Engine](#ai-decision-engine)
8. [Testing](#testing)
9. [Seed Data](#seed-data)
10. [Phase 1 Deliverables](#phase-1-deliverables)
11. [Phase 2 Deliverables](#phase-2-deliverables)
12. [Deferred to Future Phases](#deferred-to-future-phases)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (future)                        │
└──────────────────────────────┬──────────────────────────────────┘
                               │ REST / JSON
┌──────────────────────────────▼──────────────────────────────────┐
│                      FastAPI Application                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  Channel Adapter Layer                                   │    │
│  │  WhatsApp ──┐                                           │    │
│  │  WebChat  ──┼──► UnifiedEvent ──► InboundService        │    │
│  │  SMS      ──┘          │                                │    │
│  └────────────────────────┼────────────────────────────────┘    │
│                           │ (Phase 2) ai_enabled=True           │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │  AI Job Queue (ARQ / Redis)                              │    │
│  │  create AIJob ──► enqueue ──► Worker picks up           │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Domain API (tenants / users / customers /               │   │
│  │              conversations / tickets / ai-jobs)           │   │
│  └──────────────────────────────────────────────────────────┘   │
│  Auth (JWT) │ RBAC (owner / agent) │ Multi-tenant isolation      │
└──────────────────────────────┬──────────────────────────────────┘
                               │ SQLAlchemy async
┌──────────────────────────────▼──────────────────────────────────┐
│                     PostgreSQL 16                                │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  AI Worker (separate process — ARQ)                             │
│  Redis ──► process_ai_job ──► AIDecisionEngine ──► AIResult DB  │
└─────────────────────────────────────────────────────────────────┘
```

**Key principles:**
- **Multi-tenant** — every DB row is scoped to a `tenant_id`; strict isolation enforced at service layer
- **Channel adapter** — each channel normalises its payload to a `UnifiedEvent` before processing
- **Async AI pipeline** — inbound messages enqueue an AI job and return 202 immediately; the worker processes jobs independently
- **Idempotent worker** — re-processing the same job ID is safe; completed jobs are skipped
- **Policy-driven AI** — per-tenant settings (language, tone, confidence threshold, auto-send mode) control AI behaviour
- **API-first** — paginated responses and clean DTOs ready for a frontend dashboard

---

## Project Structure

```
cx-agent-hub/
├── app/
│   ├── main.py              # FastAPI app + CORS + lifespan (queue init)
│   ├── core/
│   │   ├── config.py        # Settings from environment variables (incl. Phase 2)
│   │   ├── database.py      # Async SQLAlchemy engine + session
│   │   ├── queue.py         # ARQ Redis pool — init/close/enqueue helpers
│   │   ├── security.py      # Password hashing + JWT (stdlib only)
│   │   └── logging.py       # Structured JSON logging (structlog)
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── tenant.py        # Tenant, TenantConfig (+ Phase 2 AI policy), ChannelConfig
│   │   ├── user.py          # User (owner / agent roles)
│   │   ├── customer.py      # Customer (per-tenant, per-channel)
│   │   ├── conversation.py  # Conversation
│   │   ├── ticket.py        # Ticket
│   │   ├── event_log.py     # UnifiedEvent persistence
│   │   ├── ai_job.py        # AIJob (pending→processing→completed|failed)
│   │   └── ai_result.py     # AIResult (structured AI decision output)
│   ├── schemas/             # Pydantic DTOs (request / response)
│   │   ├── ai_job.py        # AIJobResponse, AIJobRetryResponse
│   │   └── ai_result.py     # AIResultResponse
│   ├── ai/                  # AI provider abstraction layer
│   │   ├── base.py          # AIProcessingContext, AIDecisionResult, BaseAIProvider
│   │   ├── engine.py        # AIDecisionEngine (policy enforcement)
│   │   ├── mock_provider.py # Deterministic mock (keyword-based, no API key needed)
│   │   └── openai_provider.py # OpenAI stub (Phase 3+)
│   ├── adapters/            # Channel adapter layer
│   │   ├── base.py          # UnifiedEvent model + BaseChannelAdapter
│   │   ├── whatsapp.py
│   │   ├── webchat.py
│   │   └── sms.py
│   ├── services/            # Business logic
│   │   ├── inbound_service.py  # Orchestrates inbound pipeline + AI job creation
│   │   ├── ai_job_service.py   # AIJob + AIResult CRUD (tenant-scoped)
│   │   ├── tenant_service.py
│   │   ├── user_service.py
│   │   ├── customer_service.py
│   │   ├── conversation_service.py
│   │   └── ticket_service.py
│   ├── worker/
│   │   ├── main.py          # ARQ WorkerSettings (run: python -m app.worker.main)
│   │   └── tasks.py         # process_ai_job task + _process_ai_job_inner (testable)
│   └── api/v1/              # REST API routes
│       ├── auth/            # Login, /me
│       ├── tenants/         # Tenant CRUD + config (incl. AI policy)
│       ├── users/           # User management
│       ├── customers/       # Customer management
│       ├── conversations/   # Conversations + event history
│       ├── tickets/         # Ticket management + /ai-result sub-resource
│       ├── channels/        # Inbound webhook endpoints
│       └── ai_jobs/         # AI job list / get / result / retry
├── migrations/              # Alembic migrations
│   └── versions/
│       ├── 001_initial_schema.py
│       └── 002_phase2_ai_tables.py  # ai_jobs, ai_results + tenant AI policy columns
├── tests/
│   ├── unit/
│   │   ├── test_adapters.py      # Channel adapter normalisation
│   │   ├── test_security.py      # JWT + password hashing
│   │   ├── test_ai_engine.py     # Mock provider + engine policy enforcement
│   │   └── test_ai_worker.py     # Worker task (in-memory SQLite, no Redis)
│   └── integration/
│       ├── test_health.py
│       ├── test_auth.py
│       ├── test_inbound_channels.py
│       ├── test_tenant_isolation.py
│       └── test_ai_jobs.py       # Full AI pipeline + API + multi-tenant isolation
├── scripts/
│   └── seed.py              # Demo tenant seed data
├── Dockerfile
├── docker-compose.yml       # db + redis + migrate + seed + api + worker
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
2. Start PostgreSQL (port `5432`)
3. Start Redis (port `6379`)
4. Run Alembic migrations automatically (Phase 1 + Phase 2 tables)
5. Seed the demo tenant
6. Start the FastAPI API on port `8000`
7. Start the AI worker process (polls Redis for AI jobs)

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

### Step 6 — Enable AI for the demo tenant

Once logged in, enable AI processing via the config endpoint:

```powershell
# Replace <TOKEN> with the JWT from the login response
$headers = @{ Authorization = "Bearer <TOKEN>"; "Content-Type" = "application/json" }
$body = '{"ai_enabled": true, "auto_send_mode": "supervised", "confidence_threshold": 0.7}'
Invoke-WebRequest -Uri http://localhost:8000/api/v1/tenants/me/config `
  -Method PUT -Headers $headers -Body $body |
  Select-Object -ExpandProperty Content
```

### Step 7 — Send a test inbound message and check AI result

```powershell
# Send inbound message
$body = '{"from":"+15551234567","type":"text","text":{"body":"Hello I need help"},"message_id":"test-001"}'
$resp = Invoke-WebRequest -Uri http://localhost:8000/api/v1/inbound/whatsapp/demo-corp `
  -Method POST -ContentType "application/json" -Body $body |
  Select-Object -ExpandProperty Content
# Note the ai_job_id in the response

# Check AI job status (worker processes it within seconds)
$jobId = ($resp | ConvertFrom-Json).ai_job_id
Invoke-WebRequest -Uri "http://localhost:8000/api/v1/ai/jobs/$jobId" `
  -Headers $headers | Select-Object -ExpandProperty Content

# Get the AI decision result
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

# Stop and remove volumes (wipes database and Redis)
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
| `AI_PROVIDER` | `mock` | AI provider: `mock` or `openai` (stub) |
| `OPENAI_API_KEY` | _(none)_ | OpenAI key (required only if `AI_PROVIDER=openai`) |
| `OPENAI_MODEL` | `gpt-4o-mini` | OpenAI model name |
| `AI_MAX_RETRIES` | `3` | Max retry attempts per AI job |
| `AI_JOB_TIMEOUT_SECONDS` | `300` | Worker job timeout |

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
| `PUT` | `/api/v1/tenants/me/config` | owner | Update tenant config (incl. AI policy) |
| `GET` | `/api/v1/users` | agent+ | List users in tenant |
| `POST` | `/api/v1/users` | owner | Create user |
| `GET` | `/api/v1/customers` | agent+ | List customers (paginated, filterable) |
| `GET` | `/api/v1/conversations` | agent+ | List conversations |
| `GET` | `/api/v1/conversations/{id}/events` | agent+ | Conversation message history |
| `GET` | `/api/v1/tickets` | agent+ | List tickets (paginated, filterable) |
| `PATCH` | `/api/v1/tickets/{id}` | agent+ | Update ticket (status, priority, assign) |
| `GET` | `/api/v1/tickets/{id}/ai-result` | agent+ | **[Phase 2]** AI decision result for a ticket |
| `POST` | `/api/v1/inbound/whatsapp/{slug}` | None | Receive WhatsApp message |
| `POST` | `/api/v1/inbound/webchat/{slug}` | None | Receive web chat message |
| `POST` | `/api/v1/inbound/sms/{slug}` | None | Receive SMS message |
| `GET` | `/api/v1/ai/jobs` | agent+ | **[Phase 2]** List AI jobs (filterable by status/ticket) |
| `GET` | `/api/v1/ai/jobs/{id}` | agent+ | **[Phase 2]** Get AI job status |
| `GET` | `/api/v1/ai/jobs/{id}/result` | agent+ | **[Phase 2]** Get AI decision result |
| `POST` | `/api/v1/ai/jobs/{id}/retry` | agent+ | **[Phase 2]** Retry a failed AI job |

All list endpoints support `?page=1&page_size=20` pagination.

---

## Channel Adapter Architecture

Each inbound channel has a dedicated **adapter** that normalises the raw webhook payload into a `UnifiedEvent`:

```python
# app/adapters/base.py
class UnifiedEvent(BaseModel):
    event_id: str          # unique per event
    tenant_id: str         # owning tenant
    channel: ChannelType   # whatsapp | webchat | sms
    external_user_identifier: str  # sender ID (phone, session ID, etc.)
    message_text: str | None
    timestamp: datetime
    raw_payload: dict | None      # original payload preserved
    metadata: dict | None         # channel-specific metadata
```

To add a new channel (e.g. Telegram):

1. Create `app/adapters/telegram.py` subclassing `BaseChannelAdapter`
2. Implement the `normalize()` method
3. Add a `ChannelType.telegram` enum value
4. Register it in `app/api/v1/channels/router.py`

The rest of the pipeline (customer/conversation/ticket creation, event logging, AI job creation) requires no changes.

---

## AI Decision Engine

### Overview

When a tenant has `ai_enabled=True`, every inbound message triggers:

1. **AIJob creation** (status: `pending`) — persisted in DB before the queue call
2. **Enqueue** via ARQ to Redis — fire-and-forget; inbound response is not blocked
3. **Worker picks up** the job, runs `AIDecisionEngine.process(context)`
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
                                               AIDecisionEngine
                                                       |
                                               MockAIProvider
                                               (or real provider)
                                                       |
                                               AIResult persisted
                                               AIJob --> completed
```

### AI Provider abstraction

All providers implement `BaseAIProvider` from `app/ai/base.py`:

```python
class BaseAIProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @abstractmethod
    async def generate_decision(self, context: AIProcessingContext) -> AIDecisionResult: ...

    @abstractmethod
    async def health_check(self) -> bool: ...
```

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

**auto_send_mode values:**

| Mode | Behaviour |
|---|---|
| `"off"` | AI processes and drafts a reply, but `safe_to_auto_send` is always `false` |
| `"supervised"` | Draft is present; human reviews before sending |
| `"auto"` | `safe_to_auto_send=true` when `confidence >= confidence_threshold` (not escalating) |

> **Phase 2 note:** `safe_to_auto_send=true` is computed and stored but outbound sending is deferred to a later phase.

### AIResult fields

| Field | Description |
|---|---|
| `intent` | Detected intent label |
| `answer` | Draft reply candidate (not sent in Phase 2) |
| `confidence` | Provider confidence score (0.0–1.0) |
| `should_escalate` | True if a human agent must handle this |
| `risk_flags` | List of risk indicators (e.g. `"escalation_intent:complaint"`) |
| `escalation_reason` | Human-readable reason for escalation |
| `safe_to_auto_send` | True if policy allows automatic sending |
| `processing_notes` | Provider debug notes |
| `provider_name` | AI provider used (`"mock"`, `"openai"`, ...) |
| `model_name` | Model version identifier |
| `processing_duration_ms` | Processing time in milliseconds |

### Job lifecycle

```
pending --> processing --> completed
                     \--> failed (after max_retries)
```

Failed jobs can be reset via `POST /api/v1/ai/jobs/{id}/retry`.

---

## Testing

```bash
# All tests (142 tests)
python -m pytest tests/ -v

# Unit tests only (no DB, no Redis, no external services)
python -m pytest tests/unit/ -v

# Integration tests (uses in-memory SQLite)
python -m pytest tests/integration/ -v

# With coverage report
python -m pytest tests/ --cov=app --cov-report=term-missing
```

**Test coverage includes:**

*Unit tests:*
- Channel adapter normalisation (WhatsApp, WebChat, SMS)
- JWT creation and validation
- Password hashing and verification
- AI intent detection (all intent categories + custom keywords)
- Mock AI provider (all auto_send_mode combinations)
- AI decision engine (policy enforcement, provider error propagation)
- Worker task (idempotency, retry logic, result persistence)

*Integration tests:*
- Multi-tenant data isolation (customers, conversations, tickets, users, AI jobs)
- RBAC enforcement (agent vs owner)
- Inbound channel pipeline (entity creation, conversation reuse)
- AI job creation when `ai_enabled=True`
- AI job NOT created when `ai_enabled=False`
- Worker processing → AIResult in DB
- AI Jobs API (`GET /ai/jobs`, `GET /ai/jobs/{id}`, `GET /ai/jobs/{id}/result`, retry)
- Ticket AI result sub-resource (`GET /tickets/{id}/ai-result`)
- Cross-tenant AI job isolation (404 for wrong tenant)
- Health/system endpoints
- Authentication flows

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
| 8 | OpenAI provider stub (Phase 3+ implementation) | ✅ |
| 9 | AI decision engine with tenant policy enforcement | ✅ |
| 10 | Inbound pipeline integration — AI job created + enqueued on `ai_enabled=True` | ✅ |
| 11 | Tenant AI configuration (language, tone, threshold, auto_send_mode, keywords) | ✅ |
| 12 | Structured logging for all AI job events | ✅ |
| 13 | AI Jobs API (`/ai/jobs` — list, get, result, retry) | ✅ |
| 14 | Ticket AI result sub-resource (`/tickets/{id}/ai-result`) | ✅ |
| 15 | Worker service in docker-compose.yml | ✅ |
| 16 | Idempotent worker task (safe to re-run, retry tracking) | ✅ |
| 17 | Unit tests — AI engine, mock provider, worker task | ✅ |
| 18 | Integration tests — AI job pipeline, API endpoints, tenant isolation | ✅ |
| 19 | README updated for Phase 2 | ✅ |

---

## Deferred to Future Phases

| Feature | Notes |
|---|---|
| Real OpenAI / LLM integration | Stub present in `app/ai/openai_provider.py`; activate by setting `AI_PROVIDER=openai` + `OPENAI_API_KEY` |
| RAG / knowledge base | Vector store + retrieval pipeline for grounded answers |
| Outbound message sending | `safe_to_auto_send` flag is computed but sending is not yet implemented |
| Real WhatsApp provider | Plug in Meta Cloud API or Twilio adapter |
| Real SMS provider | Plug in Twilio, Vonage, or AWS SNS adapter |
| Frontend UI | Consumes existing REST APIs (pagination + DTOs ready) |
| Email channel adapter | Same pattern as existing adapters |
| Webhook signature verification | Per-channel HMAC validation (secret stored in ChannelConfig) |
| Rate limiting | Redis-based per-tenant throttling |
| Audit log | Track all state changes with actor |
| Analytics API | Aggregated metrics per tenant |
