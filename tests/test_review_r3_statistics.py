"""Round 3 independent review probes, using invented MOCK responses only.

Cases from the round-3 independent review (GPT-6.1 Sol, 2026-10-25), kept as regression tests.
They first ran as strict expected failures against aa6fbad; the fixes made them pass.
"""

import numpy as np
import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from i86 import dists
from i86.graph import load
from i86.report import cell
from i86.response import parse
from i86.simulate import simulate
from i86.summarize import condition_bands, pool
from mock import MOCK_response


@settings(max_examples=40, deadline=None)
@given(
    fs=st.lists(st.integers(0, 1000), min_size=19, max_size=19).map(sorted),
    condition=st.sampled_from(["N", "Y", "Nc", "Yc"]),
)
def test_review_truncated_share_inverts_the_restricted_cdf(graph, fs, condition):
    """F(V) must be uniform on [F(lo), F(hi)], including CDFs with flat sections."""
    fc = parse(graph, MOCK_response(graph))
    fc.values["yes_share"]["all"] = np.asarray(fs) / 1000
    lo, hi = condition_bands(graph)[condition]
    f_lo, f_hi = dists.share_cdf_at(
        graph.share_grid, fc.values["yes_share"]["all"],
        graph.share_floor, graph.share_ceiling, [lo, hi],
    )
    assume(f_hi - f_lo > 1e-6)
    n, seed = 41, 193
    draw = simulate(graph, fc, n, seed, share_band=(lo, hi))["yes_share"]
    expected = f_lo + np.random.default_rng(seed).random(n) * (f_hi - f_lo)
    got = dists.share_cdf_at(
        graph.share_grid, fc.values["yes_share"]["all"],
        graph.share_floor, graph.share_ceiling, draw,
    )
    np.testing.assert_allclose(got, expected, atol=5e-10, rtol=0)
    assert np.all(draw <= hi)
    assert np.all(draw > lo) if lo >= 0.5 else np.all(draw >= lo)


@settings(max_examples=30, deadline=None)
@given(p=st.floats(0, 1), increase=st.floats(0, 1))
def test_review_shared_uniforms_preserve_monotone_cutoff_response(graph, p, increase):
    """Increasing an unrelated binary forecast cannot turn a paired True into False."""
    obj = MOCK_response(graph)
    fs = obj["nodes"]["federal_preemption_2030"]["forecasts"]
    fs["yes_49.5"]["p"] = p
    fs["yes_50.5"]["p"] = p + (1 - p) * increase
    denver = obj["nodes"]["denver_io311_passes"]["forecasts"]
    denver["yes_49.5"]["p"], denver["yes_50.5"]["p"] = 0, 1
    fc = parse(graph, obj)
    fail = simulate(graph, fc, 257, 13, fixed_share=.495, continuous_share=.5)
    passed = simulate(graph, fc, 257, 13, fixed_share=.505, continuous_share=.5)
    assert np.all(passed["federal_preemption_2030"] >= fail["federal_preemption_2030"])
    np.testing.assert_array_equal(passed["denver_io311_passes"], fail["denver_io311_passes"])
    np.testing.assert_array_equal(passed["turnout"], fail["turnout"])


def _MOCK_existence_pair(graph, rare_probability):
    runs = {}
    for label, standing, narrowing in [
        ("MOCK-rare-1", rare_probability, 1),
        ("MOCK-common", 1, 0),
    ]:
        obj = MOCK_response(graph)
        for v in obj["nodes"]["ban_status"]["forecasts"].values():
            v.update(repealed=1-standing, congress=0, court=0,
                     not_certified=0, certified=standing)
        for v in obj["nodes"]["fattened_narrowed"]["forecasts"].values():
            v["p"] = narrowing
        runs[label] = parse(graph, obj)
    return runs


@settings(max_examples=10, deadline=None)
@given(numerator=st.integers(min_value=1, max_value=10))
def test_review_each_positive_existence_condition_counts_equally(numerator):
    """The analytic mean of the two conditional forecasts is exactly (1+0)/2."""
    graph = load()
    # Keep Hypothesis shrinking cheap; review_r3/statistics.json records the same
    # counterexample executed separately with the default 20,000 draws per run.
    result = pool(graph, _MOCK_existence_pair(graph, numerator / 10_000), n=200, seed=0)
    entry = result["nodes"]["fattened_narrowed"]
    assert entry["Y|given"]["runs"] == 2
    assert entry["Y|given"]["p"] == .5


def test_review_report_discloses_missing_conditional_forecaster(graph):
    # Updated after the fix: a forecaster with any positive chance of the ban standing now counts, so
    # the disclosure is tested with one that gives it exactly zero.
    result = pool(graph, _MOCK_existence_pair(graph, 0.0), n=200, seed=0)
    entry = result["nodes"]["fattened_narrowed"]
    assert entry["Y"]["runs"] == 2 and entry["Y|given"]["runs"] == 1
    assert "1 of 2 runs" in cell(graph, "fattened_narrowed", entry, "Y", 2)
