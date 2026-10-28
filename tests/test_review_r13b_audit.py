"""Round-13b findings on the audit (GPT-6.1 Sol and Opus 5.5 lanes) that
tests/test_review_r13b_findings.py does not reproduce: Codex ids and lifecycles, where the next Bash
call starts after a call that may outlast its timeout or redefines `pwd`, a background call the
audit cannot follow, URLs in a Codex search's action, and an audit.json cut short. All transcripts
and files are MOCK, in a temporary MOCK work area (runners.WORK monkeypatched)."""

import json
import sys

import pytest

from i86 import audit, runners
from test_review_r13_inputs import TESTS, area, audit_lines, claude, held  # noqa: F401 (area is a fixture)

OTHER = "../opus-2/draft.json"  # another run's MOCK answer, from the work directory
FROM_SUB = "../../opus-2/draft.json"  # the same, from MOCK-sub


def bash(command, **flags):
    return claude("Bash", {"command": command, **flags})


def codex(event, **item):
    return {"type": event, "item": item}


def records(out):
    return {key: [r["call"] for r in out[key]] for key in ("violations", "suspect", "local_calls")}


# --- Codex items -----------------------------------------------------------------------------

def test_an_id_too_large_for_a_float_does_not_crash(area, tmp_path):
    """Sol 1: `_id_key` converted ids to float (OverflowError past 1.8e308)."""
    item = {"id": 10 ** 400, "type": "command_execution", "command": f"cat {OTHER}"}
    out = audit_lines(area, tmp_path, [codex("item.started", **item), codex("item.completed", **item)])
    assert out["tool_calls"] == 1 and out["violations"], out


@pytest.mark.parametrize("ids, calls", [((2 ** 53, 2 ** 53 + 1), 2), ((1, 2), 2), ((1, 1.0), 1), ((2 ** 53, float(2 ** 53)), 1)])
def test_ids_are_alike_only_when_their_numbers_are_equal(area, tmp_path, ids, calls):
    """Sol 7: through float, 2^53 + 1 was 2^53, so a completion covered another item's start."""
    begun, done = ids
    out = audit_lines(area, tmp_path, [codex("item.started", id=begun, type="command_execution", command="echo MOCK"),
                                       codex("item.completed", id=done, type="command_execution", command="echo MOCK")])
    assert out["tool_calls"] == calls, out


@pytest.mark.parametrize("kind", ["file_change", "collab_tool_call", "MOCK_kind"])
def test_an_item_whose_status_changes_is_counted_once(area, tmp_path, kind):
    """Sol 8, Opus m11: the whole item, status included, was the call, so a start `in_progress`
    and a completion `completed` were two calls."""
    item = {"id": "f", "type": kind, "changes": [{"path": str(area / "MOCK.txt"), "kind": "update"}]}
    out = audit_lines(area, tmp_path, [codex("item.started", **item, status="in_progress"),
                                       codex("item.completed", **item, status="completed")])
    assert out["tool_calls"] == 1, out


def test_an_update_stands_for_its_start(area, tmp_path):
    """An item started, updated and completed is one call; one updated and never completed is
    audited as updated."""
    item = {"id": "c", "type": "command_execution", "command": f"cat {OTHER}"}
    out = audit_lines(area, tmp_path, [codex("item.started", **item), codex("item.updated", **item),
                                       codex("item.completed", **item)])
    assert out["tool_calls"] == 1 and len(out["violations"]) == 1, out
    out = audit_lines(area, tmp_path, [codex("item.started", id="c", type="command_execution", command=""),
                                       codex("item.updated", **item)])
    assert out["tool_calls"] == 1 and out["violations"], out


def test_an_event_of_a_type_the_audit_does_not_know_with_an_item_is_suspect(area, tmp_path):
    out = audit_lines(area, tmp_path, [{"type": "item.MOCK", "item": {"id": "x", "type": "command_execution",
                                                                     "command": "echo MOCK"}}])
    assert out["suspect"] and not out["local_calls"], out


def test_a_line_that_is_neither_an_object_nor_a_list_is_suspect(area, tmp_path):
    out = audit_lines(area, tmp_path, [claude("Read", {"file_path": str(area / "MOCK-own.txt")}), '"MOCK"', "7"])
    assert len(out["suspect"]) == 2 and out["events"] == 1, out


def test_a_codex_search_s_action_is_read_for_urls(area, tmp_path):
    """Opus m1: a web_search item's `action.queries` was never passed on."""
    item = {"id": "w", "type": "web_search", "query": "MOCK",
            "action": {"type": "search", "queries": ["MOCK", "http://127.0.0.1/MOCK"]}}
    out = audit_lines(area, tmp_path, [codex("item.completed", **item)])
    assert out["web_calls"] == 0 and out["suspect"], out
    item["action"]["queries"] = ["MOCK", "https://example.org/MOCK"]
    out = audit_lines(area, tmp_path, [codex("item.completed", **item)])
    assert out["web_calls"] == 1 and not out["suspect"], out


def test_a_search_s_start_is_covered_by_its_completion(area, tmp_path):
    """Codex starts a search with an empty query and an action that names only its kind, as the
    committed Sol transcripts do; the completion covers it. An action of another shape is read."""
    begun = {"id": "w", "type": "web_search", "query": "", "action": {"type": "other"}}
    done = {"id": "w", "type": "web_search", "query": "MOCK",
            "action": {"type": "search", "queries": ["MOCK", "https://example.org/MOCK"]}}
    out = audit_lines(area, tmp_path, [codex("item.started", **begun), codex("item.completed", **done)])
    assert out["tool_calls"] == out["web_calls"] == 1 and not out["suspect"], out
    for action in ("http://127.0.0.1/MOCK", {"type": "http://127.0.0.1/MOCK"}, ["http://127.0.0.1/MOCK"]):
        out = audit_lines(area, tmp_path, [codex("item.completed", id="w", type="web_search", query="MOCK",
                                                 action=action)])
        assert out["web_calls"] == 0 and out["suspect"], (action, out)


@pytest.mark.parametrize("query, web", [
    ("MOCK http://example.org/a and http://example.org", True),  # two hosts, both remote
    ("http status codes (MOCK)", True),  # no `http:`
    ("see http: MOCK", True),  # the parser fails on the space: no host
    ("visit http://127.0.0.1 now", False),  # to the first space: 127.0.0.1
    ("HTTPS:\\\\localhost/MOCK", False),
    ("MOCKhttp://127.0.0.1/", False),  # after any character
    ("http://example.org:8080@[::1]/", False),
])
def test_urls_in_a_query_are_read_as_whatwg_reads_them(area, tmp_path, query, web):
    out = audit_lines(area, tmp_path, [claude("WebSearch", {"query": query})])
    assert (out["web_calls"] == 1 and not out["suspect"]) if web else (out["web_calls"] == 0 and out["suspect"]), out


# --- where the next Bash call starts ---------------------------------------------------------

@pytest.mark.parametrize("first", [
    bash("cd MOCK-sub; sleep 1; true", timeout=10),  # Sol 6: finite, past its 10 ms timeout
    bash("cd MOCK-sub; ls > /dev/null; true"),  # any program may run past the timeout
    bash("cd MOCK-sub; read -r x; true"),  # read waits for its input
    bash("cd MOCK-sub; x=$(sleep 300); true"),
    bash("cd MOCK-sub; f() { :; }; f"),
    bash("cd MOCK-sub; echo MOCK >> MOCK-out.txt"),  # a FIFO there would wait for a reader
])
def test_a_call_that_may_outlast_its_timeout_keeps_the_start(area, tmp_path, first):
    """Claude Code moves a call to the background at its timeout, and the next starts where this
    one started (tests/test_review_r13_carry.py): from there the read is another run's."""
    out = audit_lines(area, tmp_path, [first, bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], records(out)


@pytest.mark.parametrize("first", ["cd MOCK-sub", "cd MOCK-sub; true", "cd MOCK-sub && echo MOCK > /dev/null 2>&1",
                                   "[ -d MOCK-sub ] && cd MOCK-sub", "x=$(pwd); cd MOCK-sub"])
def test_a_call_of_builtins_that_return_at_once_moves_the_next(area, tmp_path, first):
    """Such a call ends with status 0 before any timeout: the next starts in MOCK-sub, where the
    read stays inside the work directory."""
    out = audit_lines(area, tmp_path, [bash(first), bash(f"cat {OTHER}")])
    assert not out["violations"] and out["passed"], records(out)


@pytest.mark.parametrize("first", ["cd MOCK-sub; false", "cd MOCK-sub; exit 0", "cd MOCK-sub && false"])
def test_a_quick_call_that_exits_or_fails_keeps_the_start(area, tmp_path, first):
    """Opus m10: test_review_r12_audit's cases all `cd ..`, which adds the work directory anyway.
    Here the call stays inside it, so only the exit or failing status keeps the start."""
    out = audit_lines(area, tmp_path, [bash(first), bash(f"cat {OTHER}")])
    assert out["violations"] and not out["passed"], records(out)


def test_the_exit_trap_runs_after_claude_code_reads_where_the_shell_is(area, tmp_path):
    """Opus m10: the shell is in MOCK-sub when `pwd -P` runs, and the trap's `cd ..` comes after;
    so MOCK-sub is a place the next call may start, and from there the read is another run's."""
    out = audit_lines(area, tmp_path, [bash("cd MOCK-sub; trap 'cd ..' EXIT"), bash(f"cat {FROM_SUB}")])
    assert out["violations"] and not out["passed"], records(out)


@pytest.mark.parametrize("command, known", [
    ("pwd() { builtin cd MOCK-sub; builtin pwd -P; }", False),
    ("function pwd { echo /; }", False),
    ("alias pwd='echo /'", True),  # round 14a, F8: the wrapper's `pwd -P` was read before the alias
    ("(pwd() { echo /; })", True),  # a subshell's function ends with it
    ("cd MOCK-sub; pwd", True),
])
def test_a_pwd_function_leaves_the_next_start_unknown(area, command, known):
    """Opus m5: Claude Code's `pwd -P` runs the call's own `pwd` function, which prints what it
    likes; the model kept the work directory as a known start. An alias does not reach it."""
    place: dict = {}
    audit.model_call("Bash", {"command": command}, area, audit.protected_roots(), {}, place)
    assert place["known"] is known, place


@pytest.mark.parametrize("flag", [None, "yes", [], {}])
def test_a_flag_the_audit_cannot_read_gives_both(area, tmp_path, flag):
    """Opus m4: JSON's null was read as false; any flag but true or false may have done either."""
    for second in (OTHER, FROM_SUB):
        out = audit_lines(area, tmp_path, [bash("cd MOCK-sub", run_in_background=flag), bash(f"cat {second}")])
        assert out["violations"] and not out["passed"], (second, records(out))


def test_a_background_call_the_audit_cannot_follow_leaves_the_place(area, tmp_path, monkeypatch):
    """Opus m5: the exception path reset the next start to an unknown one even for a call in the
    background, which leaves it where it was (MOCK-sub, from the call before)."""
    check_call = audit.check_call

    def failing(tool, inp, *args, **kwargs):
        if isinstance(inp, dict) and inp.get("command") == "MOCK-fail":
            raise RuntimeError("MOCK")
        return check_call(tool, inp, *args, **kwargs)

    monkeypatch.setattr(audit, "check_call", failing)
    out = audit_lines(area, tmp_path, [bash("cd MOCK-sub"), bash("MOCK-fail", run_in_background=True),
                                       bash(f"cat {FROM_SUB}")])
    assert out["violations"] and not out["passed"], records(out)


# --- pooling ---------------------------------------------------------------------------------

@pytest.mark.parametrize("text", ['{"events": 3, "passed": true, "violations": [], "susp', "", "[" * 100000])
def test_an_audit_json_that_is_not_json_keeps_its_run_out_of_the_pool(tmp_path, monkeypatch, text):
    """Opus m12: `accepted_runs` raised on an audit.json cut short, which stopped `i86 simulate`."""
    sys.path.insert(0, str(TESTS))
    from mock import MOCK_response

    from i86 import cli
    from i86 import graph as graph_mod

    monkeypatch.setattr(runners, "RUNS", tmp_path / "runs")
    g = graph_mod.load()
    d = runners.RUNS / "MOCK-run"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"prompt_sha256": "MOCKSHA", "backend": "subfleet"}))
    (d / "response.json").write_text(json.dumps(MOCK_response(g)))
    (d / "audit.json").write_text(text)
    assert "MOCK-run" not in cli.accepted_runs(g, "MOCKSHA")
