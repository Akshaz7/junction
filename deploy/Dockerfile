# Production API container. Build from repo root: docker build -f deploy/Dockerfile .
# (run through scripts/heavy.sh)
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app
RUN useradd --create-home --uid 1000 app
# The API only needs the web stack; install it directly instead of the full ML project.
RUN uv pip install --system fastapi "uvicorn[standard]" asyncpg httpx pydantic \
    sse-starlette python-multipart python-dotenv pyyaml jsonschema
COPY server ./server
COPY engine ./engine
# Baked-in demo artifacts (deploy/build_demo_artifacts.py); empty unless built before the image build.
COPY --chown=app:app deploy/demo_artifacts/ /app/artifacts/
ENV ARTIFACTS_DIR=/app/artifacts MODELS_CACHE_DIR=/tmp/hologram/models-cache MODELS_COSTS_LOG=/tmp/hologram/costs.jsonl
USER app
ENV RATE_LIMIT=1
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
