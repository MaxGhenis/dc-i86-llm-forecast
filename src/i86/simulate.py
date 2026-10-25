"""Monte Carlo through the causal map, for one forecaster's response.

A draw picks the certified Yes share (from the forecaster's own `yes_share` CDF, or a fixed value),
then visits nodes in topological order. A node forecast at cells uses the cells on the same side of
50% as the draw, interpolating linearly between neighbouring cells and holding the end cells flat
beyond them; it never mixes a passing cell with a failing one. The exception is a `continuous` node,
which DC's result cannot cause (Denver's same-day vote): it interpolates across 50%, and the cutoff
simulations hold it at 50% in both arms so a bare pass cannot move it. A node forecast in
states uses the state its parents' draws put it in. A node with `exists_if` is false (or, for a
categorical node, the empty string) wherever its condition is false.

Every node draws its uniforms in the same order whatever the draw's values, so two simulations with
the same seed share random numbers. The cutoff contrast (49.5% against 50.5%) uses this.

A simulation can also be restricted to worlds where a condition holds (`restrict`), for questions
defined only under that condition. The restricted node is drawn from the forecaster's answer limited
to the allowed values and renormalized, and each draw carries the weight `_weight`: the probability
the forecaster gave those values at that draw. Weighted means over the draws are then the
forecaster's conditional distribution given the condition (self-normalized importance sampling),
however unlikely the forecaster thinks the condition is.
"""

from __future__ import annotations

import numpy as np

from . import dists
from .graph import Condition, Entry, Graph, Node, assignments, boolean_scope
from .response import Forecasts

# condition_restriction's answer for a condition that depends on more than one random node.
FILTER = "filter"


def condition_restriction(graph: Graph, condition: Condition, passes: bool):
    """How to simulate worlds where `condition` holds, on one side of 50%.

    Returns None if the condition cannot hold on that side, {} if it always holds, {node: allowed
    values} if it depends on one random node (values: options, None for 'does not exist', or
    False/True for a binary node), or FILTER if it depends on more than one.
    """
    scope = boolean_scope(graph, set(condition.names) | {"passes"})
    random = [x for x in scope if x != "passes" and graph.nodes[x].kind != "derived"]
    worlds = [w for w in assignments(graph, scope) if w["passes"] == passes]
    holds = [w for w in worlds if condition.evaluate(w)]
    if not holds:
        return None
    if len(holds) == len(worlds):
        return {}
    if len(random) != 1 or graph.nodes[random[0]].kind not in {"binary", "categorical"}:
        return FILTER
    x = random[0]
    return {x: frozenset(w[x] for w in holds)}


def _cell_weights(cells: list[float], v: np.ndarray):
    """Indices and weights to interpolate between sorted cells at shares v (flat beyond the ends)."""
    c = np.asarray(cells, dtype=float)
    if len(c) == 1:
        z = np.zeros(len(v), dtype=int)
        return z, z, np.zeros(len(v))
    vv = np.clip(v, c[0], c[-1])
    j = np.clip(np.searchsorted(c, vv, side="right") - 1, 0, len(c) - 2)
    w = (vv - c[j]) / (c[j + 1] - c[j])
    return j, j + 1, w


def _table(graph: Graph, node: Node, fc: Forecasts, cells: list[float | None], state: str | None):
    """Answers for one state at the given cells, shape (cells, k).

    A (cell, state) pair that cannot occur has no answer; any answer of the node's stands in for it.
    Draws never use those rows: no draw is in that state on that side of 50%, and draws where the node
    does not exist are masked.
    """
    answers = fc.values[node.id]
    filler = np.atleast_1d(np.asarray(next(iter(answers.values())), dtype=float))
    rows = [np.atleast_1d(np.asarray(answers[Entry(c, state).key], dtype=float))
            if Entry(c, state).key in answers else filler for c in cells]
    return np.vstack(rows)


def node_params(graph: Graph, node: Node, fc: Forecasts, v: np.ndarray, state_idx: np.ndarray | None,
                v_continuous: np.ndarray | None = None):
    """Per-draw parameters, shape (n, k): k=1 for binary, quantiles, pmf probs or the share CDF."""
    n = len(v)
    states = list(node.states) or [None]
    k = None
    out = None
    for s_i, state in enumerate(states):
        if node.cells_mode == "none":
            table = _table(graph, node, fc, [None], state)
            params = np.repeat(table, n, axis=0)
        elif node.continuous:
            table = _table(graph, node, fc, graph.cells, state)
            j0, j1, w = _cell_weights(graph.cells, v if v_continuous is None else v_continuous)
            params = table[j0] * (1 - w)[:, None] + table[j1] * w[:, None]
        else:
            sides = [("pass", graph.pass_cells, v > 0.5)]
            if node.cells_mode == "all":
                sides.append(("fail", graph.fail_cells, v <= 0.5))
            elif node.cells_mode == "near":
                sides = [("pass", graph.near_cells[1:], v > 0.5), ("fail", graph.near_cells[:1], v <= 0.5)]
            params = None
            for _, cells, mask in sides:
                table = _table(graph, node, fc, cells, state)
                j0, j1, w = _cell_weights(cells, v)
                side_params = table[j0] * (1 - w)[:, None] + table[j1] * w[:, None]
                if params is None:
                    # Draws on a side where the node is not forecast get the first side's values;
                    # they are masked out by exists_if.
                    params = side_params
                else:
                    params = np.where(mask[:, None], side_params, params)
        if out is None:
            k = params.shape[1]
            out = np.empty((n, k))
            if state_idx is None:
                return params
        mask = state_idx == s_i
        out[mask] = params[mask]
    return out


def band_mass(graph: Graph, fc: Forecasts, band: tuple[float, float]) -> float:
    """The forecaster's probability that the Yes share lies in (lo, hi]."""
    cdf = np.asarray(fc.values["yes_share"]["all"], dtype=float)
    lo, hi = band
    f = dists.share_cdf_at(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling, np.array([lo, hi]))
    return float(f[1] - f[0])


def simulate(graph: Graph, fc: Forecasts, n: int, seed, fixed_share: float | None = None,
             continuous_share: float | None = None, share_band: tuple[float, float] | None = None,
             restrict: dict | None = None):
    """Draws for every node. Booleans are bool arrays; quantities floats; pmf nodes their value;
    categorical nodes their option name ('' where the node does not exist). `_weight` holds each
    draw's weight: 1 unless `restrict` is given.

    The Yes share is drawn from the forecaster's CDF, fixed (`fixed_share`), or drawn from the CDF
    truncated to a band (`share_band`, (lo, hi]; a band whose lower end is 0.5 or more excludes it).
    `restrict` maps a binary or categorical node to the values it may take (see the module notes).
    """
    rng = np.random.default_rng(seed)
    share_node = graph.nodes["yes_share"]
    cdf = np.asarray(fc.values["yes_share"]["all"], dtype=float)
    u_share = rng.random(n)
    if fixed_share is not None:
        v = np.full(n, float(fixed_share))
    elif share_band is not None:
        # The forecaster's Yes-share distribution truncated to (lo, hi]: inverse CDF on [F(lo), F(hi)].
        lo, hi = share_band
        f_lo, f_hi = dists.share_cdf_at(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling,
                                        np.array([lo, hi]))
        v = dists.sample_share(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling,
                               f_lo + u_share * (f_hi - f_lo))
        v = np.clip(v, np.nextafter(lo, 1.0) if lo >= 0.5 else lo, hi)
    else:
        v = dists.sample_share(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling, u_share)
    draws: dict[str, np.ndarray] = {"yes_share": v, "passes": v > 0.5}
    weight = np.ones(n)
    restrict = restrict or {}
    v_cont = None if continuous_share is None else np.full(n, float(continuous_share))
    for nid in graph.order:
        node = graph.nodes[nid]
        if node is share_node:
            continue
        if node.kind == "derived":
            draws[nid] = node.rule.evaluate_vec(draws)
            continue
        u = rng.random(n)
        exists = node.exists_if.evaluate_vec(draws) if node.exists_if is not None else np.ones(n, bool)
        state_idx = None
        if node.states:
            conds = np.column_stack([c.evaluate_vec(draws) for c in node.states.values()])
            state_idx = np.argmax(conds, axis=1)
        params = node_params(graph, node, fc, v, state_idx, v_cont)
        allowed = restrict.get(nid)
        if allowed is not None and node.kind == "binary":
            p_true = np.where(exists, params[:, 0], 0.0)
            mass = (p_true if True in allowed else 0.0) + ((1 - p_true) if False in allowed else 0.0)
            if allowed == {True}:
                draws[nid] = exists.copy()
            elif allowed == {False}:
                draws[nid] = np.zeros(n, bool)
            else:
                draws[nid] = (u < params[:, 0]) & exists
            weight = weight * mass
        elif allowed is not None and node.kind == "categorical":
            options = list(node.options)
            keep = np.array([o in allowed for o in options], dtype=float)
            p_opts = params * keep[None, :]
            mass_opts = p_opts.sum(axis=1)
            mass = np.where(exists, mass_opts, 1.0 if None in allowed else 0.0)
            ok = mass_opts > 0
            probs = np.where(ok[:, None], p_opts / np.where(ok, mass_opts, 1.0)[:, None], params)
            idx = dists.sample_pmf(probs, u)
            draws[nid] = np.where(exists, np.array(options)[idx], "")
            weight = weight * mass
        elif allowed is not None:
            raise ValueError(f"cannot restrict {node.kind} node {nid}")
        elif node.kind == "binary":
            draws[nid] = (u < params[:, 0]) & exists
        elif node.kind == "quantity":
            lo, hi = node.bounds
            draws[nid] = dists.sample_quantity(graph.quantiles, params, lo, hi, u, node.integer)
        elif node.kind == "pmf":
            idx = dists.sample_pmf(params, u)
            draws[nid] = dists.pmf_values(node.labels)[idx]
        elif node.kind == "categorical":
            idx = dists.sample_pmf(params, u)
            draws[nid] = np.where(exists, np.array(list(node.options))[idx], "")
        else:
            raise ValueError(node.kind)
    draws["_weight"] = weight
    return draws


def decisive_probability(graph: Graph, fc: Forecasts, n: int, seed) -> dict:
    """Chance one ballot decides I-86: density of the vote margin at a tie, in votes.

    With N Yes-plus-No votes and Yes share V, the margin is D = N(2V - 1). One ballot changes the
    outcome at exactly one value of D (a tie or one short, depending on the tie rule), so
    P(decisive) ~ f_D(0) = f_V(1/2) / (2N), averaged over the forecaster's turnout distribution.
    Turnout and share are treated as independent.
    """
    cdf = np.asarray(fc.values["yes_share"]["all"], dtype=float)
    density = dists.share_density_at_half(graph.share_grid, cdf)
    rng = np.random.default_rng(seed)
    node = graph.nodes["turnout"]
    lo, hi = node.bounds
    turnout = dists.sample_quantity(
        graph.quantiles, np.asarray(fc.values["turnout"]["all"]), lo, hi, rng.random(n), node.integer
    )
    p = float(density * np.mean(1.0 / (2.0 * turnout)))
    grid = graph.share_grid
    return {
        "density_at_half": float(density),
        "mean_turnout": float(turnout.mean()),
        "p_decisive": p,
        "one_in": (1.0 / p) if p > 0 else None,
        "p_pass": float(1.0 - cdf[grid.index(0.50)]),
        "p_close_pass": float(cdf[grid.index(0.53)] - cdf[grid.index(0.50)]),
        "p_close_fail": float(cdf[grid.index(0.50)] - cdf[grid.index(0.47)]),
    }
