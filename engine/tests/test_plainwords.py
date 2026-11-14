import copy
import re

import pytest

from engine.plainwords import apply, plain


@pytest.mark.parametrize("text, expected", [
    ("IfcFlowSegment: 12.34 m [1]", "service segment: 12.34 m [1]"),
    ("IfcPipeSegmentType DN0", "pipe segment nominal diameter 0"),
    ("Basic Wall: Generic - 200 mm", "wall: Generic - 200 mm"),
    ("M_Single-Flush 0915 x 2134 mm", "single flush door 0915 x 2134 mm"),
    ("IfcWallStandardCase, 10% waste", "wall, 10% waste"),
    ("Level 1: EI 60, 123456, 2.34 m² [3]", "Level 1: EI 60, 123456, 2.34 m² [3]"),
])
def test_plain_numbers_and_citation_markers_unchanged(text, expected):
    assert plain(text) == expected
    assert re.findall(r"\d+(?:\.\d+)?", text) == re.findall(r"\d+(?:\.\d+)?", plain(text))
    assert plain(plain(text)) == plain(text)


def test_display_only_preserves_identity_and_verbatim_sources():
    res = {"answer": {"text_md": "IfcDoor 7", "value": 7}, "citations": [{"label": "IfcDoor", "quote": "IfcDoor: 7", "item_ids": ["IfcDoor_123"]}],
           "evidence": {"scene": {"highlight_item_ids": ["IfcDoor_123"]}},
           "reasoning": {"steps": [{"text": "IfcDoor 7"}], "confidence": {"reason": "IfcDoorType", "improve": "Check DN0"}}}
    orig = copy.deepcopy(res)
    apply(res)
    assert res["answer"]["text_md"] == "door 7"
    assert res["citations"][0]["quote"] == orig["citations"][0]["quote"]
    assert res["evidence"] == orig["evidence"]
    assert res["reasoning"]["confidence"]["improve"] == "Check nominal diameter 0"
