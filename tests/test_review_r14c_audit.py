"""Round-14c findings on the audit (GPT-6.1 Sol, ~/reviews/dc-i86-llm-forecast/round14/
FINDINGS-r14c.out.md): a printf format behind an option the quick-call check skipped, ids inside
lists and objects and with exponents Decimal cannot hold, and transcript lines holding a list. All
transcripts and files are MOCK, in a temporary MOCK work area (runners.WORK monkeypatched)."""

import pytest

from i86 import audit
from test_review_r13_inputs import area, audit_lines  # noqa: F401 (area is a fixture)
from test_review_r13b_audit import OTHER, bash, records


def raw(event, ident, command="echo MOCK"):
    """A Codex event as JSON text, so that its id is written as the test spells it."""
    return ('{"type": "%s", "item": {"id": %s, "type": "command_execution", "command": "%s"}}'
            % (event, ident, command))


# --- 1: printf's format behind an option ---------------------------------------------------------

SLOW_PRINTF = [
    "printf -vMOCK '%300000000s' x",  # Sol's: bash takes -vMOCK as an option, zsh as the format
    "printf -- '%300000000s' x",
    "printf -v MOCK -- '%300000000s' x",
    "printf -vMOCK -- '%300000000s' x",
    pytest.param("printf -v \"$MOCK_NAME\" '%300000000s' x", id="control-separate-v"),  # 19d1303 caught it
    "printf -- '%100000000s' x x x x x x x x > /dev/null",  # a format reused for each argument
]


@pytest.mark.parametrize("call", SLOW_PRINTF)
def test_a_printf_width_behind_an_option_may_outlast_its_timeout(area, tmp_path, call):
    """Sol 1: `_may_outlast` read only a separate `-v` as an option, so the width behind `-vNAME` or
    `--` went unseen, and the next call started in MOCK-sub only."""
    assert audit._may_outlast(call, 1000)
    out = audit_lines(area, tmp_path, [bash(f"cd MOCK-sub; {call}", timeout=1000), bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], records(out)


@pytest.mark.parametrize("call", ["printf -vMOCK '%s' x", "printf -- '%s\\n' x", "printf -v MOCK -- '%s' x",
                                  "printf '%s' \"$MOCK\"", "printf -q '%9s'"])
def test_control_printf_with_options_and_no_width_is_quick(area, tmp_path, call):
    """Labelled controls: a literal format with no width under each reading (`printf -q '%9s'`: bash
    and dash reject -q, zsh prints it as the format)."""
    assert not audit._may_outlast(call, 1000)
    out = audit_lines(area, tmp_path, [bash(f"cd MOCK-sub; {call}", timeout=1000), bash(f"cat {OTHER}")])
    assert not out["violations"] and out["passed"], records(out)


# --- 3: ids --------------------------------------------------------------------------------------

@pytest.mark.parametrize("ids, calls", [
    (("[1e400]", "[2e400]"), 2),  # Sol's: both keys were written [Infinity]
    (('{"n": 1e-400}', '{"n": 2e-400}'), 2),  # both {"n": 0.0}
    (("[[1e400], 1]", "[[2e400], 1]"), 2),
    (("1e999999999999999999999", "1e999999999999999999999"), 1),  # Decimal raised InvalidOperation
    (("1e999999999999999999999", "2e999999999999999999999"), 2),
    (("10e999999999999999999999", "1e1000000000000000000000"), 1),
])
def test_ids_inside_lists_and_with_huge_exponents_compare_exactly(area, tmp_path, ids, calls):
    begun, done = ids
    out = audit_lines(area, tmp_path, [raw("item.started", begun), raw("item.completed", done)])
    assert out["tool_calls"] == calls and not out["suspect"], out


@pytest.mark.parametrize("ids, calls", [
    (("[1.0]", "[1]"), 1),  # equal numbers inside a list: their JSON texts differed
    (('{"a": 1, "b": [2]}', '{"b": [2.0], "a": 1e0}'), 1),
    pytest.param(("1e400", "2e400"), 2, id="control-scalars-apart"),
    pytest.param(("0", "-0"), 1, id="control-zeros-alike"),
])
def test_equal_ids_in_lists_and_objects_cover_each_other(area, tmp_path, ids, calls):
    """Equal numbers written differently, in a list or an object, are one item (one call); the
    labelled controls are scalars 19d1303 already compared as numbers."""
    begun, done = ids
    out = audit_lines(area, tmp_path, [raw("item.started", begun), raw("item.completed", done)])
    assert out["tool_calls"] == calls and not out["suspect"], out


# --- 4: a line holding a list --------------------------------------------------------------------

@pytest.mark.parametrize("line", ["[]", pytest.param("[1]", id="control-scalar-part"), '[{"type": "turn.started"}]'])
def test_a_list_line_is_suspect(area, tmp_path, line):
    """Sol 4: `[]` passed as no event, and a list of events passed as those events (the control's
    part, not an event, was suspect on 19d1303 too)."""
    out = audit_lines(area, tmp_path, [{"type": "turn.started"}, line])
    assert any(r["why"] == "a transcript line that is not an event" for r in out["suspect"]), out


@pytest.mark.parametrize("between", ["[]", '[{"type": "turn.started"}]'])
def test_a_list_line_loses_the_next_start(area, tmp_path, between):
    """Sol 4: after `cd MOCK-sub`, a list line kept the next start in MOCK-sub only."""
    out = audit_lines(area, tmp_path, [bash("cd MOCK-sub"), between, bash(f"cat {OTHER}")])
    assert any(OTHER in r["call"] for r in out["violations"]), records(out)


def test_control_a_call_inside_a_list_line_is_still_audited(area, tmp_path):
    """A labelled control: a list's parts are read, so the read inside one is a violation (on 19d1303
    too)."""
    out = audit_lines(area, tmp_path, [[bash(f"cat {OTHER}")]])
    assert any(OTHER in r["call"] for r in out["violations"]), records(out)
