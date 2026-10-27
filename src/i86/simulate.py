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

When the restricted node depends on nothing but the Yes share (no states, and an `exists_if`, if any,
on `passes` alone), as `ban_status` does, the chance that a draw meets the restriction is a
piecewise-linear function of the share, and the share is drawn exactly from the forecaster's
distribution tilted by it (dists.sample_share_tilted). Every draw then has weight 1 (the
condition's probability within the band, Z, is kept as `_mass`): the draws come from the
conditional distribution itself, so plain means over them estimate it without the variance that
weights add (bar the band's segments more than 2^1074 times less likely under the tilt than the
likeliest, which get no draws); each draw counts fully, and a forecaster who gives the condition any
probability in the band is never dropped, whatever the sample size or however small the probability.
Otherwise the share is drawn defensively (`defensive`, see dists.sample_share_band), so a condition
that holds only at shares the forecaster thinks unlikely still gets draws; the share's weight
multiplies into `_weight`.
"""

from __future__ import annotations

import math

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


def _lerp(table: np.ndarray, j0: np.ndarray, j1: np.ndarray, w: np.ndarray) -> np.ndarray:
    """Rows of `table` interpolated between cells j0 and j1, clipped to the two rows' range: a value
    both cells give comes back exactly, and one between two positive values stays positive, however
    small (5e-324 * 0.5 + 5e-324 * 0.5 would otherwise round to 0)."""
    lo, hi = table[j0], table[j1]
    out = lo * (1 - w)[:, None] + hi * w[:, None]
    return np.clip(out, np.minimum(lo, hi), np.maximum(lo, hi))


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
            params = _lerp(table, j0, j1, w)
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
                side_params = _lerp(table, j0, j1, w)
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


def _allowed_mass(node: Node, params: np.ndarray, exists: np.ndarray, allowed) -> np.ndarray:
    """Per draw, the forecaster's probability that a binary or categorical node takes one of
    `allowed` (None in `allowed` stands for 'does not exist')."""
    if node.kind == "binary":
        p_true = np.where(exists, params[:, 0], 0.0)
        return (p_true if True in allowed else 0.0) + ((1 - p_true) if False in allowed else 0.0)
    keep = np.array([o in allowed for o in node.options], dtype=float)
    return np.where(exists, (params * keep[None, :]).sum(axis=1), 1.0 if None in allowed else 0.0)


def _used_answers(graph: Graph, node: Node, answers: dict, lo: float, hi: float) -> set[str]:
    """The keys of the answers that the tilt reads at some share in (lo, hi]: on each side of 50%
    the span reaches where the node exists, the cells that node_params gives a positive weight
    between the lowest and highest shares of the span's part there (a cell an end lies exactly on
    has weight 0 on its other side). The failing side is (lo, min(hi, 50%)], so a span starting at
    50% has none; its lowest share is the float above lo, which on a span one float wide is hi
    itself. A key without an answer stands for the filler row (see _table)."""
    if node.cells_mode == "none":
        keys = {Entry(None, None).key}
    else:
        half = float(np.nextafter(0.5, 1.0))
        if node.cells_mode == "all":
            fail, passing = graph.fail_cells, graph.pass_cells
        elif node.cells_mode == "near":
            fail, passing = graph.near_cells[:1], graph.near_cells[1:]
        else:
            fail = passing = graph.pass_cells  # the passing cells' answers serve every share
        keys = set()
        first_share = float(np.nextafter(lo, 1.0))
        for cells, a, b, part in [(fail, first_share, min(hi, 0.5), min(hi, 0.5) > lo),
                                  (passing, max(first_share, half), hi, hi > max(lo, 0.5))]:
            ends = np.array([a, b])
            if not part or (node.exists_if is not None
                            and not node.exists_if.evaluate_vec({"yes_share": ends, "passes": ends > 0.5}).any()):
                continue
            j0, j1, w = _cell_weights(cells, ends)
            first = int(j0[0]) if w[0] < 1 else int(j1[0])
            last = int(j1[1]) if w[1] > 0 else int(j0[1])
            keys |= {Entry(c, None).key for c in cells[first:last + 1]}
    if keys - set(answers):
        keys.add(next(iter(answers)))
    return keys & set(answers)


class _Tilt:
    """The chance that a node takes an allowed value, as a function of the share, times 2^scale.

    The node's answers are cut to the allowed values (a binary node's to p, or 1 - p, or 1) and
    multiplied by 2^scale before they are interpolated, with `scale` >= 0 chosen so the largest is at
    least 1/2. Multiplying by a power of two is exact, so for ordinary probabilities this only rescales
    the tilt. It matters below about 2.2e-308, where floats lose precision: interpolated there, a
    chance rising from 0 to 5e-324 between two cells would round to 0 over half the segment, where the
    sampler, taking the tilt as linear, still draws. Scaled first, the tilt is positive wherever its
    exact value is at least 2^-1022, against a largest value of at least 1/2.

    Only what the shares simulate may draw can use sets the scale: shares in `band` ((lo, hi], by
    default the whole range) on the segments the sampler gives probability, each open at its left
    end as the samplers draw it, the answers they interpolate from, and absence where the node may
    not exist there. The other
    answers are set to 0, which the draws never read and which cannot overflow, so an answer of 1 at
    a cell no draw reaches leaves a tiny tilt its precision. A band without probability has no such
    shares (simulate then raises), and every answer is set to 0.
    """

    def __init__(self, graph: Graph, node: Node, fc: Forecasts, allowed,
                 band: tuple[float, float] | None = None):
        self.graph, self.node = graph, node
        answers = fc.values[node.id]
        if node.kind == "binary":
            rows = {key: (p if True in allowed else 0.0) + ((1 - p) if False in allowed else 0.0)
                    for key, p in ((key, float(p)) for key, p in answers.items())}
            # A binary node that does not exist counts as False (see _allowed_mass).
            self.absent = 1.0 if False in allowed else 0.0
        else:
            keep = np.array([o in allowed for o in node.options])
            rows = {key: np.where(keep, np.asarray(p, dtype=float), 0.0) for key, p in answers.items()}
            self.absent = 1.0 if None in allowed else 0.0
        lo, hi = band if band is not None else (graph.share_floor, graph.share_ceiling)
        # The segments of the band the sampler draws from (dists.sample_share_tilted's, those with
        # probability), each (a, b]: the samplers draw above a and at most b, so a segment starting
        # at 50% holds no failing share.
        a, b, m = dists.share_segments(graph.share_grid, np.asarray(fc.values["yes_share"]["all"], dtype=float),
                                       graph.share_floor, graph.share_ceiling, lo, hi, _breaks(graph))
        spans = [(float(x), float(y)) for x, y, mass in zip(a, b, m) if mass > 0]
        used = set().union(*(_used_answers(graph, node, answers, a, b) for a, b in spans))
        rows = {key: r if key in used else np.zeros_like(r) for key, r in rows.items()}
        # A share on each side of 50% that a span reaches (whether the node exists there depends only
        # on the side, see `_tilted`).
        ends = np.array([v for a, b in spans for v, side in ((min(b, 0.5), a < 0.5), (b, b > 0.5)) if side])
        if node.exists_if is None or self.exists(ends).all():
            self.absent = 0.0  # never used: the node exists at every share in the band
        top = max(float(np.sum(r)) for r in [*rows.values(), self.absent])
        self.scale = max(0, -math.frexp(top)[1]) if top > 0 else 0
        scaled = {key: np.ldexp(r, self.scale).tolist() for key, r in rows.items()}
        self.fc = Forecasts(values={**fc.values, node.id: scaled})

    def exists(self, v: np.ndarray) -> np.ndarray:
        draws = {"yes_share": v, "passes": v > 0.5}
        return self.node.exists_if.evaluate_vec(draws) if self.node.exists_if is not None else np.ones(len(v), bool)

    def params(self, v) -> np.ndarray:
        """Per draw, the allowed values' scaled chances (shape (n, 1) for a binary node)."""
        return node_params(self.graph, self.node, self.fc, np.asarray(v, dtype=float), None)

    def __call__(self, v) -> np.ndarray:
        v = np.asarray(v, dtype=float)
        return np.where(self.exists(v), self.params(v).sum(axis=1), math.ldexp(self.absent, self.scale))


def _tilted(graph: Graph, restrict: dict | None):
    """(node id, allowed values) when a restriction can be met by drawing the share exactly: one
    binary or categorical node with no states whose `exists_if`, if any, mentions only `passes`."""
    if not restrict or len(restrict) != 1:
        return None
    (nid, allowed), = restrict.items()
    node = graph.nodes[nid]
    if node.kind not in {"binary", "categorical"} or node.states or node.continuous:
        return None
    if node.exists_if is not None and set(node.exists_if.names) - {"passes"}:
        return None
    return nid, allowed


def exact_tilt(graph: Graph, fc: Forecasts, restrict: dict | None, band: tuple[float, float] | None = None):
    """(node id, tilt, breaks) when a restriction can be met by drawing the share exactly (see
    `_tilted`). `tilt(v)` (a _Tilt) is the chance the node takes an allowed value at share v in
    `band`, times 2^tilt.scale, linear between `breaks`."""
    tilted = _tilted(graph, restrict)
    if tilted is None:
        return None
    nid, allowed = tilted
    return nid, _Tilt(graph, graph.nodes[nid], fc, allowed, band), _breaks(graph)


def _breaks(graph: Graph) -> list[float]:
    """The shares where a node's answers may change slope or jump: 50% and the cells."""
    return sorted({0.5, *graph.cells, *graph.near_cells})


def band_mass(graph: Graph, fc: Forecasts, band: tuple[float, float]) -> float:
    """The forecaster's probability that the Yes share lies in (lo, hi]."""
    cdf = np.asarray(fc.values["yes_share"]["all"], dtype=float)
    lo, hi = band
    f = dists.share_cdf_at(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling, np.array([lo, hi]))
    return float(f[1] - f[0])


def simulate(graph: Graph, fc: Forecasts, n: int, seed, fixed_share: float | None = None,
             continuous_share: float | None = None, share_band: tuple[float, float] | None = None,
             restrict: dict | None = None, defensive: bool = False):
    """Draws for every node. Booleans are bool arrays; quantities floats; pmf nodes their value;
    categorical nodes their option name ('' where the node does not exist). `_weight` holds each
    draw's weight: 1 unless `restrict` is given.

    The Yes share is drawn from the forecaster's CDF, fixed (`fixed_share`), or drawn from the CDF
    truncated to a band (`share_band`, (lo, hi]; a band whose lower end is 0.5 or more excludes it).
    `restrict` maps a binary or categorical node to the values it may take; the share is then drawn
    exactly from its tilted distribution where `exact_tilt` allows, and otherwise, with `defensive`,
    from a defensive mixture (see the module notes).
    """
    rng = np.random.default_rng(seed)
    share_node = graph.nodes["yes_share"]
    cdf = np.asarray(fc.values["yes_share"]["all"], dtype=float)
    u_share = rng.random(n)
    weight = np.ones(n)
    exact = fixed_share is None and _tilted(graph, restrict) is not None
    if fixed_share is None and share_band is None and (defensive or exact):
        share_band = (graph.share_floor, graph.share_ceiling)
    tilt = exact_tilt(graph, fc, restrict, share_band) if exact else None
    if fixed_share is not None:
        v = np.full(n, float(fixed_share))
    elif tilt is not None:
        # The share given the restriction, drawn exactly, so every draw counts equally. The
        # restriction's probability within the band (which can underflow to 0 for a condition far
        # below 1e-300) is kept apart, never as a weight.
        lo, hi = share_band
        try:
            v, z = dists.sample_share_tilted(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling,
                                             lo, hi, u_share, tilt[1], tilt[2], log2_scale=tilt[1].scale)
            feasible = True
        except ValueError:
            # The restriction cannot hold in the band: every draw gets weight 0.
            v, _ = dists.sample_share_band(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling,
                                           lo, hi, u_share)
            z, feasible = 0.0, False
        v = np.clip(v, np.nextafter(lo, 1.0) if lo >= 0.5 else lo, hi)
        weight = np.full(n, 1.0 if feasible else 0.0)
    elif share_band is not None:
        # The forecaster's Yes-share distribution truncated to (lo, hi].
        lo, hi = share_band
        v, weight = dists.sample_share_band(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling,
                                            lo, hi, u_share, defensive=0.5 if defensive else 0.0)
        v = np.clip(v, np.nextafter(lo, 1.0) if lo >= 0.5 else lo, hi)
    else:
        v = dists.sample_share(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling, u_share)
    draws: dict[str, np.ndarray] = {"yes_share": v, "passes": v > 0.5}
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
        if tilt is not None and tilt[0] == nid:
            # Under an exact tilt the share already carries this probability. The draw uses the
            # tilt's own scaled answers, so the allowed values keep their proportions however small;
            # a draw where the tilt is 0 (at a segment's end, or where its scaled value is below
            # 2^-1022) cannot meet the restriction.
            weight = np.where(tilt[1](v) > 0, weight, 0.0)
            if node.kind == "categorical":
                params = tilt[1].params(v)
        elif allowed is not None and node.kind in {"binary", "categorical"}:
            weight = weight * _allowed_mass(node, params, exists, allowed)
        if allowed is not None and node.kind == "binary":
            if allowed == {True}:
                draws[nid] = exists.copy()
            elif allowed == {False}:
                draws[nid] = np.zeros(n, bool)
            else:
                draws[nid] = (u < params[:, 0]) & exists
        elif allowed is not None and node.kind == "categorical":
            options = list(node.options)
            keep = np.array([o in allowed for o in options], dtype=float)
            p_opts = params * keep[None, :]
            mass_opts = p_opts.sum(axis=1)
            ok = mass_opts > 0
            probs = np.where(ok[:, None], p_opts / np.where(ok, mass_opts, 1.0)[:, None], params)
            idx = dists.sample_pmf(probs, u)
            draws[nid] = np.where(exists, np.array(options)[idx], "")
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
    if tilt is not None:
        draws["_mass"] = np.full(n, z)
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
