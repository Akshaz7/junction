"""DXF layout and declared-unit handling, without dataset-specific defaults."""
import math


def drawing_layout(doc):
    """Prefer model space; use a populated paper layout when the model is empty."""
    model = doc.modelspace()
    if any(e.dxftype() != "VIEWPORT" for e in model):
        return model
    return next((layout for layout in doc.layouts if layout.name != "Model"
                 and any(e.dxftype() != "VIEWPORT" for e in layout)), model)


def metres_per_unit(doc):
    from ezdxf import units
    try:
        code = int(doc.header.get("$INSUNITS", 0))
        factor = units.conversion_factor(code, units.M)
        return factor if math.isfinite(factor) and factor > 0 else None
    except (ValueError, TypeError, IndexError):
        return None  # unitless drawings must never silently become metres


def reference_warnings(doc):
    refs = [block.name for block in doc.blocks if block.block.dxf.flags & 4]
    if not refs:
        return []
    return ["This drawing uses external references. Linked files are not loaded; counts cover only geometry stored in this DXF."]
