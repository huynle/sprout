# syntax=docker/dockerfile:1
# Sprout: family app (HTTP on :8000).

FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.12
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim
RUN useradd --uid 10001 --user-group --create-home --home-dir /home/app app \
    && mkdir -p /data \
    && chown 10001:10001 /data
COPY --from=build --chown=10001:10001 /app/.venv /app/.venv
# The root filesystem can be read-only; /data and /tmp are writable volumes.
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    TMPDIR=/tmp
WORKDIR /app
USER 10001:10001
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"
CMD ["sprout", "serve", "--host", "0.0.0.0", "--port", "8000"]
