"""Pool forecasters and summarize every node under each condition.

Each forecaster is simulated on its own, once per condition:

- all: the Yes share drawn from the forecaster's own distribution.
- N and Y: drawn from that distribution truncated to failing (at most 50%) or passing shares.
- Nc and Yc: truncated to the close bands from the graph, 47-50% and 50-53%.
- cutoff_fail and cutoff_pass: fixed at 49.5% and at 50.5%, with shared random numbers. Their
  difference is the forecaster's estimate of what a bare pass changes. It says nothing about what
  passing does in a typical passing world (a 60% win can bring a Council less willing to repeal, for
  example).

Truncating, rather than filtering one simulation, gives every forecaster the same number of draws in
each condition, however unlikely it thinks that condition is. A pooled summary then gives each
forecaster's *own conditional distribution* equal weight: P_pool(X | passes) is the average over
forecasters of P_i(X | passes). (Pooling the raw draws instead would let the forecasters who expect it
to pass dominate the 'passes' column, so a gap between the columns could reflect who believes what.)
A forecaster that puts no probability on a condition is left out of it; summaries record how many
runs contributed.

For a question defined only under a condition (the ban still standing, say), `<cond>` holds the joint
probability P(condition and event) and `<cond>|given` the conditional P(event | condition).

Y against N is not an effect: it also carries what the result says about public opinion. Every number
here is a model forecast, not an observation.
"""

from __future__ import annotations

import zlib

import numpy as np

from .graph import Entry, Graph
from .response import Forecasts
from .simulate import band_mass, decisive_probability, simulate

SUMMARY_QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
CUTOFF = (0.495, 0.505)
CONDITIONS = ("all", "N", "Y", "Nc", "Yc", "cutoff_fail", "cutoff_pass")


def condition_bands(graph: Graph) -> dict[str, tuple[float, float]]:
    """Yes-share bands (lo, hi] for the conditions simulated by truncation."""
    return {
        "N": (graph.share_floor, 0.5),
        "Y": (0.5, graph.share_ceiling),
        "Nc": tuple(graph.bands["Nc"]),
        "Yc": tuple(graph.bands["Yc"]),
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
            here = [c for c in cells if graph.possible(node, c, state)]
            if len(here) < 2:
                continue
            cells_here = here
            vals = [fc.values[node.id].get(Entry(c, state).key) for c in cells_here]
            groups += 1
            flat += all(v == vals[0] for v in vals)
            if CUTOFF[0] in cells_here and CUTOFF[1] in cells_here and not node.continuous:
                jumps += 1
                zero += vals[cells_here.index(CUTOFF[0])] == vals[cells_here.index(CUTOFF[1])]
    return {
        "groups": groups,
        "flat_share": flat / groups if groups else None,
        "cutoff_groups": jumps,
        "zero_jump_share": zero / jumps if jumps else None,
    }


def run_summary(graph: Graph, fc: Forecasts, n: int, seed) -> dict:
    """Everything for one forecaster: draws by condition, cutoff contrast, decisive odds."""
    seed = [int(x) for x in np.atleast_1d(seed)]
    sims = {"all": simulate(graph, fc, n, seed)}
    masses = {}
    for i, (cond, band) in enumerate(condition_bands(graph).items()):
        masses[cond] = band_mass(graph, fc, band)
        sims[cond] = simulate(graph, fc, n, [*seed, 3 + i], share_band=band) if masses[cond] > 1e-9 else None
    # Same-day results DC cannot cause (Denver's) are held at 50% in both arms.
    sims["cutoff_fail"] = simulate(graph, fc, n, [*seed, 1], fixed_share=CUTOFF[0], continuous_share=0.5)
    sims["cutoff_pass"] = simulate(graph, fc, n, [*seed, 1], fixed_share=CUTOFF[1], continuous_share=0.5)
    nodes, parts = {}, {}
    for key in summary_keys(graph):
        owner = graph.owner(key)
        by_cond: dict[str, np.ndarray] = {}
        for cond in CONDITIONS:
            draws = sims[cond]
            if draws is None:
                by_cond[cond] = np.array([], dtype=bool)
                if owner.exists_if is not None:
                    by_cond[f"{cond}|given"] = np.array([], dtype=bool)
                continue
            x = values(draws, key)
            by_cond[cond] = x
            if owner.exists_if is not None:
                by_cond[f"{cond}|given"] = x[owner.exists_if.evaluate_vec(draws)]
        entry = {c: describe(graph, key, v) for c, v in by_cond.items()}
        entry["cutoff_effect"] = float(np.mean(by_cond["cutoff_pass"])) - float(np.mean(by_cond["cutoff_fail"]))
        nodes[key] = entry
        parts[key] = by_cond
    return {
        "parts": parts,
        "nodes": nodes,
        "masses": masses,
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
        conds = next(iter(per_run.values()))["parts"][key]
        entry = {c: describe_parts(graph, key, [r["parts"][key][c] for r in per_run.values()]) for c in conds}
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
        "per_run": {rid: {"nodes": r["nodes"], "vote": r["vote"], "diagnostics": r["diagnostics"],
                          "masses": r["masses"]} for rid, r in per_run.items()},
    }
