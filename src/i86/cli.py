"""Command line: i86 prompt | dispatch | collect | check | audit | simulate.

    i86 prompt                      write prompts/forecaster.md and schemas/template.json
    i86 dispatch subfleet LABEL --tier standard -m opus      (or --tier hard, no -m, for GPT-6.1 Sol)
    i86 dispatch claude LABEL -m claude-opus-5-5
    i86 collect                     refresh subfleet runs; fetch answers once all have finished
    i86 check                       parse every runs/*/response.md into runs/*/response.json
    i86 audit                       check each run's transcript for local file reads
    i86 simulate [--n 20000 --seed 0]
                                    pool the accepted runs into outputs/
    i86 prereg                      hash the prompt, graph, runs and outputs into prereg/SHA256SUMS
                                    and request an OpenTimestamps proof
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from . import audit, graph as graph_mod, prompt, report, runners
from .graph import ROOT
from .response import ResponseError, extract_json, parse, template
from .summarize import pool

PROMPT_PATH = ROOT / "prompts" / "forecaster.md"
TEMPLATE_PATH = ROOT / "schemas" / "template.json"
OUTPUTS = ROOT / "outputs"


def cmd_prompt(args) -> int:
    g = graph_mod.load()
    sha = prompt.write(g, PROMPT_PATH)
    TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TEMPLATE_PATH.write_text(json.dumps(template(g), indent=1) + "\n")
    (PROMPT_PATH.parent / "forecaster.md.sha256").write_text(f"{sha}  forecaster.md\n")
    print(f"{PROMPT_PATH.relative_to(ROOT)} sha256 {sha}")
    return 0


def _prompt_sha() -> str:
    g = graph_mod.load()
    text = prompt.build(g)
    if PROMPT_PATH.read_text() != text:
        raise SystemExit("prompts/forecaster.md is stale; run `i86 prompt` and commit it first")
    return prompt.sha256(text)


def cmd_dispatch(args) -> int:
    sha = _prompt_sha()
    if args.backend == "subfleet":
        meta = runners.dispatch_subfleet(args.label, PROMPT_PATH, sha, args.tier, args.model)
    elif args.backend == "claude":
        meta = runners.dispatch_claude(args.label, PROMPT_PATH, sha, args.model or "claude-opus-5-5")
    else:
        runners.prepare(args.label, PROMPT_PATH, sha, "manual")
        print(f"runs/{args.label}/prompt.md is ready; save the agent's final message as runs/{args.label}/response.md")
        return 0
    print(json.dumps({k: meta.get(k) for k in ("label", "job_id", "backend", "dispatched_at")}))
    return 0


def run_dirs() -> list[Path]:
    return sorted(p for p in runners.RUNS.iterdir() if (p / "meta.json").exists()) if runners.RUNS.exists() else []


def cmd_collect(args) -> int:
    """Refresh every subfleet run; copy answers only once all of them have finished."""
    dirs = run_dirs()
    metas = {d: (runners.refresh_subfleet(d) if runners.read_meta(d).get("backend") == "subfleet"
                 else runners.read_meta(d)) for d in dirs}
    pending = [d.name for d, m in metas.items() if m.get("backend") == "subfleet" and m.get("state") not in runners.TERMINAL]
    if not pending:
        for d, m in metas.items():
            if m.get("backend") == "subfleet":
                runners.fetch_subfleet_output(d)
    for d, meta in metas.items():
        have = (d / "response.md").exists()
        print(f"{d.name:24s} {meta.get('state') or '-':10s} {meta.get('model_served') or '-':18s} response={'yes' if have else 'no'}")
    if pending:
        print(f"{len(pending)} subfleet run(s) still going ({', '.join(pending)}); no answers copied yet")
    return 0


def cmd_check(args) -> int:
    g = graph_mod.load()
    bad = 0
    for d in run_dirs():
        src = d / "response.md"
        if not src.exists():
            continue
        try:
            obj = extract_json(src.read_text())
            parse(g, obj)
        except ResponseError as exc:
            bad += 1
            (d / "problems.txt").write_text("\n".join(exc.problems) + "\n")
            print(f"{d.name}: {len(exc.problems)} problem(s); see runs/{d.name}/problems.txt")
            continue
        (d / "response.json").write_text(json.dumps(obj, indent=1) + "\n")
        (d / "problems.txt").unlink(missing_ok=True)
        print(f"{d.name}: ok")
    return 1 if bad else 0


def cmd_audit(args) -> int:
    worst = 0
    for d in run_dirs():
        meta = runners.read_meta(d)
        path = meta.get("transcript")
        if not path or not Path(path).exists():
            print(f"{d.name}: no transcript recorded")
            continue
        result = audit.audit_transcript(Path(path), meta.get("workdir", ""))
        (d / "audit.json").write_text(json.dumps(result, indent=1) + "\n")
        flag = "ok" if result["passed"] else ("VIOLATION" if result["violations"] else "NO EVENTS")
        worst = max(worst, 0 if result["passed"] else 1)
        print(f"{d.name}: {flag}; {result['events']} events, {result['web_calls']} web calls, "
              f"{len(result['local_calls'])} other local calls")
    return worst


def accepted_runs(g, prompt_sha: str, allow_unaudited: bool = False) -> dict:
    """Runs with a parsed response, the current prompt's hash and a passing audit."""
    runs = {}
    for d in run_dirs():
        resp = d / "response.json"
        if not resp.exists():
            continue
        meta = runners.read_meta(d)
        if meta.get("prompt_sha256") != prompt_sha:
            print(f"excluding {d.name}: made with prompt {str(meta.get('prompt_sha256'))[:12]}, not {prompt_sha[:12]}",
                  file=sys.stderr)
            continue
        audit_path = d / "audit.json"
        result = json.loads(audit_path.read_text()) if audit_path.exists() else None
        if result is None and not allow_unaudited:
            print(f"excluding {d.name}: no audit (run `i86 audit`, or pass --allow-unaudited)", file=sys.stderr)
            continue
        if result is not None and not result.get("passed"):
            print(f"excluding {d.name}: audit failed", file=sys.stderr)
            continue
        runs[d.name] = parse(g, json.loads(resp.read_text()))
    return runs


def cmd_simulate(args) -> int:
    g = graph_mod.load()
    runs = accepted_runs(g, _prompt_sha(), args.allow_unaudited)
    if not runs:
        raise SystemExit("no accepted runs: dispatch, collect and check first")
    result = pool(g, runs, n=args.n, seed=args.seed)
    meta = {d.name: runners.read_meta(d) for d in run_dirs() if d.name in runs}
    report.write(g, result, meta, OUTPUTS)
    print(f"pooled {len(runs)} run(s) into {OUTPUTS.relative_to(ROOT)}/")
    return 0


PREREG = ROOT / "prereg"


def cmd_prereg(args) -> int:
    files = [ROOT / "graph" / "graph.yaml", PROMPT_PATH, TEMPLATE_PATH, *sorted((ROOT / "context").iterdir())]
    for d in run_dirs():
        files += [p for p in (d / "meta.json", d / "response.md", d / "response.json", d / "audit.json",
                              d / "transcript.jsonl") if p.exists()]
    files += sorted(p for p in OUTPUTS.glob("*") if p.is_file())
    lines = [f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.relative_to(ROOT)}" for p in files]
    PREREG.mkdir(exist_ok=True)
    sums = PREREG / "SHA256SUMS"
    sums.write_text("\n".join(lines) + "\n")
    print(f"{len(lines)} files hashed into {sums.relative_to(ROOT)}")
    if args.no_stamp:
        return 0
    proc = subprocess.run(["uvx", "--from", "opentimestamps-client", "ots", "stamp", str(sums)],
                          capture_output=True, text=True)
    print(proc.stdout + proc.stderr)
    return proc.returncode


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="i86", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prompt")
    d = sub.add_parser("dispatch")
    d.add_argument("backend", choices=["subfleet", "claude", "manual"])
    d.add_argument("label")
    d.add_argument("--tier", default="standard", choices=["standard", "hard"])
    d.add_argument("-m", "--model")
    sub.add_parser("collect")
    sub.add_parser("check")
    sub.add_parser("audit")
    s = sub.add_parser("simulate")
    s.add_argument("--n", type=int, default=20000)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--allow-unaudited", action="store_true",
                   help="pool runs with no transcript audit (manual runs); they are still checked otherwise")
    pr = sub.add_parser("prereg")
    pr.add_argument("--no-stamp", action="store_true")
    args = ap.parse_args(argv)
    return {"prompt": cmd_prompt, "dispatch": cmd_dispatch, "collect": cmd_collect, "check": cmd_check,
            "audit": cmd_audit, "simulate": cmd_simulate, "prereg": cmd_prereg}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
