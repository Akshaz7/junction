"""S-25: real issue ids, no synthetic inputs, and honest comparisons.

Temporary artifact contents below are generated for demo test fixtures only.
These tests need neither the dataset nor a running PostgreSQL server.
"""
import asyncio
import json

import pytest

from server import changes_source as cs, docmeta_store

SPORTS = [f"opening_design__sports-complex-transfer-archive-{date}-restroom-markups-locker-rooms-and-restrooms"
          for date in (20150811, 20150812)]
STRUCTURAL = [f"opening_design__vacation-rental-transfer-{date}-for-permit-structural-review-from-regis-the-downtowner-arch-exterior-details-s401"
              for date in (20170517, 20170518)]
FOUNDATION = "opening_design__ctr-transfer-20190701-from-arch-to-struct-foundation-markups-20190630-ctr-foundation-plans-od-markups"


def record(did, title, pages=1):
    return {"doc_id": did, "source": "opening_design", "kind": "pdf", "title": title, "pages": pages}


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_DIR", str(tmp_path))
    monkeypatch.delenv("HIDE_EMPTY_DOCS", raising=False)
    docmeta_store._cache.clear()
    cs._computed.clear()
    yield tmp_path
    docmeta_store._cache.clear()
    cs._computed.clear()


def install_series(root, versions=None):
    versions = versions or [{"doc_id": did, "date": date, "pages": pages, "label": f"Version {i} · {date}"}
                            for i, (did, date, pages) in enumerate(zip(SPORTS, ("2015-08-11", "2015-08-12"), (7, 6)), 1)]
    series = {"series_id": "sports-restrooms", "title": "Locker Rooms and Restrooms", "project": "Sports Complex",
              "discipline": "Architecture", "versions": versions}
    d = root / "series"
    d.mkdir(exist_ok=True)
    (d / "sports-restrooms.json").write_text(json.dumps(series))
    return series


def write(root, did, name, data):
    d = root / did
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(data))


def test_grouping_real_ids_dates_sheet_and_project():
    records = [record(did, "S401 Bracing Details") for did in reversed(STRUCTURAL)]
    records += [record(did, "Locker Rooms and Restrooms", pages) for did, pages in zip(SPORTS, (7, 6))]
    records += [record("opening_design__different-project-transfer-20170517-s401", "S401 Bracing Details")]
    records += [record("swiss_dwellings__test@v1", "S401 Bracing Details")]
    series = cs.build_series(records)
    assert len(series) == 2
    structural = next(s for s in series if s["sheet"] == "S401")
    assert [v["doc_id"] for v in structural["versions"]] == STRUCTURAL
    assert [v["date"] for v in structural["versions"]] == ["2017-05-17", "2017-05-18"]
    assert structural["discipline"] == "Structural"


def test_registry_fallback_uses_consecutive_pairs_and_distinct_dates(isolated):
    ids = [f"opening_design__sports-complex-transfer-archive-{date}-restroom-markups-locker-rooms-and-restrooms"
           for date in (20150811, 20150812, 20150813)]
    recs = [record(did, "Locker Rooms and Restrooms", 6) for did in reversed(ids)]
    recs.append(record(ids[0] + "-copy", "Locker Rooms and Restrooms", 1))
    (isolated / "registry.jsonl").write_text("\n".join(json.dumps(r) for r in recs))
    feed = cs.series_entries()
    assert [(e["doc_a"], e["doc_b"]) for e in feed] == list(zip(ids, ids[1:]))
    assert len({e["id"] for e in feed}) == 2
    assert all(e["summary"]["discipline"] == "Architecture" for e in feed)
    assert "generated_for_demo" not in json.dumps(feed)


def test_missing_diff_is_new_issue_with_actual_page_counts(isolated):
    install_series(isolated)
    entry, = cs.series_entries()
    assert entry["summary"]["n_changes"] is None
    assert entry["summary"]["headline"] == "New issue of Locker Rooms and Restrooms (7 → 6 pages). Comparison not available."
    detail = cs.comparison(entry["id"])
    assert detail["changes"] == [] and detail["image"] is None
    assert detail["v1"]["doc_id"] == SPORTS[0] and detail["v2"]["doc_id"] == SPORTS[1]
    assert detail["v1"]["pages"] == 7 and detail["v2"]["pages"] == 6
    assert "generated_for_demo" not in json.dumps(detail)


def test_sender_recipient_are_explicit_and_missing_values_stay_unknown():
    assert cs._parties(FOUNDATION) == {"sender": "arch", "recipient": "struct"}
    assert cs._parties(SPORTS[0]) == {"sender": None, "recipient": None}
    assert cs._parties(STRUCTURAL[0])["sender"] == "regis"


def test_real_planmaps_use_engine_and_do_not_leak_demo_flag(isolated):
    series = install_series(isolated, [{"doc_id": d, "date": date, "pages": 1, "label": f"Version {n}"}
                                      for n, (d, date) in enumerate(zip(SPORTS, ("2015-08-11", "2015-08-12")), 1)])
    plan = {"image": {"w": 100, "h": 80}, "scale": {}, "items": []}
    write(isolated, SPORTS[0], "planmap-1.json", plan)
    item = {"item_id": "door-001", "kind": "door", "conf": 1, "bbox_px": [10, 10, 20, 30]}
    write(isolated, SPORTS[1], "planmap-1.json", dict(plan, items=[item]))
    diff = cs.pair_diff(series, 0)
    assert diff["source"] == "engine"
    assert diff["changes"][0]["description"] == "A door was added."
    entry, = cs.series_entries()
    detail = cs.comparison(entry["id"])
    assert entry["summary"]["n_changes"] == 1
    assert detail["changes"][0]["v2"]["bbox_px"] == item["bbox_px"]
    assert "generated_for_demo" not in json.dumps([entry, detail])


def test_page_text_diff_is_limited_to_extracted_text(isolated):
    series = install_series(isolated, [{"doc_id": d, "date": date, "pages": 1, "label": f"Version {n}"}
                                      for n, (d, date) in enumerate(zip(SPORTS, ("2015-08-11", "2015-08-12")), 1)])
    for did, text in zip(SPORTS, ("WALL A", "WALL B")):
        write(isolated, did, "text-1.json", {"words": [{"text": text, "bbox_px": [0, 0, 20, 10]}]})
    diff = cs.pair_diff(series, 0)
    assert diff["source"] == "text-diff" and len(diff["changes"]) == 1
    assert diff["changes"][0]["text_old"] == "WALL A"
    assert "geometry has not been compared" in diff["note"]
    assert cs.comparison("ser:sports-restrooms:1")["changes"][0]["old"] == "WALL A"


def test_synthetic_and_stale_caches_are_never_shown(isolated):
    install_series(isolated)
    d = isolated / "series" / "diffs"
    d.mkdir()
    path = d / "sports-restrooms--1-2.json"
    for content in ({"generated_for_demo": True, "changes": [{"description": "fake"}]},
                    {"doc_a": "wrong", "doc_b": "wrong", "changes": [{"description": "stale"}]}):
        path.write_text(json.dumps(content))
        assert cs.series_entries()[0]["summary"]["n_changes"] is None


def test_visibility_matches_listed_and_servable_documents(monkeypatch):
    class Pool:
        async def fetch(self, query):
            assert query == "select doc_id from documents"
            return [{"doc_id": d} for d in [*SPORTS, "uploads__drawing", "empty"]]

    async def servable(pool):
        return {*SPORTS, "artifact-only-not-listed"}

    monkeypatch.setenv("HIDE_EMPTY_DOCS", "1")
    monkeypatch.setattr(cs.artifact_store, "servable_ids", servable)
    feed = [{"id": "real", "type": "new_version", "doc_a": SPORTS[0], "doc_b": SPORTS[1]},
            {"id": "hidden", "type": "new_version", "doc_a": SPORTS[0], "doc_b": "empty"},
            {"id": "unlisted", "type": "new_version", "doc_a": SPORTS[0], "doc_b": "artifact-only-not-listed"},
            {"id": "demo", "type": "new_version", "doc_a": SPORTS[0], "doc_b": SPORTS[1], "summary": {"generated_for_demo": True}},
            {"id": "upload", "type": "new_document", "doc_a": None, "doc_b": "uploads__drawing"},
            {"id": "rule", "type": "rule_change", "doc_a": None, "doc_b": None}]
    assert [e["id"] for e in asyncio.run(cs.visible_feed(Pool(), feed))] == ["real", "upload", "rule"]
    assert asyncio.run(cs.visible_pair(Pool(), *SPORTS))
    assert not asyncio.run(cs.visible_pair(Pool(), SPORTS[0], "empty"))
    monkeypatch.setenv("HIDE_EMPTY_DOCS", "0")
    assert asyncio.run(cs.visible_pair(Pool(), SPORTS[0], "empty"))
