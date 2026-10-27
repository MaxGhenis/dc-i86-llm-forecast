"""Invariants of the band-aware exact tilt. All forecast answers and Yes-share CDFs are MOCK.

The shares simulate may draw under an exact tilt: those in the band as it draws it ([lo, hi], lo
moved just above 50% when the band excludes it) on a stretch between the Yes-share CDF's knots that
holds probability, or the whole band when none does (the draws then get weight 0). The CDFs are
generated with flat stretches.

- Reference: at every share simulate may draw, the tilt divided by 2^scale is the chance the node
  takes an allowed value, computed directly from the unscaled answers (node_params and
  _allowed_mass, the path the defensive mixture uses).
- Irrelevance: answers no such share reads change neither the tilt there nor its scale. Which
  answers a share reads comes from probing the node's interpolated parameters (one answer changed at
  a time, at every cell, end and midpoint of each stretch), not from `_used_answers`.
"""

import math

import numpy as np
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from i86 import graph as graph_mod
from i86.response import Forecasts
from i86.simulate import _allowed_mass, _Tilt, node_params

GRAPH = graph_mod.load()
NODES = ["ban_status", "dc_animal_initiative_filed", "federal_preemption_2030", "dc_bans_other_food_2030"]


def _answers(draw, node, keys):
    if node.kind == "binary":
        return {k: draw(st.floats(1e-3, 1 - 1e-3)) for k in keys}
    out = {}
    for k in keys:
        w = np.array(draw(st.lists(st.floats(1e-3, 1.0), min_size=len(node.options), max_size=len(node.options))))
        out[k] = (w / w.sum()).tolist()
    return out


def _cdf(draw, graph):
    """MOCK: a Yes-share CDF at the grid, its steps between knots positive but for a set left flat."""
    n = len(graph.share_grid) + 1
    steps = np.array(draw(st.lists(st.floats(1e-3, 1.0), min_size=n, max_size=n)))
    steps[sorted(draw(st.sets(st.integers(0, n - 1))))] = 0.0
    assume(steps.sum() > 0)
    return (np.cumsum(steps)[:-1] / steps.sum()).tolist()


@st.composite
def cases(draw):
    graph = GRAPH
    node = graph.nodes[draw(st.sampled_from(NODES))]
    answers = _answers(draw, node, sorted({e.key for e in graph.entries(node)}))
    options = [True, False] if node.kind == "binary" else [*node.options, None]
    allowed = set(draw(st.lists(st.sampled_from(options), min_size=1, unique=True)))
    ends = st.one_of(st.floats(graph.share_floor, graph.share_ceiling),
                     st.sampled_from([0.5, *graph.cells, *graph.share_grid, graph.share_floor, graph.share_ceiling]))
    lo, hi = sorted([draw(ends), draw(ends)])
    # simulate's bands are (lo, hi] with lo < hi; one starting at 50% or above holds no share at lo.
    assume(lo < hi and (lo < 0.5 or float(np.nextafter(lo, 1.0)) <= hi))
    return node, answers, allowed, (lo, hi), _cdf(draw, graph)


def _stretches(graph, cdf, band):
    """The parts of the band simulate may draw from (see the module notes)."""
    lo, hi = band
    lo = float(np.nextafter(lo, 1.0)) if lo >= 0.5 else lo
    xs = [graph.share_floor, *graph.share_grid, graph.share_ceiling]
    fs = [0.0, *cdf, 1.0]
    out = [(max(a, lo), min(b, hi)) for a, b, fa, fb in zip(xs, xs[1:], fs, fs[1:])
           if fb > fa and max(a, lo) < min(b, hi)]
    return out or [(lo, hi)]


def _points(graph, stretches, extra):
    """Each stretch's ends, the cells and 50% inside it, and the points `extra` of the way along it."""
    out = []
    for a, b in stretches:
        inside = [x for x in [*graph.cells, 0.5, float(np.nextafter(0.5, 1.0))] if a <= x <= b]
        out += [a, b, *inside, *np.clip(a + (b - a) * np.asarray(extra), a, b)]
    return np.array(out)


def _forecasts(node, answers, cdf):
    return Forecasts(values={"yes_share": {"all": cdf}, node.id: answers})


def test_tilt_matches_unscaled_answers_where_simulate_draws():
    graph = GRAPH

    @settings(max_examples=400, deadline=None)
    @given(cases(), st.lists(st.floats(0.0, 1.0), min_size=1, max_size=8))
    def check(case, extra):
        node, answers, allowed, band, cdf = case
        fc = _forecasts(node, answers, cdf)
        tilt = _Tilt(graph, node, fc, allowed, band)
        v = _points(graph, _stretches(graph, cdf, band), extra)
        exists = (node.exists_if.evaluate_vec({"yes_share": v, "passes": v > 0.5})
                  if node.exists_if is not None else np.ones(len(v), bool))
        ref = _allowed_mass(node, node_params(graph, node, fc, v, None), exists, allowed)
        got = np.array([math.ldexp(t, -tilt.scale) for t in tilt(v)])
        np.testing.assert_allclose(got, np.broadcast_to(ref, got.shape), rtol=1e-12, atol=0)

    check()


def _params(graph, node, answers, v):
    """The node's interpolated parameters at shares v, where it exists (zero elsewhere)."""
    fc = Forecasts(values={node.id: answers})
    exists = (node.exists_if.evaluate_vec({"yes_share": v, "passes": v > 0.5})
              if node.exists_if is not None else np.ones(len(v), bool))
    return np.where(exists[:, None], node_params(graph, node, fc, v, None), 0.0)


def _read(graph, node, answers, other, stretches):
    """The keys whose answer, replaced alone by its value in `other`, changes the node's
    parameters at some share on the stretches where the node exists. The parameters, not the chance
    of an allowed value: with every value allowed, that chance is 1 whatever the answers but for
    rounding. Interpolation is linear between cells, so each stretch's ends, the cells and 50%
    inside it, and the midpoints between them reach every row with a positive weight."""
    v = []
    for stretch in stretches:
        pts = np.unique(_points(graph, [stretch], []))
        v += [*pts, *((pts[:-1] + pts[1:]) / 2)]
    v = np.array(v)
    base = _params(graph, node, answers, v)
    return {key for key in answers
            if not np.array_equal(_params(graph, node, {**answers, key: other[key]}, v), base)}


def test_unread_answers_change_neither_tilt_nor_scale():
    graph = GRAPH

    @settings(max_examples=400, deadline=None)
    @given(cases(), st.integers(0, 1060), st.lists(st.floats(0.0, 1.0), min_size=1, max_size=8))
    def check(case, k, extra):
        node, answers, allowed, band, cdf = case
        # Tiny answers; certain allowed values in the other set.
        if node.kind == "binary":
            small = {key: p * 2.0 ** -k for key, p in answers.items()}
            certain = {key: 1.0 if True in allowed else 0.0 for key in answers}
        else:
            small = {key: [q * 2.0 ** -k for q in p[:-1]] + [1 - sum(q * 2.0 ** -k for q in p[:-1])]
                     for key, p in answers.items()}
            first = next((i for i, o in enumerate(node.options) if o in allowed), None)
            certain = {key: small[key] if first is None else
                       [1.0 if i == first else 0.0 for i in range(len(node.options))] for key in answers}
        stretches = _stretches(graph, cdf, band)
        read = _read(graph, node, small, certain, stretches)
        loud = {key: small[key] if key in read else certain[key] for key in answers}
        a = _Tilt(graph, node, _forecasts(node, small, cdf), allowed, band)
        b = _Tilt(graph, node, _forecasts(node, loud, cdf), allowed, band)
        v = _points(graph, stretches, extra)
        assert a.scale == b.scale
        np.testing.assert_array_equal(a(v), b(v))

    check()
