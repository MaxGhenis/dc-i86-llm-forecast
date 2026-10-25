import math

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from i86 import dists
from i86.graph import Entry
from i86.response import parse, quantile_key, share_key
from i86.simulate import decisive_probability, simulate
from i86.summarize import CUTOFF, pool, run_seed, run_summary
from mock import MOCK_response

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]


@st.composite
def quantiles(draw):
    lo = draw(st.floats(-1e4, 1e4))
    width = draw(st.floats(1.0, 1e5))
    hi = lo + width
    xs = sorted(draw(st.lists(st.floats(lo, hi), min_size=5, max_size=5)))
    return lo, hi, xs


@settings(max_examples=200, deadline=None)
@given(quantiles())
def test_quantity_sampler_returns_the_forecast_quantiles_and_stays_in_bounds(q):
    lo, hi, xs = q
    at_levels = dists.sample_quantity(LEVELS, [xs], lo, hi, np.array(LEVELS))
    np.testing.assert_allclose(at_levels, xs, rtol=1e-9, atol=1e-6 * (hi - lo))
    u = np.linspace(0, 1, 401)
    out = dists.sample_quantity(LEVELS, [xs], lo, hi, u)
    assert np.all(np.diff(out) >= -1e-9 * (hi - lo))
    assert out.min() >= lo - 1e-9 and out.max() <= hi + 1e-9


@st.composite
def cdfs(draw):
    raw = sorted(draw(st.lists(st.floats(0, 1), min_size=19, max_size=19)))
    return raw


@settings(max_examples=200, deadline=None)
@given(cdfs(), st.floats(0.001, 0.999))
def test_share_sampler_inverts_the_forecast_cdf(graph, cdf, u):
    x = dists.sample_share(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling, np.array([u]))[0]
    assert graph.share_floor <= x <= graph.share_ceiling
    f = dists.share_cdf_at(graph.share_grid, cdf, graph.share_floor, graph.share_ceiling, x)
    assert abs(f - u) < 1e-6


def test_pmf_sampler_matches_probabilities():
    probs = np.array([0.1, 0.2, 0.3, 0.4])
    idx = dists.sample_pmf(probs, np.random.default_rng(0).random(200_000))
    freq = np.bincount(idx, minlength=4) / len(idx)
    np.testing.assert_allclose(freq, probs, atol=0.005)


@pytest.fixture(scope="module")
def mock_fc(graph):
    return parse(graph, MOCK_response(graph, seed=3))


@pytest.fixture(scope="module")
def draws(graph, mock_fc):
    return simulate(graph, mock_fc, 40_000, seed=11)


def test_structural_invariants_hold_in_every_draw(graph, draws):
    passes = draws["yes_share"] > 0.5
    assert np.array_equal(draws["passes"], passes)
    for node in graph.nodes.values():
        x = draws[node.id]
        exists = node.exists_if.evaluate_vec(draws) if node.exists_if is not None else np.ones(len(x), bool)
        if node.kind == "categorical":
            assert np.array_equal(x != "", exists), node.id
            assert set(np.unique(x[exists])) <= set(node.options), node.id
        elif node.exists_if is not None:
            assert not np.any(x & ~exists), node.id
        if node.kind == "quantity":
            assert x.min() >= node.bounds[0] and x.max() <= node.bounds[1], node.id
            if node.integer:
                assert np.all(x == np.rint(x)), node.id
    assert np.array_equal(draws["ban_applies"], draws["ban_status"] == "applies")
    assert not np.any(draws["ban_applies"] & ~passes)
    assert not np.any(draws["pate_treated_banned"] & ~draws["ban_applies"])
    assert not np.any(draws["fattened_narrowed"] & ~draws["ban_applies"])


def test_categorical_draws_match_the_forecast_probabilities(graph, mock_fc):
    x = simulate(graph, mock_fc, 100_000, seed=8, fixed_share=0.60)["ban_status"]
    probs = mock_fc.values["ban_status"]["yes_60.0"]
    for option, p in zip(graph.nodes["ban_status"].options, probs):
        assert abs(np.mean(x == option) - p) < 0.01, option


def test_simulation_is_deterministic(graph, mock_fc):
    a = simulate(graph, mock_fc, 1000, seed=5)
    b = simulate(graph, mock_fc, 1000, seed=5)
    for k in a:
        assert np.array_equal(a[k], b[k]), k


def test_pass_share_matches_the_cdf(graph, mock_fc, draws):
    f50 = mock_fc.values["yes_share"]["all"][graph.share_grid.index(0.5)]
    assert abs(np.mean(draws["passes"]) - (1 - f50)) < 0.01


def test_fixed_cell_reproduces_the_cell_forecast(graph, mock_fc):
    for cell in graph.cells:
        x = simulate(graph, mock_fc, 60_000, seed=2, fixed_share=cell)
        p = mock_fc.values["dc_animal_initiative_filed"][Entry(cell, None).key]
        assert abs(np.mean(x["dc_animal_initiative_filed"]) - p) < 0.01
        q = mock_fc.values["dc_council_farmed_animal_bills"][Entry(cell, None).key]
        assert abs(np.median(x["dc_council_farmed_animal_bills"]) - q[2]) <= 1.0
        # A `near` node holds its nearer cell flat beyond it, on the same side of 50%.
        near = graph.near_cells[1] if cell > 0.5 else graph.near_cells[0]
        p = mock_fc.values["federal_preemption_2030"][Entry(near, None).key]
        assert abs(np.mean(x["federal_preemption_2030"]) - p) < 0.01


def test_interpolation_never_mixes_a_passing_cell_with_a_failing_one(graph):
    obj = MOCK_response(graph)
    for nid in ["dc_animal_initiative_filed", "federal_preemption_2030"]:
        for entry_key, value in obj["nodes"][nid]["forecasts"].items():
            value["p"] = 1.0 if float(entry_key.split("_")[1]) > 50 else 0.0
    fc = parse(graph, obj)
    x = simulate(graph, fc, 20_000, seed=1)
    for nid in ["dc_animal_initiative_filed", "federal_preemption_2030"]:
        assert np.all(x[nid] == x["passes"]), nid


def test_denver_is_continuous_and_held_fixed_across_the_cutoff(graph):
    obj = MOCK_response(graph)
    f = obj["nodes"]["denver_io311_passes"]["forecasts"]
    for key in f:
        f[key]["p"] = 0.2
    f["yes_49.5"]["p"], f["yes_50.5"]["p"] = 0.3, 0.7  # a gap a forecaster should not enter
    fc = parse(graph, obj)
    x = simulate(graph, fc, 200_000, seed=3, fixed_share=0.5)
    assert abs(np.mean(x["denver_io311_passes"]) - 0.5) < 0.01  # interpolated across 50%
    summary = run_summary(graph, fc, 4000, [0, 1])
    assert summary["nodes"]["denver_io311_passes"]["cutoff_effect"] == 0.0


def test_shared_random_numbers_make_unaffected_nodes_identical_across_the_cutoff(graph):
    obj = MOCK_response(graph)
    # Make one node's forecast identical at 49.5% and 50.5%: its cutoff effect must be exactly zero.
    f = obj["nodes"]["other_foie_gras_bans_2030"]["forecasts"]
    f["yes_50.5"] = dict(f["yes_49.5"])
    fc = parse(graph, obj)
    lo = simulate(graph, fc, 5000, seed=4, fixed_share=CUTOFF[0])
    hi = simulate(graph, fc, 5000, seed=4, fixed_share=CUTOFF[1])
    assert np.array_equal(lo["other_foie_gras_bans_2030"], hi["other_foie_gras_bans_2030"])
    assert np.array_equal(lo["turnout"], hi["turnout"])


def test_decisive_probability_agrees_with_the_normal_formula(graph):
    # Against the closed form used in the v1 guide (pivot.py): with a normal Yes share and a known
    # turnout, P = phi((0.5 - m) / s) / s / (2N). This shares the 1/(2N) step with the code; the next
    # test checks that step independently.
    m, s, n_votes = 0.58, 0.06, 185_000
    obj = MOCK_response(graph, share_mean=m, share_sd=s)
    obj["nodes"]["turnout"]["forecasts"]["all"] = {quantile_key(q): n_votes for q in graph.quantiles}
    fc = parse(graph, obj)
    got = decisive_probability(graph, fc, 2000, seed=0)["p_decisive"]
    z = (0.5 - m) / s
    want = math.exp(-z * z / 2) / math.sqrt(2 * math.pi) / s / (2 * n_votes)
    assert got == pytest.approx(want, rel=0.01)


def test_decisive_probability_matches_an_exact_tie_count(graph):
    # Brute force with no 1/(2N) step: a Yes ballot (against abstaining) decides the measure exactly
    # when the other N - 1 ballots tie. For each sampled turnout N, P(tie) is the binomial point
    # probability at (N - 1)/2 (zero when N - 1 is odd), integrated over the forecaster's own
    # piecewise-linear Yes-share distribution.
    m, s = 0.53, 0.05
    obj = MOCK_response(graph, share_mean=m, share_sd=s)
    obj["nodes"]["turnout"]["forecasts"]["all"] = dict(zip(
        [quantile_key(q) for q in graph.quantiles], [60_000, 62_000, 64_000, 66_000, 68_000]))
    fc = parse(graph, obj)
    got = decisive_probability(graph, fc, 4000, seed=0)["p_decisive"]

    xs, fs = dists.share_knots(graph.share_grid, fc.values["yes_share"]["all"], graph.share_floor,
                               graph.share_ceiling)
    v = np.linspace(0.45, 0.55, 40_001)
    density = np.diff(fs) / np.diff(xs)
    f_v = density[np.clip(np.searchsorted(xs, v, side="right") - 1, 0, len(density) - 1)]
    dv = v[1] - v[0]
    node = graph.nodes["turnout"]
    turnouts = dists.sample_quantity(graph.quantiles, np.asarray(fc.values["turnout"]["all"]), *node.bounds,
                                     np.random.default_rng(1).random(400), integer=True)
    ties = []
    for n_votes in turnouts.astype(int):
        others = n_votes - 1
        if others % 2:
            ties.append(0.0)
            continue
        k = others // 2
        log_pmf = (math.lgamma(others + 1) - 2 * math.lgamma(k + 1) + k * np.log(v) + k * np.log1p(-v))
        ties.append(float(np.sum(np.exp(log_pmf) * f_v) * dv))
    assert got == pytest.approx(np.mean(ties), rel=0.05)


def test_pooling_weights_each_forecasters_conditional_equally(graph):
    a = parse(graph, MOCK_response(graph, seed=1, share_mean=0.55))
    b = parse(graph, MOCK_response(graph, seed=2, share_mean=0.70))
    result = pool(graph, {"a": a, "b": b}, n=4000, seed=0)
    ra = run_summary(graph, a, 4000, run_seed(0, "a"))
    rb = run_summary(graph, b, 4000, run_seed(0, "b"))
    assert result["vote"]["p_pass"] == pytest.approx((ra["vote"]["p_pass"] + rb["vote"]["p_pass"]) / 2)
    for key in ["foie_gras_menus", "paf_statewide_2028", "ban_status.applies"]:
        want = (ra["nodes"][key]["cutoff_effect"] + rb["nodes"][key]["cutoff_effect"]) / 2
        assert result["nodes"][key]["cutoff_effect"] == pytest.approx(want)
        for cond in ["N", "Y"]:
            if "p" in ra["nodes"][key][cond]:
                want = (ra["nodes"][key][cond]["p"] + rb["nodes"][key][cond]["p"]) / 2
                assert result["nodes"][key][cond]["p"] == pytest.approx(want)
            else:
                want = (ra["nodes"][key][cond]["mean"] + rb["nodes"][key][cond]["mean"]) / 2
                assert result["nodes"][key][cond]["mean"] == pytest.approx(want)
    assert result["nodes"]["yes_share"]["all"]["n"] == 8000


def test_who_believes_what_does_not_open_a_gap_between_fails_and_passes(graph):
    # The reviewer's MOCK probe: two forecasters give one question the same answer at every cell
    # (0.10 and 0.50) but disagree about the vote (P(pass) about 0.88 and 0.16). Pooling raw draws put
    # about 45% in 'fails' and 16% in 'passes'; pooling each forecaster's conditional gives 30% in both.
    objs = []
    for share_mean, p in [(0.56, 0.10), (0.45, 0.50)]:
        obj = MOCK_response(graph, share_mean=share_mean, share_sd=0.05)
        for value in obj["nodes"]["dc_animal_initiative_filed"]["forecasts"].values():
            value["p"] = p
        objs.append(parse(graph, obj))
    result = pool(graph, {"A": objs[0], "B": objs[1]}, n=40_000, seed=0)
    entry = result["nodes"]["dc_animal_initiative_filed"]
    assert entry["N"]["p"] == pytest.approx(0.30, abs=0.01)
    assert entry["Y"]["p"] == pytest.approx(0.30, abs=0.01)
    assert entry["cutoff_effect"] == pytest.approx(0.0, abs=1e-12)


def test_run_seeds_do_not_depend_on_the_other_runs(graph):
    a = parse(graph, MOCK_response(graph, seed=1))
    b = parse(graph, MOCK_response(graph, seed=2))
    alone = pool(graph, {"a": a}, n=2000, seed=0)["per_run"]["a"]["nodes"]["foie_gras_menus"]
    together = pool(graph, {"a": a, "b": b}, n=2000, seed=0)["per_run"]["a"]["nodes"]["foie_gras_menus"]
    assert alone == together


def test_report_renders(graph, tmp_path):
    from i86 import report

    fc = parse(graph, MOCK_response(graph))
    result = pool(graph, {"MOCK-a": fc}, n=2000, seed=0)
    report.write(graph, result, {"MOCK-a": {"model_served": "MOCK"}}, tmp_path)
    text = (tmp_path / "summary.md").read_text()
    assert "Chance one ballot decides it" in text and "`foie_gras_menus`" in text
    assert "`ban_status.applies`" in text and "is not an effect" in text
    assert (tmp_path / "plots" / "ban-status.svg").exists()
