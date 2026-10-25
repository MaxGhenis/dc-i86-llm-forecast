"""Pool forecasters and summarize every node under each condition.

Each forecaster is simulated on its own. A pooled summary under a condition gives every forecaster's
*own conditional distribution* equal weight: P_pool(X | passes) is the average over forecasters of
P_i(X | passes), whatever each forecaster thinks the chance of passing is. (Pooling the raw draws
instead would let the forecasters who expect it to pass dominate the 'passes' column and those who
expect it to fail dominate the other, so a gap between the columns could reflect who believes what
rather than any effect.) A forecaster with no draws under a condition is left out of that column; the
summary records how many runs contributed.

Conditions:

- all: unconditional.
- N and Y: the measure fails or passes (share at or below, or above, 50%).
- Nc and Yc: the close bands from the graph, 47-50% and 50-53%.
- cutoff_fail and cutoff_pass: the forecaster simulated at a fixed 49.5% and a fixed 50.5% Yes share
  with shared random numbers. Their difference is the forecaster's estimate of what a bare pass
  changes. It says nothing about what passing does in a typical passing world (a 60% win can bring a
  Council less willing to repeal, for example).

Y against N is not an effect: it also carries what the result says about public opinion. Every number
here is a model forecast, not an observation.
"""

from __future__ import annotations

import zlib

import numpy as np

from .graph import Entry, Graph
from .response import Forecasts
from .simulate import decisive_probability, simulate

SUMMARY_QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
CUTOFF = (0.495, 0.505)
CONDITIONS = ("all", "N", "Y", "Nc", "Yc", "cutoff_fail", "cutoff_pass")


def condition_masks(graph: Graph, share: np.ndarray) -> dict[str, np.ndarray]:
    yc_lo, yc_hi = graph.bands["Yc"]
    nc_lo, nc_hi = graph.bands["Nc"]
    return {
        "all": np.ones(len(share), bool),
        "N": share <= 0.5,
        "Y": share > 0.5,
        "Nc": (share >= nc_lo) & (share <= nc_hi),
        "Yc": (share > yc_lo) & (share <= yc_hi),
    }


def summary_keys(graph: Graph) -> list[str]:
    """One key per reported quantity: node ids, and `node.option` for each categorical option."""
    keys = []
    for nid in ["yes_share", "turnout", *[i for i in graph.order if i not in {"yes_share", "turnout"}]]:
        node = graph.nodes[nid]
        keys += [f"{nid}.{o}" for o in node.options] if node.kind == "categorical" else [nid]
    return keys


def values(draws: dict[str, np.ndarray], key: str) -> np.ndarray:
    if "." in key:
        nid, option = key.split(".", 1)
        return np.asarray(draws[nid]) == option
    return draws[key]


def _weighted_quantiles(x: np.ndarray, w: np.ndarray, qs) -> np.ndarray:
    order = np.argsort(x, kind="stable")
    xs, cw = x[order], np.cumsum(w[order])
    cw = cw / cw[-1]
    idx = np.searchsorted(cw, np.asarray(qs) - 1e-12, side="left")
    return xs[np.clip(idx, 0, len(xs) - 1)]


def describe_parts(graph: Graph, key: str, parts: list[np.ndarray]) -> dict | None:
    """Summarize draws from one or more forecasters, each forecaster's draws weighted equally."""
    parts = [np.asarray(p) for p in parts if len(p)]
    if not parts:
        return None
    node = graph.owner(key)
    out: dict = {"runs": len(parts), "n": int(sum(len(p) for p in parts))}
    if parts[0].dtype == bool or (node is not None and node.kind in {"binary", "derived"} and "." not in key):
        out["p"] = float(np.mean([np.mean(p) for p in parts]))
        return out
    x = np.concatenate(parts).astype(float)
    w = np.concatenate([np.full(len(p), 1.0 / len(p)) for p in parts])
    out["mean"] = float(np.mean([np.mean(p) for p in parts]))
    qs = _weighted_quantiles(x, w, SUMMARY_QUANTILES)
    out.update({f"p{round(q * 100):02d}": float(v) for q, v in zip(SUMMARY_QUANTILES, qs)})
    if node is not None and node.kind == "pmf":
        vals = np.array([float(label.rstrip("+")) for label in node.labels])
        out["pmf"] = {label: float(np.mean([np.mean(p == v) for p in parts])) for label, v in zip(node.labels, vals)}
    return out


def describe(graph: Graph, key: str, x: np.ndarray) -> dict | None:
    return describe_parts(graph, key, [x])


def headline(desc: dict | None) -> float | None:
    """The one number for a summary: a probability, or a mean."""
    if desc is None:
        return None
    return desc["p"] if "p" in desc else desc["mean"]


def run_seed(seed: int, label: str) -> list[int]:
    """A run's seed depends on its label only, so adding a run leaves the others' draws unchanged."""
    return [int(seed), zlib.crc32(label.encode())]


def diagnostics(graph: Graph, fc: Forecasts) -> dict:
    """Signs of copied or formula-built answers.

    - flat_share: of the (node, state) groups forecast at two or more cells, the share whose answer is
      identical at every cell.
    - zero_jump_share: of the groups forecast at both 49.5% and 50.5% (Denver excluded), the share
      whose answer is identical at the two.
    """
    groups = flat = jumps = zero = 0
    for node in graph.forecast_nodes():
        cells = graph.cells_for(node)
        if len(cells) < 2:
            continue
        for state in list(node.states) or [None]:
            vals = [fc.values[node.id].get(Entry(c, state).key) for c in cells]
            groups += 1
            flat += all(v == vals[0] for v in vals)
            if CUTOFF[0] in cells and CUTOFF[1] in cells and not node.continuous:
                jumps += 1
                zero += vals[cells.index(CUTOFF[0])] == vals[cells.index(CUTOFF[1])]
    return {
        "groups": groups,
        "flat_share": flat / groups if groups else None,
        "cutoff_groups": jumps,
        "zero_jump_share": zero / jumps if jumps else None,
    }


def run_summary(graph: Graph, fc: Forecasts, n: int, seed) -> dict:
    """Everything for one forecaster: draws by condition, cutoff contrast, decisive odds."""
    seed = [int(x) for x in np.atleast_1d(seed)]
    draws = simulate(graph, fc, n, seed)
    masks = condition_masks(graph, draws["yes_share"])
    # Same-day results DC cannot cause (Denver's) are held at 50% in both arms.
    lo = simulate(graph, fc, n, [*seed, 1], fixed_share=CUTOFF[0], continuous_share=0.5)
    hi = simulate(graph, fc, n, [*seed, 1], fixed_share=CUTOFF[1], continuous_share=0.5)
    nodes, parts = {}, {}
    for key in summary_keys(graph):
        x = values(draws, key)
        by_cond = {c: x[m] for c, m in masks.items()}
        by_cond["cutoff_fail"] = values(lo, key)
        by_cond["cutoff_pass"] = values(hi, key)
        entry = {c: describe(graph, key, v) for c, v in by_cond.items()}
        entry["cutoff_effect"] = float(np.mean(by_cond["cutoff_pass"])) - float(np.mean(by_cond["cutoff_fail"]))
        nodes[key] = entry
        parts[key] = by_cond
    return {
        "parts": parts,
        "nodes": nodes,
        "vote": decisive_probability(graph, fc, n, [*seed, 2]),
        "diagnostics": diagnostics(graph, fc),
    }


def pool(graph: Graph, runs: dict[str, Forecasts], n: int = 20000, seed: int = 0) -> dict:
    """Per-run summaries, plus pooled summaries that weight each forecaster's conditional equally."""
    per_run = {rid: run_summary(graph, fc, n, run_seed(seed, rid)) for rid, fc in sorted(runs.items())}
    if not per_run:
        raise ValueError("no runs to pool")
    votes = [r["vote"] for r in per_run.values()]
    p_dec = [v["p_decisive"] for v in votes]
    pooled_nodes = {}
    for key in summary_keys(graph):
        entry = {c: describe_parts(graph, key, [r["parts"][key][c] for r in per_run.values()]) for c in CONDITIONS}
        effects = [r["nodes"][key]["cutoff_effect"] for r in per_run.values()]
        entry["cutoff_effect"] = float(np.mean(effects))
        entry["cutoff_effect_by_run"] = dict(zip(per_run, effects))
        # Expected change in this outcome from one Yes ballot: each forecaster's chance that the
        # ballot decides the measure times that forecaster's cutoff effect, averaged. Undefined for
        # the vote itself and for Denver's same-day result.
        owner = graph.owner(key)
        entry["per_yes_ballot"] = (
            None if owner.module == "vote" else float(np.mean([p * e for p, e in zip(p_dec, effects)]))
        )
        entry["mean_by_run"] = {rid: headline(r["nodes"][key]["all"]) for rid, r in per_run.items()}
        pooled_nodes[key] = entry
    pooled_vote = {
        "p_decisive": float(np.mean(p_dec)),
        "one_in": float(1.0 / np.mean(p_dec)) if np.mean(p_dec) > 0 else None,
        "density_at_half": float(np.mean([v["density_at_half"] for v in votes])),
        "p_pass": float(np.mean([v["p_pass"] for v in votes])),
        "p_close_pass": float(np.mean([v["p_close_pass"] for v in votes])),
        "p_close_fail": float(np.mean([v["p_close_fail"] for v in votes])),
        "by_run": {rid: r["vote"] for rid, r in per_run.items()},
    }
    return {
        "runs": sorted(per_run),
        "n_per_run": n,
        "seed": seed,
        "nodes": pooled_nodes,
        "vote": pooled_vote,
        "per_run": {rid: {"nodes": r["nodes"], "vote": r["vote"], "diagnostics": r["diagnostics"]}
                    for rid, r in per_run.items()},
    }
