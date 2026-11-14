from engine.reader.agent import final_answer_text as f


def test_tool_step_never_streams():
    assert f('{"action":"tool","tool":"search","args":{"q":"answer"}}') is None
    assert f('{"action":"final","ans') is None


def test_final_answer_streams_cumulatively_and_decodes_escapes():
    full = '{"action":"final","answer":"**12 doors**\\nsee \\"e3\\" \\u00e4","value":12}'
    for i in range(len(full)):
        f(full[:i])  # no prefix raises
    assert f('{"action":"final","answer":"**12 do') == "**12 do"
    assert f(full) == '**12 doors**\nsee "e3" ä'
    assert f('{"action":"final","answer":"a\\') == "a"          # dangling escape waits
    assert f('{"action":"final","answer":"a\\u00') == "a"        # partial unicode waits
