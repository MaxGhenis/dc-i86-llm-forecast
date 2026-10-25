"""Dispatch forecaster runs and collect their answers.

A run lives in `runs/<label>/`: `prompt.md` (the shared prompt), `meta.json` (backend, prompt hash,
command, job id, model served, timestamps) and, once collected, `response.md` (the agent's final
message, verbatim). The agent works in an empty directory outside the repository so it cannot
find other runs' files by browsing its working directory.

Backends:
- `subfleet`: Max Ghenis's supervised lanes (`subfleet run --task research`). No answer is written into
  the repository until every subfleet run has finished, so a run that starts late cannot find an
  earlier run's answer there. `collect` then copies each job's deliverable.
- `claude`: Claude Code in print mode, bare (no hooks, memory, CLAUDE.md or MCP servers; it needs
  ANTHROPIC_API_KEY), with only WebSearch and WebFetch. The stream-json transcript is saved for the
  audit.
- `manual`: write the prompt and paste the agent's final message into `response.md` yourself.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .graph import ROOT

RUNS = ROOT / "runs"
WORK = Path.home() / ".cache" / "dc-i86-llm-forecast"


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_meta(run_dir: Path) -> dict:
    path = run_dir / "meta.json"
    return json.loads(path.read_text()) if path.exists() else {}


def write_meta(run_dir: Path, meta: dict) -> None:
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")


def prepare(label: str, prompt_path: Path, prompt_sha: str, backend: str, **extra) -> Path:
    run_dir = RUNS / label
    if (run_dir / "meta.json").exists():
        raise FileExistsError(f"run {label} already exists")
    run_dir.mkdir(parents=True)
    shutil.copyfile(prompt_path, run_dir / "prompt.md")
    work = WORK / label
    work.mkdir(parents=True, exist_ok=True)
    write_meta(run_dir, {"label": label, "backend": backend, "prompt_sha256": prompt_sha,
                         "workdir": str(work), "prepared_at": now(), **extra})
    return run_dir


def subfleet_command(run_dir: Path, label: str, tier: str, model: str | None) -> list[str]:
    meta = read_meta(run_dir)
    cmd = ["subfleet", "run", "--task", "research", "--tier", tier]
    if model:
        cmd += ["-m", model]
    cmd += ["-s", "read-only", "-C", meta["workdir"], "-p", str(run_dir / "prompt.md"),
            "-n", f"i86-{label}", "--json"]
    return cmd


def claude_command(model: str) -> list[str]:
    return ["claude", "-p", "--bare", "--model", model, "--tools", "WebSearch,WebFetch",
            "--strict-mcp-config", "--no-session-persistence", "--output-format", "stream-json", "--verbose"]


def parse_stream(text: str) -> tuple[str, str | None]:
    """The final message and the model that served it, from Claude Code stream-json output."""
    final, model = "", None
    for raw in text.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "system" and event.get("model"):
            model = event["model"]
        msg = event.get("message")
        if event.get("type") == "assistant" and isinstance(msg, dict) and msg.get("model"):
            model = msg["model"]
        if event.get("type") == "result" and isinstance(event.get("result"), str):
            final = event["result"]
    return final, model


def dispatch_subfleet(label: str, prompt_path: Path, prompt_sha: str, tier: str, model: str | None) -> dict:
    run_dir = prepare(label, prompt_path, prompt_sha, "subfleet", tier=tier, model_pin=model)
    cmd = subfleet_command(run_dir, label, tier, model)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    meta = read_meta(run_dir)
    meta["command"] = cmd
    meta["dispatched_at"] = now()
    meta["dispatch_stdout"] = proc.stdout[-4000:]
    meta["dispatch_rc"] = proc.returncode
    for line in proc.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        job_id = obj.get("job_id") or (obj.get("job") or {}).get("job_id")
        if job_id:
            meta["job_id"] = job_id
            break
    write_meta(run_dir, meta)
    if proc.returncode != 0 or "job_id" not in meta:
        raise RuntimeError(f"subfleet dispatch for {label} failed (rc {proc.returncode}): {proc.stderr[-2000:]}")
    return meta


def dispatch_claude(label: str, prompt_path: Path, prompt_sha: str, model: str) -> dict:
    run_dir = prepare(label, prompt_path, prompt_sha, "claude", model_pin=model)
    meta = read_meta(run_dir)
    cmd = claude_command(model)
    meta.update(command=cmd, dispatched_at=now())
    write_meta(run_dir, meta)
    with open(run_dir / "prompt.md") as stdin:
        proc = subprocess.run(cmd, stdin=stdin, capture_output=True, text=True, cwd=meta["workdir"])
    transcript = run_dir / "transcript.jsonl"
    transcript.write_text(proc.stdout)
    final, served = parse_stream(proc.stdout)
    if final:
        (run_dir / "response.md").write_text(final)
    meta.update(finished_at=now(), rc=proc.returncode, model_served=served, transcript=str(transcript),
                stderr=proc.stderr[-2000:])
    write_meta(run_dir, meta)
    return meta


TERMINAL = {"succeeded", "failed", "cancelled", "canceled", "killed", "expired"}


def refresh_subfleet(run_dir: Path) -> dict:
    """Refresh one subfleet run's state, model and transcript path; write no answer."""
    meta = read_meta(run_dir)
    job_id = meta.get("job_id")
    if not job_id:
        return meta
    proc = subprocess.run(["subfleet", "runs", "show", job_id, "--json"], capture_output=True, text=True)
    if proc.returncode != 0:
        meta["collect_error"] = proc.stderr[-1000:]
        write_meta(run_dir, meta)
        return meta
    info = json.loads(proc.stdout)
    job = info.get("job") or {}
    meta["state"] = job.get("state")
    meta["finished_at"] = job.get("finished_at")
    accepted = [a for a in info.get("attempts", []) if a.get("state") == "succeeded"]
    if accepted:
        a = accepted[-1]
        meta["model_served"] = a.get("model_served")
        meta["lane_id"] = a.get("lane_id")
        meta["attempt_id"] = a.get("attempt_id")
        # attempt_id is '<job_id>/a<N>', the attempt's folder under the job store.
        meta["transcript"] = str(Path.home() / ".subfleet" / "jobs" / a["attempt_id"] / "stdout")
    write_meta(run_dir, meta)
    return meta


def fetch_subfleet_output(run_dir: Path) -> bool:
    """Copy a succeeded job's deliverable into response.md. Call only once every run has finished."""
    meta = read_meta(run_dir)
    if meta.get("state") != "succeeded" or (run_dir / "response.md").exists():
        return (run_dir / "response.md").exists()
    out = subprocess.run(["subfleet", "runs", "show", meta["job_id"], "--out"], capture_output=True, text=True)
    if out.returncode == 0 and out.stdout.strip():
        (run_dir / "response.md").write_text(out.stdout)
        meta["collected_at"] = now()
        write_meta(run_dir, meta)
        return True
    return False
