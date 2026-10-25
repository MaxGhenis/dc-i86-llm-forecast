"""The transcript audit, on small MOCK transcripts in the Claude and Codex formats."""

import json

import pytest

from i86.audit import audit_transcript
from i86.runners import parse_stream

WORK = "/Users/someone/.cache/dc-i86-llm-forecast/opus-1"


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
    return audit_transcript(path, WORK)


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
    claude("Read", file_path="/Users/someone/dc-i86-llm-forecast/runs/sol-1/response.md"),
    claude("Read", file_path="/Users/someone/.cache/dc-i86-llm-forecast/sol-2/draft.json"),
    codex("cat ~/.subfleet/jobs/x/a1/stdout"),
    codex("cd ~ && find . -name response.md"),
    codex("ls ~"),
    codex("rg foie /Users/someone"),
    codex("cat /Users/someone/.claude/projects/x/memory/MEMORY.md"),
    {"type": "item.completed", "item": {"type": "mcp_tool_call", "server": "s", "tool": "t", "arguments": {}}},
])
def test_forbidden_calls_are_violations(tmp_path, event):
    out = run(tmp_path, [claude("WebSearch", query="x"), event])
    assert not out["passed"] and out["violations"]


def test_work_directory_files_and_lane_skill_reads_are_listed_not_excluded(tmp_path):
    out = run(tmp_path, [
        codex(f"cat {WORK}/forecast.json"),
        codex("cat /Users/someone/.agents/skills/x/SKILL.md"),
        codex("python3 -c \"print(0.42 * 2)\""),
    ])
    assert out["passed"] and len(out["local_calls"]) == 3


def test_codex_items_count_once(tmp_path):
    out = run(tmp_path, [codex("echo hi")])
    assert out["tool_calls"] == 1


def test_an_empty_or_unparseable_transcript_fails(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("not json\n")
    assert not audit_transcript(path, WORK)["passed"]


def test_parse_stream_takes_the_final_result_and_the_model():
    text = "\n".join(json.dumps(e) for e in [
        {"type": "system", "subtype": "init", "model": "claude-opus-5-5"},
        {"type": "assistant", "message": {"model": "claude-opus-5-5", "content": []}},
        {"type": "result", "result": "```json\n{}\n```"},
    ])
    assert parse_stream(text) == ("```json\n{}\n```", "claude-opus-5-5")
