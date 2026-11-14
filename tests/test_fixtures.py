from pipeline.fixtures import load_fixtures


def test_loader_returns_10_docs():
    docs = load_fixtures()
    assert len(docs) == 10
    ids = {d["doc_id"] for d in docs}
    assert "cubicasa5k__colorful-11397" in ids and "ifc_bench__ac20-arc" in ids and "ifc_bench__digital-hub-arc" in ids
    assert sum(d["source"] == "cubicasa5k" for d in docs) == 4
    sw = [d for d in docs if d["source"] == "swiss_dwellings"]
    assert len(sw) == 3 and all({"pdf", "dxf", "png"} <= set(d["formats"]) for d in sw)
    assert sum(d["source"] == "ifc_models" and "pdf" in d["formats"] for d in docs) == 1
