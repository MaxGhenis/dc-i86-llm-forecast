"""Write the pooled results: outputs/summary.json, summary.md, nodes.csv and runs.csv."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .graph import Graph
from .summarize import headline, summary_keys

COLUMNS = [
    ("N", "Fails"),
    ("Y", "Passes"),
    ("Nc", "Fails narrowly (47–50%)"),
    ("Yc", "Passes narrowly (50–53%)"),
    ("cutoff_fail", "At 49.5%"),
    ("cutoff_pass", "At 50.5%"),
]
FAIL_CONDITIONS = {"N", "Nc", "cutoff_fail"}


def _num(x: float, integer: bool = False) -> str:
    if x is None:
        return "–"
    a = abs(x)
    if a >= 100 or (integer and a >= 10):
        return f"{x:,.0f}"
    if a >= 10:
        return f"{x:.1f}"
    return f"{x:.2f}"


def label(graph: Graph, key: str) -> str:
    node = graph.owner(key)
    if "." in key:
        option = key.split(".", 1)[1]
        return f"`{key}` {node.question.rstrip('.')}: {option}"
    return f"`{key}` {node.question}"


def cell(graph: Graph, key: str, desc: dict | None, condition: str, total_runs: int) -> str:
    node = graph.owner(key)
    if node is not None and node.exists_if is not None and condition in FAIL_CONDITIONS:
        return "n/a"
    if desc is None:
        return "–"
    note = f" ({desc['runs']} of {total_runs} runs)" if desc.get("runs", total_runs) < total_runs else ""
    if "p" in desc:
        return f"{desc['p'] * 100:.0f}%{note}"
    if key == "yes_share":
        return f"{desc['mean'] * 100:.1f}% [{desc['p05'] * 100:.1f}–{desc['p95'] * 100:.1f}]{note}"
    integer = bool(node and node.integer)
    return f"{_num(desc['mean'])} [{_num(desc['p05'], integer)}–{_num(desc['p95'], integer)}]{note}"


def effect(graph: Graph, key: str, x: float) -> str:
    node = graph.owner(key)
    if "." in key or (node is not None and node.kind in {"binary", "derived"}):
        return f"{x * 100:+.1f} pts"
    return f"{x:+,.2f}" if abs(x) < 100 else f"{x:+,.0f}"


def markdown(graph: Graph, result: dict, meta: dict) -> str:
    vote = result["vote"]
    total = len(result["runs"])
    lines = [
        "# Pooled forecasts",
        "",
        f"{total} independent forecaster runs, {result['n_per_run']:,} Monte Carlo draws each (seed "
        f"{result['seed']}). Each column weights every forecaster's own conditional forecast equally, "
        "whatever that forecaster thinks the chance of passing is. Quantities show the mean and the "
        "5th–95th percentile range; yes/no questions show a probability.",
        "",
        "'Fails' and 'Passes' differ for two reasons: what passing does, and what the result says about "
        "voters. Their gap is not an effect. 'At 49.5%' and 'At 50.5%' fix the certified Yes share, with "
        "shared random numbers. Their difference, the cutoff effect, is the forecasters' estimate of what "
        "a bare pass changes; it does not show what passing does in a typical passing world. 'Per Yes "
        "ballot' is the cutoff effect times the chance one ballot decides the measure, in the question's "
        "unit (a probability for yes/no questions). All are model forecasts under stated scenarios.",
        "",
        "## The vote",
        "",
        f"- P(passes): {vote['p_pass'] * 100:.1f}%",
        f"- P(passes with 50–53%): {vote['p_close_pass'] * 100:.1f}%; P(fails with 47–50%): {vote['p_close_fail'] * 100:.1f}%",
        f"- Density of the Yes share at 50%: {vote['density_at_half']:.2f} per unit share",
        f"- Chance one ballot decides it: 1 in {vote['one_in']:,.0f}" if vote["one_in"] else "- Chance one ballot decides it: 0",
        "",
        "| Run | Model | P(passes) | Mean Yes share | 1 ballot decides | Same at every cell | Same at 49.5% and 50.5% |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for rid in result["runs"]:
        v = vote["by_run"][rid]
        mean = result["per_run"][rid]["nodes"]["yes_share"]["all"]["mean"]
        model = (meta.get(rid) or {}).get("model_served") or "?"
        one_in = f"1 in {v['one_in']:,.0f}" if v["one_in"] else "0"
        d = result["per_run"][rid].get("diagnostics") or {}
        flat = f"{d['flat_share'] * 100:.0f}%" if d.get("flat_share") is not None else "–"
        zero = f"{d['zero_jump_share'] * 100:.0f}%" if d.get("zero_jump_share") is not None else "–"
        lines.append(f"| {rid} | {model} | {v['p_pass'] * 100:.0f}% | {mean * 100:.1f}% | {one_in} | {flat} | {zero} |")
    lines += [
        "",
        "The last two columns are the shares of a run's question-and-state groups whose answers are "
        "identical at every cell, and identical at 49.5% and 50.5%. High values can mean copied answers.",
        "",
    ]
    modules = {"vote": "Vote", "implementation": "If it passes", "direct": "Direct outcomes",
               "spillover": "Political spillovers"}
    keys = summary_keys(graph)
    for module, title in modules.items():
        lines += [f"## {title}", ""]
        header = "| Question | Unit | " + " | ".join(t for _, t in COLUMNS) + " | Cutoff effect | Per Yes ballot | Effect by run |"
        lines += [header, "|" + "---|" * (len(COLUMNS) + 5)]
        for key in keys:
            node = graph.owner(key)
            if node.module != module or key == "yes_share":
                continue
            entry = result["nodes"][key]
            unit = node.unit or ("probability" if node.kind in {"binary", "derived", "categorical"} else "")
            cells = " | ".join(cell(graph, key, entry[c], c, total) for c, _ in COLUMNS)
            runs = ", ".join(f"{rid} {effect(graph, key, x)}" for rid, x in entry["cutoff_effect_by_run"].items())
            per = "–" if entry["per_yes_ballot"] is None else f"{entry['per_yes_ballot']:+.2g}"
            lines.append(f"| {label(graph, key)} | {unit} | {cells} | {effect(graph, key, entry['cutoff_effect'])} "
                         f"| {per} | {runs} |")
        lines.append("")
    lines += [
        "Probabilities for questions defined only if the measure passes (or the ban applies) are joint: "
        "P(passes and the event). 'n/a' marks conditions where the question is undefined. In count "
        "distributions the top label ('5+') counts as 5 in means. Quantity tails beyond the 5th and 95th "
        "percentiles continue the neighbouring segment's slope, so means of heavy right tails are "
        "understated.",
        "",
    ]
    return "\n".join(lines)


def write(graph: Graph, result: dict, meta: dict, outdir: Path) -> None:
    from . import plots

    outdir.mkdir(parents=True, exist_ok=True)
    plots.write(graph, result, outdir)
    (outdir / "summary.json").write_text(json.dumps(result, indent=1, sort_keys=True) + "\n")
    (outdir / "summary.md").write_text(markdown(graph, result, meta))
    with open(outdir / "nodes.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["node", "condition", "runs", "mean_or_p", "p05", "p25", "p50", "p75", "p95"])
        for key, entry in result["nodes"].items():
            for cond in ["all", "N", "Y", "Nc", "Yc", "cutoff_fail", "cutoff_pass"]:
                d = entry.get(cond)
                if d is None:
                    continue
                w.writerow([key, cond, d.get("runs"), headline(d), *(d.get(k) for k in ("p05", "p25", "p50", "p75", "p95"))])
    with open(outdir / "runs.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["run", "model", "node", "mean_or_p_all", "mean_or_p_N", "mean_or_p_Y", "cutoff_effect"])
        for rid, r in result["per_run"].items():
            model = (meta.get(rid) or {}).get("model_served")
            for key, entry in r["nodes"].items():
                w.writerow([rid, model, key, headline(entry["all"]), headline(entry["N"]), headline(entry["Y"]),
                            entry["cutoff_effect"]])
