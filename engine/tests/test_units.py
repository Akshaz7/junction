from engine.units import convert


def R(v, u="m", text="The wall is **256.8 m** long. [1]", ab=False):
    return {"answer": {"text_md": text, "value": v, "unit": u, "confidence": 0.9, "abstained": ab}}


def test_feet():
    o = convert(R(256.8), "How long are the walls in feet?")
    t = o["answer"]["text_md"]
    assert "**842.5 ft** (256.8 m)" in t and "**256.8 m**" in t and "[1]" in t
    assert o["answer"]["value"] == 256.8


def test_sqft_acres_hectares():
    assert "**1,172 ft\u00b2** (108.9 m\u00b2)" in convert(R(108.9, "m2"), "area in square feet?")["answer"]["text_md"]
    assert "ft\u00b2" in convert(R(108.9, "m2"), "area in sq ft")["answer"]["text_md"]
    assert "**1.00 acres**" in convert(R(4046.8564224, "m2"), "area in acres")["answer"]["text_md"]
    assert "**1.00 ha**" in convert(R(10000, "m2"), "in hectares")["answer"]["text_md"]


def test_cm_mm_yards():
    assert "**300.0 cm**" in convert(R(3.0), "wall length in cm")["answer"]["text_md"]
    assert "**3,000 mm**" in convert(R(3.0), "in mm")["answer"]["text_md"]
    assert "**10.0 yd**" in convert(R(9.144), "in yards")["answer"]["text_md"]


def test_cost():
    o = convert(R(108.9, "m2", "Area **108.9 m²**. [1]"), "What is the floor area at 35 EUR per m2?")
    assert "**3,811.50 EUR** at 35 EUR/m² × 108.9 m²" in o["answer"]["text_md"]
    for q in ("cost at €35/m²?", "cost at 35 euros a square metre?"):
        assert "3,811.50 EUR" in convert(R(108.9, "m2"), q)["answer"]["text_md"]


def test_noop_cases():
    assert convert(R(5, "count"), "in feet") == R(5, "count")
    assert convert(R(5, ab=True), "in feet") == R(5, ab=True)
    assert convert(R({"a": 1}), "in feet") == R({"a": 1})
    assert convert(R(5), "how long is the wall?") == R(5)
    assert convert(R(5, "m2"), "in feet") == R(5, "m2")  # length target on an area value: no clause
