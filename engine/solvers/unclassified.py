"""Missing IFC object types cannot establish that a requested object is absent."""


def count_unavailable(question, doc, kind, trace, route, t0):
    from .solve import _answer_obj, _cite_marks, _evidence, _plural, _step

    unknown = [i for i in doc.items if i.kind == "proxy"]
    if not unknown:
        return None
    boxes, cites, scene = _evidence(doc, unknown[:20])
    trace.append(_step("unclassified", "Object types are missing; a zero count is not established."))
    text = (f"**I cannot verify a {_plural(kind, 1)} count from this model.** "
            f"It includes shapes without object types. {_cite_marks(cites)}\n\n"
            "Export the model with object classifications, or check the highlighted shapes.")
    res = _answer_obj(question, [doc.doc_id], text, None, None, 0.0, True,
                      boxes, cites, scene, trace, route, t0)
    res["reasoning"] = {
        "steps": [{"kind": "checked", "title": "Missing object types",
                   "text": "The marked shapes have no building object type in the source model.",
                   "cite": cites[0]["n"] if cites else None, "ok": False}],
        "confidence": {"label": "Estimate", "pct": 0,
                       "reason": "The source does not provide enough object classification to verify this count.",
                       "improve": "Export the model with object classifications, or inspect the highlighted shapes."},
    }
    return res
