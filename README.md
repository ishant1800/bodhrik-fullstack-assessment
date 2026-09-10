# Bodhrik Technologies Full Stack Development Assessment

Backend REST API built with **FastAPI**, **SQLAlchemy 2.x**, **PostgreSQL**, **Redis**, and **Pydantic v2**.

---

## Project Structure

```text
bodhrik-fullstack-assessment/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application entry point with /health
│   ├── api/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py  # Aggregates v1 routes
│   │       └── health.py    # Health check endpoint router
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py        # Pydantic v2 BaseSettings configuration
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py          # SQLAlchemy 2.0 DeclarativeBase
│   │   └── session.py       # DB engine, SessionLocal, check_db_connection helper
│   ├── models/              # SQLAlchemy ORM models (User, Booking, Review, enums)
│   ├── schemas/             # Pydantic schemas (UserResponse, Booking*, Review*)
│   ├── services/            # Business logic layer (empty placeholder)
│   └── workers/             # Background workers & queue tasks (empty placeholder)
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Pytest fixtures (TestClient)
│   ├── test_health.py       # Tests for /health endpoints
│   ├── test_models.py       # Tests for model metadata & in-memory constraints
│   ├── test_schemas.py      # Tests for Pydantic schema validation
│   └── test_postgres.py     # PostgreSQL integration tests
├── alembic/
│   ├── versions/            # Database migration revisions
│   ├── env.py               # Alembic runner reading app settings & Base.metadata
│   └── script.py.mako       # Migration template
├── alembic.ini              # Alembic configuration
├── docker-compose.yml       # Docker Compose setup for PostgreSQL 16
├── pyproject.toml           # Project metadata, dependencies, Ruff & Pytest configs
├── .env.example             # Environment variable template
├── .gitignore               # Git ignore rules
└── README.md                # Project documentation and setup guide
```

---

## Prerequisites

- **Python 3.12+**
- **pip** or **uv** package manager
- **Docker** and **Docker Compose** (or Docker Extension)

---

## Local Setup

### 1. Clone the repository

```bash
git clone <repo-url>
cd bodhrik-fullstack-assessment
```

### 2. Create and activate a virtual environment

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**Windows (Command Prompt):**
```cmd
python -m venv .venv
.venv\Scripts\activate.bat
```

### 3. Install dependencies

Install project dependencies including development tools (`pytest`, `ruff`, `httpx`):

```bash
pip install -e ".[dev]"
```

### 4. Configure Environment Variables

Create your local `.env` file from `.env.example`:

**Linux / macOS:**
```bash
cp .env.example .env
```

**Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

Edit `.env` to match your local configuration if needed.

---

## Local PostgreSQL Setup

### 1. Start PostgreSQL

Start the PostgreSQL service using Docker Compose:

```powershell
docker compose up -d postgres
```

*Alternatively, if using the VS Code / IDE **Docker Extension**, right-click `docker-compose.yml` in the file explorer and select **Compose Up**.*

### 2. Check PostgreSQL Status

Verify that the container is healthy and running:

```powershell
docker compose ps
```

### 3. Run Database Migrations

Apply the Alembic schema migrations against PostgreSQL:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
```

### 4. Verify Migration State

Check the current migration version and head:

```powershell
# View current database revision
.\.venv\Scripts\alembic.exe current

# View available migration heads (expected: 0001_initial_schema)
.\.venv\Scripts\alembic.exe heads
```

### 5. Stop PostgreSQL

To stop the PostgreSQL container:

```powershell
docker compose down
```

> **Data Persistence:** The PostgreSQL database files are persisted in the `postgres_data` named Docker volume. Data remains safe across container restarts and updates until explicitly removed via `docker compose down -v`.

---

## Running the API

Start the FastAPI development server with hot-reloading:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Once running:
- **API Health Check**: http://localhost:8000/health
- **Interactive Swagger Docs**: http://localhost:8000/docs
- **Alternative ReDoc**: http://localhost:8000/redoc

---

## Running Tests

Run the test suite using `pytest`:

```bash
pytest -v
```

All existing unit tests and live PostgreSQL integration tests (when the database is running) will execute automatically.

---

## Linting and Code Formatting

Check code quality with Ruff:

```bash
ruff check .
```

Automatically fix lint issues:
```bash
ruff check --fix .
```

Format code:
```bash
ruff format .
```
