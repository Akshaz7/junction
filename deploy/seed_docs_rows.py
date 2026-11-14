"""Upsert `documents` rows (from artifacts/<doc>/doc.json) for docs loaded into PG; the loader stores artifacts only.
  DATABASE_URL=... .venv/bin/python deploy/seed_docs_rows.py ids.txt"""
import asyncio, json, os, sys
from pathlib import Path
import asyncpg
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server import seed  # noqa: E402

async def main():
    ids = [l.strip() for l in Path(sys.argv[1]).read_text().split() if l.strip()]
    c = await asyncpg.connect(os.environ.get("TARGET_DATABASE_URL") or os.environ["DATABASE_URL"])
    rows = [json.loads((ROOT / "artifacts" / d / "doc.json").read_text()) for d in ids]
    print("documents upserted:", await seed.seed_documents(c, rows))
    await c.close()
asyncio.run(main())
