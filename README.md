# CX Agent Hub — Phase 1 Backend

Multi-tenant AI-powered customer service platform backend.
Phase 1 delivers the multi-tenant foundation, channel adapter layer, and core API.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Windows Docker Setup](#windows-docker-setup)
4. [Environment Variables](#environment-variables)
5. [API Documentation](#api-documentation)
6. [Channel Adapter Architecture](#channel-adapter-architecture)
7. [Testing](#testing)
8. [Seed Data](#seed-data)
9. [Phase 1 Deliverables](#phase-1-deliverables)
10. [Deferred to Future Phases](#deferred-to-future-phases)

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
│  │  SMS      ──┘                                           │    │
│  └─────────────────────────────────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Domain API (tenants / users / customers /               │   │
│  │              conversations / tickets / events)            │   │
│  └──────────────────────────────────────────────────────────┘   │
│  Auth (JWT) │ RBAC (owner / agent) │ Multi-tenant isolation      │
└──────────────────────────────┬──────────────────────────────────┘
                               │ SQLAlchemy async
┌──────────────────────────────▼──────────────────────────────────┐
│                     PostgreSQL 16                                │
└─────────────────────────────────────────────────────────────────┘
```

**Key principles:**
- **Multi-tenant** — every DB row is scoped to a `tenant_id`; strict isolation enforced at service layer
- **Channel adapter** — each channel normalises its payload to a `UnifiedEvent` before processing
- **Event-driven ready** — `EventLog` table captures every inbound event; queue workers can be added in Phase 2
- **API-first** — paginated responses and clean DTOs ready for a frontend dashboard

---

## Project Structure

```
cx-agent-hub/
├── app/
│   ├── main.py              # FastAPI app + CORS + health endpoint
│   ├── core/
│   │   ├── config.py        # Settings from environment variables
│   │   ├── database.py      # Async SQLAlchemy engine + session
│   │   ├── security.py      # Password hashing + JWT (stdlib only)
│   │   └── logging.py       # Structured JSON logging (structlog)
│   ├── models/              # SQLAlchemy ORM models
│   │   ├── tenant.py        # Tenant, TenantConfig, ChannelConfig
│   │   ├── user.py          # User (owner / agent roles)
│   │   ├── customer.py      # Customer (per-tenant, per-channel)
│   │   ├── conversation.py  # Conversation
│   │   ├── ticket.py        # Ticket (pending_agent / resolved_auto / closed)
│   │   └── event_log.py     # UnifiedEvent persistence
│   ├── schemas/             # Pydantic DTOs (request / response)
│   ├── adapters/            # Channel adapter layer
│   │   ├── base.py          # UnifiedEvent model + BaseChannelAdapter
│   │   ├── whatsapp.py      # WhatsApp adapter
│   │   ├── webchat.py       # Web chat widget adapter
│   │   └── sms.py           # SMS adapter
│   ├── services/            # Business logic
│   │   ├── inbound_service.py  # Orchestrates inbound message pipeline
│   │   ├── tenant_service.py
│   │   ├── user_service.py
│   │   ├── customer_service.py
│   │   ├── conversation_service.py
│   │   └── ticket_service.py
│   └── api/v1/              # REST API routes
│       ├── auth/            # Login, /me
│       ├── tenants/         # Tenant CRUD + config
│       ├── users/           # User management
│       ├── customers/       # Customer management
│       ├── conversations/   # Conversations + event history
│       ├── tickets/         # Ticket management
│       └── channels/        # Inbound webhook endpoints
├── migrations/              # Alembic migrations
│   └── versions/
│       └── 001_initial_schema.py
├── tests/
│   ├── unit/                # Adapter + security unit tests
│   └── integration/         # API + tenant isolation integration tests
├── scripts/
│   └── seed.py              # Demo tenant seed data
├── Dockerfile
├── docker-compose.yml
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
1. Build the FastAPI image
2. Start PostgreSQL (port `5432`)
3. Run Alembic migrations automatically
4. Seed the demo tenant
5. Start the API on port `8000`

> First startup may take 2–3 minutes while Docker pulls images and builds.

### Step 4 — Verify the API is running

Open your browser or PowerShell:

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

### Useful Docker commands

```powershell
# View logs
docker compose logs api --follow

# Stop all services
docker compose down

# Stop and remove volumes (wipes database)
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
| `GET` | `/api/v1/users` | agent+ | List users in tenant |
| `POST` | `/api/v1/users` | owner | Create user |
| `GET` | `/api/v1/customers` | agent+ | List customers (paginated, filterable) |
| `GET` | `/api/v1/conversations` | agent+ | List conversations |
| `GET` | `/api/v1/conversations/{id}/events` | agent+ | Conversation message history |
| `GET` | `/api/v1/tickets` | agent+ | List tickets (paginated, filterable) |
| `PATCH` | `/api/v1/tickets/{id}` | agent+ | Update ticket (status, priority, assign) |
| `POST` | `/api/v1/inbound/whatsapp/{slug}` | None | Receive WhatsApp message |
| `POST` | `/api/v1/inbound/webchat/{slug}` | None | Receive web chat message |
| `POST` | `/api/v1/inbound/sms/{slug}` | None | Receive SMS message |

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

The rest of the pipeline (customer/conversation/ticket creation, event logging) requires no changes.

---

## Testing

```bash
# All tests
python -m pytest tests/ -v

# Unit tests only (no DB)
python -m pytest tests/unit/ -v

# Integration tests (uses in-memory SQLite)
python -m pytest tests/integration/ -v

# With coverage report
python -m pytest tests/ --cov=app --cov-report=term-missing
```

**Test coverage includes:**
- Channel adapter normalization (WhatsApp, WebChat, SMS)
- JWT creation and validation
- Password hashing and verification
- Multi-tenant data isolation (customers, conversations, tickets, users)
- RBAC enforcement (agent vs owner)
- Inbound channel pipeline (entity creation, conversation reuse)
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
| 17 | Channel adapter normalization tests | ✅ |

---

## Deferred to Future Phases

| Feature | Notes |
|---|---|
| AI decision engine | Will process `EventLog` entries asynchronously |
| RAG / knowledge base | Vector store + retrieval pipeline |
| Queue workers (Celery / RQ) | Async task processing for AI + notifications |
| Real WhatsApp provider | Plug in Meta Cloud API or Twilio adapter |
| Real SMS provider | Plug in Twilio, Vonage, or AWS SNS adapter |
| Frontend UI | Consumes existing REST APIs (pagination + DTOs ready) |
| Email channel adapter | Same pattern as existing adapters |
| Webhook signature verification | Per-channel HMAC validation (secret stored in ChannelConfig) |
| Rate limiting | Redis-based per-tenant throttling |
| Audit log | Track all state changes with actor |
| Analytics API | Aggregated metrics per tenant |
