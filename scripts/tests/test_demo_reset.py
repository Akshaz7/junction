"""Offline deletion-safety tests using sqlite with the deployed FK relationships."""
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest


SPEC = importlib.util.spec_from_file_location("demo_reset", Path(__file__).parents[1] / "demo_reset.py")
reset = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(reset)


class Database:
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            pragma foreign_keys=on;
            create table documents (doc_id text primary key, source text, title text);
            create table chats (id text primary key, doc_id text references documents, title text);
            create table messages (id text primary key, chat_id text references chats on delete cascade);
            create table answers (id text primary key, chat_id text references chats on delete cascade,
                                  message_id text references messages on delete cascade, doc_id text);
            create table changes (id text primary key, doc_a text, doc_b text, summary text);
            create table findings (id text primary key, doc_id text references documents);
            create table doc_artifacts (doc_id text, name text, primary key(doc_id, name));
            create table scene_edits (id text primary key, chat_id text references chats on delete cascade, doc_id text);
        """)
        self.writes = []
        self.fail_table = None

    @asynccontextmanager
    async def transaction(self, **kwargs):
        self.db.commit()
        self.db.execute("begin")
        try:
            yield
        except Exception:
            self.db.rollback()
            raise
        else:
            self.db.commit()

    async def fetch(self, query):
        return self.db.execute(query.removesuffix(" for update")).fetchall()

    async def execute(self, query, *values):
        self.writes.append((query, values))
        if self.fail_table and f"delete from {self.fail_table} " in query:
            raise RuntimeError("injected deletion failure")
        return self.db.execute(query.replace("$1", "?"), values)

    def ids(self, table, column="id"):
        return {r[0] for r in self.db.execute(f"select {column} from {table}")}

    def doc(self, doc_id, title, source="uploads"):
        self.db.execute("insert into documents values (?,?,?)", (doc_id, source, title))

    def chat(self, chat_id, title, doc_id=None):
        self.db.execute("insert into chats values (?,?,?)", (chat_id, doc_id, title))
        self.db.execute("insert into messages values (?,?)", (chat_id, chat_id))
        self.db.execute("insert into answers values (?,?,?,?)", (chat_id, chat_id, chat_id, doc_id))
        self.db.execute("insert into scene_edits values (?,?,?)", (chat_id, chat_id, doc_id))

    def change(self, change_id, summary, doc_a=None, doc_b=None):
        self.db.execute("insert into changes values (?,?,?,?)", (change_id, doc_a, doc_b, json.dumps(summary)))


@pytest.fixture
def db():
    db = Database()
    db.doc("ifc_bench__ac20-arc", "AC20", "ifc_bench")
    db.doc("cubicasa5k__generated-for-demo", "upload-fixture-123", "cubicasa5k")
    db.doc("uploads__upload-fixture-123", "upload-fixture-123")
    db.doc("uploads__smoke-123-generated-for-demo", "smoke-123-generated-for-demo")
    db.doc("uploads__web3-notes-123-generated-for-demo", "web3-notes-123-generated-for-demo")
    db.doc("uploads__real-plan", "Client floor plan")
    db.chat("cross", "Cross-device 1794659581450", "ifc_bench__ac20-arc")
    db.chat("smoke", "smoke-123", "uploads__upload-fixture-123")
    db.chat("real", "Draft claim", "ifc_bench__ac20-arc")
    db.change("generated", {"generated_for_demo": True}, "ifc_bench__ac20-arc")
    db.change("smoke-change", {"title": "smoke generated-for-demo"})
    db.change("linked", {}, "uploads__upload-fixture-123")
    db.change("real-change", {"generated_for_demo": False}, "ifc_bench__ac20-arc")
    db.db.execute("insert into findings values ('finding', 'uploads__upload-fixture-123')")
    db.db.execute("insert into doc_artifacts values ('uploads__upload-fixture-123', 'doc.json')")
    db.db.execute("insert into doc_artifacts values ('ifc_bench__ac20-arc', 'scene.glb')")
    yield db
    db.db.close()


@pytest.mark.asyncio
async def test_dry_run_lists_exact_apply_plan_without_writes(db, capsys):
    before = db.db.iterdump()
    before = list(before)
    planned = await reset.reset_database(db, dry_run=True)
    assert db.writes == []
    assert list(db.db.iterdump()) == before
    output = capsys.readouterr().out
    assert "DELETE chats id=cross" in output
    assert "DELETE documents doc_id=uploads__upload-fixture-123" in output
    assert "DELETE changes id=generated" in output
    assert planned == await reset.reset_database(db, dry_run=False)


@pytest.mark.asyncio
async def test_apply_removes_test_junk_and_children_but_preserves_dataset(db):
    await reset.reset_database(db, dry_run=False)
    assert db.ids("documents", "doc_id") == {
        "ifc_bench__ac20-arc", "cubicasa5k__generated-for-demo", "uploads__real-plan"}
    assert db.ids("chats") == db.ids("messages") == db.ids("answers") == db.ids("scene_edits") == {"real"}
    assert db.ids("changes") == {"real-change"}
    assert db.ids("findings") == set()
    assert db.ids("doc_artifacts", "doc_id") == {"ifc_bench__ac20-arc"}
    assert await reset.reset_database(db, dry_run=False) == []  # safe to rerun


@pytest.mark.asyncio
async def test_keep_ids_and_retained_references_protect_generated_demo(db):
    db.chat("retained", "Presentation", "uploads__web3-notes-123-generated-for-demo")
    db.change("retained-change", {"generated_for_demo": True}, "uploads__smoke-123-generated-for-demo")
    await reset.reset_database(db, dry_run=False, keep_ids={"cross", "generated", "retained-change"})
    assert {"cross", "real", "retained"} == db.ids("chats")
    assert {"real-change", "generated", "retained-change"} == db.ids("changes")
    assert {"uploads__web3-notes-123-generated-for-demo", "uploads__smoke-123-generated-for-demo"} <= db.ids("documents", "doc_id")


@pytest.mark.asyncio
async def test_keep_document_and_chat(db):
    await reset.reset_database(db, dry_run=False, keep_ids={"smoke", "uploads__web3-notes-123-generated-for-demo"})
    assert "smoke" in db.ids("chats")
    assert "uploads__upload-fixture-123" in db.ids("documents", "doc_id")
    assert "uploads__web3-notes-123-generated-for-demo" in db.ids("documents", "doc_id")


@pytest.mark.asyncio
async def test_failure_rolls_back_entire_cleanup(db):
    before = list(db.db.iterdump())
    db.fail_table = "documents"
    with pytest.raises(RuntimeError):
        await reset.reset_database(db, dry_run=False)
    assert list(db.db.iterdump()) == before


@pytest.mark.parametrize("title", ["Cross-device 1794659581450", "Follow 1794659581450", "W-20 history 123 second",
    "Live overview 123", "e2e-123", "smoke-123", "test chat", "Voice in AR", "WEB2: spin", "FIX-2 in place",
    "Live sync verification", "Visibility return verification", "Scene commands verification", "warmup-20261114T123456123456Z"])
def test_known_e2e_titles(title):
    assert reset.automated({"title": title})


@pytest.mark.parametrize("title", ["Draft claim", "Meeting prep", "Cross-device coordination", "Follow drawing revisions",
    "Testimonial", "Testing material options", "Latest design"])
def test_preserves_ordinary_titles(title):
    assert not reset.automated({"title": title})


def test_source_and_namespace_both_required():
    assert not reset.test_document({"doc_id": "ifc_bench__upload-fixture-123", "source": "uploads", "title": "upload-fixture-123"})
    assert not reset.test_document({"doc_id": "uploads__upload-fixture-123", "source": "ifc_bench", "title": "upload-fixture-123"})


def test_no_database_dry_run_never_opens_network(monkeypatch, capsys):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(sys, "argv", ["demo_reset.py", "--dry-run"])
    monkeypatch.setattr(reset, "urlopen", lambda *a, **k: pytest.fail("unexpected network"))
    assert reset.main() == 0
    assert "no DATABASE_URL" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_database_error_does_not_print_connection_credentials(monkeypatch):
    import asyncpg
    monkeypatch.setenv("DATABASE_URL", "postgres://user:secret@invalid/db")
    async def fail(*args, **kwargs):
        raise RuntimeError("postgres://user:secret@invalid/db")
    monkeypatch.setattr(asyncpg, "connect", fail)
    with pytest.raises(reset.DemoError) as error:
        await reset.database_cleanup(True, ())
    assert "secret" not in str(error.value)


@pytest.mark.parametrize("title", [None, "", "stress stress-r1", "ttft", "audit-x", "break-ui",
    "tellfix wall shot", "lead longest wall", "live doors", "logo check", "evui check"])
def test_matches_prod_test_chat_titles(title):
    assert reset.automated({"title": title})
