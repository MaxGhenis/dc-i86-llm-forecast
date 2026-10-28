"""Round-12 findings 5 and 6 (Sol) and 8 (Opus): transcript inputs of every shape, where a Bash call
starts, file tools through links, unknown tools and Codex items that never complete. All transcripts
are MOCK; paths are built like test_audit's, from the real work area, or in a temporary MOCK area."""

import json

import pytest

from i86 import runners
from i86.audit import QUIET_TOOLS, audit_transcript, check_call, protected_roots
from test_audit import WORK, claude, run

SIBLING_ANSWER = f"../{(runners.WORK / 'opus-10').name}/draft.json"


def codex_item(**fields):
    item = {"id": "i", "type": "command_execution", **fields}
    return [{"type": "item.started", "item": item}, {"type": "item.completed", "item": item}]


def test_a_codex_command_given_as_words_is_read_as_that_command(tmp_path):
    out = run(tmp_path, [codex_item(command=["cat", SIBLING_ANSWER])])
    assert [c["tool"] for c in out["violations"]] == ["shell"] and not out["passed"], out


@pytest.mark.parametrize("fields", [{}, {"command": None}, {"command": 7}, {"command": []},
                                    {"command": ["cat", 7]}])
def test_a_codex_call_without_a_readable_command_is_suspect(tmp_path, fields):
    out = run(tmp_path, [codex_item(**fields)])
    assert len(out["suspect"]) == 1 and not out["local_calls"] and not out["violations"], out


def test_a_bash_input_that_is_not_an_object_is_suspect(tmp_path):
    event = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": f"cat {SIBLING_ANSWER}"}]}}
    out = run(tmp_path, [event])
    assert [(c["tool"], c["why"]) for c in out["suspect"]] == [("Bash", "a tool input the audit cannot read")], out
    for tool in ("Bash", "shell", "Read"):
        assert check_call(tool, f"cat {SIBLING_ANSWER}", WORK, protected_roots())[0] == "suspect"


@pytest.mark.parametrize("first", ["cd ..", "cd .. && echo MOCK", "cd /; cd .."])
def test_the_model_starts_a_bash_call_where_the_last_one_ended(tmp_path, first):
    """Claude Code starts a Bash call where the last ended with status 0, or, once a call ends
    outside the directories it allows, back in the work directory: a read that reaches another run
    from the first of these places excludes the run."""
    if first == "cd /; cd ..":
        second = f"cat {(runners.WORK / 'opus-10').relative_to('/')}/draft.json"
    else:
        second = "cat opus-10/draft.json"
    out = run(tmp_path, [claude("Bash", command=first), claude("Bash", command=second)])
    assert [c["call"] for c in out["violations"]] and not out["passed"], out
    assert second in out["violations"][-1]["call"], out


@pytest.mark.parametrize("first", ["cd ..; exit 3", "cd ..; exit 0", "cd ..; false", "cd .. && false"])
def test_the_model_starts_a_bash_call_where_the_last_one_started_after_an_exit_or_a_failure(tmp_path, first):
    """Claude Code reads where the shell is only after a call that ran to its end with status 0
    (`eval CMD && pwd -P >| FILE`; measured on 2.1.284 and 2.1.308): after an exit or a failure the
    next call starts where this one started, and a read from there that reaches another run
    excludes the run."""
    out = run(tmp_path, [claude("Bash", command=first), claude("Bash", command="cat ../opus-10/draft.json")])
    assert [c["call"] for c in out["violations"]] and not out["passed"], out
    assert "../opus-10/draft.json" in out["violations"][-1]["call"], out


def test_a_cd_inside_the_work_directory_keeps_later_reads_local(area, tmp_path):
    (area / "MOCK-sub").mkdir()
    out = audit_events(area, tmp_path, [claude("Bash", command="cd MOCK-sub"), claude("Bash", command="cat draft.json")])
    assert not out["violations"] and out["passed"], out


def test_the_work_directory_stays_a_start_after_a_call_outside_it(tmp_path):
    """The reset back to the work directory: a later relative read is taken from there too, so a
    file the run wrote in its work directory still reads as its own."""
    out = run(tmp_path, [claude("Bash", command="cd /tmp"), claude("Bash", command="cat ../opus-10/draft.json")])
    assert out["violations"], out


@pytest.fixture
def area(tmp_path, monkeypatch):
    """A MOCK work area: this run's directory, another run's with its answer, and a link in this run's
    directory to the area above it."""
    work_area = (tmp_path / "work").resolve()
    monkeypatch.setattr(runners, "WORK", work_area)
    own, other = work_area / "opus-1", work_area / "opus-2"
    own.mkdir(parents=True)
    other.mkdir()
    (other / "draft.json").write_text("MOCK other answer\n")
    (own / "MOCK-notes.txt").write_text("MOCK own notes\n")
    (own / "up").symlink_to("..")
    (own / "hosts").symlink_to("/etc/hosts")
    (own / "inside").symlink_to("MOCK-notes.txt")
    return own


def audit_events(area, tmp_path, events):
    lines = []
    for e in events:
        lines += e if isinstance(e, list) else [e]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return audit_transcript(path, str(area))


@pytest.mark.parametrize("name,inp", [
    ("Read", {"file_path": "{work}/up/opus-2/draft.json"}),
    ("Grep", {"pattern": "MOCK", "path": "{work}/up"}),
    ("Glob", {"pattern": "*/draft.json", "path": "{work}/up"}),
    ("LS", {"path": "{work}/up/opus-2"}),
])
def test_a_file_tool_through_a_link_to_another_run_excludes_the_run(area, tmp_path, name, inp):
    """Opus 8: the paths a file tool names are followed through links at audit time."""
    inp = {k: v.format(work=area) for k, v in inp.items()}
    out = audit_events(area, tmp_path, [claude(name, **inp)])
    assert out["violations"] and not out["passed"], out


@pytest.mark.parametrize("name,inp", [
    ("Read", {"file_path": "/etc/hosts"}),
    ("Read", {"file_path": "{work}/hosts"}),
    ("Grep", {"pattern": "localhost", "path": "/etc"}),
    ("Glob", {"pattern": "*", "path": "/etc"}),
    ("Write", {"file_path": "/private/tmp/MOCK-out.txt", "content": "MOCK"}),
])
def test_a_file_tool_reaching_outside_the_work_directory_is_suspect(area, tmp_path, name, inp):
    inp = {k: v.format(work=area) for k, v in inp.items()}
    out = audit_events(area, tmp_path, [claude(name, **inp)])
    assert len(out["suspect"]) == 1 and not out["violations"], out
    assert out["suspect"][0]["why"].startswith("a file outside the work directory"), out


@pytest.mark.parametrize("path", ["MOCK-notes.txt", "{work}/inside", "{work}/MOCK-notes.txt"])
def test_a_file_tool_inside_the_work_directory_stays_local(area, tmp_path, path):
    out = audit_events(area, tmp_path, [claude("Read", file_path=path.format(work=area))])
    assert out["passed"] and not out["suspect"] and len(out["local_calls"]) == 1, out


@pytest.mark.parametrize("tool", ["Task", "Agent", "Skill", "EnterWorktree", "SlashCommand", "MOCK-tool"])
def test_a_tool_the_audit_does_not_know_is_suspect(area, tmp_path, tool):
    out = audit_events(area, tmp_path, [claude(tool, prompt="MOCK")])
    assert [c["why"] for c in out["suspect"]] == [f"a tool the audit does not know ({tool})"], out


@pytest.mark.parametrize("tool", sorted(QUIET_TOOLS))
def test_tools_that_read_nothing_are_not_listed(area, tmp_path, tool):
    out = audit_events(area, tmp_path, [claude(tool, todos=[])])
    assert out["passed"] and not out["suspect"] and not out["local_calls"], out


def test_a_codex_item_that_only_started_is_audited(area, tmp_path):
    """Opus 8: a command whose item never completed (a killed run) ran all the same."""
    item = {"id": "i", "type": "command_execution", "command": "cat ../opus-2/draft.json"}
    out = audit_events(area, tmp_path, [{"type": "item.started", "item": item}])
    assert out["violations"] and not out["passed"] and out["tool_calls"] == 1, out


def test_a_codex_item_that_started_and_completed_counts_once(area, tmp_path):
    item = {"id": "i", "type": "command_execution", "command": "cat MOCK-notes.txt"}
    out = audit_events(area, tmp_path, [{"type": "item.started", "item": item},
                                        {"type": "item.completed", "item": {**item, "status": "completed"}}])
    assert out["tool_calls"] == 1 and out["passed"], out


@pytest.mark.parametrize("path,verdict", [("{other}/draft.json", "violations"), ("/private/tmp/MOCK-x", "suspect"),
                                          ("{work}/MOCK-notes.txt", "local_calls")])
def test_a_codex_file_change_is_checked_by_the_paths_it_changes(area, tmp_path, path, verdict):
    path = path.format(work=area, other=area.parent / "opus-2")
    item = {"id": "f", "type": "file_change", "changes": [{"path": path, "kind": "update"}], "status": "completed"}
    out = audit_events(area, tmp_path, [{"type": "item.completed", "item": item}])
    assert len(out[verdict]) == 1, out
