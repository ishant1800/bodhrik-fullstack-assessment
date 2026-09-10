FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install minimal OS dependencies for network utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install project dependencies
COPY pyproject.toml README.md ./
RUN pip install --upgrade pip && \
    pip install .

# Copy application source code and migrations
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app

EXPOSE 8000

# Default command (overridden per service in docker-compose.yml)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
