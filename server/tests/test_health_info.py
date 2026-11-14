"""S-27: health reports evidence from the running image, independent of BUILD_REV."""
import json
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from engine.models import core
from server import app as app_module, artifact_store, config, db
from server.image_info import code_hash

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def health_env(monkeypatch, tmp_path):
    root = tmp_path / "image"
    root.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(config, "REPO", root)
    monkeypatch.setenv("ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("RESULTS_DIR", str(tmp_path / "runtime-results"))
    monkeypatch.setattr(core, "api_key", lambda provider: None)

    async def no_db():
        return False

    async def no_pool():
        pytest.fail("health must not retry a database known to be unavailable")

    monkeypatch.setattr(db, "db_ok", no_db)
    monkeypatch.setattr(db, "get_pool", no_pool)
    app = FastAPI()
    app.add_api_route("/api/health", app_module.health)
    with TestClient(app) as client:
        yield client, root, artifacts


def test_image_metadata_is_build_evidence(health_env, monkeypatch):
    client, root, _ = health_env
    image = {"code_hash": "a" * 64, "built_at": "2026-11-14T12:00:00+00:00"}
    (root / "IMAGE_INFO.json").write_text(json.dumps(image))
    monkeypatch.setenv("BUILD_REV", "unverified-revision")
    body = client.get("/api/health").json()
    assert body["image"] == image
    assert body["build_rev"] == "unverified-revision"
    # Runtime source edits and env labels cannot manufacture a newer image fingerprint.
    (root / "server").mkdir()
    (root / "server" / "changed.py").write_text("changed = True\n")
    monkeypatch.setenv("BUILD_REV", "another-revision")
    assert client.get("/api/health").json()["image"] == image


@pytest.mark.parametrize("metadata", [None, "broken json", "[]", '{"code_hash": 42}'])
def test_missing_or_invalid_metadata_is_unknown(health_env, monkeypatch, metadata):
    client, root, _ = health_env
    if metadata is not None:
        (root / "IMAGE_INFO.json").write_text(metadata)
    monkeypatch.setenv("BUILD_REV", "claimed-revision")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["image"] == {"code_hash": None, "built_at": None}


def test_counts_use_baked_bench_and_actual_artifacts(health_env):
    client, root, artifacts = health_env
    bench = root / "results" / "bench"
    bench.mkdir(parents=True)
    (bench / "one.json").write_text("{}")
    (bench / "two.json").write_text("{}")
    (bench / "ignored.jsonl").write_text("{}")
    (bench / "directory.json").mkdir()
    (bench / "nested").mkdir()
    (bench / "nested" / "three.json").write_text("{}")
    runtime = config.results_dir() / "bench"
    runtime.mkdir(parents=True)
    (runtime / "runtime.json").write_text("{}")
    for name in ("demo__one", "demo__two", "uploads"):
        (artifacts / name).mkdir()
    (artifacts / "demo__one" / "nested").mkdir()
    (artifacts / "not-a-directory").write_text("x")
    body = client.get("/api/health").json()
    assert body["bench_files"] == 2
    assert body["artifacts_docs"] == 3
    assert body["servable_docs"] is None
    assert body["db"] is False


def test_missing_directories_have_zero_files(health_env):
    client, _, artifacts = health_env
    artifacts.rmdir()
    body = client.get("/api/health").json()
    assert body["bench_files"] == 0 and body["artifacts_docs"] == 0


@pytest.mark.parametrize("ids, expected", [(set(), 0), ({"demo__one", "db__two"}, 2), (None, None)])
def test_servable_list_zero_count_and_unavailable(health_env, monkeypatch, ids, expected):
    client, _, _ = health_env
    pool = object()

    async def db_ok():
        return True

    async def get_pool():
        return pool

    async def servable_ids(actual_pool):
        assert actual_pool is pool
        if ids is None:
            raise RuntimeError("list unavailable")
        return ids

    monkeypatch.setattr(db, "db_ok", db_ok)
    monkeypatch.setattr(db, "get_pool", get_pool)
    monkeypatch.setattr(artifact_store, "servable_ids", servable_ids)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["servable_docs"] == expected


def _sources(root):
    for folder in ("server", "engine", "pipeline"):
        (root / folder).mkdir(parents=True)
        (root / folder / "__init__.py").write_text("")
        (root / folder / "source.py").write_text(f"name = {folder!r}\n")
    (root / "engine" / "models.yaml").write_text("provider: fake\n")


def test_hash_tracks_sources_and_names_but_ignores_bytecode_and_mtimes(tmp_path):
    _sources(tmp_path)
    original = code_hash(tmp_path)
    assert re.fullmatch(r"[0-9a-f]{64}", original)
    (tmp_path / "server" / "source.py").touch()
    cache = tmp_path / "server" / "__pycache__"
    cache.mkdir()
    (cache / "source.cpython-312.pyc").write_bytes(b"bytecode")
    (tmp_path / "server" / "source.pyc").write_bytes(b"bytecode")
    assert code_hash(tmp_path) == original
    model = tmp_path / "engine" / "models.yaml"
    model.write_text("provider: changed\n")
    assert code_hash(tmp_path) != original
    model.write_text("provider: fake\n")
    assert code_hash(tmp_path) == original
    model.rename(model.with_name("renamed.yaml"))
    assert code_hash(tmp_path) != original


def test_docker_build_command_and_local_script_match_without_git(tmp_path):
    _sources(tmp_path)
    shutil.copy(REPO / "server" / "image_info.py", tmp_path / "server" / "image_info.py")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(REPO / "scripts" / "image_hash.py", scripts / "image_hash.py")
    # Execute the actual Docker RUN command in a miniature build context; no Docker job needed.
    line = next(line for line in (REPO / "deploy" / "Dockerfile").read_text().splitlines()
                if line.startswith("RUN ") and "IMAGE_INFO.json" in line)
    command = shlex.split(line.removeprefix("RUN "))
    before = datetime.now(timezone.utc)
    subprocess.run([sys.executable, *command[1:]], cwd=tmp_path, check=True, timeout=10)
    image = json.loads((tmp_path / "IMAGE_INFO.json").read_text())
    assert before <= datetime.fromisoformat(image["built_at"]) <= datetime.now(timezone.utc)
    # Invoke from outside the checkout; the script must find its own repository root.
    result = subprocess.run([sys.executable, str(scripts / "image_hash.py")], cwd=tmp_path.parent,
                            check=True, capture_output=True, text=True, timeout=10)
    assert result.stdout.strip() == image["code_hash"] == code_hash(tmp_path)
