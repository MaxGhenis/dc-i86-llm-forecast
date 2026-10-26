"""Round 5 review probes. Every response here is invented and labelled MOCK."""

import numpy as np
import pytest

from i86.response import parse, share_key
from i86.simulate import condition_restriction, simulate
from i86.summarize import pool, run_summary
from mock import MOCK_response


def _constant(graph, narrowed, standing=1.0):
    obj = MOCK_response(graph)
    for value in obj["nodes"]["ban_status"]["forecasts"].values():
        value.update(repealed=1-standing, congress=0, court=0,
                     not_certified=0, certified=standing)
    for value in obj["nodes"]["fattened_narrowed"]["forecasts"].values():
        value["p"] = narrowed
    return obj


@pytest.mark.parametrize("rare_mass", [1e-12, 2**-53])
def test_round5_smallest_positive_passing_band_counts(graph, rare_mass):
    obj = _constant(graph, 1)
    for x in graph.share_grid:
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = (
            1-rare_mass if x <= .5 else 1)
    result = pool(graph, {"MOCK-small-positive": parse(graph, obj),
                          "MOCK-common": parse(graph, _constant(graph, 0))}, n=2000)
    for cond in ["all", "Y", "Yc", "cutoff_pass"]:
        desc = result["nodes"]["fattened_narrowed"][f"{cond}|given"]
        assert desc["runs"] == 2
        assert desc["p"] == .5


def test_round5_tiny_total_status_mass_counts(graph):
    result = pool(graph, {"MOCK-tiny-status": parse(graph, _constant(graph, 1, 1e-100)),
                          "MOCK-common": parse(graph, _constant(graph, 0))}, n=2000)
    for cond in ["all", "Y", "Yc", "cutoff_pass"]:
        desc = result["nodes"]["fattened_narrowed"][f"{cond}|given"]
        assert desc["runs"] == 2
        assert desc["p"] == .5


def _quadrature(graph, obj, lo, hi):
    """Exact polynomial integrals on the merged share and forecast-cell intervals."""
    pts = sorted({lo, hi, *[x for x in graph.share_grid + graph.pass_cells if lo < x < hi]})
    a, b = np.asarray(pts[:-1]), np.asarray(pts[1:])
    z, wz = np.polynomial.legendre.leggauss(3)
    x = ((a[:, None] + b[:, None])/2 + (b-a)[:, None]/2*z).ravel()
    weights = ((b-a)[:, None]/2*wz).ravel()
    grid = [graph.share_floor, *graph.share_grid, graph.share_ceiling]
    cdf = [0, *obj["nodes"]["yes_share"]["forecasts"]["all"].values(), 1]
    segment = np.searchsorted(grid, x, side="right")-1
    density = np.diff(cdf)[segment]/np.diff(grid)[segment]
    status = obj["nodes"]["ban_status"]["forecasts"]
    cert = np.interp(x, graph.pass_cells, [status[f"yes_{c*100:.1f}"]["certified"] for c in graph.pass_cells])
    uncert = np.interp(x, graph.pass_cells, [status[f"yes_{c*100:.1f}"]["not_certified"] for c in graph.pass_cells])
    court = np.interp(x, graph.pass_cells, [status[f"yes_{c*100:.1f}"]["court"] for c in graph.pass_cells])
    lawsuit = obj["nodes"]["lawsuit_filed"]["forecasts"]
    lawsuit_court = np.interp(x, graph.pass_cells, [lawsuit[f"yes_{c*100:.1f}|blocked"]["p"] for c in graph.pass_cells])
    lawsuit_other = np.interp(x, graph.pass_cells, [lawsuit[f"yes_{c*100:.1f}|not_blocked"]["p"] for c in graph.pass_cells])
    qn = obj["nodes"]["fattened_narrowed"]["forecasts"]
    nc, nu = qn["yes_50.5|certified"]["p"], qn["yes_50.5|not_certified"]["p"]
    qp = obj["nodes"]["pate_treated_banned"]["forecasts"]
    pc = nc*qp["yes_50.5|narrowed_certified"]["p"] + (1-nc)*qp["yes_50.5|not_narrowed_certified"]["p"]
    pu = nu*qp["yes_50.5|narrowed_not_certified"]["p"] + (1-nu)*qp["yes_50.5|not_narrowed_not_certified"]["p"]
    w = weights*density
    standing_mass = np.sum(w*(cert+uncert))
    return {
        "ban_status.certified": np.sum(w*cert)/np.sum(w),
        "lawsuit_filed": np.sum(w*(court*lawsuit_court+(1-court)*lawsuit_other))/np.sum(w),
        "fattened_narrowed": np.sum(w*(cert*nc+uncert*nu))/standing_mass,
        "pate_treated_banned": np.sum(w*(cert*pc+uncert*pu))/standing_mass,
    }


def test_round5_every_exists_if_matches_exact_polynomial_integrals(graph):
    obj = MOCK_response(graph, seed=31)
    fc = parse(graph, obj)
    result = run_summary(graph, fc, 60_000, seed=791)
    for cond, lo, hi in [("all", .5, graph.share_ceiling), ("Y", .5, graph.share_ceiling),
                         ("Yc", .5, .53), ("cutoff_pass", .505-1e-8, .505)]:
        for key, exact in _quadrature(graph, obj, lo, hi).items():
            assert result["nodes"][key][f"{cond}|given"]["p"] == pytest.approx(exact, abs=.008)
            for fail_cond in ["N", "Nc", "cutoff_fail"]:
                assert result["nodes"][key][f"{fail_cond}|given"] is None


def test_round5_restriction_keeps_unrelated_cutoff_uniforms(graph):
    fc = parse(graph, MOCK_response(graph, seed=11))
    r = condition_restriction(graph, graph.nodes["fattened_narrowed"].exists_if, True)
    fail = simulate(graph, fc, 503, 29, fixed_share=.495, continuous_share=.5)
    passed = simulate(graph, fc, 503, 29, fixed_share=.505, continuous_share=.5,
                      restrict=r, defensive=True)
    for node in ["turnout", "denver_io311_passes"]:
        np.testing.assert_array_equal(fail[node], passed[node])


def test_round5_positive_support_can_still_be_missed_with_one_draw(graph):
    obj = _constant(graph, 1)
    for key, value in obj["nodes"]["ban_status"]["forecasts"].items():
        standing = int(key == "yes_50.5")
        value.update(repealed=1-standing, certified=standing)
    for x in graph.share_grid:
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = (
            0 if x <= .5 else (1e-6 if x < .75 else 1))
    result = pool(graph, {"MOCK-rare-support": parse(graph, obj),
                          "MOCK-common": parse(graph, _constant(graph, 0))}, n=1, seed=0)
    desc = result["nodes"]["fattened_narrowed"]["all|given"]
    assert desc["runs"] == 2 and desc["p"] == .5


def test_round5_ess_is_invariant_to_tiny_status_probability(graph):
    fc = parse(graph, _constant(graph, .5, 1e-200))
    summary = run_summary(graph, fc, 100, 0)
    desc = summary["nodes"]["fattened_narrowed"]["cutoff_pass|given"]
    assert desc["ess_min"] == pytest.approx(100)


if __name__ == "__main__":
    # Optional variance experiment, excluded from ordinary pytest collection.
    # Run: .venv/bin/python tests/test_review_r5_weighted.py
    import os
    import resource
    import sys
    import threading
    import time

    from i86.graph import load
    from i86.summarize import describe

    def cap_memory():
        while True:
            rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            if sys.platform != "darwin":
                rss *= 1024
            if rss > 2*1024**3:
                os._exit(137)
            time.sleep(.05)

    threading.Thread(target=cap_memory, daemon=True).start()
    graph = load()
    obj = _constant(graph, .5, 0)
    obj["nodes"]["ban_status"]["forecasts"]["yes_60.0"].update(repealed=0, certified=1)
    for j, x in enumerate(graph.share_grid, 1):
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = (
            j*1e-20 if x <= .70 else 1e-9+j*1e-20)
    fc = parse(graph, obj)
    r = condition_restriction(graph, graph.nodes["fattened_narrowed"].exists_if, True)
    ps, ess, dropped = [], [], 0
    for seed in range(100):
        d = simulate(graph, fc, 20_000, seed, share_band=(.5, graph.share_ceiling),
                     restrict=r, defensive=True)
        desc = describe(graph, "fattened_narrowed", d["fattened_narrowed"], d["_weight"])
        if desc is None:
            dropped += 1
            continue
        ps.append(desc["p"])
        ess.append(desc["ess_min"])
    print({"n": 20_000, "seeds": 100, "conditional_exact": .5, "dropped": dropped,
           "mean": float(np.mean(ps)), "sd": float(np.std(ps, ddof=1)),
           "range": [min(ps), max(ps)], "ess_range": [min(ess), max(ess)],
           "outside_1pt": sum(abs(p-.5) > .01 for p in ps)})
