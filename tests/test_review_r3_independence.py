"""Round 3 review only: MOCK transcripts and isolated shell/bookkeeping probes.

No live
forecaster, job store, staging directory or CLI dispatch/collect is used.

Cases from the round-3 independent review (GPT-6.1 Sol, 2026-10-25), kept as regression tests.
They first ran as strict expected failures against aa6fbad; the fixes made them pass.
"""

import json
import shlex
import subprocess

import pytest

from i86 import audit, cli, runners


def codex(command):
    return {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": "/bin/zsh -lc " + shlex.quote(command),
        },
    }


def claude(command):
    return {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": command}}]},
    }


def run_audit(tmp_path, event, workdir):
    transcript = tmp_path / "MOCK-transcript.jsonl"
    transcript.write_text(json.dumps(event) + "\n")
    return audit.audit_transcript(transcript, str(workdir))


@pytest.mark.parametrize("event", [codex, claude], ids=["Codex", "Claude"])
def test_attached_redirect_cannot_read_another_answer(tmp_path, monkeypatch, event):
    monkeypatch.setattr(runners, "WORK", tmp_path / "work")
    monkeypatch.setattr(audit, "protected_roots", lambda: [tmp_path / "repository", tmp_path / "staging"])
    work = runners.WORK / "opus-1"
    sibling = runners.WORK / "opus-2"
    work.mkdir(parents=True)
    sibling.mkdir()
    (sibling / "draft.json").write_text("MOCK OTHER RUN ANSWER\n")
    command = "cat <../opus-2/draft.json"
    proc = subprocess.run(["/bin/zsh", "-lc", command], cwd=work, capture_output=True, text=True, check=True)
    assert proc.stdout == "MOCK OTHER RUN ANSWER\n"
    result = run_audit(tmp_path, event(command), work)
    assert not result["passed"], result


@pytest.mark.parametrize("option", ["--", "-P"])
def test_cd_options_cannot_hide_another_answer(tmp_path, monkeypatch, option):
    monkeypatch.setattr(runners, "WORK", tmp_path / "work")
    monkeypatch.setattr(audit, "protected_roots", lambda: [tmp_path / "repository", tmp_path / "staging"])
    work = runners.WORK / "opus-1"
    sibling = runners.WORK / "opus-2"
    work.mkdir(parents=True)
    sibling.mkdir()
    (sibling / "draft.json").write_text("MOCK OTHER RUN ANSWER\n")
    command = f"cd {option} .. && cat opus-2/draft.json"
    proc = subprocess.run(["/bin/zsh", "-lc", command], cwd=work, capture_output=True, text=True, check=True)
    assert proc.stdout == "MOCK OTHER RUN ANSWER\n"
    result = run_audit(tmp_path, codex(command), work)
    assert not result["passed"], result


def test_searching_own_research_for_a_slash_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(runners, "WORK", tmp_path / "work")
    work = runners.WORK / "sol-1"
    work.mkdir(parents=True)
    (work / "report.txt").write_text("MOCK public-source URL https://example.org/report\n")
    proc = subprocess.run(["rg", "-n", "/", "report.txt"], cwd=work, capture_output=True, text=True, check=True)
    assert "https://example.org/report" in proc.stdout
    result = run_audit(tmp_path, codex("rg -n / report.txt"), work)
    assert result["passed"], result


@pytest.mark.parametrize("command", [
    "curl -L https://example.org/report.pdf -o report.pdf",
    "pdftotext report.pdf report.txt",
    "rg -n certification report.txt",
    "python3 -c 'print(0.42 * 2)'",
    "cat notes.md",
])
def test_ordinary_codex_web_and_scratch_commands_pass(tmp_path, command):
    result = run_audit(tmp_path, codex(command), runners.WORK / "sol-1")
    assert result["passed"], result


@pytest.mark.parametrize("command", [
    "cd .. && cat opus-2/draft.json",
    "cat ../opus-1*/draft.json",
    "cat ../opus-10/draft.json",
    "cat ~/.claude/notes.md",
    "cat ~/chief-of-staff/notes.md",
    "cat ~/reviews/notes.md",
    "cat ~/.subfleet/jobs/example/a1/stdout",
    "cat ~/.brier/notes.md",
])
def test_previous_simple_bypasses_are_excluded(tmp_path, command):
    result = run_audit(tmp_path, codex(command), runners.WORK / "opus-1")
    assert not result["passed"], result


def test_bookkeeping_does_not_seal_while_another_claude_is_running(tmp_path, monkeypatch):
    for name in ["RUNS", "WORK", "STAGE"]:
        monkeypatch.setattr(runners, name, tmp_path / name.lower())
    brief = tmp_path / "MOCK-brief.md"
    brief.write_text("MOCK brief\n")
    finished = runners.prepare("claude-done", brief, "MOCK-sha", "claude")
    pending = runners.prepare("claude-running", brief, "MOCK-sha", "claude")
    stage = runners.STAGE / "claude-done"
    stage.mkdir(parents=True)
    (stage / "response.md").write_text("MOCK completed answer\n")
    (stage / "transcript.jsonl").write_text("{}\n")
    done_meta = runners.read_meta(finished)
    done_meta.update(state="succeeded", transcript=str(stage / "transcript.jsonl"))
    runners.write_meta(finished, done_meta)
    pending_meta = runners.read_meta(pending)
    pending_meta.update(dispatched_at="MOCK running process; no finished_at or state yet")
    runners.write_meta(pending, pending_meta)
    # Exercise only isolated in-process bookkeeping; no i86 collect command or subprocess.
    cli.cmd_collect(None)
    assert not (finished / "response.md").exists()
