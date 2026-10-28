"""Round-14a tilt findings (GPT-6.1 Sol, ~/reviews/dc-i86-llm-forecast/round14/FINDINGS-r14a.out.md):
underflow. A narrow segment's float weights, a width times a tilt, rounded to 0 (an IndexError, or
a ValueError where a float had positive tilt), and a wide segment whose tilt underflows to 0 over
many floats drew there. All forecasts are invented MOCK ones."""

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from test_review_r13_tilt import GRAPH, _full
from test_review_r13b_tilt import _narrow_cases, drawable
from test_tilt_band import _forecasts

from i86 import dists
from i86.simulate import _breaks, _Tilt, simulate

B = 0.495
A = float(np.nextafter(np.nextafter(B, 0.0), 0.0))  # two floats below 49.5%
MID = float(np.nextafter(A, 1.0))
NODE = GRAPH.nodes["dc_animal_initiative_filed"]
CELLS = ["yes_42.0", "yes_49.5", "yes_50.5", "yes_60.0", "yes_72.0"]


def _sample(cdf, band, tilt, u, breaks=()):
    return dists.sample_share_tilted(GRAPH.share_grid, np.asarray(cdf, dtype=float), GRAPH.share_floor,
                                     GRAPH.share_ceiling, *band, np.asarray(u, dtype=float), tilt, breaks,
                                     log2_scale=getattr(tilt, "scale", 0))


def test_a_one_float_band_with_a_tiny_tilt_draws_its_float():
    """Sol F1: a width of 1.1e-16 times a tilt of 1e-310 is 0 as a float; the sampler raised
    IndexError."""
    b = 0.6
    a = float(np.nextafter(b, 0.0))
    x, z = dists.sample_share_tilted([0.5, 0.7], [0.0, 1.0], 0.0, 1.0, a, b, np.array([0.0, 0.5, 0.9]),
                                     lambda v: np.full(np.shape(v), 1e-310), [])
    assert x.tolist() == [b] * 3 and z == 0.0  # Z below 2.5e-324 rounds to 0, as documented


def test_simulate_with_tiny_failing_answers_does_not_crash():
    """Sol F1, through simulate: failing cells 1e-310, passing cells 1, and a band that starts one
    float below 49.5%, a segment of one float with the failing tilt."""
    answers = {k: (1e-310 if float(k[4:]) < 50 else 1.0) for k in CELLS}
    cdf = [0.0 if x < 0.5 else float(np.nextafter(1.0, 0.0)) if x == 0.5 else 1.0 for x in GRAPH.share_grid]
    band = (float(np.nextafter(B, 0.0)), 0.97)
    draws = simulate(GRAPH, _full(NODE.id, answers, cdf), 8, 34, share_band=band, restrict={NODE.id: {True}})
    assert np.all((draws["yes_share"] > band[0]) & (draws["yes_share"] <= band[1]))
    assert np.all(draws["_weight"] > 0), draws["_weight"]


def test_a_float_whose_tilt_rounds_to_5e_324_is_drawn():
    """Sol F1: the tilt is 5e-324 at MID and 0 at 49.5%; the segment's mean tilt as a float is 0, so
    the sampler raised ValueError although MID can be drawn."""
    tilt = lambda v: (B - np.asarray(v, dtype=float)) / (B - A) * 1e-323  # noqa: E731
    assert tilt(np.array([MID, B])).tolist() == [5e-324, 0.0]
    x, z = dists.sample_share_tilted([0.49, 0.5], [0.0, 1.0], 0.0, 1.0, A, B, np.array([0.0, 0.5, 0.99]), tilt, [])
    assert x.tolist() == [MID] * 3 and z == 0.0


def _underflow_case():
    """Sol F3: the 60% answer 5e-324 and the 72% one 1, so that the scaled tilt rises from 0 at 50.5%
    to 5e-324 at 60% and rounds to 0 below about 55%."""
    answers = dict(zip(CELLS, [0.0, 0.0, 0.0, 5e-324, 1.0]))
    cdf = [float(np.clip((x - 0.5) / 0.1, 0.0, 1.0)) if x < 0.6 else float(np.nextafter(1.0, 0.0)) if x == 0.6
           else 1.0 for x in GRAPH.share_grid]
    band = (0.5, 0.97)
    return cdf, band, _Tilt(GRAPH, NODE, _forecasts(NODE, answers, cdf), {True}, band)


def test_a_wide_segment_whose_tilt_underflows_draws_only_where_it_is_positive():
    """Sol F3: at u = 0 the sampler gave 55.000000000000003%, where the tilt is 0."""
    cdf, band, tilt = _underflow_case()
    u = [0.0, 0.5, *np.linspace(0.0, 1.0, 101)[1:-1]]
    x, _ = _sample(cdf, band, tilt, u, _breaks(GRAPH))
    assert np.all((x > band[0]) & (x <= band[1])) and np.all(np.asarray(tilt(x), dtype=float) > 0), x


@pytest.mark.parametrize("ends", [(0.0, 5e-324), (5e-324, 0.0), (0.0, 3e-323)])
def test_a_wide_segment_positive_only_near_one_end_is_drawn_there(ends):
    """A segment (50.5%, 56%] of a tilt rising (or falling) to a few times 5e-324 across (50.5%,
    60%]: both of the sampler's interior probes read 0, and it raised ValueError; cut to its floats
    of positive tilt, it is drawn there, in the order of the floats' tilts."""
    lo, hi = 0.505, 0.56 if ends[0] == 0.0 else 0.6
    tilt = lambda v: np.interp(np.asarray(v, dtype=float), [0.505, 0.6], list(ends))  # noqa: E731
    u = np.linspace(0.0, 1.0, 201)
    x, _ = dists.sample_share_tilted([0.5, 0.7], [0.0, 1.0], 0.0, 1.0, lo, hi, u, tilt, [0.505, 0.6])
    assert np.all((x > lo) & (x <= hi)) and np.all(tilt(x) > 0), x
    assert np.all(np.diff(x) >= 0)  # the inverse is monotone in u


@settings(max_examples=300, deadline=None)
@given(_narrow_cases(), st.sampled_from([5e-324, 1e-320, 1e-310, 2.2250738585072014e-308]),
       st.lists(st.one_of(st.just(0.0), st.floats(0.0, 1.0, exclude_max=True)), min_size=1, max_size=16))
def test_no_draw_lies_where_a_tiny_tilt_is_0_and_none_is_refused(case, tiny, u):
    """Sol F1 and F3: a binary node's answers scaled down to a subnormal size against one answer of 1,
    so that the tilt underflows. Every draw lies where the tilt is positive, and the sampler raises
    ValueError only where `drawable` finds no share with both probability and tilt."""
    node, answers, allowed, band, cdf = case
    if not band[0] < band[1] or node.kind != "binary":
        return  # a binary node's chances scale freely; a categorical node's sum to 1
    answers = {k: v * tiny for k, v in answers.items()}
    answers[sorted(answers)[0]] = 1.0
    tilt = _Tilt(GRAPH, node, _forecasts(node, answers, cdf), allowed, band)
    try:
        x, _ = _sample(cdf, band, tilt, u, _breaks(GRAPH))
    except ValueError:
        assert not drawable(cdf, band, tilt, _breaks(GRAPH)), (band, answers)
        return
    assert np.all((x > band[0]) & (x <= band[1])), (band, x)
    assert np.all(np.asarray(tilt(x), dtype=float) > 0), (band, x, tilt(x))


def test_a_cut_segment_keeps_a_share_mass_as_small_as_a_float_holds():
    """Half of a share mass of 5e-324 rounds to 0; cut to its half of positive tilt, the segment
    keeps the smallest float as its mass and is drawn."""
    tilt = lambda v: np.clip((np.asarray(v, dtype=float) - 0.55) * 1e-322, 0.0, None)  # noqa: E731
    x, _ = dists.sample_share_tilted([0.5, 0.6, 0.7], [0.0, 5e-324, 1.0], 0.0, 1.0, 0.5, 0.6,
                                     np.array([0.0, 0.5, 0.9]), tilt, [])
    assert np.all((x > 0.5) & (x <= 0.6)) and np.all(tilt(x) > 0), x
