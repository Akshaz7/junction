"""Keep reader numeric fields in step with cited, deterministic tool results."""
from __future__ import annotations

from engine.numeric import count_question, headline_value, unit_name, whole_count
from engine.router.parser import parse


MEASURE_UNITS = {"m", "m2", "m3", "mm", "cm", "ft", "ft2", "ft3", "ft²", "ft³", "%", "sqm", "sq m"}


def recover_value(question, text, value, unit, sess, refs):
    """Return value/unit/notes/invalid-count; headline recovery never uses prose observations."""
    p = parse(question)
    expected = "count" if count_question(question) else {"area": "m2", "length": "m", "volume": "m3"}.get(p.type)
    notes = []
    if expected is None:
        return value, unit, notes, False
    if expected == "count" and value is not None:
        if not whole_count(value) or unit_name(unit) in MEASURE_UNITS:
            return None, None, ["a measurement or fractional value cannot answer an object count"], True
        # Reader units such as "saunas" refer to counted objects. Normalise at source.
        value, unit = int(value), "count"
    if value is None:
        bases = {r.partition("#c")[0] for r in refs}
        cited_ids = {(sess.ev[b].doc_id, iid) for b in bases for iid in sess.ev[b].item_ids}
        computed = []
        for result in sess.numeric_results:
            full_selection = {(result.get("doc_id"), iid) for iid in result.get("item_ids", [])}
            if not bases.intersection(result.get("refs", [])) and not (full_selection and full_selection <= cited_ids):
                continue
            if result.get("compute"):
                if expected == "count" or not result.get("grounded"):
                    continue  # unitless arithmetic could be an area or a length, even when integral
                # The arithmetic tool supplies a scalar; the numeric question
                # supplies its dimension. It still needs cited source evidence.
                result = {**result, "unit": expected}
            elif expected == "count":
                if p.kind and result.get("kind") != p.kind:
                    continue
                if p.kind == "room":
                    from engine.solvers.solve import room_subtype
                    subtype = room_subtype(question)
                    if subtype and subtype[0].casefold() not in result.get("name", "").casefold():
                        continue
            computed.append(result)
        recovered = headline_value(text, computed, expected)
        if recovered is not None:
            value = int(recovered) if expected == "count" else recovered
            unit = {"m2": "m²", "m3": "m³"}.get(expected, expected)
            notes.append("numeric field restored from a cited tool computation matching the single headline number")
    return value, unit, notes, False
