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
# Upload ingestion (VLM plan map, no torch/weights): PDF render + text layer, DXF, 3D extrusion (see deploy/README.md).
RUN uv pip install --system --no-cache pillow numpy pypdfium2 pdfminer.six ezdxf trimesh shapely scipy
# IFC uploads: ifcopenshell (LGPL) geometry -> GLB (pipeline/ifc_scene.convert_py), pygltflib for node boxes, usd-core for the AR USDZ.
RUN uv pip install --system --no-cache ifcopenshell==0.9.0.post1 pygltflib==1.16.5 usd-core
COPY server ./server
COPY engine ./engine
COPY pipeline ./pipeline
COPY vision/verify.py vision/planmap_schema.json ./vision/
# Baked-in demo artifacts (deploy/build_demo_artifacts.py); empty unless built before the image build.
COPY --chown=app:app deploy/demo_artifacts/ /app/artifacts/
ENV ARTIFACTS_DIR=/app/artifacts RESULTS_DIR=/tmp/hologram MODELS_CACHE_DIR=/tmp/hologram/models-cache \
    MODELS_COSTS_LOG=/tmp/hologram/costs.jsonl INGEST_MODE=vlm
RUN mkdir -p /app/artifacts/uploads /tmp/hologram && python -m engine.project_index build && chown -R app:app /app/artifacts /tmp/hologram
USER app
ENV RATE_LIMIT=1
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
