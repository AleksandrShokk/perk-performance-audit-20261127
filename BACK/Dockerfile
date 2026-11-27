FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
RUN pip install --no-cache-dir uv==0.12.23 \
    && useradd --create-home --uid 10001 perk

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY app ./app
COPY migrations ./migrations
COPY scripts ./scripts
COPY alembic.ini ./

USER perk
EXPOSE 8000
# Proxy headers are trusted only from FORWARDED_ALLOW_IPS (default 127.0.0.1: nobody else).
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--proxy-headers", "--limit-concurrency", "64", "--timeout-keep-alive", "5"]

FROM runtime AS test
USER root
RUN uv sync --locked --no-install-project
COPY tests ./tests
USER perk
CMD ["pytest", "-q", "-o", "cache_dir=/tmp/perk-pytest-cache"]
