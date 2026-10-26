"""Invariants of the exact tilted sampler at tiny probabilities. All forecast answers are MOCK.

- Scaling: multiplying every allowed answer of the restricted node by 2^-k leaves the share draws,
  the restricted node's draws and the weights unchanged, for any k that keeps the answers exact
  (simulate._Tilt scales them back up before interpolating).
- Rounding: Z is the exact sum of the segments' masses times their tilt, rounded once.
"""

from fractions import Fraction

import numpy as np
from hypothesis import example, given, settings, strategies as st
from mock import MOCK_response

from i86 import dists
from i86.response import parse, share_key
from i86.simulate import condition_restriction, simulate


def _forecaster(graph, sixteenths, k, cdf_steps):
    # certified = j/16 * 2^-k at the passing cells: j * 2^(-4-k) is exact for k <= 1070.
    obj = MOCK_response(graph)
    for key, row in obj["nodes"]["ban_status"]["forecasts"].items():
        j = sixteenths[key]
        certified = float(Fraction(j, 16) / Fraction(2) ** k)
        row.update(repealed=1.0 - certified, congress=0.0, court=0.0, not_certified=0.0, certified=certified)
    total = np.cumsum(np.asarray(cdf_steps, dtype=float) + 1e-3)
    for x, f in zip(graph.share_grid, total / (total[-1] * 1.05)):
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = float(f)
    return parse(graph, obj)


@settings(max_examples=60, deadline=None)
@given(js=st.lists(st.integers(0, 16), min_size=3, max_size=3).filter(any),
       k=st.sampled_from([1, 60, 1000, 1060, 1070]),
       steps=st.lists(st.floats(0.0, 1.0), min_size=19, max_size=19),
       seed=st.integers(0, 2**16))
def test_restricted_draws_ignore_power_of_two_scaling(graph, js, k, steps, seed):
    keys = list(MOCK_response(graph)["nodes"]["ban_status"]["forecasts"])
    sixteenths = dict(zip(keys, js))
    restrict = condition_restriction(graph, graph.nodes["fattened_narrowed"].exists_if, True)
    base = simulate(graph, _forecaster(graph, sixteenths, 0, steps), 64, seed, restrict=restrict)
    scaled = simulate(graph, _forecaster(graph, sixteenths, k, steps), 64, seed, restrict=restrict)
    np.testing.assert_array_equal(scaled["yes_share"], base["yes_share"])
    np.testing.assert_array_equal(scaled["ban_status"], base["ban_status"])
    np.testing.assert_array_equal(scaled["_weight"], base["_weight"])
    assert set(scaled["ban_status"][scaled["_weight"] > 0]) <= {"certified"}


@settings(max_examples=300, deadline=None)
@given(steps=st.lists(st.one_of(st.floats(0.0, 0.3), st.sampled_from([0.0, 1e-17, 2.0**-60, 1e-200, 5e-324])),
                      min_size=3, max_size=3),
       tilts=st.lists(st.tuples(st.integers(0, 15), st.integers(0, 1074)), min_size=4, max_size=4))
@example(steps=[2.0**-60, 0.0, 0.5], tilts=[(1, 1074), (0, 0), (0, 0), (1, 1074)])
def test_z_is_the_exact_sum_rounded_once(steps, tilts):
    # A tilt constant on each segment, a * 2^-e, is exact, and the segment masses are the float
    # differences of the CDF the sampler itself uses. Z must be the exact sum of mass * tilt, rounded
    # once. The example's exact Z is just over half of 5e-324, so it rounds up to 5e-324. Summing the
    # masses relative to the largest first drops the 2^-60 (1 + 2^-59 rounds to 1), and the exact
    # halfway value left then rounds to 0, the even neighbour.
    grid = [0.25, 0.5, 0.75]
    cdf = np.cumsum(steps)
    t = [float(Fraction(a) / Fraction(2) ** e) for a, e in tilts]
    if not any(m > 0 and x > 0 for m, x in zip(np.diff([0.0, *cdf, 1.0]), t)):
        return

    def tilt(v):
        v = np.asarray(v, dtype=float)
        return np.select([v < 0.25, v < 0.5, v < 0.75], t[:3], t[3])

    _, z = dists.sample_share_tilted(grid, cdf, 0.0, 1.0, 0.0, 1.0, np.array([0.5]), tilt, grid)
    masses = np.diff([0.0, *cdf, 1.0])
    exact = sum((Fraction(float(m)) * Fraction(x) for m, x in zip(masses, t)), Fraction(0))
    assert z == float(exact)
