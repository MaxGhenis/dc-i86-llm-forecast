"""Round 4 MOCK transcripts: ordinary scratch research must not exclude a run.

Cases from the round-4 independent review (GPT-6.1 Sol, 2026-10-25), kept as regression tests.
They first ran as strict expected failures against 6844063; the fixes made them pass.
"""

import json
import shlex
import subprocess

import pytest

from i86 import audit, runners
from test_review_r4_audit import model_suspects


@pytest.fixture
def own_work(tmp_path, monkeypatch):
    monkeypatch.setattr(runners, "WORK", tmp_path / "work")
    monkeypatch.setattr(audit, "protected_roots", lambda: [tmp_path / "repository", tmp_path / "staging"])
    work = runners.WORK / "sol-1"
    work.mkdir(parents=True)
    (runners.WORK / "sol-2").mkdir()
    (work / "report.txt").write_text("/\nMOCK certification / public report\n")
    return work


def classify(tmp_path, command, work):
    path = tmp_path / "MOCK-legitimate-transcript.jsonl"
    path.write_text(json.dumps({"type": "item.completed", "item": {
        "type": "command_execution", "command": "/bin/zsh -lc " + shlex.quote(command),
    }}) + "\n")
    return audit.audit_transcript(path, str(work))


@pytest.mark.parametrize("search", [
    "rg -S", "rg -c", "rg -x", "grep -r", "grep -R -E", "grep --recursive -E",
    "grep -R -c", "grep -R -x",
])
def test_search_of_own_file_is_local(tmp_path, own_work, search):
    command = "cd .. && " + search + " / sol-1/report.txt"
    proc = subprocess.run(["/bin/sh", "-c", command], cwd=own_work,
                          capture_output=True, text=True, check=True, timeout=10)
    assert proc.stdout
    result = classify(tmp_path, command, own_work)
    assert not result["violations"], result


@pytest.mark.parametrize("option", [
    "--color never", "--color always", "--hyperlink-format default",
    "--field-match-separator :", "--field-context-separator -",
])
def test_slash_pattern_with_value_option_is_local(tmp_path, own_work, option):
    command = "rg " + option + " / report.txt"
    proc = subprocess.run(["/bin/sh", "-c", command], cwd=own_work,
                          capture_output=True, text=True, check=True, timeout=10)
    assert proc.stdout
    result = classify(tmp_path, command, own_work)
    assert not result["violations"], result


@pytest.mark.parametrize("command", [
    "cat <<'DATA'\ncd ..\ncat report.txt\nDATA",
    "cat > commands.txt <<'DATA'\ncd ..\nrg certification report.txt\nDATA",
])
def test_literal_heredoc_data_is_local(tmp_path, own_work, command):
    proc = subprocess.run(["/bin/sh", "-c", command], cwd=own_work,
                          capture_output=True, text=True, check=True, timeout=10)
    assert proc.stdout == "cd ..\ncat report.txt\n" or (own_work / "commands.txt").read_text() == (
        "cd ..\nrg certification report.txt\n"
    )
    result = classify(tmp_path, command, own_work)
    assert not result["violations"], result


@pytest.mark.parametrize("command", [
    "printf '%s\\n' ';' cd .. ';' rg certification report.txt",
    "printf '%s\\n' '|' rg certification ..",
])
def test_quoted_operator_data_is_local(tmp_path, own_work, command):
    proc = subprocess.run(["/bin/sh", "-c", command], cwd=own_work,
                          capture_output=True, text=True, check=True, timeout=10)
    assert proc.stdout
    result = classify(tmp_path, command, own_work)
    assert not result["violations"], result


@pytest.mark.parametrize("command", [
    "curl -L https://example.org/report.pdf -o report.pdf",
    "pdftotext report.pdf report.txt",
    "rg -n / report.txt", "rg -F ../ report.txt", "rg -e / report.txt",
    "sed -n '/foo/p' report.txt", "awk '/foo/ {print $0}' report.txt",
    "python3 -c 'print(1 / 2)'", "jq '.foo // 0' report.json",
    "python3 - <<'PYCODE'\nprint(1 / 2)\nPYCODE",
    "grep / <<< 'https://example.org/report'",
    "curl https://example.org/report | sed -n '/foo/p'",
    "cd .. && rg -F / sol-1/report.txt",
    "cd .. && grep -rE / sol-1/report.txt",
])
def test_research_controls_pass(tmp_path, own_work, command):
    result = classify(tmp_path, command, own_work)
    assert result["passed"], result


@pytest.mark.parametrize("command", [
    "curl -sL https://github.com/MaxGhenis/dc-i86-llm-forecast",
    "wget -qO- https://github.com/MaxGhenis/dc-i86-llm-forecast",
])
def test_own_repository_shell_fetch_is_suspect(tmp_path, own_work, command):
    result = classify(tmp_path, command, own_work)
    assert model_suspects(result), result
