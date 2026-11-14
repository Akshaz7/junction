from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.calc_routes import router


def test_calculation_exports_and_missing_calculation():
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    answer = {"question": "Area?", "answer": {"text_md": "12 m2"}, "reasoning": {"calc": {
        "formula": "area = width × depth", "status": "complete", "steps": [],
        "rows": [{"item_id": "room-1", "label": "Room", "values": {"area_m2": 12}, "source": {"doc_id": "file", "page": 1}}],
        "result": {"value": 12, "unit": "m2"}, "checks": [], "margin": {}}}}
    for fmt, expected in (("csv", "area_m2"), ("md", "# Calculation report"), ("html", "<h1>Calculation report</h1>")):
        response = client.post(f"/api/calculations/export/{fmt}", json=answer)
        assert response.status_code == 200 and expected in response.text
        assert response.headers["content-disposition"].endswith(f'calculation-report.{fmt}"')
    assert client.post("/api/calculations/export/csv", json={}).status_code == 422
    assert client.post("/api/calculations/export/nope", json=answer).status_code == 400
