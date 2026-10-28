"""Round-14c tilt finding (GPT-6.1 Sol, ~/reviews/dc-i86-llm-forecast/round14/FINDINGS-r14c.out.md):
a categorical node's tilt sums each allowed option's interpolated chance, each rounded on its own,
so below 2^-1022 the sum can be 0 at a float inside a segment whose exact tilt is positive, and a
draw landed there. All forecasts are invented MOCK ones."""

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from test_review_r13_tilt import GRAPH, _full
from test_review_r13b_tilt import _narrow_cases, drawable
from test_tilt_band import _forecasts

from i86 import dists
from i86.simulate import _breaks, _Tilt, simulate

NODE = GRAPH.nodes["ban_status"]  # options: repealed, congress, court, not_certified, certified
TINY = 5e-324
U = 1.1214372246876283e-307  # Sol's uniform, which falls on the float where the tilt is 0


def _sol_case():
    """Sol's MOCK answers: repealed's chance falls from 5e-324 at 50.5% to 0 at 60%, congress's
    rises from 0 to 5e-324, and repealed is certain at 72%; with repealed and congress allowed,
    their interpolations each round to 0 at 55.25%."""
    answers = {"yes_42.0": [0.2] * 5, "yes_49.5": [0.2] * 5, "yes_50.5": [TINY, 0, 0, 0, 1],
               "yes_60.0": [0, TINY, 0, 0, 1], "yes_72.0": [1, 0, 0, 0, 0]}
    cdf = [float(np.clip((x - 0.5) / 0.1, 0.0, 1.0)) if x < 0.6 else float(np.nextafter(1.0, 0.0)) if x == 0.6
           else 1.0 for x in GRAPH.share_grid]
    band = (0.5, 0.97)
    return answers, cdf, band, _Tilt(GRAPH, NODE, _forecasts(NODE, answers, cdf), {"repealed", "congress"}, band)


def _sample(cdf, band, tilt, u):
    return dists.sample_share_tilted(GRAPH.share_grid, np.asarray(cdf, dtype=float), GRAPH.share_floor,
                                     GRAPH.share_ceiling, *band, np.asarray(u, dtype=float), tilt, _breaks(GRAPH),
                                     log2_scale=tilt.scale)


def test_control_the_tilt_is_0_inside_the_segment():
    """A labelled control (the measurement behind the finding): 0 at 55.25%, 5e-324 one float either
    side."""
    _, _, _, tilt = _sol_case()
    x = np.array([np.nextafter(0.5525, 0.0), 0.5525, np.nextafter(0.5525, 1.0)])
    assert tilt.scale == 0 and np.asarray(tilt(x), dtype=float).tolist() == [TINY, 0.0, TINY]


def test_a_draw_on_a_zero_inside_a_segment_moves_to_a_positive_float():
    """Sol's uniform drew 55.25%, where the tilt is 0; the draw now moves one float, to where it is
    positive."""
    _, cdf, band, tilt = _sol_case()
    x, _ = _sample(cdf, band, tilt, [U, 0.0, 0.5, *np.linspace(0.0, 1.0, 51)[1:-1]])
    assert np.all((x > band[0]) & (x <= band[1])) and np.all(np.asarray(tilt(x), dtype=float) > 0), x
    assert x[0] == np.nextafter(0.5525, 0.0)  # the nearer of the two, and the lower on a tie


def test_control_simulate_gives_every_draw_a_positive_weight():
    """A labelled control, through simulate with the full MOCK response's other nodes: every draw
    meets the restriction (its random uniforms miss the zero, on 19d1303 too)."""
    answers, cdf, band, _ = _sol_case()
    draws = simulate(GRAPH, _full(NODE.id, answers, cdf), 16, 7, share_band=band,
                     restrict={NODE.id: {"repealed", "congress"}})
    assert np.all(draws["_weight"] > 0) and set(draws[NODE.id]) <= {"repealed", "congress"}


def test_off_zero_bisects_when_no_positive_float_is_near():
    """A tilt that is 0 over more than NARROW_FLOATS floats around the draw, positive past them: the
    draw moves by bisection towards the anchor, onto a positive float next to a 0."""
    a, b = 0.5, 0.6
    gap = 0.55 + 1e-9  # the tilt is 0 on (0.54, gap] and positive elsewhere
    tilt = lambda v: np.where((np.asarray(v) > 0.54) & (np.asarray(v) <= gap), 0.0, 1.0)  # noqa: E731
    x = dists._off_zero(0.55, a, b, 0.58, tilt)
    assert tilt(np.array([x]))[0] > 0 and tilt(np.array([np.nextafter(x, 0.0)]))[0] == 0 and x <= 0.58


@st.composite
def _zero_runs(draw):
    """A MOCK tilt of 1 but on runs of 0 within 5,000 floats of 55%, a draw on one of them, and an
    anchor at 58%."""
    runs = sorted(draw(st.lists(st.tuples(st.integers(-5000, 5000), st.integers(0, 3000)), min_size=1, max_size=6)))
    runs = [(lo, lo + width) for lo, width in runs]
    lo, hi = draw(st.sampled_from(runs))
    return runs, draw(st.integers(lo, hi))


CENTER = int(dists._positions(np.array([0.55]))[0])


@settings(max_examples=300, deadline=None)
@given(_zero_runs())
def test_off_zero_finds_the_nearest_positive_float(case):
    """`_off_zero` returns a float of (a, b] where the tilt is positive: the nearest within
    NARROW_FLOATS floats of the draw (the lower of two as near), or else one next to a 0."""
    runs, offset = case

    def tilt(v):
        d = dists._positions(np.asarray(v, dtype=float)) - CENTER
        return np.where(np.any([(d >= lo) & (d <= hi) for lo, hi in runs], axis=0), 0.0, 1.0)

    x0 = float(dists._at([CENTER + offset])[0])
    x = dists._off_zero(x0, 0.5, 0.6, 0.58, tilt)
    assert 0.5 < x <= 0.6 and tilt(np.array([x]))[0] > 0
    d = int(dists._positions(np.array([x]))[0]) - CENTER - offset
    near = [k for k in range(-dists.NARROW_FLOATS, dists.NARROW_FLOATS + 1)
            if tilt(dists._at([CENTER + offset + k]))[0] > 0]
    if near:
        assert d == min(near, key=lambda k: (abs(k), k)), (d, near[:3])
    else:
        assert tilt(dists._at([CENTER + offset + d - 1]))[0] == 0 or tilt(dists._at([CENTER + offset + d + 1]))[0] == 0


@settings(max_examples=300, deadline=None)
@given(_narrow_cases(), st.sampled_from([5e-324, 1e-320, 1e-310, 2.2250738585072014e-308]),
       st.lists(st.one_of(st.just(0.0), st.just(U), st.floats(0.0, 1.0, exclude_max=True)), min_size=1, max_size=16))
def test_no_categorical_draw_lies_where_a_tiny_tilt_is_0(case, tiny, u):
    """The round-14a subnormal property for categorical nodes (a guard: its random uniforms seldom
    land on a lone zero, which the tests above reach directly): every option's chance scaled down to
    a subnormal size, the remainder on an option not allowed (valid answers), and one cell's first
    allowed option certain, so the tilt's scale stays 0 and its sums underflow. Every draw lies where
    the tilt is positive, and the sampler raises ValueError only where `drawable` finds no share
    with both probability and tilt."""
    node, answers, allowed, band, cdf = case
    allowed -= {None}
    if not band[0] < band[1] or node.kind != "categorical" or not allowed or len(allowed) == len(node.options):
        return
    keep = np.array([o in allowed for o in node.options])
    spare = int(np.flatnonzero(~keep)[0])
    scaled = {}
    for k, p in answers.items():
        row = np.where(keep, np.asarray(p, dtype=float) * tiny, 0.0)
        row[spare] = 1.0 - row.sum()
        scaled[k] = row.tolist()
    first = sorted(scaled)[-1]
    scaled[first] = [1.0 if i == int(np.flatnonzero(keep)[0]) else 0.0 for i in range(len(node.options))]
    tilt = _Tilt(GRAPH, node, _forecasts(node, scaled, cdf), allowed, band)
    try:
        x, _ = _sample(cdf, band, tilt, u)
    except ValueError:
        assert not drawable(cdf, band, tilt, _breaks(GRAPH)), (band, scaled)
        return
    assert np.all((x > band[0]) & (x <= band[1])), (band, x)
    assert np.all(np.asarray(tilt(x), dtype=float) > 0), (band, x, tilt(x))
