# Bodhrik Technologies Full Stack Development Assessment

Backend REST API for a service booking and review platform built with **FastAPI**, **SQLAlchemy 2.x**, **PostgreSQL 16**, **Redis 7**, and **Pydantic v2**.

---

## Architecture Overview

```text
                                +---------------------------------------+
                                |             FastAPI API               |
                                |  (Port 8000: Auth, Bookings, Reviews) |
                                +-------------------+-------------------+
                                                    |
                       1. Enqueue Job (RPUSH)       |  2. Transient Job State (HSET/JSON)
                                                    v
                                    +---------------+---------------+
                                    |            Redis 7            |
                                    |  - Queue: queue:review_summary|
                                    |  - Key:   job:review_summary:*|
                                    +---------------+---------------+
                                                    ^
                       3. Dequeue Job (BLPOP)       |  5. Store Generated Summary
                                                    |
                                +-------------------+-------------------+
                                |     Review Summarisation Worker       |
                                |    (app.workers.review_worker)        |
                                +-------------------+-------------------+
                                                    |
                       4. Aggregate Reviews via SQL |
                                                    v
                                +-------------------+-------------------+
                                |         PostgreSQL 16                 |
                                |   (Users, Bookings, Reviews, Notifs)  |
                                +---------------------------------------+
```

---

## Core Features

- **Authentication & RBAC**: JWT-based bearer authentication with bcrypt password hashing. Fine-grained Role-Based Access Control distinguishing `CUSTOMER`, `PROVIDER`, and `ADMIN`.
- **Booking Management & Conflict Detection**:
  - Full REST CRUD support.
  - Overlap and conflict prevention queries across timezone-aware schedules.
  - Business-safe `DELETE` operation: transitions unconfirmed `PENDING` bookings to `CANCELLED` while preserving historical records, reviews, and audit trails.
- **Reviews & Ratings**: One review per completed booking with 1–5 star ratings and SQL aggregate metrics.
- **Review Summarisation Queue (Redis)**:
  - Asynchronous task processing decoupled via a Redis List FIFO queue (`queue:review_summary`).
  - Dedicated background worker (`app.workers.review_worker`) that computes metrics and generates deterministic summary reports.
  - Job tracking with 24-hour TTL state caching in Redis.
- **Persistent Notifications & Background Jobs**: In-app notifications with transactional deduplication (`ON CONFLICT DO NOTHING`) and automated background reminder/overdue schedulers.
- **Production Hardening**: Centralized exception handling, clean 422 validation formatting, separate `/health` (liveness) and `/ready` (Postgres + Redis dependency readiness) probes, security headers, CORS controls (supporting Vite dev servers), and bounded pagination.
- **CI/CD & Dockerization**: End-to-end multi-container environment in `docker-compose.yml` and automated GitHub Actions workflow.
- **Architectural Design Note**: 300–500 word written architectural analysis in [DESIGN_NOTE.md](DESIGN_NOTE.md).

---

## Technology Stack

| Layer | Technology |
| :--- | :--- |
| **Framework** | FastAPI 0.115+, Starlette |
| **Database** | PostgreSQL 16 (via SQLAlchemy 2.0 & Psycopg 3) |
| **Migrations** | Alembic 1.13+ |
| **Queue / Cache** | Redis 7 (via `redis-py` 5.0+) |
| **Data Validation** | Pydantic v2 (Pydantic Settings) |
| **Security** | PyJWT (HS256), Bcrypt |
| **Containerization**| Docker, Docker Compose |
| **Testing & Lint** | Pytest, HTTPX, Ruff |
| **CI** | GitHub Actions |

---

## Project Structure

```text
bodhrik-fullstack-assessment/
├── app/
│   ├── api/
│   │   ├── deps.py              # Auth & DB injection dependencies
│   │   └── v1/
│   │       ├── auth.py          # /api/v1/auth routes
│   │       ├── bookings.py      # /api/v1/bookings CRUD routes
│   │       ├── health.py        # /health & /ready probes
│   │       ├── notifications.py # /api/v1/notifications routes
│   │       ├── providers.py     # /api/v1/providers routes
│   │       └── reviews.py       # /api/v1/reviews & summarisation routes
│   ├── core/
│   │   ├── config.py            # Pydantic BaseSettings & CORS validation
│   │   ├── exceptions.py        # AppException domain error hierarchy
│   │   ├── redis.py             # Redis client pool & health check
│   │   └── security.py          # Password hashing & JWT issuance
│   ├── db/
│   │   ├── base.py              # DeclarativeBase
│   │   └── session.py           # Engine & SessionLocal
│   ├── jobs/                    # In-process booking reminder & overdue jobs
│   ├── models/                  # SQLAlchemy ORM models (User, Booking, Review, Notification)
│   ├── schemas/                 # Pydantic request & response schemas
│   ├── services/                # Encapsulated domain business logic
│   └── workers/
│       └── review_worker.py     # Standalone Redis review summarisation worker
├── alembic/                     # Database migrations
├── tests/                       # Pytest test suite (195+ tests)
├── .github/workflows/ci.yml     # GitHub Actions pipeline
├── docker-compose.yml           # Complete Postgres, Redis, API, and Worker stack
├── Dockerfile                   # Unified container image definition
├── pyproject.toml               # Package dependencies & tool configs
├── DESIGN_NOTE.md               # 300–500 word written architectural analysis
└── README.md                    # System documentation
```

---

## Quickstart with Docker Compose

Run the complete platform end-to-end (PostgreSQL, Redis, API, and Review Worker):

```bash
docker compose up --build
```

- **API Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Alternative ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Liveness Probe**: `GET http://localhost:8000/health`
- **Readiness Probe**: `GET http://localhost:8000/ready` (validates PostgreSQL + Redis)

To stop the containers:
```bash
docker compose down
```

---

## Local Development Setup

### 1. Prerequisites
- Python 3.12+
- Docker (for local PostgreSQL and Redis services)

### 2. Environment Configuration
Create a `.env` file from `.env.example`:
```bash
cp .env.example .env
```

### 3. Start Backing Infrastructure
```bash
# Start PostgreSQL and Redis containers
docker compose up -d postgres redis
```

### 4. Install Dependencies
```bash
python -m venv .venv
# On Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# On Linux/macOS:
source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[dev]"
```

### 5. Run Migrations
```bash
alembic upgrade head
```

### 6. Run the API Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Run the Review Summarisation Worker
In a separate terminal:
```bash
python -m app.workers.review_worker
```

---

## API Endpoints Reference

### Health & Probes
- `GET /health` — Process liveness probe (`{"status": "ok"}`).
- `GET /ready` — Dependency readiness check verifying PostgreSQL and Redis.

### Authentication
- `POST /api/v1/auth/register` — Register customer account.
- `POST /api/v1/auth/login` — Authenticate and receive JWT access token.
- `GET /api/v1/auth/me` — Retrieve profile of current authenticated user.

### Bookings (REST CRUD)
- `POST /api/v1/bookings` — Create a booking reservation (Customer).
- `GET /api/v1/bookings` — List visible bookings (Role-scoped).
- `GET /api/v1/bookings/{id}` — Retrieve details of a booking.
- `PATCH /api/v1/bookings/{id}` — Update schedule, service, or status.
- `POST /api/v1/bookings/{id}/cancel` — Cancel a booking reservation.
- `DELETE /api/v1/bookings/{id}` — Business-safe deletion (transitions PENDING to CANCELLED; protects historical records).

### Reviews & Summarisation
- `POST /api/v1/reviews` — Author a review for a completed booking (Customer only).
- `GET /api/v1/reviews` — List reviews with role-based filtering.
- `GET /api/v1/reviews/{id}` — Retrieve review details.
- `PATCH /api/v1/reviews/{id}` — Edit author's review.
- `DELETE /api/v1/reviews/{id}` — Delete review (Author customer or Admin).
- `POST /api/v1/reviews/summarize` — Enqueue asynchronous summarisation job in Redis (`202 Accepted`).
- `GET /api/v1/reviews/summarize/{job_id}` — Poll summarisation status and retrieve generated summary.

### Providers & Notifications
- `GET /api/v1/providers` — List registered providers.
- `GET /api/v1/providers/{id}/availability` — Check slot availability.
- `GET /api/v1/providers/{id}/reviews/summary` — Synchronous review metrics.
- `GET /api/v1/notifications` — List persistent user notifications.
- `PATCH /api/v1/notifications/{id}/read` — Mark notification as read.
- `POST /api/v1/notifications/read-all` — Mark all notifications read.

---

## Testing & Quality Assurance

Run the automated test suite with pytest:
```bash
pytest -v
```

Run code formatting and linter checks:
```bash
# Check code style and imports
ruff check .

# Check code formatting
ruff format --check .
```

Verify migration heads:
```bash
alembic current
alembic heads
```

---

## Continuous Integration

The repository includes a GitHub Actions pipeline in `.github/workflows/ci.yml`. On each push and pull request to `main`, CI:
1. Spins up PostgreSQL 16 and Redis 7 service containers.
2. Installs dependencies in Python 3.12.
3. Executes `ruff check .` and `ruff format --check .`.
4. Runs `alembic upgrade head`.
5. Executes the complete `pytest` test suite.

---

## Architectural Decisions

For an analysis of the schema design, normalisation tradeoffs, RBAC evolutions (including support for a 4th role and nested organisations), and production security considerations, refer to [DESIGN_NOTE.md](DESIGN_NOTE.md).
