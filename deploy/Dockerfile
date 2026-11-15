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
RUN uv pip install --system --no-cache pillow numpy pypdfium2 pdfminer.six ezdxf trimesh shapely scipy fast-simplification opencv-python-headless rapidocr-onnxruntime
# rapidocr pulls in the full opencv-python, which needs X11 libs missing from slim: keep only the headless build.
RUN uv pip uninstall --system opencv-python || true; uv pip install --system --no-cache --reinstall opencv-python-headless
# IFC uploads: ifcopenshell (LGPL) geometry -> GLB (pipeline/ifc_scene.convert_py), pygltflib for node boxes, usd-core for the AR USDZ.
RUN uv pip install --system --no-cache ifcopenshell==0.9.0.post1 pygltflib==1.16.5 usd-core
COPY server ./server
COPY engine ./engine
COPY pipeline ./pipeline
COPY scripts/heavy.sh ./scripts/heavy.sh
COPY COSTS.md /app/COSTS.md
ENV MODELS_COSTS_MD=/app/COSTS.md
RUN python -c 'import json; from pathlib import Path; from datetime import datetime, timezone; from server.image_info import code_hash; Path("IMAGE_INFO.json").write_text(json.dumps({"code_hash": code_hash(Path.cwd()), "built_at": datetime.now(timezone.utc).isoformat()}))'
COPY vision/verify.py vision/planmap_schema.json ./vision/
COPY results/bench/*.json /app/results/bench/
# Baked-in demo artifacts (deploy/build_demo_artifacts.py); empty unless built before the image build.
COPY --chown=app:app deploy/demo_artifacts/ /app/artifacts/
ENV ARTIFACTS_DIR=/app/artifacts RESULTS_DIR=/tmp/hologram MODELS_CACHE_DIR=/tmp/hologram/models-cache \
    MODELS_COSTS_LOG=/tmp/hologram/costs.jsonl INGEST_MODE=vlm
RUN mkdir -p /app/artifacts/uploads /tmp/hologram && python -m engine.project_index build && chown -R app:app /app/artifacts /tmp/hologram
USER app
# 10 GB / multi-CPU plan (startup-200-10240): several API workers (live sync fans out over PG NOTIFY, state is in PG/disk),
# bigger IFC budgets, whole-job watchdog 15 min, 3 concurrent ingests per box (heavy.sh slots).
ENV RATE_LIMIT=1 HIDE_EMPTY_DOCS=1 WEB_CONCURRENCY=3 \
    IFC_WORKER_MEMORY_MB=4096 IFC_SCENE_TIMEOUT_S=420 IFC_INDEX_TIMEOUT_S=300 IFC_INPROC_MAX_MB=60 \
    INGEST_TIMEOUT_S=900 INGEST_CONCURRENCY=1 HEAVY_SLOTS=3
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "3", "--timeout-keep-alive", "75"]
