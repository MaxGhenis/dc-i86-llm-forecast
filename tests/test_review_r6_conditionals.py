"""Round 6 conditional probes. All forecast answers are invented and labelled MOCK."""

import numpy as np
import pytest
from mock import MOCK_response

from i86 import dists
from i86.response import parse, share_key
from i86.simulate import condition_restriction
from i86.summarize import pool, run_summary


def _tiny_standing(graph, support=(.55, .60), probability=1e-200):
    obj = MOCK_response(graph)
    for x in graph.share_grid:
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = float(x > support[0])
    for key, value in obj["nodes"]["ban_status"]["forecasts"].items():
        v = float(key.split("_")[1]) / 100
        certified_fraction = min(1.0, max(0.0, (v-.505)/(.60-.505)))
        value.update(repealed=1.0, congress=0.0, court=0.0,
                     not_certified=probability*(1-certified_fraction),
                     certified=probability*certified_fraction)
    for key, value in obj["nodes"]["fattened_narrowed"]["forecasts"].items():
        value["p"] = float(key.endswith("|certified"))
    return obj


def test_round6_tilt_is_invariant_to_positive_constant_scaling():
    u = np.array([.25, .50, .75])
    ordinary, _ = dists.sample_share_tilted([.5], [0.0], .15, .97, .5, .97, u,
                                           lambda v: np.ones_like(v), [])
    tiny, z = dists.sample_share_tilted([.5], [0.0], .15, .97, .5, .97, u,
                                       lambda v: np.full_like(v, 1e-200), [])
    assert z == pytest.approx(1e-200, rel=1e-14, abs=0)
    np.testing.assert_allclose(tiny, ordinary, rtol=0, atol=1e-14)


@pytest.mark.parametrize("support", [(.55, .60), (.51, .52)])
def test_round6_tiny_standing_conditionals_match_closed_form(graph, support):
    obj = _tiny_standing(graph, support)
    fc = parse(graph, obj)
    summary = run_summary(graph, fc, 20_000, 1)
    expected = ((support[0]+support[1])/2-.505)/(.60-.505)
    conditions = ["all", "Y", *(["Yc"] if support[1] <= .53 else [])]
    actual = {}
    for cond in conditions:
        desc = summary["nodes"]["fattened_narrowed"][cond+"|given"]
        assert desc["ess_min"] == pytest.approx(20_000)
        actual[cond] = desc["p"]
    assert actual == pytest.approx(dict.fromkeys(conditions, expected), abs=.01)


@pytest.mark.parametrize("n", [1, 37])
def test_round6_positive_subnormal_condition_is_not_dropped(graph, n):
    rare = _tiny_standing(graph, probability=1e-323)
    common = _tiny_standing(graph, probability=1.0)
    for obj, narrowed, standing in [(rare, 1.0, 1e-323), (common, 0.0, 1.0)]:
        for value in obj["nodes"]["ban_status"]["forecasts"].values():
            value.update(repealed=1-standing, congress=0.0, court=0.0,
                         not_certified=0.0, certified=standing)
        for x in graph.share_grid:
            obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = (
                0.0 if x <= .5 else 1/3 if x <= .51 else 2/3 if x <= .52 else 1.0)
        for value in obj["nodes"]["fattened_narrowed"]["forecasts"].values():
            value["p"] = narrowed
    result = pool(graph, {"MOCK-positive-subnormal": parse(graph, rare),
                          "MOCK-common": parse(graph, common)}, n=n, seed=0)
    for condition in ["all", "Y", "Yc", "cutoff_pass"]:
        desc = result["nodes"]["fattened_narrowed"][condition+"|given"]
        assert desc["runs"] == 2
        assert desc["p"] == .5


def test_round6_tilt_is_linear_between_merged_breaks(graph):
    from i86.simulate import exact_tilt

    obj = MOCK_response(graph, seed=57)
    fc = parse(graph, obj)
    restrict = condition_restriction(graph, graph.nodes["fattened_narrowed"].exists_if, True)
    _, tilt, breaks = exact_tilt(graph, fc, restrict)
    merged = sorted({graph.share_floor, graph.share_ceiling, *breaks, *graph.share_grid})
    a, b = np.array(merged[:-1]), np.array(merged[1:])
    x = a+(b-a)/4
    y = a+(b-a)/2
    z = a+3*(b-a)/4
    np.testing.assert_allclose(tilt(y), (tilt(x)+tilt(z))/2, rtol=1e-13, atol=1e-14)


def test_round6_tiny_weights_ess_stays_finite(graph):
    obj = _tiny_standing(graph)
    summary = run_summary(graph, parse(graph, obj), 37, 17)
    for cond in ["all", "Y", "cutoff_pass"]:
        desc = summary["nodes"]["fattened_narrowed"][cond+"|given"]
        assert np.isfinite(desc["ess_min"])
        assert desc["ess_min"] == pytest.approx(37)
