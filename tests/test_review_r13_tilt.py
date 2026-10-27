"""Round-13 tilt findings: the shares the samplers draw are (a, b] on each segment, and the exact tilt
takes its scale and absence only from those. All forecasts are invented MOCK ones.

- A: a segment starting at 50% holds no failing share, so the 49.5% answer, which only a share at 50%
  would read, leaves the scale and the weights alone.
- B: absence the node never has at a drawn share does not set the scale.
- C: no draw lands on the band's lower end, which (lo, hi] excludes.
- D: a band whose only probability is the one float above 50% draws that float, a passing share, and
  its mass is that float's probability times the passing answer.
- Every draw of either sampler lies inside a segment (a, b] with probability.
"""

from fractions import Fraction

import numpy as np
from hypothesis import given, settings
from hypothesis import strategies as st
from mock import MOCK_response

from i86 import dists
from i86.response import parse
from i86.simulate import _breaks, _Tilt, exact_tilt, simulate
from test_tilt_band import GRAPH, _forecasts, _stretches, cases

HALF_UP = float(np.nextafter(0.5, 1.0))
# MOCK: no probability at or below 50%, and uniform on (50%, 55%].
PASSING_CDF = [float(np.clip((x - 0.5) / 0.05, 0.0, 1.0)) for x in GRAPH.share_grid]


def _full(node_id, answers, cdf):
    """MOCK forecasts for every node (tests/mock.py), with one node's answers and the Yes-share CDF
    replaced, for runs of simulate itself."""
    fc = parse(GRAPH, MOCK_response(GRAPH))
    fc.values = {**fc.values, node_id: answers, "yes_share": {"all": list(cdf)}}
    return fc


def test_a_failing_answer_only_50_percent_reads_leaves_scale_and_weights():
    """A: no probability at or below 50%; the (50%, 50.5%] segment has probability but a tilt of 0,
    so the draws lie above 50.5%, where they read only the passing answers."""
    restrict = {"dc_animal_initiative_filed": {True}}
    scales = set()
    for later in (5e-324, 1.0):
        answers = {"yes_42.0": 0.0, "yes_49.5": later, "yes_50.5": 0.0, "yes_60.0": 5e-324, "yes_72.0": 5e-324}
        fc = _full("dc_animal_initiative_filed", answers, PASSING_CDF)
        scales.add(exact_tilt(GRAPH, fc, restrict)[1].scale)
        draws = simulate(GRAPH, fc, 64, 34, restrict=restrict)
        assert np.all(draws["_weight"] == 1.0), later
        assert np.all(draws["yes_share"] > 0.505), later
    assert len(scales) == 1 and scales.pop() > 0


def test_absence_never_drawn_leaves_scale_and_weights():
    """B: ban_status exists only where I-86 passes, and every drawn share passes, so allowing its
    absence changes nothing: the scale and the weights are those of {certified} alone."""
    rows = {"yes_50.5": 0.0, "yes_60.0": 5e-324, "yes_72.0": 5e-324}
    answers = {key: [1 - p, 0.0, 0.0, 0.0, p] for key, p in rows.items()}  # repealed .. certified
    fc = _full("ban_status", answers, PASSING_CDF)
    out = []
    for allowed in ({"certified"}, {None, "certified"}):
        restrict = {"ban_status": allowed}
        tilt = exact_tilt(GRAPH, fc, restrict)[1]
        draws = simulate(GRAPH, fc, 64, 34, restrict=restrict)
        assert tilt.absent == 0.0, allowed
        assert np.all(draws["_weight"] == 1.0), allowed
        out.append((tilt.scale, draws["yes_share"].tolist()))
    assert out[0] == out[1] and out[0][0] > 0


def test_no_draw_lands_on_the_bands_lower_end():
    """C: u = 0 picks the first fraction of the first segment, whose left end is lo."""
    cdf = np.array([0.5 * (1 + np.tanh((x - 0.55) / 0.08)) for x in GRAPH.share_grid])
    u = np.array([0.0, 0.5, float(np.nextafter(1.0, 0.0))])
    for lo, hi in [(0.42, 0.97), (0.15, 0.5), (0.47, 0.5), (0.5, 0.6)]:
        v, _ = dists.sample_share_band(GRAPH.share_grid, cdf, GRAPH.share_floor, GRAPH.share_ceiling, lo, hi, u)
        w, _ = dists.sample_share_tilted(GRAPH.share_grid, cdf, GRAPH.share_floor, GRAPH.share_ceiling, lo, hi, u,
                                         lambda x: np.ones_like(np.asarray(x, dtype=float)), _breaks(GRAPH))
        for draws in (v, w):
            assert np.all((draws > lo) & (draws <= hi)), (lo, hi, draws)


def test_a_one_float_band_above_50_percent_draws_that_float():
    """D: the band (49.5%, the float above 50%] has probability only on that float, where the tilt is
    the 50.5% answer; the failing answers at 50% and below are never drawn."""
    cdf = [float(min(0.4, x / 0.45 * 0.4)) if x <= 0.50 else min(1.0, 0.4 + 0.6 * (x - 0.5) / 0.4)
           for x in GRAPH.share_grid]
    answers = {"yes_42.0": 0.9, "yes_49.5": 0.9, "yes_50.5": 0.001, "yes_60.0": 0.001, "yes_72.0": 0.001}
    band = (0.495, HALF_UP)
    fc = _full("dc_animal_initiative_filed", answers, cdf)
    draws = simulate(GRAPH, fc, 4000, 5, share_band=band, restrict={"dc_animal_initiative_filed": {True}})
    assert np.all(draws["yes_share"] == HALF_UP) and np.all(draws["passes"])
    a, b, m = dists.share_segments(GRAPH.share_grid, np.asarray(cdf), GRAPH.share_floor, GRAPH.share_ceiling,
                                   *band, _breaks(GRAPH))
    exact = sum((Fraction(float(mass)) * Fraction(0.001) for x, mass in zip(a, m) if x >= 0.5), Fraction(0))
    assert exact > 0 and float(draws["_mass"][0]) == float(exact)


def _inside_a_stretch(v, stretches) -> np.ndarray:
    return np.array([any(a < x <= b for a, b in stretches) for x in v])


@settings(max_examples=300, deadline=None)
@given(cases(), st.lists(st.one_of(st.just(0.0), st.floats(0.0, 1.0, exclude_max=True)), min_size=1, max_size=8))
def test_every_draw_lies_in_a_segment_with_probability(case, u):
    """Both samplers, at any uniforms (0 among them), draw only shares inside one of their own
    segments (a, b] that the forecaster gives probability: the band sampler's are cut at the CDF's
    knots, the tilted sampler's at the cells and 50% too (its stretches, `_stretches`)."""
    node, answers, allowed, band, cdf = case
    u = np.array(u)
    stretches = _stretches(GRAPH, cdf, band)
    grid = (GRAPH.share_grid, np.asarray(cdf, dtype=float), GRAPH.share_floor, GRAPH.share_ceiling, *band)
    a, b, m = dists.share_segments(*grid)
    v, _ = dists.sample_share_band(*grid, u, defensive=0.5)
    assert _inside_a_stretch(v, [(x, y) for x, y, mass in zip(a, b, m) if mass > 0]).all(), (band, v)
    tilt = _Tilt(GRAPH, node, _forecasts(node, answers, cdf), allowed, band)
    try:
        w, _ = dists.sample_share_tilted(*grid, u, tilt, _breaks(GRAPH), log2_scale=tilt.scale)
    except ValueError:
        return  # no segment with both probability and tilt
    assert _inside_a_stretch(w, stretches).all(), (band, w)


def test_e_a_segment_one_float_wide_reads_only_its_right_end():
    """E (found by test_tilt_band's irrelevance property): in the band (the float below 49.5%, 50%],
    the segment up to the 49.5% cell is one float wide, so its only share is 49.5% itself, where the
    42% answer has weight 0. That answer, set to 1, used to set the scale."""
    node = GRAPH.nodes["dc_animal_initiative_filed"]
    cdf = [round(0.05 * (i + 1), 2) for i in range(len(GRAPH.share_grid))]  # MOCK: 5% more per grid step
    band = (float(np.nextafter(0.495, 0.0)), 0.5)
    small = {k: 0.25 for k in ("yes_42.0", "yes_49.5", "yes_50.5", "yes_60.0", "yes_72.0")}
    tilts = [_Tilt(GRAPH, node, _forecasts(node, answers, cdf), {True}, band)
             for answers in (small, {**small, "yes_42.0": 1.0})]
    v = np.array([0.495, float(np.nextafter(0.495, 1.0)), 0.4975, 0.5])
    assert tilts[0].scale == tilts[1].scale == 1
    assert np.array_equal(tilts[0](v), tilts[1](v))
