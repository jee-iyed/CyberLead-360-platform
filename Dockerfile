# syntax=docker/dockerfile:1
# CyberLead 360 — production-style image (non-root, locked dependencies).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv

WORKDIR /app

# 1) Dependencies only (cached layer): reproducible from uv.lock
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra postgres --no-install-project

# 2) Application code
COPY src ./src
COPY alembic ./alembic
COPY pages ./pages
COPY scripts ./scripts
COPY .streamlit ./.streamlit
COPY data/samples ./data/samples
COPY app.py alembic.ini ./
RUN uv sync --frozen --no-dev --extra postgres

# 3) Least privilege: dedicated user, writable data directory only
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data/exports \
    && chown -R appuser:appuser /app/data
USER appuser

ENV DATABASE_URL=sqlite:////app/data/cyberlead360.db \
    APP_ENV=production \
    LOG_FORMAT=json

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4)" || exit 1

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
