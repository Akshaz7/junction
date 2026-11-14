"""Tool-using drawing reader: text layer, tables, scale, crops, plan map and IFC queries behind a planner loop."""


def __getattr__(name):
    # Keep the request cache importable by the lightweight document loader.
    if name == "read_answer":
        from engine.reader.agent import read_answer
        return read_answer
    raise AttributeError(name)
