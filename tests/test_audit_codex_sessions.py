"""scripts/audit_codex_sessions.py finds every Codex thread behind a run, ties each main thread to a
subfleet attempt, keeps its log and audits it. MOCK session logs, transcripts and subfleet records in
temporary directories; the tests never run subfleet or any other command. The pooling gate
(`cli._session_audit`) reads every audit a test writes and must reach the script's verdict."""

import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

from i86 import cli

spec = importlib.util.spec_from_file_location(
    "audit_codex_sessions", Path(__file__).parent.parent / "scripts" / "audit_codex_sessions.py")
acs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acs)

PARENT, HELPER = "MOCK-parent-thread", "MOCK-helper-thread"
EARLIER, EARLIER_HELPER = "MOCK-earlier-thread", "MOCK-earlier-helper-thread"
JOB = "MOCK-job-sol-1"
CITE = "cite{}"  # the web tool's cite marker: "citeturn0view0" between private-use characters


def write_log(lanes: Path, name: str, meta: dict, items=(), records=()) -> Path:
    path = lanes / "codex-9" / "sessions" / "2026" / "11" / "03" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "session_meta", "payload": meta}, *records]
    lines += [{"type": "event_msg", "payload": {"type": "item_completed", "item": it}} for it in items]
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def started(thread: str) -> dict:
    return {"type": "SubAgentActivity", "kind": "started", "agent_thread_id": thread}


def search(query: str, action: dict | None = None) -> dict:
    """A web search as a session log records it."""
    return {"type": "Extension", "kind": "web.search", "id": f"MOCK-{query}", "query": query,
            "action": action or {"type": "search", "queries": [query]}, "results": []}


def web(query: str, action: dict | None = None) -> dict:
    """The same web search as `codex exec --json` writes it in a transcript."""
    return {"id": f"MOCK-{query}", "type": "web_search", "query": query,
            "action": action or {"type": "search", "queries": [query]}, "results": []}


def command(cmd: str, cwd: str, item_id: str | None = None) -> dict:
    return {"type": "CommandExecution", "id": item_id or f"MOCK-{cmd}", "command": ["/bin/zsh", "-lc", cmd],
            "cwd": f"file://{cwd}", "status": "completed", "exit_code": 0, "aggregated_output": ""}


def exec_call(code: str, call_id: str | None = None) -> dict:
    payload = {"type": "custom_tool_call", "name": "exec", "input": code}
    return {"type": "response_item", "payload": {**payload, "call_id": call_id} if call_id else payload}


def tool_output(text: str, kind: str = "custom_tool_call_output", call_id: str | None = None) -> dict:
    """A script's result (or, as a function_call_output, a running cell's that `wait` returns)."""
    payload = {"type": kind, "output": [{"type": "input_text", "text": text}]}
    return {"type": "response_item", "payload": {**payload, "call_id": call_id} if call_id else payload}


def refusal(call_id: str) -> dict:
    """A script's output as Codex reports one that V8 refused to compile."""
    return {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": call_id, "output": [
        {"type": "input_text", "text": "Script failed\nWall time 0.0 seconds\nOutput:\n"},
        {"type": "input_text", "text": "Script error:\nSyntaxError: MOCK unexpected token"}]}}


def served(url: str, ref: str = "turn0view0") -> str:
    """A page as the web tool's reply cites it."""
    return f"MOCK page ({url})\n{CITE.format(ref)} [wordlim: 200] MOCK text"


def function_call(name: str, namespace: str | None = "collaboration") -> dict:
    """A function call as a session log records it: a sub-agent tool in its namespace, or (with no
    namespace) code mode's `wait`."""
    payload = {"type": "function_call", "name": name, "arguments": "{}"}
    if namespace is not None:
        payload["namespace"] = namespace
    return {"type": "response_item", "payload": payload}


def root_meta(workdir: str, thread: str = PARENT, timestamp: str = "2026-11-03T18:10:00Z") -> dict:
    return {"id": thread, "cwd": workdir, "source": "exec", "timestamp": timestamp}


def helper_meta(workdir: str, thread: str = HELPER, parent: str = PARENT,
                timestamp: str = "2026-11-03T18:10:30Z") -> dict:
    return {"id": thread, "cwd": workdir, "timestamp": timestamp,
            "source": {"subagent": {"thread_spawn": {"parent_thread_id": parent, "depth": 1,
                                                     "agent_path": "/root/MOCK_research"}}}}


def write_transcript(run: Path, thread: str, items=()) -> None:
    """A MOCK `codex exec --json` transcript of one thread and its items."""
    lines = [{"type": "thread.started", "thread_id": thread}, {"type": "turn.started"}]
    for it in items:
        lines += [{"type": "item.started", "item": it}, {"type": "item.completed", "item": it}]
    lines.append({"type": "turn.completed"})
    (run / "transcript.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))


def make_area(tmp_path: Path, monkeypatch) -> tuple[Path, Path, str]:
    """A MOCK collected Codex run with no attempts on record, its transcript, and a log from an
    unrelated job in the lanes. No test may start a process, and the gate must read each audit the
    script writes as passing exactly when the script says it passed."""
    def no_process(*args, **kwargs):
        raise AssertionError(f"the tests run no command: {args}")

    script_audit = acs.audit_run

    def audit_run(run_dir: Path, lanes: Path) -> dict:
        report = script_audit(run_dir, lanes)
        verdict = cli._session_audit(run_dir)
        assert isinstance(verdict, dict) and verdict["passed"] is report["passed"], verdict
        return report

    monkeypatch.setattr(acs.subprocess, "run", no_process)
    monkeypatch.setattr(acs, "audit_run", audit_run)
    workdir = str(tmp_path / "work" / "sol-1")
    Path(workdir).mkdir(parents=True)
    run = tmp_path / "runs" / "sol-1"
    run.mkdir(parents=True)
    (run / "meta.json").write_text(json.dumps({"label": "sol-1", "workdir": workdir, "lane_id": "codex-9"}))
    (run / "response.md").write_text("MOCK answer\n")
    write_transcript(run, PARENT, [web("MOCK main query")])
    monkeypatch.setattr(acs, "RUNS", tmp_path / "runs")
    lanes = tmp_path / "lanes"
    write_log(lanes, "rollout-MOCK-other.jsonl", root_meta(str(tmp_path / "elsewhere"), "MOCK-other",
                                                           "2026-11-03T18:00:00Z"),
              items=[command("cat /etc/hosts", str(tmp_path / "elsewhere"))])
    return lanes, run, workdir


@pytest.fixture
def area(tmp_path, monkeypatch):
    return make_area(tmp_path, monkeypatch)


def add_parent(lanes: Path, workdir: str, spawned=(HELPER,), records=(), items=None) -> Path:
    """The collected main thread's log: its items, one `spawn_agent` call and a started event for each
    sub-agent in `spawned`, and any other `records`."""
    items = [search("MOCK main query")] if items is None else items
    return write_log(lanes, "rollout-MOCK-parent.jsonl", root_meta(workdir),
                     records=[*records, *[function_call("spawn_agent") for _ in spawned]],
                     items=[*items, *[started(t) for t in spawned]])


def with_record(monkeypatch, run: Path, attempts, accepted: str = f"{JOB}/a2", collected: str = f"{JOB}/a2"):
    """Give the MOCK run a subfleet job whose attempts are (attempt id, session, state), each of which
    started unless a fourth item says when (None: it never did)."""
    meta = json.loads((run / "meta.json").read_text())
    meta.update(job_id=JOB, attempt_id=collected)
    (run / "meta.json").write_text(json.dumps(meta))
    record = {"job": {"accepted_attempt_id": accepted},
              "attempts": [{"attempt_id": a[0], "native_session_id": a[1], "state": a[2], "lane_id": "codex-9",
                            "started_at": a[3] if len(a) > 3 else "2026-11-03T18:00:00Z"} for a in attempts]}
    monkeypatch.setattr(acs, "subfleet_record", lambda job: record if job == JOB else None)
    return record


def add_earlier_attempt(lanes: Path, workdir: str, helper_items=()) -> None:
    """A failed first attempt in the same work directory: its main thread and one sub-agent."""
    write_log(lanes, "rollout-MOCK-earlier.jsonl", root_meta(workdir, EARLIER, "2026-11-03T18:00:00Z"),
              records=[function_call("spawn_agent")], items=[search("MOCK earlier query"), started(EARLIER_HELPER)])
    write_log(lanes, "rollout-MOCK-earlier-helper.jsonl",
              helper_meta(workdir, EARLIER_HELPER, EARLIER, "2026-11-03T18:00:30Z"),
              items=[search("MOCK earlier helper query"), *helper_items])


TWO_ATTEMPTS = [(f"{JOB}/a1", EARLIER, "failed"), (f"{JOB}/a2", PARENT, "succeeded")]


def test_the_main_thread_and_its_sub_agents_are_kept_and_audited(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
              items=[search("MOCK helper query"), command("echo MOCK", workdir)])
    report = acs.audit_run(run, lanes)
    assert {t["thread_id"] for t in report["threads"]} == {PARENT, HELPER}
    assert report["missing"] == [] and report["flags"] == [] and report["passed"]
    assert report["web_calls"] == 2 and report["commands"] == 1
    assert report["main_thread"] == PARENT and report["transcript_check"]["items"] == 1
    assert (run / "codex-sessions" / "rollout-MOCK-helper.jsonl").is_file()
    assert not (run / "codex-sessions" / "rollout-MOCK-other.jsonl").exists()
    assert json.loads((run / "codex-sessions" / "audit.json").read_text())["passed"]


def test_a_spawned_thread_with_no_log_fails(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(HELPER, "MOCK-lost-thread"))
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["missing"] == ["MOCK-lost-thread"] and not report["passed"]


def test_a_sub_agent_reading_the_repository_fails_the_audit(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
              items=[command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    report = acs.audit_run(run, lanes)
    helper = next(t for t in report["threads"] if t["thread_id"] == HELPER)
    assert helper["audit"]["violations"] and not report["passed"]


def test_tools_records_and_places_the_script_does_not_read_are_flagged(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    records = [exec_call("text(await tools.read_file({path: 'MOCK'}))"),
               function_call("MOCK_shell"),
               {"type": "response_item", "payload": {"type": "custom_tool_call", "name": "MOCK_tool", "input": ""}},
               {"type": "MOCK_record", "payload": {}},
               {"type": "event_msg", "payload": {"type": "MOCK_event"}},
               {"type": "response_item", "payload": {"type": "MOCK_response_item"}}]
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), records=records,
              items=[command("echo MOCK", "/MOCK/elsewhere"), {"type": "MOCKItem", "id": "MOCK"},
                     {"type": "Extension", "kind": "MOCK.kind", "id": "MOCK-extension"}])
    report = acs.audit_run(run, lanes)
    flags = " ".join(report["flags"])
    for expected in ("tools.read_file", "'MOCK_shell'", "'MOCK_tool'", "'MOCK_record'", "'MOCK_event'",
                     "'MOCK_response_item'", "outside the work directory", "'MOCKItem'", "'Extension'"):
        assert expected in flags
    assert not report["passed"]


@pytest.mark.parametrize("spelled, flag", [
    ("file://{}/.", None), ("file://{}/", None), ("file://{}//", None), ("file://{}/./", None), ("{}", None),
    ("file://{}/MOCK/..", "a path this script cannot place"), ("file://{}/../sol-1", "a path this script cannot place"),
    ("MOCK/work/sol-1", "a path this script cannot place"),
    ("file://localhost{}", None), ("file://LOCALHOST{}/", None),
    ("file://MOCK-remote{}", "a path this script cannot place"), ("file://MOCK-remote:22{}", "a path this script cannot place"),
    ("file://{}/MOCK", "outside the work directory"), ("file://{}0", "outside the work directory")])
def test_a_command_runs_in_the_work_directory_only_where_a_plain_path_names_it(area, spelled, flag):
    """Review 6: a command in the work directory spelled with a `.` part, `//` or a `/` at the end ran
    there. One in a path with a `..` part, or a relative one, ran wherever a link before it leads, so
    it is flagged as a place this script cannot place; one in another folder ran outside the work
    directory. Review 7: a file URL that names `localhost` names this host, and one that names another
    host names no folder here, so this script cannot place it either."""
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
              items=[{**command("echo MOCK", workdir), "cwd": spelled.format(workdir)}])
    report = acs.audit_run(run, lanes)
    places = [f for f in report["flags"] if "a command ran in" in f]
    if flag is None:
        assert places == [] and report["flags"] == [] and report["passed"]
    else:
        assert len(places) == 1 and places[0].startswith("rollout-MOCK-helper.jsonl line 2: a command ran in ") and flag in places[0]
        assert not report["passed"]


def test_code_modes_wait_and_the_sub_agent_tools_are_read(area):
    lanes, run, workdir = area
    names = ["send_message", "followup_task", "wait_agent", "interrupt_agent", "list_agents"]
    add_parent(lanes, workdir, records=[*[function_call(name) for name in names], function_call("wait", None)])
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["passed"]
    parent = next(t for t in report["threads"] if t["thread_id"] == PARENT)
    assert parent["functions"] == {name: 1 for name in [*names, "wait", "spawn_agent"]}


@pytest.mark.parametrize("name, namespace", [("send_message", "MOCK_connector"), ("wait", "collaboration"),
                                             ("spawn_agent", None)])
def test_a_function_is_read_only_in_its_own_namespace(area, name, namespace):
    """Review finding 8: a connector's function of the same name is not a sub-agent tool."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[function_call(name, namespace)])
    report = acs.audit_run(run, lanes)
    assert f"function {name!r} in namespace {namespace!r}, which this script does not read" in " ".join(report["flags"])
    assert not report["passed"]


def test_a_rerun_after_the_lane_prunes_its_logs_audits_the_kept_copies(area):
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir)
    helper = write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    assert acs.audit_run(run, lanes)["passed"]
    first = (run / "codex-sessions" / "audit.json").read_bytes()
    parent.unlink()
    helper.unlink()
    assert acs.audit_run(run, lanes)["passed"]
    assert (run / "codex-sessions" / "audit.json").read_bytes() == first


def test_a_kept_log_is_final(area):
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    assert acs.audit_run(run, lanes)["passed"]
    with parent.open("a") as fh:
        fh.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count"}}) + "\n")
    with pytest.raises(SystemExit, match="the kept copy is final"):
        acs.audit_run(run, lanes)


@pytest.mark.parametrize("kind, why", [
    ("a folder", "is not a regular file"), ("a pipe", "is not a regular file"),
    ("a link to nothing", "is not a regular file"),
    pytest.param("no permission to read it", "this script cannot read",
                 marks=pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file"))])
def test_a_kept_copy_that_is_no_regular_file_this_script_can_read_stops_the_audit(area, kind, why):
    """Review 6: discovery flags such a kept copy, and keeping the lane's log beside it then stops the
    audit with the reason, as a kept copy that differs does, instead of an error from reading it."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    kept = run / "codex-sessions" / parent.name
    kept.parent.mkdir()
    {"a folder": kept.mkdir, "a pipe": lambda: os.mkfifo(kept),
     "a link to nothing": lambda: kept.symlink_to(kept.with_name("MOCK-gone")),
     "no permission to read it": lambda: (shutil.copyfile(parent, kept), kept.chmod(0))}[kind]()
    with pytest.raises(SystemExit, match=f"{why}.*the kept copy is final"):
        acs.audit_run(run, lanes)


@pytest.mark.parametrize("kind, why", [
    ("a folder", "is not a regular file, so this script will not write the audit over it"),
    ("a pipe", "is not a regular file, so this script will not write the audit over it"),
    ("a link to nothing", "is not a regular file, so this script will not write the audit over it"),
    ("a link to a file", "is not a regular file, so this script will not write the audit over it"),
    pytest.param("no permission to write it", r"this script cannot write .*audit\.json \(PermissionError\)",
                 marks=pytest.mark.skipif(os.geteuid() == 0, reason="root writes any file"))])
def test_an_audit_file_this_script_cannot_write_stops_the_audit(area, kind, why):
    """Review 7: a folder, a pipe (whose open for writing would wait for a reader forever) or a link
    (which would take the audit wherever it leads, over a run's answer, say) in the place of
    `audit.json` stops the audit before it starts, and a file the system will not let this script
    write stops it with the reason, instead of an error from writing it."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    out = run / "codex-sessions" / "audit.json"
    out.parent.mkdir()
    elsewhere = run / "MOCK-elsewhere.md"
    elsewhere.write_text("MOCK untouched\n")
    {"a folder": out.mkdir, "a pipe": lambda: os.mkfifo(out),
     "a link to nothing": lambda: out.symlink_to(out.with_name("MOCK-gone")),
     "a link to a file": lambda: out.symlink_to(elsewhere),
     "no permission to write it": lambda: (out.write_text("{}\n"), out.chmod(0o444))}[kind]()
    with pytest.raises(SystemExit, match=why):
        acs.audit_run(run, lanes)
    assert not out.with_name("MOCK-gone").exists()
    assert elsewhere.read_text() == "MOCK untouched\n"


@pytest.mark.parametrize("kind", ["a file", "a link to a folder"])
def test_a_run_whose_kept_folder_is_not_a_folder_stops_the_audit(area, kind):
    """A file, or a link (which would take this script's writes wherever it leads), in the place of
    `codex-sessions` stops the audit before it writes anything."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    elsewhere = run.parent / "MOCK-elsewhere"
    elsewhere.mkdir()
    {"a file": lambda: (run / "codex-sessions").write_text("MOCK\n"),
     "a link to a folder": lambda: (run / "codex-sessions").symlink_to(elsewhere)}[kind]()
    with pytest.raises(SystemExit, match="codex-sessions is not a folder"):
        acs.audit_run(run, lanes)
    assert not any(elsewhere.iterdir())


@pytest.mark.parametrize("line, flag", [
    ("{MOCK", "does not parse"),
    ("[1]", "is not a record"),
    # A key given twice reads as its last value here, and could read otherwise elsewhere.
    ('{"type": "response_item", "payload": {"type": "custom_tool_call", "name": "MOCK_tool", "name": "exec", '
     '"input": "text(1)"}}', "does not parse"),
    ("[" * 100_000 + "]" * 100_000, "does not parse"),
    # Python parses it, but it nests more than `DEPTH` levels: a line nearly as deep as Python's parser
    # reads could parse and then stop the audit when it wrote the line's item out.
    ('{"type": "event_msg", "payload": {"type": "token_count", "MOCK": ' + "[" * 63 + "]" * 63 + "}}",
     "does not parse"),
    (b'{"type": "event_msg", "payload": {"type": "token_count", "MOCK": "\xff"}}', "does not parse"),
], ids=["cut", "a list", "a key twice", "nested too deeply", "nested 65 levels", "not UTF-8"])
def test_a_log_line_that_is_not_a_record_is_flagged(area, line, flag):
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    with parent.open("ab") as fh:
        fh.write((line if isinstance(line, bytes) else line.encode()) + b"\n")
    report = acs.audit_run(run, lanes)
    assert f"rollout-MOCK-parent.jsonl line 3 {flag}" in report["flags"] and not report["passed"]


def completed(item: dict) -> dict:
    return {"type": "event_msg", "payload": {"type": "item_completed", "item": item}}


@pytest.mark.parametrize("record, error", [
    ({"type": ["event_msg"], "payload": {}}, "TypeError"),
    ({"type": "event_msg", "payload": {"type": {"MOCK": 1}}}, "TypeError"),
    ({"type": "response_item", "payload": {"type": "function_call", "name": ["spawn_agent"],
                                           "namespace": "collaboration"}}, "TypeError"),
    ({"type": "response_item", "payload": {"type": "function_call", "name": "wait", "namespace": ["collaboration"]}},
     "TypeError"),
    (completed({"type": {"MOCK": 1}, "id": "MOCK"}), "TypeError"),
    (completed({**command("echo MOCK", "/MOCK/work"), "command": ["/bin/zsh", "-lc", 1]}), "TypeError"),
    (completed({"type": "AgentMessage", "id": "MOCK", "content": 1}), "TypeError"),
    (exec_call("text('\ud800')"), "UnicodeEncodeError"),
    ({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": ["text(1)"]}},
     "TypeError"),
    ({"type": "response_item", "payload": {"type": "custom_tool_call", "name": "exec", "input": None}}, "TypeError"),
    (completed({**started(HELPER), "agent_thread_id": {"MOCK": 1}}), "TypeError"),
    (completed({**command("echo MOCK", "/MOCK/work"), "cwd": ["/MOCK/work"]}), "TypeError"),
    (completed({**command("echo MOCK", "/MOCK/work"), "cwd": None}), "TypeError"),
    ({"type": "response_item", "payload": {"type": "custom_tool_call_output", "output": {"text": "MOCK"}}},
     "TypeError"),
    ({"type": "response_item", "payload": {"type": "custom_tool_call_output",
                                           "output": [served("https://MOCK.example")]}}, "TypeError"),
    ({"type": "response_item", "payload": {"type": "function_call_output", "output": [
        {"type": "input_text", "text": [served("https://MOCK.example")]}]}}, "TypeError"),
], ids=["record type a list", "event type an object", "function name a list", "namespace a list",
        "item type an object", "command word a number", "message content a number", "script a lone surrogate",
        "script a list", "script null", "sub-agent id an object", "command cwd a list", "command cwd null",
        "tool output an object", "tool output part a string", "tool output text a list"])
def test_a_record_with_a_field_of_another_type_is_flagged(area, record, error):
    """A field of another JSON type than Codex writes (a list where it writes a string, say) fails the
    run with a flag on its line that names the error; it does not stop the audit."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    with parent.open("a") as fh:
        fh.write(json.dumps(record) + "\n")
    report = acs.audit_run(run, lanes)
    flag = f"rollout-MOCK-parent.jsonl line 3: a record with a field this script cannot read ({error})"
    assert flag in report["flags"]
    assert not report["passed"]


def nested(levels: int) -> list:
    """An array nested `levels` deep."""
    value: list = []
    for _ in range(levels - 1):
        value = [value]
    return value


@pytest.mark.parametrize("levels, passes", [(64, True), (65, False)])
def test_a_log_line_nests_at_most_depth_levels(area, levels, passes):
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    with parent.open("a") as fh:
        fh.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count", "MOCK": nested(levels - 2)}})
                 + "\n")
    report = acs.audit_run(run, lanes)
    assert report["passed"] is passes
    assert ("rollout-MOCK-parent.jsonl line 3 does not parse" in report["flags"]) is not passes


@given(value=st.recursive(st.none() | st.integers(), lambda inner: st.lists(inner, max_size=3)
                          | st.dictionaries(st.text(max_size=2), inner, max_size=3), max_leaves=12),
       levels=st.integers(min_value=0, max_value=8))
def test_the_depth_check_agrees_with_counting_levels(value, levels):
    """Differential: the check without recursion against levels counted recursively."""
    def depth(node) -> int:
        children = node.values() if isinstance(node, dict) else node if isinstance(node, list) else None
        return 0 if children is None else 1 + max(map(depth, children), default=0)
    assert acs._nests_deeper_than(value, levels) is (depth(value) > levels)
    assert cli._nests_deeper_than(value, levels) is (depth(value) > levels)


def test_the_gate_reads_a_record_by_the_scripts_own_tables():
    """Differential: what the pooling gate lets a passing record hold is what the script passes a run
    with: the tools a script may call, the functions a thread may call, the items it passes over, and
    how deep a line may nest."""
    assert cli.SCRIPT_TOOLS == acs.SCRIPT_TOOLS
    assert cli.FUNCTIONS == {name for _, name in acs.FUNCTIONS}
    assert cli.QUIET_ITEMS == acs.SKIPPED_ITEMS
    assert cli.DEPTH == acs.DEPTH


def test_a_plain_web_script_passes(area):
    lanes, run, workdir = area
    code = ('text(await tools.web__run({search_query: [{q: "MOCK query"}], '
            'open: [{ref_id: "https://www.example.org/MOCK"}, {ref_id: "turn0search1"}]}))')
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["suspect"] == 0 and report["passed"]
    assert report["threads"][0]["script_tools"] == {"web__run": 1}


@pytest.mark.parametrize("code", [
    # The pattern of sol-3's keys: strings built around values, with a piece that is part of no name
    # the script denies.
    'const cells = ["a", "b"]; const m = {}; for (let i = 0; i < cells.length; i++) { const s = "x"; '
    'm["yes_" + cells[i] + "|" + s] = i; m[`no_${cells[i]}`] = i - 1; } text(JSON.stringify(m))',
    'const xs = [1, 2, 3]; text(xs[xs.length - 1], xs[0], ({a: 1})["a"])',
    'const {a, b: [c = 1, ...rest]} = {a: 1, b: [2]}; text(a + c + rest.length)',
    'async function f(q) { return await tools.web__run({search_query: [{q}]}); } '
    'try { text(await f("MOCK")); } catch (e) { text(String(e)); }',
    'class Store { get() { return 1; } } text(new Store().get(), ALL_TOOLS.map((t) => t.name).join(","))',
    'setTimeout(() => text("MOCK"), 0); for (const [k, v] of Object.entries({MOCK: 1})) text(k, v)',
    'const r = await tools.web__run({open: [{ref_id: `turn0view0`}, {"ref_id": "https://www.example.org/MOCK"}]}); '
    'text(r)',
])
def test_a_script_that_uses_only_the_language_and_the_web_tool_passes(area, code):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["suspect"] == 0 and report["passed"]


@pytest.mark.parametrize("code", [
    'text(await tools["web__run"]({search_query: [{q: "MOCK"}]}))',
    'text(await tools .mcp__codex_apps__github_fetch_file({path: "MOCK"}))',
    'text(await tools\n.web__run({}))',
    'text(await tools?.web__run({}))',
    'text(await tools/* MOCK */.web__run({}))',
    'const t = tools; text(await t.web__run({}))',
    'const {web__run} = tools; text(await web__run({}))',
    'text(Object.keys({...tools}))',
    'text(Object.values(tools).length)',
])
def test_a_script_that_reaches_tools_other_than_by_name_is_flagged(area, code):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert any("reaches tools other than by name" in flag for flag in report["flags"]) and not report["passed"]


@pytest.mark.parametrize("code", [
    "text(await \\u0074ools.mcp__codex_apps__github_fetch_file({path: 'MOCK'}))",
    'text("\\x74ools")',
    'text((0, eval)("MOCK"))',
    'text(new Function("return MOCK")())',
    'text([].map.constructor("return MOCK")())',
    'text(Object.keys(globalThis))',
    'text(await import("MOCK"))',
    'const m = require("MOCK")',
    'text(Deno.readTextFileSync("MOCK"))',
    'text(process.env.MOCK)',
    'text(Bun.file("MOCK"))',
    'text(fs.readFileSync("MOCK"))',
    # Review finding 1: a getter on every object's prototype hands back the global object.
    'Object.defineProperty(Object.prototype, "g", {get() { return this; }});\n'
    'await g["to" + "ols"]["mcp__codex_apps__github_fetch_file"]({});',
    'Object.__defineGetter__("g", () => 1)',
    'text(Object.__lookupGetter__("g"))',
    'Object.defineProperty({}, "g", {value: 1})',
    'Object.defineProperties({}, {})',
    'text(Object.getPrototypeOf([]))',
    'text(Object.getOwnPropertyDescriptor(Object, "MOCK"))',
    'text(Object.setPrototypeOf({}, null))',
    'text(Array.prototype)',
    'text({}.__proto__)',
    'text(Reflect.ownKeys({}))',
    'text(new Proxy({}, {}))',
    'const o = {get g() { return 1; }}',
    'class A { static set g(v) {} }',
])
def test_a_script_that_can_spell_or_build_code_is_flagged(area, code):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert any("can spell or build code" in flag for flag in report["flags"]) and not report["passed"]


@pytest.mark.parametrize("code, problem", [
    # Review finding 1: a split "constructor" reaches the Function constructor, which builds code.
    ('[]["con" + "structor"]["con" + "structor"]("return to" + "ols")()["mcp__codex_apps__github_fetch_file"]({})',
     "indexes with 'constructor'"),
    ('const o = {}; text(await o["to" + "ols"].web__run({}))', "indexes with 'tools'"),
    ('const o = {}; text(o[`${"__pro"}to__`])', "indexes with '__proto__'"),
    ('const w = `to${"ols"}`; text(w)', "builds the string 'tools'"),
    ('const o = {get ["g"]() { return 1; }}; text(o.g)', "defines an accessor"),
    ("text(this)", "uses this"),
    ("text(MOCK_global)", "names 'MOCK_global', which it does not declare"),
    ("with ({}) { text(1) }", "uses with"),
    ('const o = {}; const k = "a"; text(o[k.repeat(1)])', "a key this script cannot read"),
    ("Error.prepareStackTrace = (e, f) => f; text(1)", "names prepareStackTrace"),
])
def test_a_script_that_reaches_past_its_tools_is_flagged_from_its_syntax(area, code, problem):
    """None of these holds a word the text checks look for; the syntax tree shows what each does."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    flags = " ".join(report["flags"])
    assert problem in flags and "can spell or build code" not in flags and not report["passed"]


@pytest.mark.parametrize("code, problem", [
    ("const t = tools; text(t)", "reaches tools other than as tools.web__run or tools.exec_command"),
    ("text(tools[0])", "reaches tools other than as tools.web__run or tools.exec_command"),
    ("text(await tools.mcp__codex_apps__github_fetch_file({}))", "reaches tools other than as tools.web__run"),
    ("text(await tools?.web__run({}))", "reaches tools other than as tools.web__run"),
    ("text([].map.constructor)", "names constructor"),
    ('text(({})["__proto__"])', "indexes with '__proto__'"),
    ("text(eval)", "names 'eval', which it does not declare"),
    ("text(globalThis)", "names 'globalThis', which it does not declare"),
    ("const o = {set s(v) {}}", "defines an accessor"),
])
def test_the_syntax_check_reads_each_rule_on_its_own(code, problem):
    """The text checks flag these too; the syntax check must not lean on them."""
    src = code.encode()
    assert any(problem in found for found in acs.cell_problems(acs._JS.parse(src), src))


@pytest.mark.parametrize("code", ["text(" + " + ".join(['"MOCK"'] * 3000) + ' + "http://127.0.0.1:8080/MOCK")',
                                  "text(" + "(" * 3000 + '"http://127.0.0.1:8080/MOCK"' + ")" * 3000 + ")"],
                         ids=["a long sum", "deep parentheses"])
def test_a_script_too_deep_to_read_is_flagged(area, code):
    """The syntax checks (a long sum) and the string folding (deep parentheses) stop at Python's
    stack; the text checks still read the script, and find the local address."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    assert any("nests too deeply for this script to read" in flag for flag in report["flags"])
    parent = next(t for t in report["threads"] if t["thread_id"] == PARENT)
    assert [call["tool"] for call in parent["script_suspect"]] == ["exec script"] and not report["passed"]


@pytest.mark.parametrize("replies, passes", [
    (["refused"], True), ([], False), (["result"], False), (["refused", "refused"], False),
    (["refused elsewhere"], False), (["type error"], False), (["three parts"], False)])
def test_a_script_the_grammar_cannot_parse_passes_only_as_one_v8_refused(area, replies, passes):
    lanes, run, workdir = area
    type_error, three_parts = refusal("MOCK-call"), refusal("MOCK-call")
    type_error["payload"]["output"][1]["text"] = "Script error:\nTypeError: MOCK"
    three_parts["payload"]["output"].append({"type": "input_text", "text": "MOCK more"})
    outputs = {"refused": refusal("MOCK-call"), "result": tool_output("MOCK result", call_id="MOCK-call"),
               "refused elsewhere": refusal("MOCK-other-call"), "type error": type_error, "three parts": three_parts}
    records = [exec_call("text(await tools.web__run({)", "MOCK-call"), *[outputs[r] for r in replies]]
    add_parent(lanes, workdir, spawned=(), records=records)
    report = acs.audit_run(run, lanes)
    flagged = any("does not parse as JavaScript" in flag for flag in report["flags"])
    assert flagged is not passes and report["passed"] is passes


@pytest.mark.parametrize("args, why", [
    ('{open: [{ref_id: "http://127.0.0.1:8080/MOCK"}]}', "127.0.0.1"),
    ('{open: [{ref_id: "https://lim s.example.gov/MOCK"}]}', "`lim`"),
    ('{open: [{ref_id: "https://github.com/MaxGhenis/dc-i86-llm-forecast/blob/main/README.md"}]}', "repository"),
    ('{open: [{ref_id: "file:///etc/hosts"}]}', "neither a web address"),
    ('{open: [{ref_id: "~/.ssh/MOCK"}]}', "neither a web address"),
    ('{search_query: [{q: "ftp://MOCK.example.org/MOCK"}]}', "other than http(s)"),
    # Review finding 6: each string's text with its escapes decoded, and each `+` of constants.
    (r'{open: [{ref_id: "https://github.com/MaxGhenis/dc-i86-llm-fore\cast"}]}', "repository"),
    (r'{search_query: [{q: `https://github.com/MaxGhenis/dc-i86-llm-fore\cast/${Math.PI}`}]}', "repository"),
    ('{search_query: [{q: "dc-i86-" + "llm-forecast"}]}', "repository"),
    ('{search_query: [{q: "http://" + "127.0.0.1:8080/MOCK"}]}', "127.0.0.1"),
    (r'{search_query: [{q: "file\:///etc/hosts"}]}', "other than http(s)"),
    # Review 3: a number that a template or a `+` puts in a string, as JavaScript writes it there.
    ('{search_query: [{q: "http" + `://${127n}.${0n}.${0n}.${1n}`}]}', "127.0.0.1"),
    ('{search_query: [{q: "http" + `://${0x7f}.${0b0}.${0e5}.${.1e1}`}]}', "127.0.0.1"),
    ("""JSON.parse('{"open": [{"ref_id": ' + '"http' + `://127.0.0.${0o1}"}]}`)""", "127.0.0.1"),
    pytest.param('{search_query: [{q: "http://127.0.0.1:8080/" + ' + "1" * 4301 + "}]}", "127.0.0.1",
                 id="a decimal past 4,300 digits"),
    pytest.param('{search_query: [{q: "http://127.0.0.1:8080/" + 0x' + f"{10**4301:x}n}}]}}", "127.0.0.1",
                 id="a hex BigInt past 4,300 digits"),
    # Review 6: `true`, `false` and `null` as JavaScript writes them in a string, and a template's text.
    ('{search_query: [{q: "http://" + `${true}` + ".localhost"}]}', "`true.localhost`"),
    ('{search_query: [{q: "http://" + false + ".localhost"}]}', "`false.localhost`"),
    ('{search_query: [{q: "http://" + null + ".localhost"}]}', "`null.localhost`"),
    ('{search_query: [{q: "http://" + `a` + 1 + ".localhost"}]}', "`a1.localhost`"),
])
def test_a_scripts_urls_are_read_as_a_web_calls_input(area, args, why):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(f"text(await tools.web__run({args}))")])
    report = acs.audit_run(run, lanes)
    [suspect] = report["threads"][0]["script_suspect"]
    assert suspect["tool"] == "exec script" and why in suspect["why"]
    assert report["suspect"] == 1 and report["flags"] == [] and report["passed"]


@pytest.mark.parametrize("code, why", [
    ('text(await tools.web__run({open: [{"ref_id": "/etc/hosts"}]}))', "neither a web address"),
    ("text(await tools.web__run({open: [{'ref_id': '/etc/hosts'}]}))", "neither a web address"),
    ('const ref_id = "/MOCK"; text(await tools.web__run({open: [{ref_id}]}))', "holds in a variable"),
    ('const r = "/MOCK"; text(await tools.web__run({open: [{ref_id: r}]}))', "not one string written out"),
    ('text(await tools.web__run({open: [{"ref_id": "file" + ":///etc/hosts"}]}))', "neither a web address"),
    ('text(await tools.web__run({open: [{ref_id: "https://www.example.org/" + "MOCK"}]}))', "not one string"),
    ('text(await tools.web__run({open: [{ref_id: `https://www.example.org/${"MOCK"}`}]}))', "not one string"),
    ('const r = "/MOCK"; text(await tools.web__run({open: [{["ref_id"]: r}]}))', "not one string written out"),
    ('const o = {}; o.ref_id = "/MOCK"; text(await tools.web__run({open: [o]}))', "a ref_id member"),
    ('const o = {}; o["ref_id"] = "/MOCK"; text(await tools.web__run({open: [o]}))', "a ref_id member"),
    # Review finding 6: a page given by a constant the regular expression does not read.
    ('text(await tools.web__run({open: [{ref_id:/**/"/etc/hosts"}]}))', "neither a web address"),
    ('text(await tools.web__run({open: [{["ref_id"]:"/etc/hosts"}]}))', "neither a web address"),
    ('text(await tools.web__run({open: [{[/**/"ref_id"]: "/etc/hosts"}]}))', "neither a web address"),
    ('text(await tools.web__run({open: [{[("ref_" + "id")]: "/etc/hosts"}]}))', "neither a web address"),
    (r'text(await tools.web__run({open: [JSON.parse("{\"ref_id\": \"/etc/hosts\"}")]}))', "neither a web address"),
    ('const k = "ref_id"; text(await tools.web__run({open: [{[k]: "/MOCK"}]}))', "writes the string ref_id"),
    ('const k = `${"ref_id"}`; text(await tools.web__run({open: [{[k]: "/MOCK"}]}))', "writes the string ref_id"),
    ('const e = ""; text(await tools.web__run({open: [{[e + "ref_id"]: "/MOCK"}]}))', "writes the string ref_id"),
    ('text(await tools.web__run({open: [Object.fromEntries([["ref_id", "/MOCK"]])]}))', "writes the string ref_id"),
    ('class P { ref_id = "/MOCK" } text(await tools.web__run({open: [new P()]}))', "names ref_id in a field_definition"),
])
def test_a_page_a_script_opens_must_be_one_string_written_out(area, code, why):
    """Review findings 4 and 6: a `ref_id` under a quoted or computed key, held in a variable, built
    from pieces, given with a comment before it, parsed from JSON, or built as an object's key."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(code)])
    report = acs.audit_run(run, lanes)
    [suspect] = report["threads"][0]["script_suspect"]
    assert suspect["tool"] == "exec script" and why in suspect["why"]
    assert report["suspect"] == 1 and report["passed"]


@pytest.mark.parametrize("pages", [
    '{ref_id: "turn0search3"}, {ref_id: "https://www.example.org/MOCK"}',
    '{"ref_id": "turn1view0"}, {\'ref_id\': `https://www.example.org/MOCK`}',
    '{["ref_id"]: "turn0search3"}, {[("ref_" + "id")]: "https://www.example.org/MOCK"}',
    '{[/* MOCK */ ("ref_id")]: "turn0search3", lineno: 1}',
])
def test_a_page_a_script_opens_by_one_string_written_out_is_a_web_call(area, pages):
    """No false flag: a page a script opens by a `ref_id` key written out, quoted or computed from
    constants, with a web address or a page the web tool returned."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call(f"text(await tools.web__run({{open: [{pages}]}}))")])
    report = acs.audit_run(run, lanes)
    assert report["threads"][0]["script_suspect"] == [] and report["flags"] == [] and report["passed"]


def test_each_page_the_web_tool_served_is_audited(area):
    lanes, run, workdir = area
    records = [tool_output(served("https://www.example.org/MOCK") + served("http://192.168.0.1/MOCK", "turn0view1")),
               tool_output(served("https://www.example.org/MOCK", "turn1view0")
                           + served("https://github.com/MaxGhenis/dc-i86-llm-forecast", "turn1view1")
                           + served("http://192.168.0.1/MOCK", "turn1view2"),  # served again: one suspect
                           kind="function_call_output")]
    add_parent(lanes, workdir, spawned=(), records=records)
    report = acs.audit_run(run, lanes)
    thread = report["threads"][0]
    assert thread["served_pages"] == 3 and report["served_pages"] == 3
    assert [(s["tool"], s["call"]) for s in thread["script_suspect"]] == [
        ("web page", "http://192.168.0.1/MOCK"), ("web page", "https://github.com/MaxGhenis/dc-i86-llm-forecast")]
    assert report["suspect"] == 2 and report["passed"]


def test_a_page_cited_after_an_escaped_newline_is_audited(area):
    """Review finding 2: a script that prints the web tool's reply as JSON leaves `\\n` between a page's
    address and its cite marker; an empty "()" names no page, and a link inside a page has a marker of
    its own."""
    lanes, run, workdir = area
    text = (json.dumps(served("http://127.0.0.1:8080/MOCK"), ensure_ascii=False)
            + f" MOCK () {CITE.format('turn1view0')} MOCK link cite9†MOCK anchor")
    add_parent(lanes, workdir, spawned=(), records=[tool_output(text)])
    report = acs.audit_run(run, lanes)
    [suspect] = report["threads"][0]["script_suspect"]
    assert (suspect["tool"], suspect["call"]) == ("web page", "http://127.0.0.1:8080/MOCK")
    assert report["served_pages"] == 1 and report["flags"] == [] and report["passed"]


@pytest.mark.parametrize("text", [
    f"MOCK page {CITE.format('turn0view0')}",
    "MOCK entityMOCK",
    f"MOCK (https://www.example.org/MOCK) {CITE.format('MOCK')}",
])
def test_a_cite_marker_this_script_cannot_read_is_flagged(area, text):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[tool_output(text)])
    report = acs.audit_run(run, lanes)
    assert "a tool's reply holds 1 cite marker(s) this script does not read" in " ".join(report["flags"])
    assert not report["passed"]


def test_a_shell_command_a_script_ran_with_no_item_is_flagged(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[exec_call('text(await tools.exec_command({cmd: "echo MOCK"}))')])
    report = acs.audit_run(run, lanes)
    assert "1 tools.exec_command calls in exec scripts, 0 completed commands" in " ".join(report["flags"])
    assert not report["passed"]


def test_every_script_that_calls_the_shell_is_suspect(area):
    """Review finding 3: one script runs two commands, so the counts match although the second script's
    command has no item; each script is suspect, and the shell rules read the command it names."""
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    records = [exec_call('for (const c of ["true", "true"]) await tools.exec_command({cmd: c});'),
               exec_call('await tools.exec_command({cmd: "cat ~/.ssh/MOCK_key"});')]
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), records=records,
              items=[command("true", workdir), command("true", workdir, "MOCK-true-2")])
    report = acs.audit_run(run, lanes)
    helper = next(t for t in report["threads"] if t["thread_id"] == HELPER)
    whys = [s["why"] for s in helper["script_suspect"]]
    assert len(whys) == 2 and "only a command's completed item says what ran" in whys[0]
    assert "calls tools.exec_command with 'cat ~/.ssh/MOCK_key' (suspect: " in whys[1]
    assert report["flags"] == [] and report["suspect"] == 2 and report["passed"]


def test_a_command_a_script_names_is_read_by_the_shell_rules():
    code = f'await tools.exec_command({{cmd: "cat " + "{acs.ROOT / "README.md"}"}})'
    tree = acs._JS.parse(code.encode())
    verdict, why = acs.check_script(code, "/MOCK/work", tree)
    assert verdict == "suspect" and "(violation: " in why


def test_web_actions_compare_as_the_transcript_writes_them(area):
    lanes, run, workdir = area
    pairs = [({"type": "openPage", "url": "https://www.example.org/MOCK"},
              {"type": "open_page", "url": "https://www.example.org/MOCK"}),
             ({"type": "findInPage", "url": None, "pattern": "MOCK"}, {"type": "find_in_page", "pattern": "MOCK"}),
             ({"type": "search", "query": None, "queries": ["MOCK a", "MOCK b"]},
              {"type": "search", "queries": ["MOCK a", "MOCK b"]})]
    add_parent(lanes, workdir, spawned=(), items=[search(f"MOCK {i}", log) for i, (log, _) in enumerate(pairs)])
    write_transcript(run, PARENT, [web(f"MOCK {i}", theirs) for i, (_, theirs) in enumerate(pairs)])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"] == {"items": 3, "only_in_transcript": [], "only_in_log": [], "different": []}
    assert report["passed"]


def test_a_command_compares_by_its_words(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[command("echo 'MOCK words'", workdir)])
    write_transcript(run, PARENT, [{"id": "MOCK-echo 'MOCK words'", "type": "command_execution",
                                    "command": "/bin/zsh -lc \"echo 'MOCK words'\"", "aggregated_output": "",
                                    "exit_code": 0, "status": "completed"}])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == [] and report["passed"]


@pytest.mark.parametrize("theirs, key", [
    ([web("MOCK main query", {"type": "search", "queries": ["MOCK other query"]})], "different"),
    ([web("MOCK main query"), web("MOCK transcript only")], "only_in_transcript"),
    ([], "only_in_log"),
])
def test_the_log_and_the_transcript_must_record_the_same_calls(area, theirs, key):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_transcript(run, PARENT, theirs)
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"][key]
    assert any("record different calls" in flag for flag in report["flags"]) and not report["passed"]


@pytest.mark.parametrize("line", ['{"type": "item.completed", "item": ', "[" * 100_000 + "]" * 100_000, "[1]",
                                  '"MOCK"', "\u00a0"],
                         ids=["cut", "nested too deeply", "an array", "a string", "other whitespace"])
def test_a_transcript_line_this_script_cannot_read_fails(area, line):
    """A transcript line that does not parse or is not an object could hold a call, so the check counts
    it, by its number, as a line only the transcript holds; the audit still reaches a verdict."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    number = len((run / "transcript.jsonl").read_text().split("\n"))
    with (run / "transcript.jsonl").open("a") as fh:
        fh.write(line + "\n")
    report = acs.audit_run(run, lanes)
    check = report["transcript_check"]
    assert check["items"] == 1 and check["only_in_transcript"] == [f"line {number}"] and check["different"] == []
    assert not report["passed"]


def test_a_blank_transcript_line_is_no_line(area):
    """A line of JSON's whitespace alone is no line, as `audit` reads a transcript."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    with (run / "transcript.jsonl").open("a") as fh:
        fh.write(" \t\r\n\n")
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["only_in_transcript"] == [] and report["passed"]


@pytest.mark.parametrize("thread, recorded", [("7", 7), ("None", None), ("True", True)])
def test_a_transcript_thread_id_that_is_not_a_string_names_no_thread(area, thread, recorded):
    """A transcript whose `thread.started` event gives a number, null or a boolean names no thread,
    though Python writes it as the main thread's id."""
    lanes, run, workdir = area
    write_log(lanes, "rollout-MOCK-parent.jsonl", root_meta(workdir, thread), items=[search("MOCK main query")])
    write_transcript(run, PARENT, [web("MOCK main query")])
    lines = (run / "transcript.jsonl").read_text().split("\n")
    lines[0] = json.dumps({"type": "thread.started", "thread_id": recorded})
    (run / "transcript.jsonl").write_text("\n".join(lines))
    assert acs.transcript_thread(run / "transcript.jsonl") is None
    report = acs.audit_run(run, lanes)
    assert report["main_thread"] is None and not report["passed"]
    assert (f"the transcript records no thread whose id this script can read, not the collected main thread "
            f"{thread}") in report["flags"]


EXTRA = {"id": "MOCK-MOCK main query", "type": "command_execution", "command": "cat /MOCK/elsewhere",
         "aggregated_output": "", "exit_code": 0, "status": "completed"}


@pytest.mark.parametrize("theirs", [
    [EXTRA, web("MOCK main query")],
    [web("MOCK main query"), EXTRA],
    [{**EXTRA, "type": ["web_search"]}, web("MOCK main query")],
], ids=["a command first", "a command last", "an item of a type this script cannot read"])
def test_a_transcript_item_that_repeats_an_id_fails(area, theirs):
    """An item that repeats another's id still counts, so the transcript's extra call fails the check."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_transcript(run, PARENT, theirs)
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["items"] == 2
    assert report["transcript_check"]["different"] == ['"MOCK-MOCK main query"'] and not report["passed"]


def test_a_log_item_that_repeats_an_id_fails(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[command("echo MOCK", workdir, item_id="MOCK-MOCK main query"),
                                                  search("MOCK main query")])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == ['"MOCK-MOCK main query"'] and not report["passed"]


@pytest.mark.parametrize("kind", [["web_search"], {"MOCK": 1}], ids=["a list", "an object"])
def test_a_transcript_item_of_a_type_this_script_cannot_read_fails(area, kind):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_transcript(run, PARENT, [web("MOCK main query"), {"id": "MOCK-odd", "type": kind, "query": "MOCK"}])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["only_in_transcript"] == ['"MOCK-odd"'] and not report["passed"]


CMD = {"id": "MOCK-cmd", "type": "command_execution", "command": "cat /MOCK/elsewhere", "aggregated_output": "",
       "status": "in_progress"}
TOOL_USE = {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "cat /MOCK/elsewhere"}}]}


@pytest.mark.parametrize("line", [
    {"type": "item.completed", "item": ["MOCK"]}, {"type": "item.completed", "item": "MOCK"},
    {"type": "item.completed", "item": None}, {"type": "item.completed"},
    {"type": "item.started", "item": CMD}, {"type": "item.updated", "item": CMD},
    {"type": "item.started", "item": ["MOCK"]}, {"type": "item.started", "item": None},
    {"type": "item.updated", "item": "MOCK-id"}, {"type": "item.started", "item": web("MOCK main query")},
    {"type": "MOCK.event"}, {"MOCK": "no type"}, {"type": ["turn.started"]}, {"type": {"MOCK": "turn.started"}},
    {"type": "assistant", "message": TOOL_USE},
    {"type": "turn.started", "message": TOOL_USE}, {"type": "error", "item": {**CMD, "status": "failed"}},
    {"type": "thread.started", "thread_id": PARENT},
], ids=["an item a list", "an item a string", "an item null", "no item", "a command started, never completed",
        "a command updated, never completed", "a started item a list", "a started item null",
        "an updated item a string", "a search started again",
        "an event of another type", "an event of no type", "a type a list", "a type an object", "a call in a message",
        "a call in a turn's event",
        "an item in an error", "a second start"])
def test_a_transcript_line_that_is_neither_an_item_nor_a_turns_event_fails(area, line):
    """Review 6: each line of the transcript must be an item that completes as it started, the
    thread's one start, or a turn's event with no call in it. Any other line (an item that is not an
    object, one that starts and never completes, an event of another type or of none, a call in a
    message) could hold a call `audit` reads, so it counts, by its number, as a line only the
    transcript holds, and the run fails. A start or an update whose item is not an object pairs with
    no completion."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    number = len((run / "transcript.jsonl").read_text().split("\n"))
    with (run / "transcript.jsonl").open("a") as fh:
        fh.write(json.dumps(line) + "\n")
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"] == {"items": 1, "only_in_transcript": [f"line {number}"], "only_in_log": [],
                                          "different": []}
    assert not report["passed"]


@pytest.mark.parametrize("kind", sorted(acs.audit.CODEX_NOT_CALLS))
def test_a_message_whose_line_holds_a_call_counts_as_an_item(area, kind):
    """Review 7: `audit` reads a tool use in a line's `message` as well as in its item, so a message,
    reasoning, a to-do list or an error whose line holds one carries a call. The check compares it
    with the main thread's log, which holds no such item, and the run fails."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    with (run / "transcript.jsonl").open("a") as fh:
        fh.write(json.dumps({"type": "item.completed", "item": {"id": "MOCK-quiet", "type": kind},
                             "message": {"content": [{"type": "tool_use", "name": "mcp:MOCK/read", "input": {}}]}})
                 + "\n")
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"] == {"items": 2, "only_in_transcript": ['"MOCK-quiet"'], "only_in_log": [],
                                          "different": []}
    assert not report["passed"]


@pytest.mark.parametrize("begun, done, passes", [
    ("1.0", "1.0000000000000001", False), ("1e400", "2e400", False), ("1e-400", "2e-400", False),
    ("1.0", "1", True), ("1e400", "10e399", True)])
def test_a_start_pairs_only_with_a_completion_whose_number_id_equals_its_own(area, begun, done, passes):
    """Review 7: `audit` reads each number in a transcript with its text, and pairs a start with a
    completion whose id equals its own exactly. The check reads the transcript and the log alike: a
    start whose id differs from the completion's only where a double cannot tell them apart (in a
    seventeenth digit, or past the largest or smallest double) is left over and counts as a line only
    the transcript holds; one whose id equals the completion's, written otherwise, pairs with it."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=(), items=[{**search("MOCK main query"), "id": "MOCK-number"}])
    parent.write_text(parent.read_text().replace('"MOCK-number"', done))
    item = {**web("MOCK main query"), "id": "MOCK-number"}
    lines = [json.dumps({"type": "thread.started", "thread_id": PARENT}), json.dumps({"type": "turn.started"}),
             json.dumps({"type": "item.started", "item": item}).replace('"MOCK-number"', begun),
             json.dumps({"type": "item.completed", "item": item}).replace('"MOCK-number"', done),
             json.dumps({"type": "turn.completed"})]
    (run / "transcript.jsonl").write_text("\n".join(lines) + "\n")
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"] == {"items": 1, "only_in_transcript": [] if passes else ["line 3"],
                                          "only_in_log": [], "different": []}
    assert report["passed"] is passes


@pytest.mark.parametrize("logged, written, passes", [
    ("1.0000000000000001", "1.0", False), ("2e400", "1e400", False), ("2e-400", "1e-400", False),
    ("1", "1.0", True), ("1e400", "10e399", True)])
def test_a_transcript_item_is_the_logs_only_when_their_number_ids_are_equal(area, logged, written, passes):
    """Review 7: the check keys each item by its id as `audit` keys it, so a transcript item and a log
    item whose number ids differ only where a double cannot tell them apart are two items, each in one
    place only, and the run fails; ids that are equal but written otherwise (1 and 1.0) name one item."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=(), items=[{**search("MOCK main query"), "id": "MOCK-number"}])
    parent.write_text(parent.read_text().replace('"MOCK-number"', logged))
    write_transcript(run, PARENT, [{**web("MOCK main query"), "id": "MOCK-number"}])
    transcript = run / "transcript.jsonl"
    transcript.write_text(transcript.read_text().replace('"MOCK-number"', written))
    report = acs.audit_run(run, lanes)
    shown = {"only_in_transcript": [json.dumps(json.loads(written))], "only_in_log": [json.dumps(json.loads(logged))]}
    assert report["transcript_check"] == {"items": 1, "only_in_transcript": [] if passes else shown["only_in_transcript"],
                                          "only_in_log": [] if passes else shown["only_in_log"], "different": []}
    assert report["passed"] is passes


@pytest.mark.parametrize("lines, unread", [
    ([{"type": "item.started", "item": web("MOCK main query")}, {"type": "item.started", "item": web("MOCK main query")},
      {"type": "item.completed", "item": web("MOCK main query")}], 4),
    ([{"type": "item.started", "item": {**CMD, "id": "MOCK-MOCK main query"}},
      {"type": "item.completed", "item": web("MOCK main query")}], 3),
], ids=["started twice, completed once", "started as another call than it completed as"])
def test_a_start_that_no_completion_covers_fails(area, lines, unread):
    """`audit` pairs each completion with one start it covers, by id and calls, and audits a start
    left over as a call. The check pairs them alike, so a start left over counts, by its line's
    number, as a line only the transcript holds."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    lines = [{"type": "thread.started", "thread_id": PARENT}, {"type": "turn.started"}, *lines, {"type": "turn.completed"}]
    (run / "transcript.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"] == {"items": 1, "only_in_transcript": [f"line {unread}"], "only_in_log": [],
                                          "different": []}
    assert not report["passed"]


@pytest.mark.parametrize("levels, passes", [(64, True), (65, False)])
def test_a_transcript_line_nests_at_most_depth_levels(area, levels, passes):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    number = len((run / "transcript.jsonl").read_text().split("\n"))
    with (run / "transcript.jsonl").open("a") as fh:
        fh.write(json.dumps({"type": "turn.completed", "MOCK": nested(levels - 1)}) + "\n")
    report = acs.audit_run(run, lanes)
    assert report["passed"] is passes
    assert report["transcript_check"]["only_in_transcript"] == ([] if passes else [f"line {number}"])


def test_a_transcript_whose_items_start_update_and_complete_between_turns_events_passes(area):
    """A search starts with an empty query, is updated, and completes with its query; an error event
    between them reports a retry, a message completes, and a second turn fails. Each line is read,
    and the run passes."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    begun = {**web("MOCK main query"), "query": "", "action": {"type": "other"}}
    lines = [{"type": "thread.started", "thread_id": PARENT}, {"type": "turn.started"},
             {"type": "item.started", "item": begun}, {"type": "item.updated", "item": begun},
             {"type": "error", "message": "MOCK reconnecting"},
             {"type": "item.completed", "item": web("MOCK main query")},
             {"type": "item.completed", "item": {"id": "MOCK-message", "type": "agent_message", "text": "MOCK"}},
             {"type": "turn.completed"}, {"type": "turn.started"}, {"type": "turn.failed", "error": {"message": "MOCK"}}]
    (run / "transcript.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"] == {"items": 1, "only_in_transcript": [], "only_in_log": [], "different": []}
    assert report["passed"]


def test_every_attempts_threads_are_audited_and_the_collected_one_matches_the_transcript(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["missing"] == [] and report["passed"]
    assert report["main_thread"] == PARENT and report["web_calls"] == 3
    threads = {t["thread_id"]: (t["attempt"], t["collected"]) for t in report["threads"]}
    assert threads == {EARLIER: (f"{JOB}/a1", False), EARLIER_HELPER: (f"{JOB}/a1", False),
                       PARENT: (f"{JOB}/a2", True)}
    kept = json.loads((run / "codex-sessions" / "attempts.json").read_text())
    assert kept["accepted_attempt_id"] == f"{JOB}/a2"
    assert [a["native_session_id"] for a in kept["attempts"]] == [EARLIER, PARENT]


def test_a_violation_in_an_earlier_attempt_fails_the_run(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir, helper_items=[command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    assert report["violations"] == 1 and not report["passed"]


def test_a_suspect_call_in_an_earlier_attempt_is_counted(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    write_log(lanes, "rollout-MOCK-earlier.jsonl", root_meta(workdir, EARLIER, "2026-11-03T18:00:00Z"),
              records=[exec_call('text(await tools.web__run({open: [{ref_id: "http://localhost/MOCK"}]}))')],
              items=[search("MOCK earlier query")])
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    earlier = next(t for t in report["threads"] if t["thread_id"] == EARLIER)
    assert len(earlier["script_suspect"]) == 1 and report["suspect"] == 1 and report["passed"]


@pytest.mark.parametrize("case", ["stray main thread", "attempt without a log", "no record, two main threads",
                                  "another attempt accepted", "no session for the collected attempt"])
def test_main_threads_must_match_the_attempts(area, monkeypatch, case):
    lanes, run, workdir = area
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir, spawned=())
    expected = {
        "stray main thread": "is no attempt's session",
        "attempt without a log": None,
        "no record, two main threads": "2 threads started by codex exec",
        "another attempt accepted": f"subfleet accepted {JOB}/a1",
        "no session for the collected attempt": "records no session for the collected attempt",
    }[case]
    if case == "stray main thread":
        with_record(monkeypatch, run, [(f"{JOB}/a1", PARENT, "succeeded")], accepted=f"{JOB}/a1", collected=f"{JOB}/a1")
    elif case == "attempt without a log":
        with_record(monkeypatch, run, [*TWO_ATTEMPTS, (f"{JOB}/a3", "MOCK-lost-session", "failed")])
    elif case == "another attempt accepted":
        with_record(monkeypatch, run, TWO_ATTEMPTS, accepted=f"{JOB}/a1")
    elif case == "no session for the collected attempt":
        with_record(monkeypatch, run, [(f"{JOB}/a1", EARLIER, "failed"), (f"{JOB}/a2", None, "succeeded")])
    report = acs.audit_run(run, lanes)
    if expected is None:
        assert report["missing"] == ["MOCK-lost-session"]
    else:
        assert any(expected in flag for flag in report["flags"])
    assert not report["passed"]


@pytest.mark.parametrize("started_at, passes", [("2026-11-03T18:00:00Z", False), (None, True)])
def test_an_attempt_that_started_must_name_its_session(area, monkeypatch, started_at, passes):
    """Review finding 6, gap A: an earlier attempt that started with no session on record could have
    left threads no log is known for; one that never started has none."""
    lanes, run, workdir = area
    with_record(monkeypatch, run, [(f"{JOB}/a1", None, "failed", started_at), (f"{JOB}/a2", PARENT, "succeeded")])
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    assert (f"subfleet records no session for attempt {JOB}/a1, which started" in report["flags"]) is not passes
    assert report["passed"] is passes


@pytest.mark.parametrize("collected, passes", [(None, True), (f"{JOB}/a1", True), (f"{JOB}/a2", False)])
def test_without_attempts_on_record_a_run_must_have_collected_its_jobs_first(area, collected, passes):
    """Review finding 6, gap B: with no record, nothing says what an earlier attempt left."""
    lanes, run, workdir = area
    if collected:
        meta = json.loads((run / "meta.json").read_text())
        (run / "meta.json").write_text(json.dumps({**meta, "attempt_id": collected}))
    add_parent(lanes, workdir, spawned=())
    report = acs.audit_run(run, lanes)
    assert any("not its job's first attempt" in flag for flag in report["flags"]) is not passes
    assert report["passed"] is passes


def test_two_logs_of_one_thread_must_hold_the_same_bytes(area):
    """Review finding 6, gap D: a second log of a thread is the same log only if it matches the first."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    shutil.copyfile(parent, parent.with_name("rollout-MOCK-parent-copy.jsonl"))
    assert acs.audit_run(run, lanes)["passed"]
    write_log(lanes, "rollout-MOCK-parent-edited.jsonl", root_meta(workdir),
              items=[search("MOCK main query"), search("MOCK added query")])
    report = acs.audit_run(run, lanes)
    assert any(f"both hold thread {PARENT}, and they differ" in flag for flag in report["flags"])
    assert not report["passed"]


@pytest.mark.parametrize("case, flag", [
    ("cut", "names the work directory, but its first line does not parse"),
    ("other record", "names the work directory, but its first line is not a session's record"),
    ("no id", "a session in the work directory with no thread id"),
    ("sub-agent source as a string", "gives a source this script cannot read"),
    ("other source", "gives a source this script cannot read"),
    ("nested too deeply", "names the work directory, but its first line does not parse"),
])
def test_a_log_in_the_work_directory_this_script_cannot_read_is_flagged(area, case, flag):
    """Review findings 6 (gap E) and 9: such a log is flagged, not skipped, and does not stop the audit."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    first = {
        "cut": json.dumps({"type": "session_meta", "payload": root_meta(workdir, "MOCK-odd")})[:-10],
        "other record": json.dumps({"type": "MOCK_record", "payload": {"cwd": workdir}}),
        "no id": json.dumps({"type": "session_meta", "payload": {"cwd": workdir, "source": "exec"}}),
        "sub-agent source as a string": json.dumps(
            {"type": "session_meta", "payload": {**root_meta(workdir, "MOCK-odd"), "source": {"subagent": "MOCK"}}}),
        "other source": json.dumps(
            {"type": "session_meta", "payload": {**root_meta(workdir, "MOCK-odd"), "source": "MOCK-cli"}}),
        "nested too deeply": json.dumps({"type": "session_meta", "payload": root_meta(workdir, "MOCK-odd")})[:-2]
        + ', "MOCK": ' + "[" * 100_000 + "]" * 100_000 + "}}",
    }[case]
    (lanes / "codex-9" / "sessions" / "2026" / "11" / "03" / "rollout-MOCK-odd.jsonl").write_text(first + "\n")
    report = acs.audit_run(run, lanes)
    assert any(flag in f for f in report["flags"]) and not report["passed"]


def odd_log(lanes: Path, name: str, where: str, case: str) -> Path:
    """A main thread's log in `where`, with a cell that calls a tool this script flags, written so that
    its first line says nothing of where the thread started."""
    meta = root_meta(where, "MOCK-extra")
    cwd = {"work directory a list": [where], "work directory empty": "", "work directory a dot": ".",
           "work directory relative": "MOCK/work/sol-1", "work directory a NUL": "\u0000",
           "work directory a slash and a NUL": "/\u0000", "work directory with a NUL inside": "/MOCK\u0000elsewhere",
           "work directory a lone surrogate": "/\ud800"}
    if case in cwd:
        meta["cwd"] = cwd[case]
    elif case == "no work directory":
        del meta["cwd"]
    log = write_log(lanes, name, meta, records=[{"type": "turn_context", "payload": {"cwd": where}},
                                                exec_call('text(await tools.read_file({path: "MOCK"}))')])
    text = log.read_text()
    other = json.dumps({"type": "event_msg", "payload": {"type": "task_started"}}) + "\n"
    written = {"blank first line": ("\n" + text).encode(), "another record first": (other + text).encode(),
               "byte order mark": b"\xef\xbb\xbf" + b"\n" + text.encode(),
               "UTF-16": text.encode("utf-16"), "UTF-16, little-endian": text.encode("utf-16-le"),
               "UTF-32": text.encode("utf-32"), "UTF-32, little-endian": text.encode("utf-32-le")}.get(case)
    if written is not None:
        log.write_bytes(written)
    return log


@pytest.mark.parametrize("case", ["blank first line", "another record first", "byte order mark", "UTF-16",
                                  "UTF-16, little-endian", "UTF-32", "UTF-32, little-endian",
                                  "work directory a list", "no work directory", "work directory empty",
                                  "work directory a dot", "work directory relative", "work directory a NUL",
                                  "work directory a slash and a NUL", "work directory with a NUL inside",
                                  "work directory a lone surrogate"])
def test_a_log_whose_first_line_says_nothing_of_where_it_started_is_flagged_if_it_names_the_work_directory(
        area, case):
    """Review 5: a log in the work directory whose first line is blank or another record, one this
    script reads in another encoding, and a session's record with no work directory it can read, each
    hold a call that a search of first lines alone never reads. Review 6: so does a record whose work
    directory is empty, `.`, a relative path or a NUL, none of them an absolute path. Review 7: and so
    does one whose work directory, though it starts with `/`, holds a NUL, which no path holds, or a
    lone surrogate, which UTF-8 cannot encode. Each is flagged when it names the work directory
    anywhere; the same log in a sibling (`sol-10` beside `sol-1`) is not."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    odd_log(lanes, "rollout-MOCK-extra.jsonl", workdir, case)
    odd_log(lanes, "rollout-MOCK-sibling.jsonl", workdir + "0", case)
    report = acs.audit_run(run, lanes)
    assert [flag.split(":")[0] for flag in report["flags"]] == ["rollout-MOCK-extra.jsonl"], report["flags"]
    assert "names the work directory, but its first line" in report["flags"][0]
    assert {t["thread_id"] for t in report["threads"]} == {PARENT} and not report["passed"]


@pytest.mark.parametrize("case", ["UTF-16, big-endian", "UTF-32, big-endian"])
def test_a_log_whose_lines_python_reads_in_another_encoding_is_audited(area, case):
    """Python's JSON reader takes a line of UTF-16 or UTF-32 that starts with a zero byte as big-endian
    text, so such a log's every line parses: its thread is found and its calls audited."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    log = odd_log(lanes, "rollout-MOCK-extra.jsonl", workdir, "")
    log.write_bytes(log.read_text().encode({"UTF-16, big-endian": "utf-16-be", "UTF-32, big-endian": "utf-32-be"}[case]))
    report = acs.audit_run(run, lanes)
    assert {t["thread_id"] for t in report["threads"]} == {PARENT, "MOCK-extra"}
    assert any("an exec script calls tools.read_file" in flag for flag in report["flags"]) and not report["passed"]


@pytest.mark.parametrize("spelled, result", [
    ("{}/", "found"), ("{}/.", "found"), ("/{}", "found"), ("{}/MOCK/..", "found"),
    ("{}/MOCK", "flagged"), ("file://{}", "no folder"),
    ("{}0", "neither"), ("{}-MOCK", "neither"), ("{}.MOCK", "neither"), ("{}_MOCK", "neither")])
def test_a_session_in_another_spelling_of_the_work_directory_is_audited(area, spelled, result):
    """A sub-agent whose `cwd` spells the work directory otherwise (a `/` at the end, a `.` part, `//`
    at the start, a name and `..`) is audited. One in a path that names the work directory but is
    another (a folder inside it) is flagged, and so is one whose `cwd` is no absolute path but names
    the work directory (a file URL). One in a sibling is neither: the parent's started sub-agent is
    missing."""
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", {**helper_meta(workdir), "cwd": spelled.format(workdir)},
              items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    if result == "found":
        assert {t["thread_id"] for t in report["threads"]} == {PARENT, HELPER} and report["passed"]
        return
    assert {t["thread_id"] for t in report["threads"]} == {PARENT} and report["missing"] == [HELPER]
    assert report["flags"] == {
        "neither": [],
        "flagged": [f"rollout-MOCK-helper.jsonl: a session in {spelled.format(workdir)}, a path that names the work "
                    "directory but is another"],
        "no folder": ["rollout-MOCK-helper.jsonl: it names the work directory, but its first line gives no work "
                      "directory this script can read, an absolute path"]}[result] and not report["passed"]


def test_a_session_in_the_work_directory_in_capitals_is_flagged(area):
    """A disk that ignores case, as macOS's does by default, reads the work directory in capitals as the
    same folder, so the audit flags a sub-agent recorded there."""
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", {**helper_meta(workdir), "cwd": workdir.upper()},
              items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["missing"] == [HELPER] and not report["passed"]
    assert report["flags"] == [f"rollout-MOCK-helper.jsonl: a session in {workdir.upper()}, a path that names the "
                               "work directory but is another"]


@pytest.mark.parametrize("kind, why", [
    ("a folder", "not a regular file"), ("a pipe", "not a regular file"), ("a link to nothing", "not a regular file"),
    pytest.param("no permission to read it", "PermissionError",
                 marks=pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file"))])
def test_a_log_this_script_cannot_open_is_flagged(area, kind, why):
    """A log that is no regular file is flagged without being opened: opening a pipe would wait for a
    writer forever. So is a regular file the system will not let this script read."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    odd = lanes / "codex-9" / "sessions" / "2026" / "11" / "03" / "rollout-MOCK-odd.jsonl"
    {"a folder": odd.mkdir, "a pipe": lambda: os.mkfifo(odd),
     "a link to nothing": lambda: odd.symlink_to(odd.with_name("MOCK-gone")),
     "no permission to read it": lambda: (odd.write_text("{}\n"), odd.chmod(0))}[kind]()
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [f"rollout-MOCK-odd.jsonl: this script cannot open it ({why})"]
    assert not report["passed"]


def test_a_log_whose_whole_text_this_script_cannot_read_is_flagged(area, monkeypatch):
    """A log whose first line says nothing of where its thread started is read whole for the work
    directory's name; when that read fails (the log's permissions changed after its first line was
    read, say), the log is flagged as one this script cannot open."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    log = odd_log(lanes, "rollout-MOCK-extra.jsonl", workdir, "blank first line")
    read_bytes = Path.read_bytes

    def refuse(path):
        if path.name == log.name:
            raise PermissionError("MOCK")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", refuse)
    report = acs.audit_run(run, lanes)
    assert report["flags"] == ["rollout-MOCK-extra.jsonl: this script cannot open it (PermissionError)"]
    assert not report["passed"]


@pytest.mark.parametrize("workdir", [None, "", "MOCK/work/sol-1", ["/MOCK/work/sol-1"]],
                         ids=["none", "empty", "relative", "a list"])
def test_a_run_whose_work_directory_is_not_an_absolute_path_fails(area, workdir):
    lanes, run, real = area
    add_parent(lanes, real, spawned=())
    meta = json.loads((run / "meta.json").read_text())
    (run / "meta.json").write_text(json.dumps({**meta, "workdir": workdir}))
    report = acs.audit_run(run, lanes)
    assert report["threads"] == [] and not report["passed"]
    assert report["flags"][0] == f"the run gives {json.dumps(workdir)} as its work directory, not an absolute path"


@pytest.mark.parametrize("timestamp", [1762193430, ["2026-11-03T18:10:30Z"]], ids=["a number", "a list"])
def test_a_thread_whose_start_time_this_script_cannot_read_is_flagged_and_audited(area, timestamp):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", {**helper_meta(workdir), "timestamp": timestamp},
              items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert f"rollout-MOCK-helper.jsonl: thread {HELPER} gives a start time this script cannot read" in report["flags"]
    helper = next(t for t in report["threads"] if t["thread_id"] == HELPER)
    assert helper["started"] is None and helper["audit"]["web_calls"] == 1 and not report["passed"]


@pytest.mark.parametrize("agent_path", [["/root/MOCK_research"], 7], ids=["a list", "a number"])
def test_a_thread_whose_agent_path_this_script_cannot_read_is_flagged_and_audited(area, agent_path):
    """Review 6: an agent path that is not a string is flagged and recorded as none, and the thread is
    still audited."""
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    meta = helper_meta(workdir)
    meta["source"]["subagent"]["thread_spawn"]["agent_path"] = agent_path
    write_log(lanes, "rollout-MOCK-helper.jsonl", meta, items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert f"rollout-MOCK-helper.jsonl: thread {HELPER} gives an agent path this script cannot read" in report["flags"]
    helper = next(t for t in report["threads"] if t["thread_id"] == HELPER)
    assert helper["agent_path"] is None and helper["audit"]["web_calls"] == 1 and not report["passed"]


def spell(text: str, how: str) -> str:
    """`text` as the body of a JSON string that spells it with escapes."""
    if how == "escaped slashes":
        return text.replace("/", "\\/")
    if how == "unicode slashes":
        return text.replace("/", "\\u002F")
    return "".join(f"\\u{ord(char):04x}" for char in text)


def escape_first_line(log: Path, workdir: str, how: str) -> None:
    """Rewrite a log's first line to spell the work directory with escapes."""
    first, rest = log.read_text().split("\n", 1)
    first = first.replace(json.dumps(workdir), '"' + spell(workdir, how) + '"')
    assert json.dumps(workdir) not in first and json.loads(first)["payload"]["cwd"] == workdir
    log.write_text(first + "\n" + rest)


@pytest.mark.parametrize("how", ["escaped slashes", "unicode slashes", "every character"])
def test_a_log_that_spells_the_work_directory_with_escapes_is_compared(area, how):
    """Review finding 2: discovery reads the work directory however a log's JSON spells it, so a second
    log of the main thread, with a call the first lacks, fails the run."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    copy = write_log(lanes, "rollout-MOCK-parent-escaped.jsonl", root_meta(workdir),
                     items=[search("MOCK main query"), command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    escape_first_line(copy, workdir, how)
    report = acs.audit_run(run, lanes)
    assert any(f"both hold thread {PARENT}, and they differ" in flag for flag in report["flags"])
    assert not report["passed"]


@pytest.mark.parametrize("how", ["escaped slashes", "unicode slashes", "every character"])
def test_a_sub_agent_whose_log_spells_the_work_directory_with_escapes_is_audited(area, how):
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    helper = write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
                       items=[search("MOCK helper query"), command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    escape_first_line(helper, workdir, how)
    report = acs.audit_run(run, lanes)
    assert {t["thread_id"] for t in report["threads"]} == {PARENT, HELPER} and report["missing"] == []
    assert report["violations"] == 1 and not report["passed"]


@pytest.mark.parametrize("before", [None, 'MOCK "quote'], ids=["alone", "after an escaped quote"])
@pytest.mark.parametrize("case", ["cut", "other record", "quotes paired otherwise", "a key twice"])
def test_a_first_line_that_escapes_the_work_directory_and_cannot_be_read_is_flagged(area, tmp_path, case, before):
    """A log whose first line spells the work directory with escapes, but does not parse as a session's
    record, is flagged: also after a string that escapes a quote, when a missing quote pairs the
    line's quotes otherwise (review 3), and when the line gives a key twice. One that spells another
    directory so is not."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    folder = lanes / "codex-9" / "sessions" / "2026" / "11" / "03"
    for name, where in [("rollout-MOCK-odd.jsonl", workdir), ("rollout-MOCK-odd-elsewhere.jsonl", str(tmp_path / "MOCK"))]:
        payload = {"cwd": where} if case == "other record" else root_meta(where, "MOCK-odd")
        if before is not None:
            payload = {"note": before, **payload}
        record = {"type": "MOCK_record" if case == "other record" else "session_meta", "payload": payload}
        first = json.dumps(record).replace(json.dumps(where), '"' + spell(where, "escaped slashes") + '"')
        first = {"cut": first[:-10], "other record": first,
                 # Read left to right, the quote that closes the key opens a string, and the directory
                 # falls between two strings.
                 "quotes paired otherwise": first.replace('"cwd"', 'cwd"'),
                 "a key twice": first[:-2] + ', "cwd": "/MOCK/elsewhere"}}'}[case]
        (folder / name).write_text(first + "\n")
    report = acs.audit_run(run, lanes)
    assert [flag.split(":")[0] for flag in report["flags"]] == ["rollout-MOCK-odd.jsonl"] and not report["passed"]


def test_a_transcript_of_another_thread_fails(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir, spawned=())
    write_transcript(run, EARLIER, [web("MOCK earlier query")])
    report = acs.audit_run(run, lanes)
    assert report["main_thread"] is None and "transcript_check" not in report
    assert any(f"records thread {EARLIER}" in flag for flag in report["flags"]) and not report["passed"]


def test_the_kept_attempts_are_final(area, monkeypatch):
    lanes, run, workdir = area
    record = with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir, spawned=())
    assert acs.audit_run(run, lanes)["passed"]
    first = (run / "codex-sessions" / "audit.json").read_bytes()
    monkeypatch.setattr(acs, "subfleet_record", lambda job: None)  # subfleet has pruned the job
    assert acs.audit_run(run, lanes)["passed"]
    assert (run / "codex-sessions" / "audit.json").read_bytes() == first
    changed = {**record, "attempts": record["attempts"][1:]}
    monkeypatch.setattr(acs, "subfleet_record", lambda job: changed)
    with pytest.raises(SystemExit, match="the kept copy is final"):
        acs.audit_run(run, lanes)


@pytest.mark.parametrize("case, flag", [
    ("only the collected attempt", f"lists attempts ['{JOB}/a2'], not {JOB}/a1 to {JOB}/a1"),
    ("another job's attempt", f"of job {JOB} lists attempts ['MOCK-other-job/a1'], not {JOB}/a1 to {JOB}/a1"),
    ("one session for two attempts", f"names session {PARENT} for 2 attempts"),
    ("a sub-agent as an attempt's session", f"attempt {JOB}/a2's session {EARLIER_HELPER} is a sub-agent"),
    ("a session that is not a string", f"gives attempt {JOB}/a1 a session this script cannot read"),
    ("an attempt id that is not a string", f"lists attempts [None, '{JOB}/a2'], not {JOB}/a1 to {JOB}/a2"),
    ("a kept record of another job", f"of job MOCK-other-job lists attempts ['{JOB}/a1'], not {JOB}/a1 to {JOB}/a1"),
])
def test_each_attempt_must_be_its_jobs_with_a_main_thread_of_its_own(area, monkeypatch, case, flag):
    """Review finding 3: a record that leaves out an attempt, gives two attempts one session, or gives
    an attempt a sub-agent as its session cannot say which threads each attempt left. Each case fails
    the run on this flag alone."""
    lanes, run, workdir = area
    if case == "a sub-agent as an attempt's session":
        with_record(monkeypatch, run, [(f"{JOB}/a1", EARLIER, "failed"), (f"{JOB}/a2", EARLIER_HELPER, "succeeded")])
        add_earlier_attempt(lanes, workdir)
        write_transcript(run, EARLIER_HELPER, [web("MOCK earlier helper query")])
    elif case == "a kept record of another job":
        add_parent(lanes, workdir, spawned=())
        with_record(monkeypatch, run, [(f"{JOB}/a1", PARENT, "succeeded")], accepted=f"{JOB}/a1", collected=f"{JOB}/a1")
        monkeypatch.setattr(acs, "subfleet_record", lambda job: None)  # subfleet has pruned the job
        (run / "codex-sessions").mkdir()
        (run / "codex-sessions" / "attempts.json").write_text(json.dumps({
            "job_id": "MOCK-other-job", "accepted_attempt_id": f"{JOB}/a1",
            "attempts": [{"attempt_id": f"{JOB}/a1", "native_session_id": PARENT, "started_at": "MOCK"}]}))
    else:
        add_parent(lanes, workdir, spawned=())
        with_record(monkeypatch, run, *{
            "only the collected attempt": ([(f"{JOB}/a2", PARENT, "succeeded")],),
            "another job's attempt": ([("MOCK-other-job/a1", PARENT, "succeeded")], "MOCK-other-job/a1",
                                      "MOCK-other-job/a1"),
            "one session for two attempts": ([(f"{JOB}/a1", PARENT, "failed"), (f"{JOB}/a2", PARENT, "succeeded")],),
            "a session that is not a string": ([(f"{JOB}/a1", ["MOCK"], "failed"), (f"{JOB}/a2", PARENT, "succeeded")],),
            "an attempt id that is not a string": ([(None, None, "failed", None), (f"{JOB}/a2", PARENT, "succeeded")],),
        }[case])
    report = acs.audit_run(run, lanes)
    [only] = report["flags"]
    assert flag in only and report["missing"] == [] and not report["passed"]


@pytest.mark.parametrize("text", ['{"attempts": "MOCK"}', '["MOCK"]', '{"attempts": ["MOCK"]}', "null", "", "{",
                                  '{"attempts":', b'{"attempts": [], "MOCK": "\xff"}',
                                  '{"attempts": [{"MOCK": ' + "[" * 63 + "]" * 63 + "}]}",
                                  '{"attempts": [' + "[" * 100_000 + "]" * 100_000 + "]}"],
                         ids=["attempts a string", "a list", "an attempt a string", "null", "empty", "cut short",
                              "cut after a key", "not UTF-8", "nested too deeply", "nested past the parser"])
def test_a_kept_attempts_file_that_is_not_a_record_stops_the_audit(area, text):
    """A kept record is final, so one that is not a record of attempts stops the audit with the reason;
    review 6: so does one that is empty, cut short, not UTF-8 or nested more than 64 levels, instead of
    an error from reading it."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    (run / "codex-sessions").mkdir()
    (run / "codex-sessions" / "attempts.json").write_bytes(text if isinstance(text, bytes) else text.encode())
    with pytest.raises(SystemExit, match="is not a record of attempts"):
        acs.audit_run(run, lanes)


@pytest.mark.parametrize("kind", ["a folder", "a pipe", "a link to nothing"])
def test_a_kept_attempts_file_that_is_not_a_regular_file_stops_the_audit(area, kind):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    kept = run / "codex-sessions" / "attempts.json"
    kept.parent.mkdir()
    {"a folder": kept.mkdir, "a pipe": lambda: os.mkfifo(kept),
     "a link to nothing": lambda: kept.symlink_to(kept.with_name("MOCK-gone"))}[kind]()
    with pytest.raises(SystemExit, match="is not a record of attempts"):
        acs.audit_run(run, lanes)


def test_a_grandchild_thread_belongs_to_its_attempt(area, monkeypatch):
    lanes, run, workdir = area
    with_record(monkeypatch, run, TWO_ATTEMPTS)
    add_earlier_attempt(lanes, workdir)
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), records=[function_call("spawn_agent")],
              items=[search("MOCK helper query"), started("MOCK-grandchild")])
    write_log(lanes, "rollout-MOCK-grandchild.jsonl",
              helper_meta(workdir, "MOCK-grandchild", HELPER, "2026-11-03T18:11:00Z"),
              items=[search("MOCK grandchild query")])
    report = acs.audit_run(run, lanes)
    grandchild = next(t for t in report["threads"] if t["thread_id"] == "MOCK-grandchild")
    assert grandchild["attempt"] == f"{JOB}/a2" and grandchild["collected"] and report["passed"]


def test_a_thread_whose_parent_has_no_log_fails(area):
    """Review finding 7: the orphan's own audit passes, so only the orphan rule fails the run."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_log(lanes, "rollout-MOCK-orphan.jsonl", helper_meta(workdir, "MOCK-orphan", "MOCK-gone"),
              items=[search("MOCK orphan query")])
    report = acs.audit_run(run, lanes)
    assert report["orphans"] == ["MOCK-orphan"] and report["flags"] == [] and report["missing"] == []
    assert all(t["audit"]["passed"] for t in report["threads"]) and not report["passed"]


def test_a_threads_spawn_calls_must_match_the_sub_agents_it_started(area):
    """Review finding 6: each sub-agent comes from one `spawn_agent` call."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, records=[function_call("spawn_agent")])  # two calls, one sub-agent
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [f"thread {PARENT} made 2 spawn_agent calls and started 1 sub-agents"]
    assert not report["passed"]


def test_threads_whose_parents_form_a_cycle_fail(area):
    """Review finding 4: two sub-agents that each name the other as their parent, and each started the
    other, descend from no main thread."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    loop = ["MOCK-loop-a", "MOCK-loop-b"]
    for me, other in zip(loop, reversed(loop)):
        write_log(lanes, f"rollout-{me}.jsonl", helper_meta(workdir, me, other), records=[function_call("spawn_agent")],
                  items=[search(f"{me} query"), started(other)])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [f"thread {t} descends from no main thread: its parents form a cycle" for t in loop]
    assert report["orphans"] == [] and report["missing"] == [] and not report["passed"]


def test_a_sub_agent_must_name_the_thread_that_started_it(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir), items=[search("MOCK helper query")])
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [f"thread {PARENT} started [], but ['{HELPER}'] name it as their parent"]
    assert not report["passed"]


def test_a_sibling_work_directory_is_not_this_runs(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    write_log(lanes, "rollout-MOCK-sibling.jsonl", root_meta(workdir + "0", "MOCK-sibling"))
    write_log(lanes, "rollout-MOCK-mention.jsonl",
              {**root_meta(workdir + "-elsewhere", "MOCK-mention"), "note": workdir})
    report = acs.audit_run(run, lanes)
    assert [t["thread_id"] for t in report["threads"]] == [PARENT] and report["passed"]


@pytest.mark.parametrize("result, expected", [
    ({"returncode": 0, "stdout": '{"attempts": []}'}, {"attempts": []}),
    ({"returncode": 1, "stdout": '{"attempts": []}'}, None),
    ({"returncode": 0, "stdout": "MOCK not JSON"}, None),
    (OSError("MOCK: no subfleet"), None),
])
def test_subfleet_is_asked_for_the_job_and_any_failure_means_no_record(monkeypatch, result, expected):
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append(cmd)
        if isinstance(result, Exception):
            raise result
        return subprocess.CompletedProcess(cmd, result["returncode"], result["stdout"], "")

    monkeypatch.setattr(acs.subprocess, "run", fake_run)
    assert acs.subfleet_record(JOB) == expected
    assert seen == [["subfleet", "runs", "show", JOB, "--json"]]


def test_the_script_prints_a_lone_surrogate_as_its_escape_and_returns_its_verdict(area, capsys):
    """Review 6: a log's JSON can spell a lone surrogate, which no encoding writes. The script prints a
    suspect call that holds one with the surrogate's escape, so it still returns its verdict."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), records=[tool_output(served("http://\ud800.localhost"))])
    assert acs.main(["sol-1", "--lanes", str(lanes)]) == 0
    out = capsys.readouterr().out
    assert "1 suspect" in out and "\\ud800" in out


def test_session_logs_stay_out_of_git():
    """`.gitignore` keeps each log out of this public repository and keeps its audit and attempts in."""
    def ignored(rel: str) -> bool:
        proc = subprocess.run(["git", "check-ignore", "-q", rel], cwd=acs.ROOT, capture_output=True)
        if proc.returncode not in (0, 1):
            pytest.skip("not a git checkout")
        return proc.returncode == 0

    assert ignored("runs/MOCK/codex-sessions/rollout-MOCK.jsonl")
    assert not ignored("runs/MOCK/codex-sessions/audit.json")
    assert not ignored("runs/MOCK/codex-sessions/attempts.json")
    tracked = subprocess.run(["git", "ls-files", "runs"], cwd=acs.ROOT, capture_output=True, text=True).stdout
    assert {Path(p).name for p in tracked.split() if "/codex-sessions/" in p} <= {"audit.json", "attempts.json"}


NAMES = st.lists(st.from_regex(r"[a-z][a-z0-9]{0,6}", fullmatch=True), min_size=1, max_size=4)


@given(words=NAMES, fields=st.dictionaries(st.from_regex(r"[a-z]{1,8}", fullmatch=True).filter(lambda k: k != "type"),
                                           st.none() | st.text(max_size=5) | st.lists(st.text(max_size=3), max_size=2),
                                           max_size=4))
def test_a_web_action_takes_the_transcripts_form(words, fields):
    """Property: the kind's camelCase words join with underscores, null fields drop, the rest stay,
    and the form is a fixed point."""
    camel = words[0] + "".join(w[0].upper() + w[1:] for w in words[1:])
    out = acs.web_action({"type": camel, **fields})
    assert out["type"] == "_".join(words)
    assert {k: v for k, v in out.items() if k != "type"} == {k: v for k, v in fields.items() if v is not None}
    assert acs.web_action(out) == out


@given(argv=st.lists(st.text(st.characters(blacklist_categories=("Cs",), blacklist_characters="\x00"), max_size=8),
                     min_size=1, max_size=4))
def test_a_command_compares_the_same_however_it_is_quoted(argv):
    """Property: a command the log keeps as words compares equal to any quoting of the same words."""
    def line(cmd):
        return [{"type": "item.completed", "item": {"id": "MOCK", "type": "command_execution", "command": cmd}}]

    double = " ".join('"' + re.sub(r'(["\\])', r"\\\1", word) + '"' for word in argv)
    assert acs._calls(line(shlex.join(argv))) == acs._calls(line(double))


@given(pieces=st.lists(st.text(max_size=6), min_size=1, max_size=4))
@example(pieces=["\U0001f600", "\u2028\\"])
def test_a_constant_string_folds_to_what_the_script_builds(pieces):
    """Property: a sum of string literals, each written as JSON writes it (escapes JavaScript reads the
    same way, surrogate pairs included), and a template of them both fold to the string they build."""
    template = "`" + "".join("${" + json.dumps(p) + "}" for p in pieces) + "`"
    for expr in (" + ".join(json.dumps(p) for p in pieces), template):
        src = f"x = {expr};".encode()
        tree = acs._JS.parse(src)
        assert not tree.root_node.has_error
        assignment = tree.root_node.named_children[0].named_children[0]
        assert acs._fold(assignment.child_by_field_name("right"), src) == "".join(pieces)


@pytest.mark.parametrize("expr, folded", [
    ('"a" + 1 + 2', "a12"),  # a string, then each number joined to it
    ('(1) + "a" + 0x10', "1a16"),
    ("`${1n}${1e21}${1e-7}${0.000001}`", "11e+211e-70.000001"),
    ('1 + 2 + "a"', None),  # `1 + 2` adds, which this script does not fold
    ('(1) + (2) + "a"', None),
    ('"a" + (1 + 2)', None),
    ('"a" + 1_0', "a10"),
    ('"a" + 0x' + "f" * 300, "aInfinity"),  # past the largest double
    ('"a" + 9007199254740993n + 9007199254740993', "a90071992547409939007199254740992"),  # a BigInt keeps each digit
    ('"a" + 0x20000000000001n + 0x20000000000001', "a90071992547409939007199254740992"),
    ('"a" + 1_000n', "a1000"),
    ('"a" + 017', None),  # a legacy octal, which a module refuses
    # Python turns at most 4,300 decimal digits into an int or back; JavaScript has no such limit.
    pytest.param('"a" + ' + "1" * 4301, "aInfinity", id="a decimal past 4,300 digits"),
    pytest.param('"a" + ' + "1" * 4301 + "n", "a" + "1" * 4301, id="a decimal BigInt past 4,300 digits"),
    *[pytest.param(f'"a" + 0{base}{10**4301:{base}}n', "a1" + "0" * 4301,
                   id=f"a BigInt in base {base} past 4,300 digits") for base in "xob"],
])
def test_a_number_joins_a_string_as_javascript_writes_it(expr, folded):
    src = f"x = {expr};".encode()
    assignment = acs._JS.parse(src).root_node.named_children[0].named_children[0]
    assert acs._fold(assignment.child_by_field_name("right"), src) == folded


@pytest.mark.parametrize("expr, folded", [
    ('"a" + true', "atrue"),
    ('false + "a"', "falsea"),
    ('"a" + null', "anull"),
    ("`${true}${false}${null}`", "truefalsenull"),
    ('"a" + true + 1', "atrue1"),
    ("`a` + 1", "a1"),  # a template is a string, so `+` joins
    ('(true) + "a"', "truea"),
    ('true + 1 + "a"', None),  # `true + 1` adds, as `1 + 2` does
    ('true + null + "a"', None),
    ('"a" + undefined', None),  # a name, which a script may declare
    ('"a" + -1', None),  # a unary operator
    ("`${-1}`", None),
    ('"\\uD83D" + "\\uDE00"', "\U0001f600"),  # the halves of one character, joined
    ('"\\uD83D" + `\\uDE00`', "\U0001f600"),
    ('`\\uD83D${"\\uDE00"}`', "\U0001f600"),
    ("`\\uD83D\\uDE00`", "\U0001f600"),
    ('"\\uDE00" + "\\uD83D"', "\ude00\ud83d"),  # in the other order, two halves
    ("`a\r\nb\rc\nd`", "a\nb\nc\nd"),  # a template reads CR LF and CR as LF
    ("`a\\\r\nb`", "ab"),  # and a backslash before them as no character at all
    ("`a\u2028b`", "a\u2028b"),  # but keeps a line separator
    ('"a\\\r\nb"', "ab"),
])
def test_a_literal_joins_a_string_as_javascript_joins_it(expr, folded):
    src = f"x = {expr};".encode()
    tree = acs._JS.parse(src)
    assert not tree.root_node.has_error
    assignment = tree.root_node.named_children[0].named_children[0]
    assert acs._fold(assignment.child_by_field_name("right"), src) == folded


@given(x=st.floats(min_value=0, allow_nan=False))
@example(x=0.0)
@example(x=100.0)
@example(x=1e20)
@example(x=1e21)
@example(x=1e-6)
@example(x=1e-7)
@example(x=5e-324)
def test_a_numbers_string_gives_back_the_number(x):
    """Property: the string `_number` makes of a double gives back the double, in the form ECMAScript
    writes: no exponent from 1e-6 up to 1e21, and no zero at the end of the digits after a point."""
    x = abs(x)
    text = acs._number("1e400" if x == math.inf else repr(x))
    assert float(text) == x
    assert re.fullmatch(r"0|Infinity|[1-9]\d*(\.\d*[1-9])?|0\.0*[1-9](\d*[1-9])?|[1-9](\.\d*[1-9])?e[+-][1-9]\d*", text)
    assert ("e" in text) is not (x == 0 or x == math.inf or 1e-6 <= x < 1e21)


@given(data=st.data())
def test_an_index_that_can_build_a_denied_name_is_flagged(data):
    """Property: split a name the script denies into pieces, write at least one of them out as a string
    and hold the rest in variables; an index with their sum, or with a template of them, is flagged."""
    word = data.draw(st.sampled_from(sorted(acs.SPELLED)))
    cuts = sorted(data.draw(st.sets(st.integers(1, len(word) - 1), max_size=3)))
    pieces = [word[i:j] for i, j in zip([0, *cuts], [*cuts, len(word)])]
    written = data.draw(st.lists(st.booleans(), min_size=len(pieces), max_size=len(pieces)).filter(any))
    parts = [json.dumps(p) if w else f"v{i}" for i, (p, w) in enumerate(zip(pieces, written))]
    held = "".join(f"const v{i} = {json.dumps(p)}; " for i, (p, w) in enumerate(zip(pieces, written)) if not w)
    for key in (" + ".join(parts), "`" + "".join("${" + part + "}" for part in parts) + "`"):
        src = f"{held}const o = {{}}; text(o[{key}]);".encode()
        problems = acs.cell_problems(acs._JS.parse(src), src)
        assert any(problem.startswith("indexes with") for problem in problems), (src, problems)


@pytest.mark.parametrize("key", ['v0 + "unction"', "`${v0}unction`"])
def test_an_index_that_builds_a_denied_name_around_a_variable_is_flagged(key):
    """A fixed case of the property above: `Function` from a piece a variable holds and a piece written
    out, which is part of a denied name."""
    src = f'const v0 = "F"; const o = {{}}; text(o[{key}]);'.encode()
    problems = acs.cell_problems(acs._JS.parse(src), src)
    assert any(problem.startswith("indexes with") for problem in problems), problems


@settings(deadline=None)
@given(path=st.lists(st.from_regex(r"[A-Za-z0-9._-]{1,8}", fullmatch=True), min_size=1, max_size=5),
       note=st.text(alphabet='M "\\', max_size=6), data=st.data())
def test_discovery_reads_the_work_directory_however_json_spells_it(path, note, data):
    """Property (review finding 2): a log whose first line spells the work directory with any mix of
    escapes (`\\/`, `\\u` in either case), after a string that may escape quotes and backslashes, is
    found, and flagged when it does not parse: cut short, missing the quote that closes that string
    (review 3), or giving a key twice. One that spells another directory is neither."""
    workdir = "/" + "/".join(path)

    def spelled(text: str) -> str:
        out = []
        for char in text:
            how = data.draw(st.sampled_from(["raw", "unicode", "UNICODE", *(["slash"] if char == "/" else [])]))
            out.append({"raw": char, "slash": "\\/", "unicode": f"\\u{ord(char):04x}",
                        "UNICODE": f"\\u{ord(char):04X}"}[how])
        return '"' + "".join(out) + '"'

    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "rollout-MOCK.jsonl"
        for where, named in [(workdir, True), (workdir + "-MOCK", False)]:
            head = '{"type": "session_meta", "payload": {"note": '
            tail = ', "id": "MOCK-thread", "cwd": ' + spelled(where) + ', "source": "exec"}}'
            first = head + json.dumps(note) + tail
            log.write_text(first + "\n")
            threads, problems = acs.find_threads([log], workdir)
            assert (set(threads) == {"MOCK-thread"}) is named and problems == []
            for broken in (first[:-3],  # cut inside its last string
                           # Read left to right, the directory falls between two strings.
                           head + json.dumps(note)[:-1] + tail,
                           first[:-2] + ', "cwd": "/MOCK-elsewhere"}}'):
                with pytest.raises(ValueError):
                    acs._record(broken)
                log.write_text(broken + "\n")
                threads, problems = acs.find_threads([log], workdir)
                assert threads == {} and len(problems) == int(named)


def _json_ways(char: str) -> list[str]:
    """Each way JSON can write a character in a string: as itself (but a quote or a backslash), as a
    short escape, or as `\\u` escapes in either case, two of them for a character past U+FFFF."""
    if char in '"\\':
        return {'"': ['\\"', "\\u0022"], "\\": ["\\\\", "\\u005c"]}[char]
    units = char.encode("utf-16-be")
    escaped = ["".join(f"\\u{int.from_bytes(units[i:i + 2]):04{case}}" for i in range(0, len(units), 2))
               for case in "xX"]
    return [char, *escaped, *(["\\/"] if char == "/" else [])]


# What may stand before and after the work directory in a log's text, and what of it ends the name.
BEFORE = ["", "/", " ", '"', ":", "\\", "MOCK", "0", "-", ".", "_", "~"]
AFTER = ["", "/", "/MOCK", " MOCK", '"', "0", "-MOCK", ".MOCK", "_MOCK", "\\MOCK"]
ENDS_BEFORE = {"", "/", " ", '"', ":", "\\"}
ENDS_AFTER = {"", "/", "/MOCK", " MOCK", '"'}


@settings(deadline=None)
@given(path=st.lists(st.from_regex(r"[A-Za-z0-9._\-Ā😀]{1,8}", fullmatch=True), min_size=1, max_size=4),
       before=st.sampled_from(BEFORE), after=st.sampled_from(AFTER), slash=st.booleans(),
       encoding=st.sampled_from(["utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "utf-32", "utf-32-le",
                                 "utf-32-be"]),
       pad=st.integers(0, 3), capitals=st.booleans(), data=st.data())
def test_a_log_names_the_work_directory_in_any_encoding_and_spelling(path, before, after, slash, encoding, pad,
                                                                     capitals, data):
    """Property: `_mentions` finds the work directory in a log however its JSON spells it, in either
    case, as UTF-8, UTF-16 or UTF-32 text after any number of other bytes, exactly when what stands
    next to it ends its name. Before it, that is a `/`, a space, a quote, a `:`, a backslash or
    nothing, but not a letter, digit, `-`, `.`, `_` or `~`; after it, a `/`, a space, a quote or
    nothing, but not a letter, digit, `-`, `.`, `_` or backslash. A `/` at the end of the work
    directory names the same folder."""
    workdir = "/" + "/".join(path)
    text = before + workdir + after
    spelled = "".join(data.draw(st.sampled_from(_json_ways(char))) for char in (text.upper() if capitals else text))
    line = '{"type": "MOCK", "payload": {"note": "MOCK", "cwd": "' + spelled + '"}}\n'
    named = before in ENDS_BEFORE and after in ENDS_AFTER
    assert acs._mentions(b"\x00" * pad + line.encode(encoding), workdir + "/" * slash) is named


def test_what_stands_next_to_the_work_directory_ends_its_name_or_not():
    """The property above for each thing it puts before and after the work directory, in the work
    directory's case and in capitals, with and without a `/` at its end, since a run of the property
    may draw none of the few that tell one rule from another."""
    wrong = [(before, after, case.__name__, slash) for before in BEFORE for after in AFTER
             for case in (str, str.upper) for slash in ("", "/")
             if acs._mentions(('{"cwd": ' + json.dumps(case(before + "/MOCK/work" + after)) + "}\n").encode(),
                              "/MOCK/work" + slash) is not (before in ENDS_BEFORE and after in ENDS_AFTER)]
    assert wrong == []


@pytest.mark.parametrize("way", range(4))
def test_a_log_names_the_work_directory_however_json_spells_its_characters(way):
    """Each way JSON writes the work directory's characters, all of them one way: as themselves, as
    `\\u` escapes in lower case or in capitals (two of them for a character past U+FFFF), and `/` as
    `\\/` beside the rest in capitals."""
    workdir = "/MOCK/Ā😀"
    spelled = "".join(ways[min(way, len(ways) - 1)] for ways in map(_json_ways, workdir))
    assert acs._mentions(('{"cwd": "' + spelled + '"}\n').encode(), workdir)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"])
@pytest.mark.parametrize("pad", [0, 1, 2, 3])
def test_a_log_names_the_work_directory_in_each_encoding_after_any_bytes(encoding, pad):
    """`_mentions` reads a log in each encoding from each byte a character can start at. Text in one
    byte order, read in the other from one byte off (later for little-endian text, earlier for
    big-endian), spells the same characters up to U+00FF, so a path with characters past U+00FF shows
    that each reading counts."""
    workdir = "/MOCK/Ā😀"
    line = '{"type": "MOCK", "payload": {"cwd": "' + workdir + '"}}\n'
    assert acs._mentions(b"\x00" * pad + line.encode(encoding), workdir)


def test_a_byte_that_does_not_decode_is_no_letter():
    """A byte that does not decode reads as U+FFFD, which is no letter, `.`, `_` or `-`, so it ends a
    name: the work directory after `-` and such a byte is named, and after `-` alone it is not."""
    assert acs._mentions(b'{"cwd": "-\xff/MOCK/work"}\n', "/MOCK/work")
    assert not acs._mentions(b'{"cwd": "-/MOCK/work"}\n', "/MOCK/work")


# What a JavaScript string may escape as the character itself: no escape with a meaning of its own
# (`\b`, `\n`, `\u`...), no digit (an octal escape, which a module refuses) and no line break.
IDENTITY = set("acdeghijklmopqswyzABCDEFGHIJKLMNOPQRSTUVWXYZ./:-_ ")
PLACES = {"open": 'text(await tools.web__run({{open: [{{ref_id: "{}"}}]}}))',
          "search": 'text(await tools.web__run({{search_query: [{{q: "{}"}}]}}))'}
TARGETS = ["https://www.example.org/MOCK", "http://127.0.0.1:8080/MOCK", "http://localhost/MOCK",
           "https://github.com/MaxGhenis/dc-i86-llm-forecast", "file:///etc/hosts", "ftp://MOCK.example.org/MOCK",
           "https://lim s.example.gov/MOCK", "/etc/hosts", "turn0search3"]


@given(target=st.sampled_from(TARGETS), place=st.sampled_from(sorted(PLACES)), data=st.data())
def test_no_escape_hides_what_a_scripts_string_opens(target, place, data):
    """Property (review finding 6): write a script's string with escapes JavaScript reads as the
    character itself, and with line continuations, and the script stays suspect whenever the plain
    string makes it so."""
    choices = data.draw(st.lists(st.sampled_from(["plain", "escaped", "continued"]), min_size=len(target),
                                 max_size=len(target)))
    escaped = "".join("\\" + char if how == "escaped" and char in IDENTITY else
                      char + "\\\n" if how == "continued" else char for char, how in zip(target, choices))

    def verdict(text: str) -> str:
        code = PLACES[place].format(text)
        tree = acs._JS.parse(code.encode())
        assert not tree.root_node.has_error
        return acs.check_script(code, "/MOCK/work", tree)[0]

    if verdict(target) == "suspect":
        assert verdict(escaped) == "suspect", escaped



JSON_VALUES = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=6)
    | st.sampled_from(sorted(acs.RECORDS | acs.EVENTS | acs.RESPONSE_ITEMS | {"Extension", "CommandExecution"})),
    lambda inner: st.lists(inner, max_size=3)
    | st.dictionaries(st.sampled_from(["type", "id", "payload", "item", "kind", "MOCK"]), inner, max_size=3),
    max_leaves=6)


def fields(node):
    """Each (container, key) in a JSON value."""
    for key in list(node) if isinstance(node, dict) else range(len(node)) if isinstance(node, list) else ():
        yield node, key
        yield from fields(node[key])


def passing_logs(workdir: str) -> dict[str, list[dict]]:
    """A main thread that opens a page by script, cites it and starts a sub-agent, which searches the
    web and runs a command in the work directory: logs that pass with `area`'s transcript."""
    url = "https://www.example.org/MOCK"
    return {"rollout-MOCK-parent.jsonl": [
                {"type": "session_meta", "payload": root_meta(workdir)},
                exec_call(f'text(await tools.web__run({{open: [{{ref_id: "{url}"}}]}}))', "MOCK-call"),
                tool_output(served(url), call_id="MOCK-call"), function_call("spawn_agent"),
                completed(search("MOCK main query")), completed(started(HELPER))],
            "rollout-MOCK-helper.jsonl": [
                {"type": "session_meta", "payload": helper_meta(workdir)},
                completed(search("MOCK helper query")), completed(command("echo MOCK", workdir))]}


def write_logs(lanes: Path, logs: dict[str, list[dict]]) -> None:
    for name, records in logs.items():
        path = lanes / "codex-9" / "sessions" / "2026" / "11" / "03" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(record) + "\n" for record in records))


def test_the_logs_the_property_changes_pass(area):
    lanes, run, workdir = area
    write_logs(lanes, passing_logs(workdir))
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["served_pages"] == 1 and report["passed"]


@settings(deadline=None, max_examples=60)
@given(data=st.data())
def test_a_run_with_any_field_changed_gets_a_verdict_the_gate_shares(data):
    """Property: drop or replace one to three fields anywhere in a passing run's logs and transcript,
    with any JSON value, and the audit still reaches a verdict, which the pooling gate shares
    (`make_area`'s `audit_run` checks the gate)."""
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as monkeypatch:
        lanes, run, workdir = make_area(Path(tmp), monkeypatch)
        logs = passing_logs(workdir)
        transcript = [json.loads(line) for line in (run / "transcript.jsonl").read_text().splitlines()]
        for _ in range(data.draw(st.integers(1, 3), label="changes")):
            spots = [spot for records in (*logs.values(), transcript) for record in records for spot in fields(record)]
            container, key = data.draw(st.sampled_from(spots), label="field")
            if isinstance(container, dict) and data.draw(st.booleans(), label="drop"):
                del container[key]
            else:
                container[key] = data.draw(JSON_VALUES, label="value")
        write_logs(lanes, logs)
        (run / "transcript.jsonl").write_text("".join(json.dumps(line) + "\n" for line in transcript))
        acs.audit_run(run, lanes)
