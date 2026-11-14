"""Plumbing IFC detection at ingest: byte scan for pipe/flow segments."""
from server.ingest_job import _has_piping


def test_has_piping(tmp_path):
    a = tmp_path / "a.ifc"
    a.write_text("#1=IFCWALL('x');\n#2=IFCPIPESEGMENT('y',$);\n")
    b = tmp_path / "b.ifc"
    b.write_text("#1=IFCWALL('x');\n" + "#9=IFCDOOR('d');\n" * 1000)
    c = tmp_path / "c.ifc"
    c.write_text("#2=ifcflowsegment('y');")
    assert _has_piping(a) and _has_piping(c) and not _has_piping(b)
