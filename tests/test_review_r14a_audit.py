"""Round-14a findings on the audit (GPT-6.1 Sol, ~/reviews/dc-i86-llm-forecast/round14/
FINDINGS-r14a.out.md): a call of quick builtins that still outlasts its timeout, ids JSON reads as
one float, lines and events of no known type, the next Bash start after a line the audit cannot
read, keys that the scrub makes alike, and the host text the URL scan finds. All transcripts and
files are MOCK, in a temporary MOCK work area (runners.WORK monkeypatched)."""

import pytest

from i86 import audit
from test_review_r13_inputs import area, audit_lines, claude  # noqa: F401 (area is a fixture)
from test_review_r13b_audit import OTHER, bash, records
from test_review_r13_shell import model_in
from test_audit_output_differential import matches


def raw(event, ident, command="echo MOCK"):
    """A Codex event as JSON text, so that its id is written as the test spells it."""
    return ('{"type": "%s", "item": {"id": %s, "type": "command_execution", "command": "%s"}}'
            % (event, ident, command))


# --- F2: where the next Bash call starts (F8, an alias: test_review_r13b_audit.py) ---------------

@pytest.mark.parametrize("first", [
    bash("cd MOCK-sub; printf '%100000000s' MOCK > /dev/null", timeout=50),  # Sol's: past 50 ms on both shells
    bash("cd MOCK-sub; printf '%100000000s' MOCK > /dev/null"),  # a width prints as much as it says
    bash('cd MOCK-sub; printf "$MOCK" > /dev/null'),  # a format the call does not write out
    bash("cd MOCK-sub", timeout=10),  # a timeout too short for any call to be sure of
    bash("cd MOCK-sub", timeout="120000"),  # a timeout that is not a number
    bash("cd MOCK-sub", timeout=True),
    bash("cd MOCK-sub; echo {1..100000000} > /dev/null"),  # brace expansion
    bash("cd MOCK-sub; typeset -Z 100000000 MOCK=1"),  # zsh pads the value to that width
    bash("cd MOCK-sub; [[ MOCK == *M* ]]"),  # a pattern match
    bash("cd MOCK-sub; x=MOCK; x=$x$x; x=$x$x; x=$x$x; x=$x$x; x=$x$x; true"),  # each doubles it
])
def test_a_quick_builtin_that_may_still_outlast_its_timeout_keeps_the_start(area, tmp_path, first):
    """Sol F2: `_may_outlast` took these as quick, so the model started the next call in MOCK-sub
    only; from where the call started, the read is another run's."""
    out = audit_lines(area, tmp_path, [first, bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], records(out)


@pytest.mark.parametrize("first", [
    bash("cd MOCK-sub", timeout=1000),
    bash("cd MOCK-sub", timeout=600000.0),
    bash("cd MOCK-sub; printf '%s\\n' MOCK > /dev/null"),
    bash("cd MOCK-sub; export MOCK=1; typeset -r MOCK2=1"),
    bash('cd MOCK-sub; x=$(pwd); echo "$x" > /dev/null'),
])
def test_a_quick_call_under_an_ample_timeout_moves_the_start(area, tmp_path, first):
    out = audit_lines(area, tmp_path, [first, bash(f"cat {OTHER}")])
    assert not out["violations"] and out["passed"], records(out)


# --- F4: ids -----------------------------------------------------------------------------------

@pytest.mark.parametrize("ids, calls", [(("1e400", "2e400"), 2), (("1e-400", "2e-400"), 2), (("-1e400", "1e400"), 2),
                                        (("1e400", "1e400"), 1), (("1.0e2", "100"), 1), (("0.1", "1e-1"), 1)])
def test_ids_python_reads_as_one_float_stay_apart(area, tmp_path, ids, calls):
    """Sol F4: JSON's 1e400 and 2e400 both read as infinity, and 1e-400 and 2e-400 as 0, so one
    item's completion covered the other's start."""
    begun, done = ids
    out = audit_lines(area, tmp_path, [raw("item.started", begun), raw("item.completed", done)])
    assert out["tool_calls"] == calls, out


# --- F5, F6: lines -----------------------------------------------------------------------------

@pytest.mark.parametrize("line", [{}, {"type": "item.MOCK"}, {"type": "item.MOCK", "item": None},
                                  {"type": ["assistant"]}, {"type": None, "message": {}}, {"MOCK": 1}])
def test_an_event_of_no_type_the_audit_knows_is_suspect(area, tmp_path, line):
    """Sol F5: each passed, as one event with no call."""
    out = audit_lines(area, tmp_path, [line])
    assert out["suspect"] and out["events"] == 0 and not out["passed"], out


@pytest.mark.parametrize("line", [{"type": "turn.started"}, {"type": "system", "subtype": "init"},
                                  {"type": "rate_limit_event"}, {"type": "thread.started", "thread_id": "MOCK"}])
def test_an_event_of_a_known_type_with_no_call_is_not_suspect(area, tmp_path, line):
    out = audit_lines(area, tmp_path, [line])
    assert not out["suspect"] and out["events"] == 1 and out["passed"], out


@pytest.mark.parametrize("between", ['{"type": "assistant",', "7", '"MOCK"', '{"type": "item.MOCK"}'])
def test_a_line_the_audit_cannot_read_loses_the_next_start(area, tmp_path, between):
    """Sol F6: after `cd MOCK-sub` the next call starts there, but a line between that the audit
    cannot read may hold a call that moved it (here the work directory, where the read is another
    run's)."""
    out = audit_lines(area, tmp_path, [bash("cd MOCK-sub"), bash(f"cat {OTHER}")])
    assert not out["violations"], records(out)  # the control
    out = audit_lines(area, tmp_path, [bash("cd MOCK-sub"), between, bash(f"cat {OTHER}")])
    assert any(OTHER in r["call"] for r in out["violations"]), records(out)


# --- F7: the scrub ---------------------------------------------------------------------------

@pytest.mark.parametrize("extra", [{"\u0000": "dc-i86-llm-forecast", "�": "MOCK"},
                                   {"�": "MOCK", "\u0000": "dc-i86-llm-forecast"},
                                   {"\ud800": "MOCK", "\u0000": "MOCK", "�": "dc-i86-llm-forecast"}],
                         ids=["sol", "control-protected-last", "control-three-keys"])
def test_keys_the_scrub_makes_alike_keep_their_values(area, extra):
    """Sol F7: both keys became U+FFFD and one value was lost, the one that names this repository.
    The two controls (round-14c finding 5) pass on 7280074 too: its scrub kept the value inserted
    last, which there is the protected one."""
    inp = {"file_path": str(area / "MOCK.txt"), **extra}
    assert audit.model_call("Read", inp, area, audit.protected_roots(), {}, {})[0] == "violation"


# --- F10: hosts ------------------------------------------------------------------------------

@pytest.mark.parametrize("query, web", [
    ("http://EXAMPLE.org/MOCK", True),  # the parser lowercases it, as `exact.remote_url` does
    ("http://example.org./MOCK", True),
    ("http://127.1/MOCK", False),  # 127.0.0.1 to the parser
    ("http://%65xample.org/MOCK", False),  # example.org to the parser; not a plain name here
    ("http://example.org:bad/MOCK", True),  # the parser rejects the URL, which reaches no machine
])
def test_a_host_is_web_only_where_it_is_a_plain_name(area, tmp_path, query, web):
    """Sol F10: the scan finds host text as the parser finds it, before the parser decodes it; only
    a plain dotted name, which decoding leaves alike or rejects, counts as web."""
    out = audit_lines(area, tmp_path, [claude("WebSearch", {"query": query})])
    assert (out["web_calls"] == 1 and not out["suspect"]) if web else (out["web_calls"] == 0 and out["suspect"]), out


# --- CI at 7280074: a group's one statement, traced ---------------------------------------------

@pytest.mark.parametrize("name", ["bash", "zsh", "sh", "dash"])
@pytest.mark.parametrize("program", [
    "x=MOCK-init\nset -x 2>/dev/null\n{ echo\n} 2>&1",  # the output differential's counterexample
    "set -x; { echo MOCK; } 2>&1",
    "set -x; ( echo MOCK; ) 2>&1",
    "set -x; echo MOCK | { cat; } 2>&1",
    "set -e; { false; } 2>/dev/null; echo MOCK-after",
    "set -e; ( false; ) 2>/dev/null; echo MOCK-after",
    "{ echo MOCK; } 2>&1",
])
def test_a_group_s_one_statement_is_traced_and_ends_as_visit_has_it(name, program):
    """7280074 ran a group's one statement directly, so `set -x` no longer wrote it to the group's
    standard error (bash printed `+ echo` where the model said the output was a newline), and
    `set -e` was not checked after it."""
    real, model = model_in(name, program)
    assert model is None or matches(real, model), (real, audit._choices(model))
