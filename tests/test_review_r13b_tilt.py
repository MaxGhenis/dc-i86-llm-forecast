"""Round-13b tilt findings (GPT-6.1 Sol 2; Opus 5.5 m10): a segment a few floats wide. The tilted
sampler read the tilt at two interior points that rounded to one float, so a linear tilt became a
constant one and draws landed where the tilt is 0; its narrow-segment branch fired only for a
segment one float wide. A segment with at most dists.NARROW_FLOATS floats is now drawn over its
floats, and a wider one never on an end float where the tilt is 0. All forecasts are invented MOCK
ones."""

from fractions import Fraction

import numpy as np
from hypothesis import example, given, settings
from hypothesis import strategies as st
from test_review_r13_tilt import GRAPH, _full
from test_tilt_band import _cdf, _forecasts

from i86 import dists
from i86.simulate import _breaks, _Tilt, simulate

B = 0.495
A = float(np.nextafter(np.nextafter(B, 0.0), 0.0))  # two floats below 49.5%
MID = float(np.nextafter(A, 1.0))


def _linear(x):
    """MOCK: 1 at A, 1/2 at MID and 0 at 49.5%."""
    return (B - np.asarray(x, dtype=float)) / (B - A)


def test_a_two_float_segment_draws_only_where_the_tilt_is_positive():
    """Sol 2: at u = 0.75 the sampler gave 49.5%, where the tilt is 0."""
    u = np.array([0.0, 0.25, 0.5, 0.75, float(np.nextafter(1.0, 0.0))])
    x, z = dists.sample_share_tilted([0.49, 0.5], [0.0, 1.0], 0.0, 1.0, A, B, u, _linear, [])
    assert x.tolist() == [MID] * len(u)
    a, b, m = dists.share_segments([0.49, 0.5], np.array([0.0, 1.0]), 0.0, 1.0, A, B)
    # MID stands for (A, MID], half the segment, at tilt 1/2.
    assert z == float(Fraction(float(m[0])) * Fraction(1, 2) * Fraction(1, 2))


def test_a_narrow_segment_s_floats_are_drawn_in_proportion_to_their_tilt():
    """Four floats with MOCK tilts 1, 0, 3, 0 (by position): under evenly spread uniforms, the first
    gets a quarter of the draws and the third three quarters."""
    b = 0.6
    a = float(np.nextafter(np.nextafter(np.nextafter(np.nextafter(b, 0.0), 0.0), 0.0), 0.0))
    xs = dists._floats_in(a, b)
    weights = dict(zip(xs.tolist(), [1.0, 0.0, 3.0, 0.0]))
    x, _ = dists.sample_share_tilted([0.5, 0.7], [0.0, 1.0], 0.0, 1.0, a, b, (np.arange(4000) + 0.5) / 4000,
                                     lambda v: np.array([weights.get(float(t), 0.0) for t in np.atleast_1d(v)]), [])
    counts = {float(t): int((x == t).sum()) for t in xs}
    assert counts == {xs[0]: 1000, xs[1]: 0, xs[2]: 3000, xs[3]: 0}, counts


def test_no_draw_has_weight_0_in_sols_two_float_band():
    """Sol 2: with the 42% answer 1 and the others 0, a band two floats below 49.5% gave 981 of 4,000
    draws weight 0."""
    cdf = [float(np.clip((x - 0.3) / 0.6, 0.0, 1.0)) for x in GRAPH.share_grid]
    answers = {"yes_42.0": 1.0, "yes_49.5": 0.0, "yes_50.5": 0.0, "yes_60.0": 0.0, "yes_72.0": 0.0}
    fc = _full("dc_animal_initiative_filed", answers, cdf)
    draws = simulate(GRAPH, fc, 4000, 5, share_band=(A, B), restrict={"dc_animal_initiative_filed": {True}})
    assert np.all(draws["_weight"] == 1.0) and np.all(draws["yes_share"] == MID)


def _answers(draw, node, keys):
    """MOCK answers, 0 and 1 among them, so that the tilt is 0 at some cells."""
    chance = st.one_of(st.just(0.0), st.just(1.0), st.floats(0.0, 1.0))
    if node.kind == "binary":
        return {k: draw(chance) for k in keys}
    out = {}
    for k in keys:
        w = np.array(draw(st.lists(chance, min_size=len(node.options), max_size=len(node.options))))
        out[k] = (w / w.sum()).tolist() if w.sum() > 0 else [1.0 / len(w)] * len(w)
    return out


def drawable(cdf, band, tilt, breaks) -> bool:
    """Whether some share in the band has both probability and positive tilt, found without the
    sampler: every float of a segment of at most NARROW_FLOATS floats, and the floats inside a wider
    one next to its ends (where a tilt linear on the segment is largest; at b itself the tilt may
    jump to the next piece's value)."""
    a, b, m = dists.share_segments(GRAPH.share_grid, np.asarray(cdf, dtype=float), GRAPH.share_floor,
                                   GRAPH.share_ceiling, *band, breaks)
    for lo, hi, mass in zip(a, b, m):
        if mass <= 0:
            continue
        if dists._float_counts(np.array([lo]), np.array([hi]))[0] <= dists.NARROW_FLOATS:
            xs = dists._floats_in(float(lo), float(hi))
        else:
            xs = np.array([np.nextafter(lo, 1.0), np.nextafter(hi, 0.0)])
        if np.any(np.asarray(tilt(xs), dtype=float) > 0):
            return True
    return False


@st.composite
def _narrow_cases(draw):
    """A node, MOCK answers and an allowed set, and a band whose ends lie within 3,000 floats of the
    cells, 50% and the grid's points, so that segments run from one float to a few thousand."""
    node = GRAPH.nodes[draw(st.sampled_from(["dc_animal_initiative_filed", "ban_status"]))]
    answers = _answers(draw, node, sorted({e.key for e in GRAPH.entries(node)}))
    options = [True, False] if node.kind == "binary" else [*node.options, None]
    allowed = set(draw(st.lists(st.sampled_from(options), min_size=1, unique=True)))
    marks = [0.5, *GRAPH.cells, *GRAPH.share_grid]

    def near():
        x = draw(st.sampled_from(marks))
        steps = draw(st.integers(-3000, 3000))
        return float((np.array([x]).view(np.int64) + steps).view(np.float64)[0])

    lo, hi = sorted([near(), near()])
    cdf = _cdf(draw, GRAPH)
    return node, answers, allowed, (lo, hi), cdf


SOL_2 = (GRAPH.nodes["dc_animal_initiative_filed"],
         {"yes_42.0": 1.0, "yes_49.5": 0.0, "yes_50.5": 0.0, "yes_60.0": 0.0, "yes_72.0": 0.0}, {True}, (A, B),
         [float(np.clip((x - 0.3) / 0.6, 0.0, 1.0)) for x in GRAPH.share_grid])


@settings(max_examples=400, deadline=None)
@example(SOL_2, [0.75])
@given(_narrow_cases(), st.lists(st.one_of(st.just(0.0), st.just(float(np.nextafter(1.0, 0.0))),
                                           st.floats(0.0, 1.0, exclude_max=True)), min_size=1, max_size=16))
def test_no_tilted_draw_lies_where_the_tilt_is_0(case, u):
    node, answers, allowed, band, cdf = case
    if not band[0] < band[1]:
        return
    tilt = _Tilt(GRAPH, node, _forecasts(node, answers, cdf), allowed, band)
    try:
        x, _ = dists.sample_share_tilted(GRAPH.share_grid, np.asarray(cdf, dtype=float), GRAPH.share_floor,
                                         GRAPH.share_ceiling, *band, np.array(u), tilt, _breaks(GRAPH),
                                         log2_scale=tilt.scale)
    except ValueError:  # round 14a, F1: it raised where a float had both
        assert not drawable(cdf, band, tilt, _breaks(GRAPH)), (band, answers)
        return
    assert np.all((x > band[0]) & (x <= band[1])), (band, x)
    assert np.all(np.asarray(tilt(x), dtype=float) > 0), (band, x, tilt(x))
