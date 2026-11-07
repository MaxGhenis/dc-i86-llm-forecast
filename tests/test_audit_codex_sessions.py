"""scripts/audit_codex_sessions.py finds every Codex thread behind a run, ties each main thread to a
subfleet attempt, keeps its log and audits it. MOCK session logs, transcripts and subfleet records in
temporary directories. The tests never run the real subfleet; a few run git, the script itself, a MOCK
`subfleet`, or zsh and bash, to see how each shell reads a command. The pooling gate
(`cli._session_audit`) reads every audit a test writes and must reach the script's verdict."""

import errno
import importlib.util
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, event, example, given, settings
from hypothesis import strategies as st

from i86 import audit, cli

spec = importlib.util.spec_from_file_location(
    "audit_codex_sessions", Path(__file__).parent.parent / "scripts" / "audit_codex_sessions.py")
acs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acs)

PARENT, HELPER = "MOCK-parent-thread", "MOCK-helper-thread"
EARLIER, EARLIER_HELPER = "MOCK-earlier-thread", "MOCK-earlier-helper-thread"
JOB = "MOCK-job-sol-1"
REAL_RUN = subprocess.run  # `make_area` blocks it; a test of what it refuses before it starts anything restores it
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
                     "'MOCK_response_item'", "not in the work directory itself", "'MOCKItem'", "'Extension'"):
        assert expected in flags
    assert not report["passed"]


@pytest.mark.parametrize("spelled, flag", [
    ("file://{}/.", None), ("file://{}/", None), ("file://{}//", None), ("file://{}/./", None), ("{}", None),
    ("file://{}/MOCK/..", "a path this script cannot place"), ("file://{}/../sol-1", "a path this script cannot place"),
    ("MOCK/work/sol-1", "a path this script cannot place"),
    ("file://localhost{}", None), ("file://LOCALHOST{}/", None),
    ("file://MOCK-remote{}", "a path this script cannot place"), ("file://MOCK-remote:22{}", "a path this script cannot place"),
    ("file://{}/MOCK", "not in the work directory itself"), ("file://{}0", "not in the work directory itself"),
    ("file://{}#/../../MOCK", "a path this script cannot place"), ("file://{}?/../../MOCK", "a path this script cannot place"),
    ("file://{}#", "a path this script cannot place"), ("file://{}?", "a path this script cannot place"),
    ("file://{}%2F", "a path this script cannot place"), ("file://{}/%2E", "a path this script cannot place"),
    ("{}#", "not in the work directory itself")])
def test_a_command_runs_in_the_work_directory_only_where_a_plain_path_names_it(area, spelled, flag):
    """Review 6: a command in the work directory spelled with a `.` part, `//` or a `/` at the end ran
    there. One in a path with a `..` part, or a relative one, ran wherever a link before it leads, so
    it is flagged as a place this script cannot place; one in another folder, a folder inside the work
    directory among them, did not run in the work directory itself. Review 7: a file URL that names
    `localhost` names this host, and one that names another host names no folder here, so this script
    cannot place it either. Review 9: a file URL read as a URL drops a query and a fragment and decodes
    its escapes, so `file://<work directory>#/../..` read as the work directory; Codex may write a path
    into the URL as it stands, so a URL with a `?`, `#` or `%` names one of two folders, and this script
    cannot place it. A plain path holds no URL syntax, so a `#` there belongs to a folder's name."""
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
     "no permission to read it": lambda: (shutil.copyfile(parent, kept), kept.chmod(0))}[kind]()
    with pytest.raises(SystemExit, match=f"{why}.*the kept copy is final"):
        acs.audit_run(run, lanes)


@pytest.mark.parametrize("name", ["rollout-MOCK-parent.jsonl", "attempts.json", ".audit-MOCK-link.part", "MOCK-other"])
@pytest.mark.parametrize("target", ["a part file beside it", "a file elsewhere", "nothing"])
def test_a_link_among_the_kept_files_stops_the_audit_before_it_removes_anything(area, name, target):
    """Review 11: a kept log could be a link to a file in the same folder that takes the name of a part
    file. The next run removed that file as a part file and lost the only copy of the log once the lane
    pruned its own. `git` holds no link here, and what one leads to lies outside the record, so a link
    anywhere in `codex-sessions` stops the script, by name, before it removes or reads anything."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    folder = run / "codex-sessions"
    folder.mkdir()
    elsewhere = run.parent / "MOCK-elsewhere"
    elsewhere.write_text("MOCK bytes\n")
    part = folder / ".audit-aaaaaaaa.part"
    part.write_text("MOCK bytes\n")
    (folder / name).symlink_to({"a part file beside it": part.name, "a file elsewhere": elsewhere,
                                "nothing": folder / "MOCK-gone"}[target])
    before = sorted(os.listdir(folder))
    with pytest.raises(SystemExit, match=rf"{re.escape(name)} is a link; the kept copies are final"):
        acs.audit_run(run, lanes)
    assert sorted(os.listdir(folder)) == before
    assert part.read_text() == "MOCK bytes\n" and elsewhere.read_text() == "MOCK bytes\n"


def test_a_kept_file_with_a_second_name_loses_only_the_part_files_name(area):
    """A process that dies between its two steps (`_create`) leaves one file under two names, the part
    file's and the kept copy's. The next run removes the part file's name and the bytes stay."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    assert acs.audit_run(run, lanes)["passed"]
    folder = run / "codex-sessions"
    kept = folder / parent.name
    os.link(kept, folder / ".audit-MOCK1234.part")
    data = kept.read_bytes()
    parent.unlink()
    assert acs.audit_run(run, lanes)["passed"]
    assert kept.read_bytes() == data and not (folder / ".audit-MOCK1234.part").exists()


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


@pytest.mark.skipif(os.geteuid() == 0, reason="root lists any folder")
def test_a_kept_folder_this_script_cannot_list_stops_the_audit(area):
    """Review 8: `glob` read a `codex-sessions` it could not list as one that keeps no log. This script
    lists the folder itself, and one it cannot list stops it: the kept copies are final."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    assert acs.audit_run(run, lanes)["passed"]
    folder = run / "codex-sessions"
    folder.chmod(0o300)  # it may write in the folder and reach what it holds, but not list it
    try:
        with pytest.raises(SystemExit, match=r"cannot list .*codex-sessions \(PermissionError\); the kept copies"):
            acs.audit_run(run, lanes)
    finally:
        folder.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes in any folder")
@pytest.mark.parametrize("left, why", [
    ("a new log to keep", r"this script cannot keep .*rollout-MOCK-parent\.jsonl as .* \(PermissionError\)"),
    ("a new record of attempts", r"this script cannot write .*attempts\.json \(PermissionError\)"),
    ("only the audit", r"this script cannot write .*audit\.json \(PermissionError\)")])
def test_a_kept_folder_this_script_cannot_write_in_stops_the_audit(area, monkeypatch, left, why):
    """Review 8: in a `codex-sessions` the system will not let this script write in, keeping a new log,
    keeping subfleet's record of attempts or writing the audit stops it with the reason, instead of an
    error from writing, and it leaves the folder as it found it."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    if left == "a new record of attempts":
        with_record(monkeypatch, run, [(f"{JOB}/a1", PARENT, "succeeded")], accepted=f"{JOB}/a1",
                    collected=f"{JOB}/a1")
    folder = run / "codex-sessions"
    if left == "only the audit":
        assert acs.audit_run(run, lanes)["passed"]
    else:
        folder.mkdir()
    before = {name: (folder / name).read_bytes() for name in os.listdir(folder)}
    folder.chmod(0o555)
    try:
        with pytest.raises(SystemExit, match=why):
            acs.audit_run(run, lanes)
    finally:
        folder.chmod(0o755)
    assert {name: (folder / name).read_bytes() for name in os.listdir(folder)} == before


def test_the_audit_is_a_new_file_so_another_name_of_the_old_one_keeps_its_bytes(area):
    """Review 8: a second name of the file at `audit.json` (a hard link to a file outside the run's
    folder, say) took the audit when this script wrote that file over. The script writes the audit to a
    new file and renames it into place, so the other name keeps its bytes. It leaves no part file, and
    the new file has the mode `open` gives one."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    folder = run / "codex-sessions"
    folder.mkdir()
    outside = run.parent / "MOCK-outside.md"
    outside.write_text("MOCK untouched\n")
    os.link(outside, folder / "audit.json")
    report = acs.audit_run(run, lanes)
    assert report["passed"]
    assert outside.read_text() == "MOCK untouched\n"
    assert json.loads((folder / "audit.json").read_text()) == report
    assert sorted(os.listdir(folder)) == ["audit.json", "rollout-MOCK-parent.jsonl"]
    mask = os.umask(0)
    os.umask(mask)
    assert (folder / "audit.json").stat().st_mode & 0o777 == 0o666 & ~mask


def test_a_new_file_is_written_through_nothing_and_whole_or_not_at_all(tmp_path):
    """`_create` stops at anything at its path, a link included; `_replace` takes the place of what
    stood at its path without writing through it. A write that fails leaves no part of the data and no
    part file (an object `write` refuses stands in for a failure part way)."""
    target = tmp_path / "MOCK-target.md"
    target.write_text("MOCK untouched\n")
    link = tmp_path / "MOCK-link.json"
    link.symlink_to(target)
    with pytest.raises(FileExistsError):
        acs._create(link, b"MOCK new\n")
    acs._replace(link, b"MOCK new\n")
    assert target.read_text() == "MOCK untouched\n"
    assert not link.is_symlink() and link.read_bytes() == b"MOCK new\n"
    for write, path in ((acs._create, tmp_path / "MOCK-new.json"), (acs._replace, link)):
        with pytest.raises(TypeError):
            write(path, object())
    assert link.read_bytes() == b"MOCK new\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["MOCK-link.json", "MOCK-target.md"]



def test_a_write_whose_last_bytes_fail_as_the_file_closes_leaves_nothing(tmp_path, monkeypatch):
    """A file takes its last buffered bytes when it closes, and that can fail (a full disk, say). Then
    `_create` leaves no file and `_replace` leaves the old one, and neither leaves a part file."""
    real = os.fdopen

    class FailsAsItCloses:
        def __init__(self, fh):
            self.fh = fh

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.fh.close()
            raise OSError(errno.ENOSPC, "MOCK: no space left for the last bytes")

        def write(self, data):
            return self.fh.write(data)

        def flush(self):
            return self.fh.flush()

        def fileno(self):
            return self.fh.fileno()

    monkeypatch.setattr(acs.os, "fdopen", lambda fd, mode: FailsAsItCloses(real(fd, mode)))
    old = tmp_path / "MOCK-old.json"
    old.write_text("MOCK old\n")
    with pytest.raises(OSError, match="MOCK: no space"):
        acs._create(tmp_path / "MOCK-new.json", b"MOCK new\n")
    with pytest.raises(OSError, match="MOCK: no space"):
        acs._replace(old, b"MOCK new\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["MOCK-old.json"]
    assert old.read_text() == "MOCK old\n"


def test_a_part_file_the_system_will_not_give_its_name_goes(tmp_path, monkeypatch):
    """When the system refuses the link or the rename that gives a part file its name, `_create` leaves
    no file and `_replace` leaves the old one, and neither leaves its part file."""
    def refuses(*args):
        raise PermissionError(errno.EPERM, "MOCK: not permitted")

    for name in ("link", "replace"):
        monkeypatch.setattr(acs.os, name, refuses)
    old = tmp_path / "MOCK-old.json"
    old.write_text("MOCK old\n")
    with pytest.raises(PermissionError, match="MOCK: not permitted"):
        acs._create(tmp_path / "MOCK-new.json", b"MOCK new\n")
    with pytest.raises(PermissionError, match="MOCK: not permitted"):
        acs._replace(old, b"MOCK new\n")
    assert sorted(p.name for p in tmp_path.iterdir()) == ["MOCK-old.json"]
    assert old.read_text() == "MOCK old\n"


def test_a_new_file_reaches_the_disk_before_it_takes_its_name(tmp_path, monkeypatch):
    """Review 9: each write syncs its part file, with every byte in it, to the disk (fsync) before the file
    takes its name, by a link (`_create`) or a rename (`_replace`)."""
    calls, sizes = [], []
    for name in ("link", "replace"):
        monkeypatch.setattr(acs.os, name, lambda *args, real=getattr(os, name), name=name: (
            calls.append(name), real(*args))[1])

    def fsync(fd, real=os.fsync):
        calls.append("fsync")
        sizes.append(os.fstat(fd).st_size)
        return real(fd)

    monkeypatch.setattr(acs.os, "fsync", fsync)
    acs._create(tmp_path / "MOCK-new.json", b"MOCK new\n")
    acs._replace(tmp_path / "MOCK-new.json", b"MOCK newer\n")
    assert calls == ["fsync", "link", "fsync", "replace"]
    assert sizes == [len(b"MOCK new\n"), len(b"MOCK newer\n")]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["MOCK-new.json"]


# A child process that runs `audit_run` on a MOCK run and dies (SIGKILL) part way through writing the
# first file whose name, or whose part file's final name, holds `target`, whether the script opens it
# with `os.open` (as `tempfile` does), `open` or `Path.open`: half the bytes on the disk, then gone, as
# `kill -9`, the system's out-of-memory killer or a crash would leave it. It patches its own `os`, `io`,
# `builtins` and `_part_file`, so only it dies.
DIES_PART_WAY = """
import builtins, importlib.util, io, os, signal, sys
from pathlib import Path
script, run, lanes, target = sys.argv[1:]
spec = importlib.util.spec_from_file_location("audit_codex_sessions", script)
acs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acs)
names, real_open, real_io_open, real_part_file, writing = {}, os.open, io.open, acs._part_file, [""]


def part_file(path, data):
    writing[0] = path.name
    return real_part_file(path, data)


def opened(path, flags, *args, **kwargs):
    fd = real_open(path, flags, *args, **kwargs)
    names[fd] = writing[0] + os.path.basename(path)
    return fd


class DiesPartWay:
    def __init__(self, fh, name):
        self.fh, self.name = fh, name

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fh.close()

    def __getattr__(self, attr):
        return getattr(self.fh, attr)

    def write(self, data):
        if target in self.name:
            self.fh.write(data[:len(data) // 2])
            self.fh.flush()
            os.kill(os.getpid(), signal.SIGKILL)
        return self.fh.write(data)


def opened_file(file, mode="r", *args, **kwargs):
    fh = real_io_open(file, mode, *args, **kwargs)
    if not any(c in mode for c in "wxa+"):
        return fh
    return DiesPartWay(fh, names.get(file, "") if isinstance(file, int) else os.path.basename(os.fspath(file)))


os.open, io.open, builtins.open, acs._part_file = opened, opened_file, opened_file, part_file
acs.audit_run(Path(run), Path(lanes))
"""


@pytest.mark.parametrize("target", ["rollout-MOCK-helper", "audit.json"])
def test_a_run_that_dies_part_way_through_a_write_leaves_nothing_at_the_files_name(area, target):
    """Review 9: `_create` wrote a kept copy at its final path, so a run killed part way through left a cut
    copy there, and later runs took it as final. Once the lane pruned its logs, a sub-agent's violation
    past the cut was gone and the run passed. Each write now goes to a part file that takes the file's
    name only once whole, so a death part way leaves the part file and nothing at the name, and a death
    while it writes the audit leaves the old one. The next run removes the part file and keeps the whole
    log, and after the lane prunes its logs the violation still fails the run."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir)
    helper = write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
                       items=[search("MOCK helper query"), command(f"cat {acs.ROOT / 'README.md'}", workdir)])
    folder = run / "codex-sessions"
    if target == "audit.json":
        assert not acs.audit_run(run, lanes)["passed"]
    before = {name: (folder / name).read_bytes() for name in os.listdir(folder)} if folder.exists() else {}
    child = subprocess.Popen([sys.executable, "-c", DIES_PART_WAY, acs.__file__, str(run), str(lanes), target],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    _, err = child.communicate(timeout=300)
    assert child.returncode == -signal.SIGKILL, err
    parts = [name for name in os.listdir(folder) if acs.PART.fullmatch(name)]
    assert len(parts) == 1
    after = {name: (folder / name).read_bytes() for name in os.listdir(folder) if name not in parts}
    if target == "audit.json":
        assert after == before
    else:
        assert after == {parent.name: parent.read_bytes()}
    for pruned in (False, True):
        if pruned:
            parent.unlink()
            helper.unlink()
        report = acs.audit_run(run, lanes)
        assert not report["passed"] and report["violations"] == 1
        assert sorted(os.listdir(folder)) == sorted(["audit.json", parent.name, helper.name])


def test_a_part_file_a_run_left_is_removed_and_one_this_script_cannot_remove_stops_it(area, monkeypatch):
    """Review 9: a run that died part way through a write left its part file in `codex-sessions`, where
    later runs passed it by. The next run removes each file named as this script names its part files,
    and leaves any other; a part file it cannot remove stops it, by name."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    folder = run / "codex-sessions"
    folder.mkdir()
    for name in (".audit-MOCK1234.part", ".audit-MOCK\n5678.part", ".audit.json.MOCK1234.part", ".MOCK-notes.part",
                 "MOCK-audit.json.part", ".audit-MOCK1234"):
        (folder / name).write_text("MOCK part\n")
    assert acs.audit_run(run, lanes)["passed"]
    assert sorted(os.listdir(folder)) == [".MOCK-notes.part", ".audit-MOCK1234", ".audit.json.MOCK1234.part",
                                          "MOCK-audit.json.part", "audit.json", "rollout-MOCK-parent.jsonl"]
    stuck = folder / ".audit-MOCK5678.part"
    stuck.write_text("MOCK part\n")
    real = os.unlink

    def unlink(path, *args, **kwargs):
        if Path(path) == stuck:
            raise PermissionError(errno.EPERM, "MOCK: not permitted", str(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(acs.os, "unlink", unlink)
    with pytest.raises(SystemExit, match=r"this script cannot remove .*/\.audit-MOCK5678\.part, a part file a "
                                         r"run of it left \(PermissionError\)"):
        acs.audit_run(run, lanes)


@pytest.mark.parametrize("name", ["rollout-" + "M" * 241 + ".jsonl", "rollout-MOCK\nparent.jsonl"],
                         ids=["every byte a name can hold", "a line feed"])
def test_a_log_is_kept_whatever_its_name_and_its_part_file_goes(area, name):
    """Review 10: a part file's name held the kept file's, so a log whose name took more than 240 bytes
    could not be kept, and a part file whose name held a line feed stayed for good. A part file's name
    now leaves out the kept file's."""
    lanes, run, workdir = area
    log = write_log(lanes, name, root_meta(workdir), items=[search("MOCK main query")])
    assert acs.audit_run(run, lanes)["passed"]
    folder = run / "codex-sessions"
    assert sorted(os.listdir(folder)) == sorted(["audit.json", name])
    assert (folder / name).read_bytes() == log.read_bytes()


@given(name=st.text(st.characters(blacklist_characters="/\x00"), min_size=1, max_size=40))
def test_a_part_file_never_goes_by_the_name_of_a_file_this_script_keeps(name):
    """Property: the removal of part files can reach neither a kept log nor a record, whatever the log's
    name, and it reaches each name `_part_file` can give."""
    assert not any(acs.PART.fullmatch(kept) for kept in (f"rollout-{name}.jsonl", "audit.json", "attempts.json"))
    assert acs.PART.fullmatch(f".audit-{name}.part")


def test_a_part_file_takes_the_name_the_removal_looks_for(tmp_path):
    part = acs._part_file(tmp_path / ("rollout-" + "M" * 241 + ".jsonl"), b"MOCK\n")
    assert acs.PART.fullmatch(os.path.basename(part))


@pytest.mark.parametrize("linked", ["the run", "runs"])
def test_a_link_in_place_of_a_run_or_of_runs_stops_the_script_before_it_writes(area, linked):
    """Review 10: the script stopped at a link in place of `codex-sessions`, but a link in place of the
    run took its writes wherever it led, outside `runs/`."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    place = run if linked == "the run" else run.parent
    outside = place.with_name("MOCK-outside")
    place.rename(outside)
    place.symlink_to(outside)
    before = sorted(str(p) for p in outside.rglob("*"))
    with pytest.raises(SystemExit, match=rf"{re.escape(str(place))} is a link"):
        acs.audit_run(run, lanes)
    assert sorted(str(p) for p in outside.rglob("*")) == before


@pytest.mark.parametrize("label", ["sol-1/../sol-1", "../sol-1", "..", ".", "", "sol-1/MOCK", "./../sol-1", "/", "//",
                                   "///", "/MOCK", "//MOCK", "sol-1/.."], ids=repr)
def test_a_label_that_is_not_one_folder_name_stops_the_script_before_it_writes(area, label):
    """Review 11: a label is the name of a folder in `runs/`. One spelled as a path led `audit_run` out of
    `runs/` or past its look for a link, which reads only the last names on a path."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    with pytest.raises(SystemExit, match="names no run"):
        acs.main([label, "--lanes", str(lanes)])
    assert not (run / "codex-sessions").exists()


@pytest.mark.parametrize("linked", ["the run", "runs"])
def test_a_label_spelled_as_a_path_cannot_pass_a_link(area, linked):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    place = run if linked == "the run" else run.parent
    outside = place.with_name("MOCK-outside")
    place.rename(outside)
    place.symlink_to(outside)
    before = sorted(str(p) for p in outside.rglob("*"))
    with pytest.raises(SystemExit, match="names no run"):
        acs.main(["sol-1/../sol-1", "--lanes", str(lanes)])
    assert sorted(str(p) for p in outside.rglob("*")) == before


@pytest.mark.parametrize("label", ["sol-1", "sol-1/", "./sol-1", "sol-1/.", "sol-1//"], ids=repr)
def test_a_label_may_spell_a_run_folders_name_as_a_path_to_it_from_runs(area, label, capsys):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    assert acs.main([label, "--lanes", str(lanes)]) == 0
    assert capsys.readouterr().out.startswith("sol-1: ok;")
    assert (run / "codex-sessions" / "audit.json").is_file()


def test_a_link_among_the_runs_stops_the_script_with_no_labels(area):
    lanes, run, workdir = area
    (run.parent / "MOCK-link").symlink_to(run)
    with pytest.raises(SystemExit, match=r"MOCK-link is a link"):
        acs.codex_runs()


@pytest.mark.skipif(os.geteuid() == 0, reason="root searches any folder")
def test_a_kept_folder_this_script_cannot_search_stops_the_audit(area):
    """Review 9: in a `codex-sessions` this script may list but not search, it read every entry as absent
    and stopped with the wrong reason ("cannot keep", "cannot write"), though the files were there. It
    now stops at the first file it looks for, by name, and leaves the folder as it found it."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    assert acs.audit_run(run, lanes)["passed"]
    folder = run / "codex-sessions"
    before = {name: (folder / name).read_bytes() for name in os.listdir(folder)}
    folder.chmod(0o600)  # it may list the folder, but not reach what it holds
    try:
        with pytest.raises(SystemExit, match=r"this script cannot look for .*codex-sessions/audit\.json "
                                             r"\(PermissionError\)"):
            acs.audit_run(run, lanes)
    finally:
        folder.chmod(0o755)
    assert {name: (folder / name).read_bytes() for name in os.listdir(folder)} == before


def a_folder_whose_path_takes(base: Path, length: int) -> Path:
    """A new folder below `base` whose path takes `length` bytes, made of names of at most 200 bytes."""
    q, r = divmod(length - len(os.fsencode(base)), 201)  # 201: a name and the separator before it
    sizes = [200] * (q - 1) + [100, 100] if r == 1 else [200] * q + ([r - 1] if r else [])
    path = base.joinpath(*("d" * size for size in sizes))
    path.mkdir(parents=True)
    assert len(os.fsencode(path)) == length
    return path


@pytest.mark.parametrize("name, room", [("attempts.json", 13), ("rollout-MOCK-parent.jsonl", 20)])
def test_a_kept_file_this_script_cannot_look_up_stops_the_audit(area, tmp_path, name, room):
    """A kept file this script cannot look up stops the audit, by name, and leaves the run as it was. A
    link in `codex-sessions` and a folder this script cannot search stop the audit before it looks for a
    kept file, so what remains is a lookup that fails another way: here, a path past the system's limit,
    where the audit's own path fits and the kept file's does not. `Path.exists` raises on such a path
    before Python 3.14, and from 3.14 on reads it as absent."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    limit = os.pathconf(tmp_path, "PC_PATH_MAX")
    deep = a_folder_whose_path_takes(tmp_path / "MOCK-deep", limit - room - len("/sol-1/codex-sessions")) / "sol-1"
    run.rename(deep)
    folder = deep / "codex-sessions"
    assert len(os.fsencode(folder / "audit.json")) < limit <= len(os.fsencode(folder / name))
    before = sorted(os.listdir(deep))
    with pytest.raises(SystemExit, match=rf"this script cannot look for .*/{re.escape(name)} \(OSError\)"):
        acs.audit_run(deep, lanes)
    assert sorted(os.listdir(deep)) == before


def test_a_link_counts_as_something_there_wherever_it_leads(tmp_path):
    """`_present` reads a link as something there, whether it leads to a file, to nothing or round in a
    loop, and reads a path with nothing at it, or below a file, as nothing there. The audit stops at a link
    at or in `codex-sessions/` before it calls `_present` on that path, so no other test brings it a link."""
    (tmp_path / "MOCK-file").write_text("MOCK\n")
    links = {"MOCK-to-a-file": tmp_path / "MOCK-file", "MOCK-to-nothing": tmp_path / "MOCK-gone",
             "MOCK-loop": tmp_path / "MOCK-loop"}
    for name, target in links.items():
        (tmp_path / name).symlink_to(target)
    assert all(acs._present(tmp_path / name) for name in ("MOCK-file", *links))
    assert not acs._present(tmp_path / "MOCK-gone")
    assert not acs._present(tmp_path / "MOCK-file" / "MOCK-below")


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


def shell_item(item_id: str, text: str) -> dict:
    """A command as `codex exec --json` writes it in a transcript: one string, quoted."""
    return {"id": item_id, "type": "command_execution", "command": text, "aggregated_output": "", "exit_code": 0,
            "status": "completed"}


@pytest.mark.parametrize("program, theirs", [
    ("cd MOCK;pwd", "/bin/zsh -lc 'cd MOCK';pwd"),
    ("echo $MOCK", "/bin/zsh -lc 'echo '$MOCK"),
    ("$(printf MOCK)", '/bin/zsh -lc "$(printf MOCK)"'),
    ("`printf MOCK`", '/bin/zsh -lc "`printf MOCK`"'),
    ("MOCK*", "/bin/zsh -lc MOCK*"),
    ("MOCK?", "/bin/zsh -lc MOCK?"),
    ("[MOCK]", "/bin/zsh -lc [MOCK]"),
    (">MOCK", "/bin/zsh -lc >MOCK"),
    ("<MOCK", "/bin/zsh -lc <MOCK"),
    ("MOCK&", "/bin/zsh -lc MOCK&"),
    ("MOCK|cat", "/bin/zsh -lc MOCK|cat"),
    ("(MOCK)", "/bin/zsh -lc (MOCK)"),
    ("~/MOCK", "/bin/zsh -lc ~/MOCK"),
    ("{a,b}", "/bin/zsh -lc {a,b}"),
    ("MOCK#", "/bin/zsh -lc MOCK#"),
], ids=lambda value: value)
def test_a_transcript_command_a_shell_reads_otherwise_fails(area, program, theirs):
    """Review 10: the check compared `shlex.split`'s words, which read `;`, `$`, `*` or `>` outside quotes as
    plain text: `/bin/zsh -lc 'cd MOCK';pwd` split as the log's `/bin/zsh -lc 'cd MOCK;pwd'` did, though
    the first prints another folder. Each pair here splits alike and runs otherwise."""
    lanes, run, workdir = area
    assert shlex.split(shlex.join(["/bin/zsh", "-lc", program])) == shlex.split(theirs)
    add_parent(lanes, workdir, spawned=(), items=[command(program, workdir, "MOCK-1")])
    write_transcript(run, PARENT, [shell_item("MOCK-1", theirs)])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == ['"MOCK-1"']
    assert any("record different calls" in flag for flag in report["flags"]) and not report["passed"]


def test_a_transcript_command_that_runs_what_the_log_keeps_as_one_word_fails(area):
    """Review 10: a log that keeps the words `echo` and `MOCK;echo` and a transcript that writes
    `echo MOCK;echo` split alike and print different lines."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[{**command("MOCK", workdir, "MOCK-1"), "command": ["echo", "MOCK;echo"]}])
    write_transcript(run, PARENT, [shell_item("MOCK-1", "echo MOCK;echo")])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == ['"MOCK-1"'] and not report["passed"]


@pytest.mark.parametrize("program, theirs", [
    ("echo MOCK", "'/bin/zsh' '-lc' 'echo MOCK'"),
    ("echo MOCK", '"/bin/zsh" "-lc" "echo MOCK"'),
    ("echo MOCK", "/bin/zsh -lc echo\\ MOCK"),
    ("echo MOCK", "  /bin/zsh\t-lc   'echo MOCK'  "),
    ('echo "MOCK"', "/bin/zsh -lc 'echo \"MOCK\"'"),
    ('echo "MOCK"', '/bin/zsh -lc "echo \\"MOCK\\""'),
    ("echo 'MOCK'", """/bin/zsh -lc 'echo '"'"'MOCK'"'"''"""),
    ("echo $MOCK", '/bin/zsh -lc "echo \\$MOCK"'),
    ("echo `MOCK`", '/bin/zsh -lc "echo \\`MOCK\\`"'),
    ("echo \\MOCK", '/bin/zsh -lc "echo \\\\MOCK"'),
    ("echo \\MOCK", '/bin/zsh -lc "echo \\MOCK"'),
], ids=lambda value: value)
def test_a_transcript_may_quote_a_command_any_way_a_shell_reads_the_same(area, program, theirs):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[command(program, workdir, "MOCK-1")])
    write_transcript(run, PARENT, [shell_item("MOCK-1", theirs)])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == [] and not any("different calls" in f for f in report["flags"])


@pytest.mark.parametrize("program", ["echo MOCK", "cat MOCK.txt", "cat /etc/hosts", "echo $HOME", "cd /tmp; ls",
                                     "ls | wc -l", "echo 'MOCK a' > MOCK", 'printf "%s" "$(cat /etc/hosts)"',
                                     "`echo cat` /etc/hosts"])
def test_a_program_in_single_or_double_quotes_reads_the_same_to_the_audit(tmp_path, program):
    """Differential: a shell's `-lc` program reads as the same words in single quotes and in double quotes,
    and `i86 audit`, which reads a transcript's own spelling, reaches the same verdict on each."""
    double = '/bin/zsh -lc "' + re.sub(r'(["\\$`])', r"\\\1", program) + '"'
    assert acs._words(shlex.join(["/bin/zsh", "-lc", program])) == acs._words(double) == ["/bin/zsh", "-lc", program]
    verdicts = []
    for name, text in (("single", shlex.join(["/bin/zsh", "-lc", program])), ("double", double)):
        (tmp_path / name).mkdir()
        write_transcript(tmp_path / name, PARENT, [shell_item("MOCK-1", text)])
        result = audit.audit_transcript(tmp_path / name / "transcript.jsonl", str(tmp_path))
        verdicts.append({key: [(call["tool"], call.get("reason")) for call in result[key]]
                         for key in ("violations", "suspect", "local_calls")})
    assert verdicts[0] == verdicts[1]


def test_a_spelling_the_audit_cannot_read_stays_suspect_though_it_counts_as_one_command(area):
    """Review 11: `/bin/zsh -lc echo\\ MOCK` gives a shell the words of the log's `/bin/zsh -lc 'echo MOCK'`,
    so the check counts the two as one command. `i86 audit` reads the transcript's own spelling and has
    no rule for that backslash, so it lists a suspect call, and `simulate` counts that call."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[command("echo MOCK", workdir, "MOCK-1")])
    write_transcript(run, PARENT, [shell_item("MOCK-1", "/bin/zsh -lc echo\\ MOCK")])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == [] and report["passed"]
    assert [call["tool"] for call in audit.audit_transcript(run / "transcript.jsonl", workdir)["suspect"]] == ["shell"]


@pytest.mark.parametrize("theirs", ["'%MOCK'", '"%MOCK"', "\\%MOCK", "''%MOCK"])
def test_a_transcript_that_quotes_a_first_word_a_shell_reads_as_a_job_fails(area, theirs):
    """Review 11: `shlex.join` leaves `%MOCK` bare, and zsh reads that as a job and `'%MOCK'` as a program."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[{**command("MOCK", workdir, "MOCK-1"), "command": ["%MOCK"]}])
    write_transcript(run, PARENT, [shell_item("MOCK-1", theirs)])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == ['"MOCK-1"'] and not report["passed"]


@pytest.mark.parametrize("ours, theirs", [
    ([1, 2], [2, 1]),
    ([1, 2, 3], [2, 3, 1]),
    ([1, 2, 1], [1, 1, 2]),
], ids=str)
def test_a_transcript_that_records_the_same_calls_in_another_order_fails(area, ours, theirs):
    """Review 10: the check compared each id's calls alone, so a transcript passed with the log's calls in
    any order across ids, though order changes what the audit reads: a script run before it is written
    reads nothing it should not, and run after, whatever it now holds."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[command(f"echo MOCK-{i}", workdir, f"MOCK-{i}") for i in ours])
    write_transcript(run, PARENT, [shell_item(f"MOCK-{i}", shlex.join(["/bin/zsh", "-lc", f"echo MOCK-{i}"]))
                                   for i in theirs])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["only_in_log"] == report["transcript_check"]["only_in_transcript"] == []
    assert report["transcript_check"]["different"] and not report["passed"]


def test_a_transcript_that_records_the_calls_in_the_logs_order_passes(area):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[search("MOCK a"), command("echo MOCK-1", workdir, "MOCK-1"), search("MOCK b"),
                                                  command("echo MOCK-1", workdir, "MOCK-1")])
    write_transcript(run, PARENT, [web("MOCK a"), shell_item("MOCK-1", "/bin/zsh -lc 'echo MOCK-1'"), web("MOCK b"),
                                   shell_item("MOCK-1", "/bin/zsh -lc 'echo MOCK-1'")])
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"]["different"] == [] and not report["flags"]


def test_a_call_on_one_side_alone_does_not_read_as_a_move(area):
    """A call that only the log or only the transcript holds fails under its own name, and leaves the
    calls around it in order."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[search("MOCK a"), search("MOCK log only"), search("MOCK b")])
    write_transcript(run, PARENT, [web("MOCK a"), web("MOCK b"), web("MOCK transcript only")])
    check = acs.audit_run(run, lanes)["transcript_check"]
    assert check["different"] == [] and check["only_in_log"] and check["only_in_transcript"]


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


@pytest.mark.parametrize("completes", [True, False], ids=["completes", "never completes"])
@pytest.mark.parametrize("kind", ["item.started", "item.updated"])
def test_a_start_or_an_update_whose_line_holds_a_call_fails(area, kind, completes):
    """Review 8: `audit` audits a tool use in a start's or an update's `message` there and then, as a call
    of its own, and pairs the line's item and that call with a completion that covers them. The check
    paired them alike but compared no such call, so a message's start whose line held the search's own
    call passed beside the completed search, though `audit` read two calls from the transcript and one
    from the log. Such a line now counts, by its number and once, as one only the transcript holds,
    whether or not its item completes."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    item = web("MOCK main query")
    call = next(acs.audit._tool_calls({"type": "item.completed", "item": item}))[1]
    quiet = item["id"] if completes else "MOCK-never-completes"
    lines = [{"type": "thread.started", "thread_id": PARENT}, {"type": "turn.started"},
             {"type": kind, "item": {"id": quiet, "type": "agent_message", "text": "MOCK"},
              "message": {"content": [{"type": "tool_use", "name": "web_search", "input": call}]}},
             {"type": "item.completed", "item": item}, {"type": "turn.completed"}]
    (run / "transcript.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    assert acs.audit.audit_transcript(run / "transcript.jsonl", workdir)["tool_calls"] >= 2
    report = acs.audit_run(run, lanes)
    assert report["transcript_check"] == {"items": 1, "only_in_transcript": ["line 3"], "only_in_log": [],
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
    ("a link in a loop", "not a regular file"),
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
     "a link in a loop": lambda: odd.symlink_to(odd),
     "no permission to read it": lambda: (odd.write_text("{}\n"), odd.chmod(0))}[kind]()
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [f"rollout-MOCK-odd.jsonl: this script cannot open it ({why})"]
    assert not report["passed"]


def test_a_log_a_link_leads_to_is_read(area):
    """A lane's log may be a link to a regular file elsewhere: the script reads and keeps the file it
    leads to, as it reads any log."""
    lanes, run, workdir = area
    parent = add_parent(lanes, workdir, spawned=())
    elsewhere = lanes.parent / "MOCK-elsewhere" / parent.name
    elsewhere.parent.mkdir()
    parent.rename(elsewhere)
    parent.symlink_to(elsewhere)
    report = acs.audit_run(run, lanes)
    assert report["passed"] and report["flags"] == []
    assert (run / "codex-sessions" / parent.name).read_bytes() == elsewhere.read_bytes()


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


@pytest.mark.skipif(os.geteuid() == 0, reason="root lists any folder")
@pytest.mark.parametrize("folder, shown", [
    ("", "the lanes folder"), ("codex-10", "codex-10/sessions"), ("codex-10/sessions", "codex-10/sessions"),
    ("codex-10/sessions/2026", "codex-10/sessions/2026"), ("codex-10/sessions/2026/11", "codex-10/sessions/2026/11"),
    ("codex-10/sessions/2026/11/03", "codex-10/sessions/2026/11/03")])
def test_a_folder_of_the_lanes_this_script_cannot_list_is_flagged(area, folder, shown):
    """Review 8: `glob` passes over a folder it cannot list without a word, so a second main thread whose
    log sat in one went unread and the run passed. The listing flags each folder on the way to the logs
    that it cannot list, by its path under the lanes folder, and the run fails."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    extra = write_log(lanes, "rollout-MOCK-extra.jsonl", root_meta(workdir, "MOCK-extra"),
                      items=[search("MOCK extra query")])
    day = lanes / "codex-10" / "sessions" / "2026" / "11" / "03"
    day.mkdir(parents=True)
    extra.rename(day / extra.name)
    (lanes / folder).chmod(0)
    try:
        report = acs.audit_run(run, lanes)
    finally:
        (lanes / folder).chmod(0o755)
    assert (f"{shown}: this script cannot list this folder (PermissionError), and a log in it could hold one of "
            "the run's threads") in report["flags"]
    assert not report["passed"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root searches any folder")
def test_a_log_in_a_lanes_folder_this_script_may_list_but_not_search_is_flagged_with_the_reason(area):
    """Review 9: in a lanes folder this script may list but not search, it found each log's name and then
    flagged the log as "not a regular file". The flag now gives the reason the system gave."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    extra = write_log(lanes, "rollout-MOCK-extra.jsonl", root_meta(workdir, "MOCK-extra"),
                      items=[search("MOCK extra query")])
    day = lanes / "codex-10" / "sessions" / "2026" / "11" / "03"
    day.mkdir(parents=True)
    extra.rename(day / extra.name)
    day.chmod(0o600)
    try:
        report = acs.audit_run(run, lanes)
    finally:
        day.chmod(0o755)
    assert report["flags"] == ["rollout-MOCK-extra.jsonl: this script cannot open it (PermissionError)"]
    assert not report["passed"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root searches any folder")
def test_a_run_folder_or_answer_this_script_cannot_look_for_stops_it_by_name(area):
    """Review 9: with no labels, the script looks in each folder of `runs/` for a meta.json and an answer.
    In a folder it may not search, `Path.exists` raised before Python 3.14, and from 3.14 on reads
    nothing there, so the script would pass over a Codex run without a word. It stops, by name, on every
    Python, and so does an answer it cannot look for."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    other = run.parent / "sol-2"
    other.mkdir()
    (other / "meta.json").write_text(json.dumps({"label": "sol-2", "lane_id": "codex-9"}))
    for mode in (0o000, 0o600):
        other.chmod(mode)
        try:
            with pytest.raises(SystemExit, match=r"cannot look for .*runs/sol-2/meta\.json \(PermissionError\)"):
                acs.main(["--lanes", str(lanes)])
        finally:
            other.chmod(0o755)
    hidden = run.parent.parent / "MOCK-hidden"
    hidden.mkdir()
    (hidden / "response.md").write_text("MOCK answer\n")
    (other / "response.md").symlink_to(hidden / "response.md")
    hidden.chmod(0o600)
    try:
        with pytest.raises(SystemExit, match=r"cannot look for .*runs/sol-2/response\.md \(PermissionError\)"):
            acs.main(["--lanes", str(lanes)])
    finally:
        hidden.chmod(0o755)
    assert not (other / "codex-sessions").exists()


@pytest.mark.parametrize("kind", ["missing", "a folder", "a pipe", "not JSON", "a list", pytest.param(
    "no permission to read it", marks=pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file"))])
def test_a_runs_meta_json_this_script_cannot_read_stops_it_by_name(area, kind):
    """Review 9: a run named on the command line whose meta.json is missing, is no regular file (a pipe
    would block), does not parse or holds no object stopped the script with a traceback, or never
    returned. It stops, by name, before it writes anything, and so does a collected run's meta.json when
    the script audits every run: with no labels, it passed over one that was no regular file."""
    lanes, run, workdir = area
    meta = run / "meta.json"
    text = meta.read_text()
    meta.unlink()
    {"missing": lambda: None, "a folder": meta.mkdir, "a pipe": lambda: os.mkfifo(meta),
     "not JSON": lambda: meta.write_text("{MOCK"), "a list": lambda: meta.write_text("[]"),
     "no permission to read it": lambda: (meta.write_text(text), meta.chmod(0o000))}[kind]()
    match = r"this script cannot read .*sol-1/meta\.json as a run's record"
    with pytest.raises(SystemExit, match=match):
        acs.main(["sol-1", "--lanes", str(lanes)])
    if kind != "missing":  # with no labels, a folder without a meta.json holds no run
        with pytest.raises(SystemExit, match=match):
            acs.main(["--lanes", str(lanes)])
    assert not (run / "codex-sessions").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root searches any folder")
def test_a_transcript_this_script_cannot_look_at_records_no_thread(area):
    """Review 9: a transcript that is a link into a folder this script may not search raised an error from
    `Path.is_file` before Python 3.14. The script reads it as recording no thread, on every Python, and
    the run fails."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    hidden = run.parent.parent / "MOCK-hidden"
    hidden.mkdir()
    (run / "transcript.jsonl").rename(hidden / "transcript.jsonl")
    (run / "transcript.jsonl").symlink_to(hidden / "transcript.jsonl")
    hidden.chmod(0o600)
    try:
        report = acs.audit_run(run, lanes)
    finally:
        hidden.chmod(0o755)
    assert report["flags"] == [f"the transcript records no thread whose id this script can read, not the collected "
                               f"main thread {PARENT}"]
    assert not report["passed"]


def lane_tree(data, folder: Path, parts: tuple, spare: list[Path]) -> None:
    """Fill `folder` with what Hypothesis draws for the rest of a log's path (`parts`): folders, files,
    links to folders elsewhere (each in a folder of `spare`'s), to nothing and to themselves, hidden
    names, and names the logs' pattern matches or nearly matches."""
    part, rest = parts[0], parts[1:]
    if part == "sessions":
        # `glob` goes straight to the name, so on a file system that ignores case it finds `Sessions` too.
        names = [data.draw(st.sampled_from(["sessions", "Sessions"]))]
    elif rest:
        names = data.draw(st.lists(st.sampled_from(["2026", "11", ".MOCK", "MOCK"]), min_size=1, max_size=2,
                                   unique=True))
    else:
        names = data.draw(st.lists(st.sampled_from(["rollout-a.jsonl", "rollout-.jsonl", ".rollout-b.jsonl",
                                                    "ROLLOUT-C.JSONL", "rollout-d.json", "MOCK.jsonl"]),
                                   min_size=1, max_size=3, unique=True))
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        # Folders and files most of the time, so that most trees hold logs.
        kinds = (["folder"] * 8 + ["file", "link to a folder", "link to nothing", "link to itself"] if rest
                 else ["file"] * 3 + ["folder", "link to nothing"])
        kind = data.draw(st.sampled_from(kinds if part != "sessions" else [*kinds, "nothing"]))
        path = folder / name
        if kind == "folder":
            lane_tree(data, path, rest, spare) if rest else path.mkdir()
        elif kind == "file":
            path.write_text("MOCK\n")
        elif kind == "link to a folder":
            target = spare[0] / str(len(spare))
            spare.append(target)
            lane_tree(data, target, rest, spare)
            path.symlink_to(target)
        elif kind == "link to nothing":
            path.symlink_to(folder / "MOCK-gone")
        elif kind == "link to itself":
            path.symlink_to(path)


@settings(deadline=None, max_examples=100)
@given(data=st.data())
def test_the_lanes_listing_finds_what_glob_finds(data):
    """Differential: in folders this script can list, `session_logs` finds the paths `glob` finds (links
    to folders, hidden names and entries of every kind among them) and flags nothing."""
    with tempfile.TemporaryDirectory() as tmp:
        lanes = Path(tmp) / "lanes"
        lane_tree(data, lanes, acs.LOG_PARTS, [Path(tmp) / "elsewhere"])
        found = sorted(lanes.glob("/".join(acs.LOG_PARTS)))
        event(f"glob finds {min(len(found), 3)}{'+' if len(found) > 3 else ''} logs")
        assert acs.session_logs(lanes) == (found, [])


def test_the_lanes_listing_passes_over_loops_and_sorts_what_it_finds(tmp_path, monkeypatch):
    """Fixed cases for the differential above, which its drawn trees reach only now and then. Links in a
    loop, to nothing or to a file name no folder, so `glob` passes over them and this script flags
    nothing. And `os.scandir` yields names in no set order, so the listing sorts the logs it finds:
    here the system lists each folder last name first."""
    lanes = tmp_path / "lanes"
    for lane in ("codex-1", "codex-2"):
        day = lanes / lane / "sessions" / "2026" / "11" / "03"
        day.mkdir(parents=True)
        for name in ("rollout-a.jsonl", "rollout-b.jsonl"):
            (day / name).write_text("MOCK\n")
    (lanes / "codex-loop").symlink_to(lanes / "codex-loop")
    (lanes / "codex-1" / "sessions" / "2027").symlink_to(lanes / "codex-1" / "sessions" / "2027")
    (lanes / "codex-gone").symlink_to(tmp_path / "MOCK-gone")
    (lanes / "codex-file").write_text("MOCK\n")
    found = sorted(lanes.glob("/".join(acs.LOG_PARTS)))
    assert len(found) == 4
    real = os.scandir

    class LastNameFirst:
        def __init__(self, path):
            self.entries = real(path)

        def __enter__(self):
            return iter(sorted(self.entries, key=lambda entry: entry.name, reverse=True))

        def __exit__(self, *exc):
            self.entries.close()

    monkeypatch.setattr(acs.os, "scandir", LastNameFirst)
    assert acs.session_logs(lanes) == (found, [])


def test_lanes_that_hold_no_folder_hold_no_log(tmp_path):
    """A lanes folder that is not there, or a file, holds no log, as `glob` finds none: the audit then
    reads only the kept copies."""
    assert acs.session_logs(tmp_path / "MOCK-gone") == ([], [])
    (tmp_path / "MOCK-file").write_text("MOCK\n")
    assert acs.session_logs(tmp_path / "MOCK-file") == ([], [])


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


@pytest.mark.parametrize("kind", ["a folder", "a pipe"])
def test_a_kept_attempts_file_that_is_not_a_regular_file_stops_the_audit(area, kind):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    kept = run / "codex-sessions" / "attempts.json"
    kept.parent.mkdir()
    {"a folder": kept.mkdir, "a pipe": lambda: os.mkfifo(kept)}[kind]()
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
    """Property: a command the log keeps as words compares equal to any quoting of the same words, and
    reads back as those words. `shlex.join` leaves bare a word that starts with `=`, an `=` in the first
    word, a first word that starts with `%` and a reserved word at the head, which a shell reads otherwise:
    that command stays as written, so a transcript that quotes it fails the check, and here the generator
    leaves them out."""
    def line(cmd):
        return [{"type": "item.completed", "item": {"id": "MOCK", "type": "command_execution", "command": cmd}}]

    assume(argv[0] not in acs.LEADERS and "=" not in argv[0] and not any(word.startswith("=") for word in argv))
    assume(not argv[0].startswith("%"))
    assume(not any(acs._CONTROL.search(word) for word in argv))
    double = " ".join('"' + re.sub(r'(["\\$`])', r"\\\1", word) + '"' for word in argv)
    assert acs._calls(line(shlex.join(argv))) == acs._calls(line(double))
    assert acs._words(shlex.join(argv)) == argv


@pytest.mark.parametrize("command_text, words", [
    ("", []),
    (" \t ", []),
    ("/bin/zsh -lc 'cd MOCK;pwd'", ["/bin/zsh", "-lc", "cd MOCK;pwd"]),
    ("echo 'MOCK a' \"MOCK b\" MOCK\\ c", ["echo", "MOCK a", "MOCK b", "MOCK c"]),
    ("echo '$MOCK' \"\\$MOCK\" \\$MOCK", ["echo", "$MOCK", "$MOCK", "$MOCK"]),
    ('echo "\\`\\"\\\\" "\\MOCK"', ["echo", '`"\\', "\\MOCK"]),
    ("echo '' \"\"", ["echo", "", ""]),
    ("echo MOCK=a MOCK=''", ["echo", "MOCK=a", "MOCK="]),
    ("echo \\=MOCK '='MOCK \"=\"MOCK", ["echo", "=MOCK", "=MOCK", "=MOCK"]),
    ("echo a''=MOCK ''a=MOCK", ["echo", "a=MOCK", "a=MOCK"]),
    ("echo 'MOCK\ta' \"MOCK\tb\" 'MOCK\nc'", ["echo", "MOCK\ta", "MOCK\tb", "MOCK\nc"]),
    ("'MOCK=a' echo", ["MOCK=a", "echo"]),
    ("MOCK\\=a echo", ["MOCK=a", "echo"]),
    ('echo "MOCK\nline"', ["echo", "MOCK\nline"]),
    ("echo a,b:c@d+e%f-g.h/i_j]", ["echo", "a,b:c@d+e%f-g.h/i_j]"]),
    ("echo 0 a1 9", ["echo", "0", "a1", "9"]),
    ("echo \u00e9 \u00a0 \u2028", ["echo", "\u00e9", "\u00a0", "\u2028"]),
    ("echo %MOCK %", ["echo", "%MOCK", "%"]),
    ("a%b echo", ["a%b", "echo"]),
    ("'' %MOCK", ["", "%MOCK"]),
], ids=repr)
def test_a_command_of_words_alone_reads_as_its_words(command_text, words):
    assert acs._words(command_text) == words


@pytest.mark.parametrize("command_text", [
    "echo MOCK;echo", "echo MOCK&", "echo MOCK|cat", "echo >MOCK", "echo <MOCK", "(echo)", "echo $MOCK", "echo `MOCK`",
    'echo "$MOCK"', 'echo "`MOCK`"', "echo MOCK*", "echo MOCK?", "echo [MOCK", "echo ~", "echo {a,b}", "echo #MOCK",
    "echo !MOCK", "echo ^MOCK", "echo MOCK\necho", "echo a\\\nb", 'echo "a\\\nb"', "echo a\rb", "echo a\x01b",
    "echo a\x7fb", "echo a\x85b", "echo 'MOCK", 'echo "MOCK', "echo MOCK\\", "echo =MOCK", "MOCK=a echo", "M=a",
    "M'O'=a echo", "echo a\x00b", "echo 'a\x00b'", "time echo", "'time' echo", "if MOCK", "]] MOCK",
    "echo ''=MOCK", 'echo ""=MOCK', "echo ''''=MOCK", "echo 'a\x01b'", 'echo "a\x7fb"', "echo \\\x01", 'echo "\\\x7f"',
    "echo 'a\rb'", 'echo "a\x1bb"', "echo 'a\x0bb'", "echo 'a\x0cb'", "echo a(b", "echo a)b", "\necho", "echo \nMOCK",
    "echo \n", "%MOCK", "%", "%%", "%+", "%-", "%1", "%MOCK echo", "'%MOCK'", '"%MOCK"', "\\%MOCK", "''%MOCK", "%'MOCK'",
], ids=repr)
def test_a_command_that_holds_anything_but_words_stays_as_written(command_text):
    assert acs._words(command_text) == command_text


SHELLS = {"zsh": ["/bin/zsh", "-f", "-c"], "bash": ["/bin/bash", "--norc", "--noprofile", "-c"]}
# Letters that name no command, so what a misread piece runs is nothing, in a folder of its own. The first
# list reads as words in most orders, so the property reaches the shells often; the second adds pieces that
# keep most commands as written.
WORD_PIECES = ["a", "b", " ", "  ", "\t", "%", ",", ":", "+", "-", ".", "/", "@", "]", "é", " ", " ", "'a b'",
               '"a b"', "'a;b'", '"a;b"', "\\ ", '\\"', "\\$", "\\`", "\\\\", "\\a", "''", '""', '"\\a"', '"\\$"', '"\\`"', '"\\\\"',
               '"\\""', "'$a'", '"\n"', "'\n'", "a=b", "=a"]
PIECES = [*WORD_PIECES, "'", '"', "\\", "$", "`", ";", "&", "|", "<", ">", "(", ")", "*", "?", "[", "~", "{", "}", "#", "!", "^",
          "=", "\n", "\r", "\x01", "\x7f"]


@pytest.mark.parametrize("shell", sorted(SHELLS))
@given(command_text=st.one_of(st.lists(st.sampled_from(WORD_PIECES), max_size=8),
                              st.lists(st.sampled_from(PIECES), max_size=8)).map("".join))
@settings(max_examples=400, suppress_health_check=[HealthCheck.filter_too_much])
@example(command_text="a 'b c' \"d\\$e\" f\\ g")
@example(command_text="a ''=b")  # zsh reads `''=b` as `=b`, and looks for a command named b.
@example(command_text='"\\\x7f"')  # bash 3.2 reads this with a mark of its own in the word.
@example(command_text="'\r'")
def test_the_shells_read_the_words_this_script_reads(shell, command_text):
    """Differential: wherever this script reads a command as words, zsh and bash read those words from
    it, as a function's arguments, and nothing else."""
    words = acs._words(command_text)
    assume(isinstance(words, list))
    with tempfile.TemporaryDirectory() as folder:
        proc = subprocess.run([*SHELLS[shell], 'args() { for word; do printf "%s\\0" "$word"; done; }; args ' + command_text], cwd=folder,
                              capture_output=True, stdin=subprocess.DEVNULL, timeout=60,
                              env={"PATH": "/usr/bin:/bin", "LC_ALL": "en_US.UTF-8"})
        assert os.listdir(folder) == []
    assert proc.returncode == 0 and proc.stderr == b"", proc.stderr
    assert proc.stdout.decode().split("\0")[:-1] == words


def _quoted(words: list[str]) -> str:
    """A command that quotes every word, so a shell reads each as plain text, whatever it holds."""
    return " ".join("'" + word.replace("'", "'\\''") + "'" for word in words)


def _read_at_the_head(shell: str, command_text: str, folder: str) -> tuple:
    """How a shell reads a command as the whole of its program, with nothing on its PATH but `folder`."""
    proc = subprocess.run([*SHELLS[shell], "\n" + command_text], cwd=folder, capture_output=True,
                          stdin=subprocess.DEVNULL, timeout=60, env={"PATH": folder, "LC_ALL": "en_US.UTF-8"})
    return proc.returncode, proc.stdout, proc.stderr


@pytest.mark.parametrize("shell", sorted(SHELLS))
@given(command_text=st.one_of(st.lists(st.sampled_from(WORD_PIECES), max_size=6),
                              st.lists(st.sampled_from(["a", "b", " ", "%", "-", "=", ".", ":", "'", '"', "\\", "]"]),
                                       max_size=6)).map("".join))
@settings(max_examples=150, suppress_health_check=[HealthCheck.filter_too_much])
@example(command_text="a 'b c'")
@example(command_text="%a")  # zsh reads this as a job, and `'%a'` as a program of that name.
@example(command_text="time a")
@example(command_text="a=b a")
@example(command_text="- a")
def test_a_shell_reads_a_command_of_words_as_it_reads_each_word_quoted(shell, command_text):
    """Differential: wherever this script reads a command as words, a shell reads the head of the command
    as it reads the same words each in quotes: nothing there acts as syntax, a job or an assignment. A
    program on the PATH takes the first word's name and prints what it gets."""
    words = acs._words(command_text)
    assume(isinstance(words, list))
    with tempfile.TemporaryDirectory() as folder:
        if words and words[0] and "/" not in words[0] and words[0] not in (".", ".."):
            program = Path(folder) / words[0]
            program.write_text('#!/bin/sh\nfor word; do printf "%s\\0" "$word"; done\n')
            program.chmod(0o755)
        assert _read_at_the_head(shell, command_text, folder) == _read_at_the_head(shell, _quoted(words), folder)


def test_zsh_reads_a_bare_first_word_with_a_percent_sign_as_a_job(tmp_path):
    """What the rule in `_words` rests on, and what the differential above can see."""
    program = tmp_path / "%MOCK"
    program.write_text('#!/bin/sh\nprintf MOCK\n')
    program.chmod(0o755)
    bare = _read_at_the_head("zsh", "%MOCK", str(tmp_path))
    assert _read_at_the_head("zsh", "'%MOCK'", str(tmp_path)) == (0, b"MOCK", b"")
    assert bare[0] != 0 and bare[1] == b""


def test_every_word_the_shells_reserve_keeps_a_command_as_written():
    """Differential: a word a shell reserves acts as syntax at the head of a command, and not once quoted,
    so no command that starts with one reads as words."""
    env = {"PATH": "/usr/bin:/bin"}
    zsh = subprocess.run([*SHELLS["zsh"], "zmodload zsh/parameter; print -l ${(k)reswords}"], capture_output=True,
                         text=True, env=env, timeout=60, check=True).stdout.split()
    bash = subprocess.run([*SHELLS["bash"], "compgen -k"], capture_output=True, text=True, env=env, timeout=60,
                          check=True).stdout.split()
    assert {"time", "if", "nocorrect", "foreach", "function"} <= {*zsh, *bash}
    for word in {*zsh, *bash}:
        assert acs._words(f"{word} MOCK") == f"{word} MOCK", word


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


def test_a_record_whose_thread_drops_a_suspect_call_does_not_hold_up(area):
    """Review 8: a sub-agent that opens a page on this machine makes a suspect call, which keeps the run
    out of the pool until `--accept-suspect` names the run. A record edited to drop that call, its total lowered to
    match, said it passed, and the gate pooled the run: it let a thread's audit sort fewer calls than it
    read. The gate now finds that such a record does not hold up."""
    lanes, run, workdir = area
    add_parent(lanes, workdir)
    write_log(lanes, "rollout-MOCK-helper.jsonl", helper_meta(workdir),
              items=[search("MOCK helper query", {"type": "open_page", "url": "http://127.0.0.1/MOCK"})])
    report = acs.audit_run(run, lanes)
    assert report["passed"] and report["suspect"] == 1
    next(t for t in report["threads"] if t["thread_id"] == HELPER)["audit"]["suspect"] = []
    report["suspect"] = 0
    (run / "codex-sessions" / "audit.json").write_text(json.dumps(report, indent=1) + "\n")
    assert cli._session_audit(run) == ("one thread's audit sorts more or fewer calls than it read, or lists web "
                                       "addresses that do not match its web calls")


TOOL_USES = st.sampled_from([None] * 4 + ["the search's call", "a shell call"])  # most lines hold none


def with_message(line: dict, use, item: dict) -> dict:
    """A transcript line with a tool use in its `message`: the call `audit` reads from `item`, or a shell
    call; none for None."""
    if use is None:
        return line
    tool, inp = (next(acs.audit._tool_calls({"type": "item.completed", "item": item})) if use == "the search's call"
                 else ("Bash", {"command": "cat MOCK.md"}))
    return {**line, "message": {"content": [{"type": "tool_use", "name": tool, "input": inp}]}}


@settings(deadline=None, max_examples=150)
@given(data=st.data())
def test_a_transcript_the_check_passes_holds_as_many_calls_for_audit_as_the_log(data):
    """Property (differential against `audit_transcript`): whenever the check of the transcript finds no
    call in one place only and none that differs, `audit` reads as many calls from the transcript as
    from the main thread's log. The transcript's lines: each search's start, update and completion (a
    start under the search's id may be a message's), each with or without a call in its `message`, a
    completed message, turns' events, and a second start of the thread."""
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as monkeypatch:
        lanes, run, workdir = make_area(Path(tmp), monkeypatch)
        queries = [f"MOCK query {i}" for i in range(data.draw(st.integers(0, 2), label="searches"))]
        add_parent(lanes, workdir, spawned=(), items=[search(q) for q in queries])
        lines = [{"type": "thread.started", "thread_id": PARENT}, {"type": "turn.started"}]
        for query in queries:
            item = web(query)
            quiet = {"id": item["id"], "type": "agent_message", "text": "MOCK"}
            for kind in ("item.started", "item.updated"):
                begun = data.draw(st.sampled_from([None, None, item, {**item, "query": "", "action": {"type": "other"}},
                                                   quiet]), label=kind)
                if begun is not None:
                    lines.append(with_message({"type": kind, "item": begun}, data.draw(TOOL_USES), item))
            for _ in range(data.draw(st.sampled_from([1, 1, 1, 0, 2]), label="completions")):
                lines.append(with_message({"type": "item.completed", "item": item}, data.draw(TOOL_USES), item))
        others = [with_message({"type": "item.completed", "item": {"id": "MOCK-message", "type": "agent_message",
                                                                   "text": "MOCK"}}, data.draw(TOOL_USES), web("MOCK")),
                  with_message({"type": "turn.completed"}, data.draw(TOOL_USES), web("MOCK")),
                  {"type": "thread.started", "thread_id": PARENT}]
        for other in data.draw(st.lists(st.sampled_from(others), max_size=2), label="others"):
            lines.insert(data.draw(st.integers(2, len(lines)), label="where"), other)
        lines.append({"type": "turn.completed"})
        (run / "transcript.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
        report = acs.audit_run(run, lanes)
        check = report["transcript_check"]
        clean = not (check["only_in_transcript"] or check["only_in_log"] or check["different"])
        event(f"the check passes the transcript of {len(queries)} searches" if clean else "the check flags it")
        if clean:
            main = next(t for t in report["threads"] if t["thread_id"] == PARENT)
            assert acs.audit.audit_transcript(run / "transcript.jsonl", workdir)["tool_calls"] == len(queries)
            assert main["audit"]["tool_calls"] == len(queries) == check["items"]


@pytest.mark.parametrize("change", [
    {"state": "succeeded"}, {"state": "running"}, {"state": "starting"}, {"state": "finalizing"},
    {"state": "failed", "outcome_class": "transient"}, {"state": "failed", "outcome_class": "ok"},
    {"state": "lost", "outcome_class": "limited"}, {"state": "failed", "started_at": "2026-11-03T18:00:00Z"},
], ids=str)
def test_an_attempt_the_record_says_ran_must_name_a_session(area, monkeypatch, change):
    """Review 10: the script and the gate read an attempt as started only from its session or its start
    time, so an attempt that succeeded with neither, whose log could hold any call, left nothing to find,
    and the run passed on the later attempt's log alone."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    record = with_record(monkeypatch, run, [(f"{JOB}/a1", None, "failed", None), (f"{JOB}/a2", PARENT, "succeeded")])
    record["attempts"][0].update({"finished_at": "2026-11-03T18:10:00Z", **change})
    report = acs.audit_run(run, lanes)
    assert f"subfleet records no session for attempt {JOB}/a1, which started" in report["flags"]
    assert not report["passed"]


@pytest.mark.parametrize("change", [
    {"state": "failed", "outcome_class": "unknown", "finished_at": "2026-11-03T18:10:00Z"},
    {"state": "interrupted", "outcome_class": "unknown", "finished_at": "2026-11-03T18:10:00Z"},
    {"state": "reserved"}, {"state": "cancelled"},
], ids=str)
def test_an_attempt_subfleet_never_launched_needs_no_session(area, monkeypatch, change):
    """subfleet ends an attempt it never launched `failed` or `interrupted`, with the outcome class
    `unknown` and a finish time; no provider ran, so no log can exist."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    record = with_record(monkeypatch, run, [(f"{JOB}/a1", None, "failed", None), (f"{JOB}/a2", PARENT, "succeeded")])
    record["attempts"][0].update(change)
    report = acs.audit_run(run, lanes)
    assert report["flags"] == [] and report["passed"]


@pytest.mark.parametrize("job, attempt, passes", [
    (JOB, f"{JOB}/a1", True),
    (JOB, "MOCK-other-job/a1", False),
    (JOB, f"{JOB}/a2", False),
    (JOB, f"x{JOB}/a1", False),
    (None, f"{JOB}/a1", True),
    (None, f"{JOB}/a2", False),
    (JOB, None, True),
    (None, None, True),
], ids=str)
def test_with_no_attempts_on_record_a_run_collected_its_own_jobs_first_attempt(area, monkeypatch, job, attempt, passes):
    """Review 10: without attempts on record, the script and the gate read only the `/a1` at the end of
    the collected attempt's id, so a run of one job that named another job's first attempt passed."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    monkeypatch.setattr(acs, "subfleet_record", lambda job_id: None)
    meta = json.loads((run / "meta.json").read_text())
    meta.update({key: value for key, value in (("job_id", job), ("attempt_id", attempt)) if value is not None})
    (run / "meta.json").write_text(json.dumps(meta))
    assert acs.audit_run(run, lanes)["passed"] is passes


def test_a_job_no_command_can_name_has_no_record(tmp_path, monkeypatch):
    """Review 11: a NUL in a `job_id` stops `subprocess.run` before it starts anything, and the script
    stopped with a traceback. Only an empty PATH could be reached here."""
    monkeypatch.setenv("PATH", str(tmp_path))
    assert acs.subfleet_record("MOCK\0job") is None


@pytest.mark.parametrize("output, record", [(b"\xff", None), (b"{MOCK", None), (b'{"MOCK": 1}', {"MOCK": 1})], ids=repr)
def test_a_reply_from_subfleet_that_is_not_json_text_gives_no_record(tmp_path, monkeypatch, output, record):
    """Bytes that are not UTF-8 stop `subprocess.run` as it decodes them. A MOCK `subfleet` on an otherwise
    empty PATH prints them."""
    (tmp_path / "MOCK-reply").write_bytes(output)
    program = tmp_path / "subfleet"
    program.write_text(f'#!/bin/sh\nwhile read -r line || [ -n "$line" ]; do printf "%s" "$line"; done < {tmp_path}/MOCK-reply\n')
    program.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert acs.subfleet_record("MOCK-job") == record


def test_a_run_whose_job_no_command_can_name_is_audited_with_no_attempts_on_record(area, monkeypatch):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    meta = json.loads((run / "meta.json").read_text())
    (run / "meta.json").write_text(json.dumps({**meta, "job_id": "MOCK\0job"}))
    monkeypatch.setattr(acs.subprocess, "run", REAL_RUN)
    report = acs.audit_run(run, lanes)
    assert report["passed"] and not (run / "codex-sessions" / "attempts.json").exists()


@pytest.mark.parametrize("job", [5, 0, ["MOCK"], [], {"MOCK": 1}, {}, True, False], ids=str)
def test_a_job_id_that_is_not_a_string_is_flagged(area, job):
    """Review 10's fuzz of the record: a `job_id` of another type went to `subfleet` as an argument, and
    the script stopped with a traceback."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=())
    meta = json.loads((run / "meta.json").read_text())
    meta["job_id"] = job
    (run / "meta.json").write_text(json.dumps(meta))
    report = acs.audit_run(run, lanes)
    assert any("as its job, not a string" in flag for flag in report["flags"]) and not report["passed"]


@pytest.mark.parametrize("control", ["\t", "\n", "\r", "\x01", "\x1f", "\x7f"], ids=repr)
def test_a_file_url_with_a_control_character_names_no_folder_this_script_can_place(area, control):
    """Review 10: `urlparse` drops a tab, a line feed and a carriage return, so a command in the folder
    `<work directory><tab>`, another folder, read as one in the work directory."""
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[command("echo MOCK", workdir + control, "MOCK-1")])
    write_transcript(run, PARENT, [shell_item("MOCK-1", "/bin/zsh -lc 'echo MOCK'")])
    report = acs.audit_run(run, lanes)
    assert any("a path this script cannot place" in flag for flag in report["flags"]) and not report["passed"]


@given(path=st.text(st.sampled_from(list("ab/.?#%;:@[]\t\n\r \x01\x7f\\\u00e9")), max_size=12))
@example(path="work\t")
@example(path="work;a")
@example(path="work/\n")
def test_a_file_url_places_the_folder_its_path_names_or_none(path):
    """Property: a file URL on this host and the raw path written into it place one folder, or this script
    places neither. A URL `urlparse` refuses raises ValueError, which the log's reader flags as a field it
    cannot read."""
    path = "/" + path
    for url in (f"file://{path}", f"file://localhost{path}"):
        try:
            place = acs.local_path(url)
        except ValueError:
            continue
        assert acs._plain(place) in (None, acs._plain(path))


@pytest.mark.parametrize("url", ["file://[MOCK/work", "file://\u2100/work"], ids=repr)
def test_a_file_url_that_urlparse_refuses_is_a_field_this_script_cannot_read(area, url):
    lanes, run, workdir = area
    add_parent(lanes, workdir, spawned=(), items=[{**command("echo MOCK", workdir, "MOCK-1"), "cwd": url}])
    write_transcript(run, PARENT, [shell_item("MOCK-1", "/bin/zsh -lc 'echo MOCK'")])
    report = acs.audit_run(run, lanes)
    assert any("a record with a field this script cannot read (ValueError)" in flag for flag in report["flags"])
    assert not report["passed"]
