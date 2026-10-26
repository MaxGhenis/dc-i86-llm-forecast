"""Round 7 numerical review probes. Every response is invented and labelled MOCK."""

import numpy as np
import pytest
from mock import MOCK_response

from i86 import dists
from i86.response import parse, share_key
from i86.summarize import run_summary


@pytest.mark.parametrize("probability", [1.0, 1e-200, 1e-300, 1e-308])
def test_round7_constant_tilt_keeps_its_distribution(probability):
    u = np.array([0.25, 0.5, 0.75])
    v, z = dists.sample_share_tilted(
        [.51, .52], [1/3, 2/3], .5, .53, .5, .53, u,
        lambda x: np.full_like(x, probability), [],
    )
    np.testing.assert_allclose(v, [.5075, .515, .5225], atol=1e-15)
    assert z == pytest.approx(probability, rel=1e-14, abs=0)


@pytest.mark.parametrize("probability", [1e-323, 5e-324])
def test_round7_constant_subnormal_tilt_reports_its_mass(probability):
    _, z = dists.sample_share_tilted(
        [.51, .52], [1/3, 2/3], .5, .53, .5, .53, np.array([.5]),
        lambda x: np.full_like(x, probability), [],
    )
    assert z == probability


@pytest.mark.parametrize("tiny", [1e-200, 1e-300])
def test_round7_positive_tilt_is_not_lost_between_unrelated_maxima(tiny):
    v, z = dists.sample_share_tilted(
        [.4, .6], [tiny, 1.0], .2, .8, .2, .8, np.array([.25, .5, .75]),
        lambda x: np.where(x < .4, tiny, np.where(x < .6, 0.0, 1.0)), [.4, .6],
    )
    # The condition's probability is tiny**2 (below the float range), but the
    # conditional remains exactly uniform on (.2, .4].
    assert z == 0.0
    np.testing.assert_allclose(v, [.25, .3, .35], atol=1e-15)


def test_round7_positive_representable_total_mass_survives_unrelated_maxima():
    v, z = dists.sample_share_tilted(
        [.3, .4, .5, .6, .7], [1e-323, 2e-323, 3e-323, 1.0, 1.0],
        .2, .8, .2, .8, np.array([.25, .5, .75]),
        lambda x: np.where(x < .5, .2, np.where(x < .6, 0.0, 1.0)), [.5, .6],
    )
    assert z == 5e-324
    np.testing.assert_allclose(v, [.275, .35, .425], atol=1e-15)


def test_round7_positive_representable_run_survives_midpoint_interpolation(graph):
    obj = MOCK_response(graph)
    for row in obj["nodes"]["ban_status"]["forecasts"].values():
        row.update(repealed=1.0, congress=0.0, court=0.0,
                   not_certified=0.0, certified=5e-324)
    for row in obj["nodes"]["fattened_narrowed"]["forecasts"].values():
        row["p"] = 1.0
    for x in graph.share_grid:
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = (
            0.0 if x < .55 else .8769178269555045 if x < .60 else 1.0)
    summary = run_summary(graph, parse(graph, obj), n=1, seed=0)
    # Y's seed [0, 4] gives share .5525. The true constant condition mass is 5e-324;
    # node_params instead computes 5e-324 * .5 + 5e-324 * .5 = 0.
    for condition in ["all", "Y", "cutoff_pass"]:
        desc = summary["nodes"]["fattened_narrowed"][condition + "|given"]
        assert desc is not None
        assert desc["runs"] == 1 and desc["p"] == 1.0
