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
│   │   └── session.py       # DB engine, SessionLocal, and get_db dependency
│   ├── models/              # SQLAlchemy ORM models (empty placeholder)
│   ├── schemas/             # Pydantic schemas / DTOs (empty placeholder)
│   ├── services/            # Business logic layer (empty placeholder)
│   └── workers/             # Background workers & queue tasks (empty placeholder)
├── tests/
│   ├── __init__.py
│   ├── conftest.py          # Pytest fixtures (TestClient)
│   └── test_health.py       # Tests for /health endpoints
├── alembic/
│   ├── versions/            # Database migration revisions
│   ├── env.py               # Alembic runner reading app settings & Base.metadata
│   └── script.py.mako       # Migration template
├── alembic.ini              # Alembic configuration
├── pyproject.toml           # Project metadata, dependencies, Ruff & Pytest configs
├── .env.example             # Environment variable template
├── .gitignore               # Git ignore rules
└── README.md                # Project documentation and setup guide
```

---

## Prerequisites

- **Python 3.12+**
- **pip** or **uv** package manager

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
pytest
```

Run with verbose output:
```bash
pytest -v
```

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

---

## Database Migrations (Alembic)

When database models are added, run migrations using:

```bash
# Generate a new migration revision
alembic revision --autogenerate -m "migration description"

# Apply migrations
alembic upgrade head
```
