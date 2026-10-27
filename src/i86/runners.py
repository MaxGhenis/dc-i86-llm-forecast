"""Dispatch forecaster runs and collect their answers.

A run lives in `runs/<label>/`: `prompt.md` (the shared brief), `meta.json` (backend, prompt hash,
command, job id, model served, timestamps) and, once collected, `response.md` (the agent's final
message, verbatim), `transcript.jsonl` and, for subfleet, `prompt.sent.md` (exactly what the model was
given, with the lane's own preamble). The agent works in an empty directory outside the repository so
it cannot find other runs' files by browsing its working directory.

No answer enters the repository until every run has finished: the `claude` and `manual` backends
write to a staging directory, and `collect` copies answers in only when no run of any backend is
still going. A run that will never finish (a killed process, a manual run given up) is marked with
`i86 abandon <label>`; abandonment is final, and an answer that run produces later is not collected.
A subfleet run that its supervisor reports lost although the agent finished (processes the agent
started outlived it) can instead be recovered with `i86 recover <label>`, which takes the final message
from the attempt's own transcript under conditions `recover` lists; the report flags such runs.
Collection reads each transcript once, checks it, and copies those same bytes, with their SHA-256 in
`meta.json`; a recovered run's transcript must be byte for byte the one recovery read.
After collection, `dispatch` refuses new runs unless they are marked `--late`, and the report flags
late runs, which could have found the others' answers. Dispatch, abandon and collect hold a lock
file beside the staging directory while they check and change runs, so no run can start between
collect's check and its copy. The lock is reentrant within one thread; other threads and other
processes wait for it. A process holds the file lock through one descriptor, opened at its first use
and kept open. A forked child does not hold its parent's lock, even one held or waited for as it
forked: it closes its copy of that descriptor as it starts, so the lock cannot outlive a parent that
exits while the child runs, and a use in the child waits for the lock like any other process. A use
the child inherits, by being forked inside it, runs on in the child without the lock. An exception
raised in a use, by its body or by a signal handler (Ctrl-C's KeyboardInterrupt), leaves the lock free
once the exception and its traceback are gone. One that lands just as the descriptor is opened can
leave that descriptor open, without the lock, until the process exits; the next use opens another. A
signal handler must not take the lock or fork; i86 installs none. Every change to a run's metadata
reads it afresh under the lock. Whatever a run's backend reports after it is abandoned (a Claude
process that returns, a subfleet job that finishes, a manual answer saved late) is recorded as
`backend_state`, never as its state.

Backends:
- `subfleet`: Max Ghenis's supervised lanes (`subfleet run --task research`).
- `claude`: Claude Code in print mode, bare (no hooks, memory, CLAUDE.md or MCP servers; it needs
  ANTHROPIC_API_KEY), with only WebSearch and WebFetch. The stream-json transcript is its audit trail.
- `manual`: write the prompt; save the agent's final message as `response.md` in the run's staging
  directory yourself.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .graph import ROOT

RUNS = ROOT / "runs"
WORK = Path.home() / ".cache" / "dc-i86-llm-forecast"
STAGE = Path.home() / ".cache" / "dc-i86-llm-forecast-staging"
JOBS = Path.home() / ".subfleet" / "jobs"  # subfleet's job store: <job_id>/a<N>/ per attempt
# Run states. Anything not known to be finished counts as still going.
FINISHED = {"succeeded", "failed", "cancelled", "canceled", "lost", "killed", "expired", "abandoned"}


# The file lock serializes processes; the mutex serializes threads within one, and is what makes
# the lock reentrant for the thread that holds it. A process takes the file lock through one
# descriptor, opened at its first use and kept open between uses, so a use opens and closes nothing
# once the process has it. _depth changes only with the mutex held; _fd and _fd_path with _fd_guard
# held. A forked child replaces all of them as it starts.
_mutex = threading.RLock()
_depth = 0  # how many uses of the lock the thread holding _mutex is inside
_fd: int | None = None  # this process's descriptor on the lock file
_fd_path: Path | None = None  # the lock file _fd is open on
_fd_guard = threading.Lock()  # held while _fd is opened or closed, and by fork
_pid = os.getpid()  # this process's id, read without a call (see bookkeeping_lock)


def _before_fork() -> None:
    _fd_guard.acquire()


def _after_fork_in_parent() -> None:
    _fd_guard.release()


def _after_fork_in_child() -> None:
    # A forked child holds none of its parent's lock. Its copy of _fd shares the open file, and so
    # the lock, with the parent's (a flock lock belongs to the open file every copy shares), so the
    # child closes it: otherwise the lock would outlive a parent that exits while the child still
    # runs. Fork waits for _fd_guard, so _fd is not half opened or half closed. The child's first use
    # opens a descriptor of its own and waits for the lock like any other process.
    global _mutex, _depth, _fd, _fd_path, _fd_guard, _pid
    fd = _fd
    _mutex, _depth, _fd, _fd_path, _fd_guard, _pid = (threading.RLock(), 0, None, None, threading.Lock(),
                                                      os.getpid())
    if fd is not None:
        try:
            os.close(fd)
        except OSError:
            pass


os.register_at_fork(before=_before_fork, after_in_parent=_after_fork_in_parent,
                    after_in_child=_after_fork_in_child)


def _open(path: Path) -> int:
    """This process's descriptor on the lock file at `path`. Called with _mutex held, outside any use."""
    global _fd, _fd_path
    with _fd_guard:
        if _fd is not None and _fd_path != path:  # the lock file moved (tests point STAGE elsewhere)
            old, _fd = _fd, None
            os.close(old)
        if _fd is None:
            _fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            _fd_path = path
        return _fd


@contextmanager
def bookkeeping_lock():
    """Hold the runs' lock file. Reentrant within a thread; other threads and processes wait.

    A use that a forked child inherits, by forking inside it, runs on in the child without the lock and
    leaves the child's lock alone as it ends (`_pid` tells it apart without a call, where an
    exception could land)."""
    global _depth
    pid = _pid
    with _mutex:
        if _depth:
            _depth += 1
            try:
                yield
            finally:
                if _pid == pid:
                    _depth -= 1
            return
        path = STAGE.with_name(STAGE.name + ".lock")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = None
        try:
            fd = _open(path)
            fcntl.flock(fd, fcntl.LOCK_EX)
            if _pid != pid:
                # Only a child that a signal handler forked as this thread waited gets here: it closed
                # its copy of fd, so its wait went on on a number since reused (closed, it raises).
                raise RuntimeError("forked while waiting for the bookkeeping lock")
            _depth = 1
            yield
        finally:
            if _pid == pid:  # a forked child neither holds its parent's lock nor releases it
                _depth = 0
                if fd is not None:
                    fcntl.flock(fd, fcntl.LOCK_UN)


def run_dirs() -> list[Path]:
    return sorted(p for p in RUNS.iterdir() if (p / "meta.json").exists()) if RUNS.exists() else []


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_meta(run_dir: Path) -> dict:
    path = run_dir / "meta.json"
    return json.loads(path.read_text()) if path.exists() else {}


def write_meta(run_dir: Path, meta: dict) -> None:
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")


def record(run_dir: Path, state: str | None = None, **fields) -> dict:
    """Merge fields (and a state) into a run's metadata, read afresh under the lock. A state that
    arrives for an abandoned or recovered run is kept as `backend_state`: both are final."""
    with bookkeeping_lock():
        meta = read_meta(run_dir)
        meta.update(fields)
        if state is not None:
            meta["backend_state" if meta.get("state") == "abandoned" or meta.get("recovered") else "state"] = state
        write_meta(run_dir, meta)
        return meta


def staged_response(label: str) -> Path:
    return STAGE / label / "response.md"


def still_going(meta: dict) -> bool:
    """Whether a run may still produce an answer. A manual run is done once its answer is staged."""
    if meta.get("state") in FINISHED:
        return False
    if meta.get("backend") == "manual":
        return not staged_response(meta["label"]).exists()
    return True


def abandon(label: str) -> dict:
    with bookkeeping_lock():
        run_dir = RUNS / label
        meta = read_meta(run_dir)
        if not meta:
            raise FileNotFoundError(f"no run {label}")
        if (run_dir / "response.md").exists():
            raise RuntimeError(f"run {label} is already collected")
        meta.update(state="abandoned", abandoned_at=now())
        write_meta(run_dir, meta)
        return meta


def recover(label: str) -> dict:
    """Mark a subfleet run that its supervisor reports lost, but whose agent finished, as succeeded.

    Subfleet reports a run lost, and accepts no answer from it, when processes the agent started are
    still alive after the agent exits ("writers remain after exit receipt"). The agent may still have
    exited 0 with its final message in the attempt's stream-json transcript; for an accepted Claude
    attempt, subfleet's deliverable is exactly that transcript's final `result` text. Recovery takes
    the message only when the job's state is `lost`, the run is neither collected nor abandoned, and
    one attempt exited 0 without a signal and has a transcript with exactly one `result` event, a
    successful one with a non-empty message. It records the attempt, the supervisor's reason, and the
    SHA-256 of the message and of the whole transcript; `seal` copies the transcript only if it is
    unchanged, so the audit reads what recovery read. Recovery is final, like abandonment.
    """
    with bookkeeping_lock():
        run_dir = RUNS / label
        meta = read_meta(run_dir)
        if not meta:
            raise FileNotFoundError(f"no run {label}")
        if meta.get("backend") != "subfleet" or not meta.get("job_id"):
            raise RuntimeError(f"run {label} is not a subfleet run")
        if (run_dir / "response.md").exists() or meta.get("state") == "abandoned" or meta.get("recovered"):
            raise RuntimeError(f"run {label} is already collected, abandoned or recovered")
        proc = subprocess.run(["subfleet", "runs", "show", meta["job_id"], "--json"], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"subfleet runs show failed: {proc.stderr[-1000:]}")
        info = json.loads(proc.stdout)
        state = (info.get("job") or {}).get("state")
        if state != "lost":
            raise RuntimeError(f"run {label}: subfleet reports {state!r}; only a lost run can be recovered")
        why = []
        for a in reversed(info.get("attempts") or []):
            folder = JOBS / a["attempt_id"]
            try:
                exit_ = json.loads((folder / "exit.json").read_text())
                data = (folder / "stdout").read_bytes()
                text = data.decode()
            except (OSError, ValueError) as e:
                why.append(f"{a['attempt_id']}: {e}")
                continue
            results = []
            for raw in text.splitlines():
                try:
                    event = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("type") == "result":
                    results.append(event)
            final, served = parse_stream(text)
            if exit_.get("rc") != 0 or exit_.get("signal") is not None:
                why.append(f"{a['attempt_id']}: exit {exit_}")
            elif len(results) != 1 or results[0].get("subtype") != "success" or results[0].get("is_error") \
                    or not isinstance(results[0].get("result"), str) or not results[0]["result"].strip():
                why.append(f"{a['attempt_id']}: no single successful result in the transcript")
            else:
                meta.update(state="succeeded", backend_state=state, attempt_id=a["attempt_id"],
                            lane_id=a.get("lane_id"), model_served=served, transcript=str(folder / "stdout"),
                            finished_at=(info.get("job") or {}).get("finished_at"),
                            recovered={"at": now(), "attempt_state": a.get("state"),
                                       "supervisor_reason": a.get("quarantine_reason"),
                                       "result_sha256": hashlib.sha256(final.encode()).hexdigest(),
                                       "transcript_sha256": hashlib.sha256(data).hexdigest()})
                write_meta(run_dir, meta)
                return meta
        raise RuntimeError(f"run {label}: no attempt can be recovered ({'; '.join(why) or 'no attempts'})")


def collected_any() -> bool:
    return RUNS.exists() and any((d / "response.md").exists() for d in RUNS.iterdir() if d.is_dir())


def prepare(label: str, prompt_path: Path, prompt_sha: str, backend: str, late: bool = False, **extra) -> Path:
    with bookkeeping_lock():
        run_dir = RUNS / label
        if (run_dir / "meta.json").exists():
            raise FileExistsError(f"run {label} already exists")
        if collected_any() and not late:
            raise RuntimeError("answers are already in runs/; a new run could read them. Pass --late to "
                               "dispatch anyway (the report will flag it)")
        if late:
            extra["late"] = True
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


def dispatch_subfleet(label: str, prompt_path: Path, prompt_sha: str, tier: str, model: str | None,
                      late: bool = False) -> dict:
    run_dir = prepare(label, prompt_path, prompt_sha, "subfleet", late=late, tier=tier, model_pin=model)
    cmd = subfleet_command(run_dir, label, tier, model)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    fields = {"command": cmd, "dispatched_at": now(), "dispatch_stdout": proc.stdout[-4000:],
              "dispatch_rc": proc.returncode}
    for line in proc.stdout.splitlines():
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        job_id = obj.get("job_id") or (obj.get("job") or {}).get("job_id")
        if job_id:
            fields["job_id"] = job_id
            break
    meta = record(run_dir, **fields)  # fresh: the run may have been abandoned while subfleet ran
    if proc.returncode != 0 or "job_id" not in meta:
        raise RuntimeError(f"subfleet dispatch for {label} failed (rc {proc.returncode}): {proc.stderr[-2000:]}")
    return meta


def dispatch_claude(label: str, prompt_path: Path, prompt_sha: str, model: str, late: bool = False) -> dict:
    run_dir = prepare(label, prompt_path, prompt_sha, "claude", late=late, model_pin=model)
    cmd = claude_command(model)
    meta = record(run_dir, command=cmd, dispatched_at=now())
    with open(run_dir / "prompt.md") as stdin:
        proc = subprocess.run(cmd, stdin=stdin, capture_output=True, text=True, cwd=meta["workdir"])
    stage = STAGE / label
    stage.mkdir(parents=True, exist_ok=True)
    (stage / "transcript.jsonl").write_text(proc.stdout)
    final, served = parse_stream(proc.stdout)
    if final:
        (stage / "response.md").write_text(final)
    # Fresh: the run may have been abandoned while it ran.
    return record(run_dir, state="succeeded" if final else "failed", finished_at=now(), rc=proc.returncode,
                  model_served=served, transcript=str(stage / "transcript.jsonl"), stderr=proc.stderr[-2000:])


def refresh_subfleet(run_dir: Path) -> dict:
    """Refresh one subfleet run's state, model and transcript path; write no answer.

    A collected run is final: its metadata is returned untouched, so a later collect cannot point
    its transcript back at the job store."""
    meta = read_meta(run_dir)
    job_id = meta.get("job_id")
    if not job_id or (run_dir / "response.md").exists():
        return meta
    proc = subprocess.run(["subfleet", "runs", "show", job_id, "--json"], capture_output=True, text=True)
    if proc.returncode != 0:
        return record(run_dir, collect_error=proc.stderr[-1000:])
    info = json.loads(proc.stdout)
    job = info.get("job") or {}
    fields = {}
    accepted = [a for a in info.get("attempts", []) if a.get("state") == "succeeded"]
    if accepted:
        a = accepted[-1]
        # attempt_id is '<job_id>/a<N>', the attempt's folder under the job store.
        fields.update(model_served=a.get("model_served"), lane_id=a.get("lane_id"), attempt_id=a.get("attempt_id"),
                      transcript=str(JOBS / a["attempt_id"] / "stdout"))
    with bookkeeping_lock():
        if read_meta(run_dir).get("state") != "abandoned":
            fields["finished_at"] = job.get("finished_at")
        return record(run_dir, state=job.get("state"), **fields)


def seal(run_dir: Path) -> bool:
    """Copy a finished run's answer, transcript and model-input prompt into runs/<label>/.

    Call only once every run has finished. Returns whether the run has an answer.
    """
    with bookkeeping_lock():
        return _seal(run_dir)


def _seal(run_dir: Path) -> bool:
    meta = read_meta(run_dir)
    if (run_dir / "response.md").exists():
        return True
    if meta.get("state") == "abandoned":
        # Abandonment is final, whatever arrived since; a manual answer saved anyway is noted.
        if (meta.get("backend") == "manual" and staged_response(run_dir.name).exists()
                and meta.get("backend_state") != "staged"):
            meta["backend_state"] = "staged"
            write_meta(run_dir, meta)
        return False
    if meta.get("backend") == "manual" and staged_response(run_dir.name).exists():
        meta["state"] = "succeeded"
    if meta.get("state") != "succeeded":
        return False
    # The transcript is read once: what is checked here is what is copied below.
    transcript = Path(meta.get("transcript") or "")
    data = transcript.read_bytes() if transcript.is_file() else None
    if meta.get("backend") == "subfleet" and meta.get("recovered"):
        rec = meta["recovered"]
        answer = parse_stream(data.decode(errors="replace"))[0] if data is not None else ""
        if (data is None or hashlib.sha256(answer.encode()).hexdigest() != rec["result_sha256"]
                or hashlib.sha256(data).hexdigest() != rec.get("transcript_sha256")):
            meta["collect_error"] = "the recovered transcript changed after `i86 recover`"
            write_meta(run_dir, meta)
            return False
    elif meta.get("backend") == "subfleet":
        out = subprocess.run(["subfleet", "runs", "show", meta["job_id"], "--out"], capture_output=True, text=True)
        if out.returncode != 0 or not out.stdout.strip():
            return False
        answer = out.stdout
    if meta.get("backend") == "subfleet":
        attempt = JOBS / meta["attempt_id"] if meta.get("attempt_id") else None
        if attempt and (attempt / "prompt.sent.md").exists():
            sent = (attempt / "prompt.sent.md").read_bytes()
            (run_dir / "prompt.sent.md").write_bytes(sent)
            meta["prompt_sent_sha256"] = hashlib.sha256(sent).hexdigest()
    elif meta.get("backend") in {"claude", "manual"}:
        staged = staged_response(run_dir.name)
        if not staged.exists():
            return False
        answer = staged.read_text()
    else:
        return False
    if data is not None:
        (run_dir / "transcript.jsonl").write_bytes(data)
        meta["transcript_original"] = str(transcript)
        meta["transcript"] = str(run_dir / "transcript.jsonl")
        meta["transcript_sha256"] = hashlib.sha256(data).hexdigest()
    (run_dir / "response.md").write_text(answer)
    meta["collected_at"] = now()
    write_meta(run_dir, meta)
    return True
