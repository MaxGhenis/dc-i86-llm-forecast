"""Round 4 review probes; all responses are invented MOCK forecasts.

Cases from the round-4 independent review (GPT-6.1 Sol, 2026-10-25), kept as regression tests.
They first ran as strict expected failures against 6844063; the fixes made them pass.
"""

import numpy as np
import pytest

from i86.response import parse, share_key
from i86.simulate import condition_restriction, simulate
from i86.summarize import pool, run_summary
from mock import MOCK_response


def _MOCK_constant(graph, narrowed, standing=1.0):
    obj = MOCK_response(graph)
    for value in obj["nodes"]["ban_status"]["forecasts"].values():
        value.update(repealed=1-standing, congress=0, court=0,
                     not_certified=0, certified=standing)
    for value in obj["nodes"]["fattened_narrowed"]["forecasts"].values():
        value["p"] = narrowed
    return obj


def test_review_r4_every_existing_exists_if_on_both_sides(graph):
    expected = {
        "passes": {},
        "ban_standing": {"ban_status": frozenset({"certified", "not_certified"})},
    }
    for node in graph.nodes.values():
        if node.exists_if is not None:
            assert condition_restriction(graph, node.exists_if, False) is None
            assert condition_restriction(graph, node.exists_if, True) == expected[node.exists_if.text]


def test_review_r4_varied_status_conditionals_match_closed_forms(graph):
    obj = MOCK_response(graph)
    for x in graph.share_grid:
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = (
            (x - graph.share_floor) / (graph.share_ceiling - graph.share_floor)
        )
    by_cell = {
        "yes_50.5": (.6, .1, .3),
        "yes_60.0": (.4, .2, .4),
        "yes_72.0": (.1, .2, .7),
    }
    for key, (removed, uncert, cert) in by_cell.items():
        obj["nodes"]["ban_status"]["forecasts"][key].update(
            repealed=removed, congress=0, court=0, not_certified=uncert, certified=cert)
    for key, value in obj["nodes"]["fattened_narrowed"]["forecasts"].items():
        value["p"] = .8 if key.endswith("|certified") else .2
    for key, value in obj["nodes"]["pate_treated_banned"]["forecasts"].items():
        value["p"] = {
            "narrowed_certified": .9, "not_narrowed_certified": .3,
            "narrowed_not_certified": .4, "not_narrowed_not_certified": .1,
        }[key.split("|")[1]]
    fc = parse(graph, obj)
    result = run_summary(graph, fc, n=60_000, seed=193)

    def exact(lo, hi, event_cert, event_uncert):
        xs = np.array(sorted({lo, hi, *[x for x in [.505, .6, .72] if lo < x < hi]}))
        cert = np.interp(xs, [.505, .6, .72], [.3, .4, .7])
        uncert = np.interp(xs, [.505, .6, .72], [.1, .2, .2])
        return np.trapezoid(cert*event_cert + uncert*event_uncert, xs) / np.trapezoid(cert+uncert, xs)

    for node, probs in [("fattened_narrowed", (.8, .2)), ("pate_treated_banned", (.78, .16))]:
        entry = result["nodes"][node]
        for condition in ["all", "Y"]:
            assert entry[f"{condition}|given"]["p"] == pytest.approx(
                exact(.5, graph.share_ceiling, *probs), abs=.007)
        assert entry["Yc|given"]["p"] == pytest.approx(exact(.5, .53, *probs), abs=.007)
        assert entry["cutoff_pass|given"]["p"] == pytest.approx(
            (.3*probs[0] + .1*probs[1])/.4, abs=.007)
        for condition in ["N", "Nc", "cutoff_fail"]:
            assert entry[f"{condition}|given"] is None
    restriction = condition_restriction(graph, graph.nodes["fattened_narrowed"].exists_if, True)
    base = simulate(graph, fc, 200, 193, fixed_share=.505)
    restricted = simulate(graph, fc, 200, 193, fixed_share=.505, restrict=restriction)
    for node in ["yes_share", "turnout", "denver_io311_passes", "federal_preemption_2030"]:
        np.testing.assert_array_equal(base[node], restricted[node])


def test_review_r4_small_positive_vote_band_must_not_drop_a_forecaster(graph):
    rare = _MOCK_constant(graph, narrowed=1)
    for x in graph.share_grid:
        rare["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = (
            1-1e-10 if x <= .5 else 1)
    result = pool(graph, {"MOCK-rare": parse(graph, rare),
                          "MOCK-common": parse(graph, _MOCK_constant(graph, narrowed=0))},
                  n=20_000, seed=0)
    entry = result["nodes"]["fattened_narrowed"]
    assert result["per_run"]["MOCK-rare"]["masses"]["Y"] > 0
    conditions = ["all", "Y", "Yc", "cutoff_pass"]
    observed = {c: (entry[f"{c}|given"]["runs"], entry[f"{c}|given"]["p"]) for c in conditions}
    assert observed == dict.fromkeys(conditions, (2, .5))


def test_review_r4_rare_share_support_must_not_drop_a_forecaster(graph):
    rare = _MOCK_constant(graph, narrowed=1)
    for key, value in rare["nodes"]["ban_status"]["forecasts"].items():
        standing = int(key == "yes_50.5")
        value.update(repealed=1-standing, certified=standing)
    for x in graph.share_grid:
        rare["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = (
            0 if x <= .5 else (1e-6 if x < .75 else 1))
    result = pool(graph, {"MOCK-rare-support": parse(graph, rare),
                          "MOCK-common": parse(graph, _MOCK_constant(graph, narrowed=0))},
                  n=20_000, seed=0)
    # Rare's standing probability is 1e-6 times the average standing probability on
    # (.50,.51): 0.5 + 0.5*(1 + 18/19)/2 = 0.9868421052631579.
    # Its conditional narrowed probability is exactly one.
    entry = result["nodes"]["fattened_narrowed"]
    conditions = ["all", "Y", "Yc", "cutoff_pass"]
    observed = {c: (entry[f"{c}|given"]["runs"], entry[f"{c}|given"]["p"]) for c in conditions}
    assert observed == dict.fromkeys(conditions, (2, .5))
