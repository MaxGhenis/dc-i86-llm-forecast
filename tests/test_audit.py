"""The transcript audit, on small MOCK transcripts in the Claude and Codex formats.

Paths are built from the real home directory and the real work area, because the audit resolves
them the way the shell would on this machine.
"""

import json
from pathlib import Path

import pytest

from i86 import runners
from i86.audit import audit_transcript, shell_paths
from i86.cli import discloses
from i86.runners import parse_stream

HOME = Path.home()
WORK = runners.WORK / "opus-1"
SIBLING = runners.WORK / "opus-10"


def claude(name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def codex(command):
    item = {"id": "i", "type": "command_execution", "command": f"/bin/zsh -lc '{command}'"}
    return [{"type": "item.started", "item": item}, {"type": "item.completed", "item": item}]


def run(tmp_path, events):
    lines = []
    for e in events:
        lines += e if isinstance(e, list) else [e]
    path = tmp_path / "t.jsonl"
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n")
    return audit_transcript(path, str(WORK))


def test_web_calls_pass_and_are_logged(tmp_path):
    out = run(tmp_path, [
        claude("WebSearch", query="DC Initiative 86 poll"),
        claude("WebFetch", url="https://electionresults.dcboe.org/"),
        codex("curl -sL https://www.bls.gov/sae/"),
        {"type": "item.completed", "item": {"type": "web_search", "query": "Denver IO 311"}},
    ])
    assert out["passed"] and out["web_calls"] == 4
    assert "https://electionresults.dcboe.org/" in out["urls"] and "https://www.bls.gov/sae/" in out["urls"]


@pytest.mark.parametrize("event", [
    claude("Read", file_path=str(runners.RUNS / "sol-1" / "response.md")),
    claude("Read", file_path=str(runners.STAGE / "opus-2" / "response.md")),
    claude("Read", file_path=str(SIBLING / "draft.json")),
    codex(f"cat {SIBLING}/draft.json"),
    codex("cat ~/.subfleet/jobs/x/a1/stdout"),
    codex("cat $HOME/.claude/projects/x/memory/MEMORY.md"),
    codex("cd ~ && find . -name response.md"),
    codex("cd .. && cd .. && grep -r foie ."),
    codex("find .. -name response.md | xargs cat"),
    codex("cat $(find .. -name response.md)"),
    codex("find .. -name response.md -exec cat {} +"),
    codex("cd .. && ls opus-2"),
    codex("cat <../opus-2/draft.json"),
    codex("cat < ../opus-2/draft.json"),
    codex("cd -- .. && cat opus-2/draft.json"),
    codex("cd -P .. && cat opus-2/draft.json"),
    codex("pushd .. && cat opus-2/draft.json"),
    codex("D=..; cat $D/opus-2/draft.json"),
    codex("export D=~/.claude && cat $D/x"),
    codex("bash -c \"cd .. && cat opus-2/draft.json\""),
    codex("eval \"cat ../opus-2/draft.json\""),
    codex("xargs -a ../opus-2/list cat"),
    codex("grep --file=../opus-2/draft.json notes.md"),
    codex("grep -f ../opus-2/draft.json notes.md"),
    codex("python3 -c \"print(open(\\\"../opus-2/draft.json\\\").read())\""),
    codex("cat <(cat ../opus-2/draft.json)"),
    codex("cd -- ~/reviews && cat notes.md"),
    codex("ls $HOME/reviews"),
    codex(f"rg foie {HOME}"),
    codex("rg foie /"),
    codex("locate response.md"),
    codex("mdfind foie"),
    codex("cat ~/.cache/*/sol-*/response.md"),
    codex("cat ~/.c*/dc-i86*/opus-2/x"),
    codex("curl -s https://example.com -o ~/.claude/x"),
    claude("Grep", pattern="foie", path=str(HOME)),
    claude("Glob", pattern="**/response.md", path="/"),
    claude("Bash", command="ls ../opus-2"),
    claude("mcp__brier__search", query="i86"),
    {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "s", "tool": "t", "arguments": {}}},
])
def test_forbidden_calls_are_violations(tmp_path, event):
    out = run(tmp_path, [claude("WebSearch", query="x"), event])
    assert not out["passed"] and out["violations"], out


@pytest.mark.parametrize("event", [
    codex("ls ~"),
    codex("cat /tmp/i86.pdf"),
    codex("cd \"$TARGET\" && cat x"),
    codex("find .. -maxdepth 1 -name AGENTS.md"),
    {"type": "item.completed", "item": {"type": "collab_tool_call", "id": "c"}},
])
def test_suspect_calls_are_reported_without_excluding(tmp_path, event):
    out = run(tmp_path, [event])
    assert out["passed"] and out["suspect"] and not out["violations"], out


def test_work_directory_files_and_ordinary_reads_are_listed_not_excluded(tmp_path):
    out = run(tmp_path, [
        codex(f"cat {WORK}/forecast.json"),
        codex("cat notes.md && python3 -c \"print(0.42 * 2)\""),
        codex("cat /Users/someone-else/.agents/skills/x/SKILL.md"),
        codex("pdftotext /tmp/report.pdf -"),
        codex("rg -n / report.txt"),
        codex("grep -rn -e / ."),
        codex("rg --glob \"*.md\" -n certification ."),
        codex("find . -name \"*.txt\" -maxdepth 2"),
        codex("cd /tmp && ls && cd - && cat notes.md"),
        codex("cat > notes.md <<\"EOF\"\nThe CFO certification decides it.\nEOF"),
        codex("python3 - <<\"EOF\"\nprint(0.3 * 0.8)\nEOF"),
        codex("curl -sL https://code.dccouncil.gov/x.pdf -o law.pdf 2>/dev/null && pdftotext law.pdf -"),
        codex("sed -n 1,40p law.txt | grep -n certif"),
    ])
    assert out["passed"] and not out["suspect"] and not out["violations"], out


def test_a_cd_chain_moves_the_base_for_later_paths():
    paths, problems, _ = shell_paths("cd /usr && cd share && cat dict/words", WORK)
    assert Path("/usr/share/dict/words") in paths and not problems


def test_a_sibling_work_directory_is_not_mistaken_for_the_runs_own():
    # opus-10 starts with the same characters as opus-1; masking the run's own directory must not hide it.
    paths, _, _ = shell_paths(f"cat {SIBLING}/x", WORK)
    assert SIBLING / "x" in paths


def test_codex_items_count_once(tmp_path):
    out = run(tmp_path, [codex("echo hi")])
    assert out["tool_calls"] == 1


def test_an_empty_or_unparseable_transcript_fails(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("not json\n")
    assert not audit_transcript(path, str(WORK))["passed"]


def test_parse_stream_takes_the_final_result_and_the_model():
    text = "\n".join(json.dumps(e) for e in [
        {"type": "system", "subtype": "init", "model": "claude-opus-5-5"},
        {"type": "assistant", "message": {"model": "claude-opus-5-5", "content": []}},
        {"type": "result", "result": "```json\n{}\n```"},
    ])
    assert parse_stream(text) == ("```json\n{}\n```", "claude-opus-5-5")


@pytest.mark.parametrize("text, excluded", [
    ("none", False),
    ("None.", False),
    ("\"none\"", False),
    ("None beyond the brief.", False),
    ("System prompt asks for concise answers.", False),
    ("My memory notes say an earlier forecast put I-86 at 60%.", True),
    ("A note about foie gras forecasts from an earlier session.", True),
])
def test_prior_context_that_mentions_these_questions_excludes_a_run(text, excluded):
    assert discloses(text) is excluded
