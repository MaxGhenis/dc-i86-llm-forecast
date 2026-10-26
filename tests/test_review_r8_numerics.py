"""Round-8 numerical and chart probes. Forecast inputs are invented MOCK data."""

from fractions import Fraction
import json
from pathlib import Path

import numpy as np
import pytest
from mock import MOCK_response

from i86 import dists, plots
from i86.response import parse, share_key
from i86.simulate import _lerp
from i86.summarize import run_summary


class NumericalDefect(AssertionError):
    """Only a reproduced numerical defect is expected to fail."""


@pytest.mark.parametrize("a,b", [
    (5e-324, 5e-324), (5e-324, 1e-323), (1e-323, 5e-324),
    (-np.finfo(float).max, np.finfo(float).max),
    (np.finfo(float).max, np.finfo(float).max),
])
def test_mock_interpolation_stays_between_cell_values(a, b):
    w = np.array([0., np.nextafter(0., 1.), .1, .25, .5, .75, .9,
                  np.nextafter(1., 0.), 1.])
    out = _lerp(np.array([[a], [b]]), np.zeros(len(w), int), np.ones(len(w), int), w)
    assert np.all(out >= min(a, b)) and np.all(out <= max(a, b))
    if a == b:
        assert np.all(out == a)


@pytest.mark.parametrize("p", [1., 1e-200, 1e-300, 5e-324])
def test_mock_separated_constant_tilts_keep_their_relative_mass(p):
    # Active share masses .2 and .2 have tilt p and 2p, so the first
    # interval receives 1/3 of the conditional mass at every scale.
    v, z = dists.sample_share_tilted(
        [.25, .75], [.2, .8], 0., 1., 0., 1., np.array([1/6, 2/3]),
        lambda x: np.where(x < .25, p, np.where(x > .75, 2*p, 0.)), [.25, .75],
    )
    np.testing.assert_allclose(v, [.125, .875], atol=1e-15, rtol=0.)
    assert z == pytest.approx(float(Fraction.from_float(p) * Fraction(3, 5)), rel=1e-14, abs=0)


@pytest.mark.parametrize("tiny", [1e-17, 1e-18, 1e-200])
def test_mock_representable_tilt_total_is_rounded_once(tiny):
    p = 5e-324
    v, z = dists.sample_share_tilted(
        [.25, .75], [tiny, .5], 0., 1., 0., 1., np.array([.25, .5, .75]),
        lambda x: np.where((x < .25) | (x > .75), p, 0.), [.25, .75],
    )
    np.testing.assert_allclose(v, [.8125, .875, .9375], atol=1e-15, rtol=0.)
    expected = float((Fraction(1, 2) + Fraction.from_float(tiny)) * Fraction.from_float(p))
    assert expected == p
    if z != expected:
        raise NumericalDefect((z, expected))


def test_mock_positive_condition_does_not_drop_the_run(graph):
    obj = MOCK_response(graph)
    for key, row in obj["nodes"]["ban_status"]["forecasts"].items():
        p = 0. if key == "yes_50.5" else 5e-324
        row.update(repealed=1., congress=0., court=0., not_certified=0., certified=p)
    for row in obj["nodes"]["fattened_narrowed"]["forecasts"].values():
        row["p"] = 1.
    for x in graph.share_grid:
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = float(np.clip((x-.5)/.3, 0., 1.))
    result = run_summary(graph, parse(graph, obj), n=1, seed=26)
    conditional = result["nodes"]["fattened_narrowed"]["Y|given"]
    if conditional is None:
        raise NumericalDefect("positive condition was omitted in the Y arm")
    assert conditional["runs"] == 1 and conditional["p"] == 1.


def test_committed_charts_match_committed_summary(graph, tmp_path):
    root = Path(__file__).resolve().parents[1]
    result = json.loads((root / "outputs/summary.json").read_text())
    regenerated = plots.write(graph, result, tmp_path)
    assert len(regenerated) == 12
    for path in regenerated:
        assert path.read_bytes() == (root / "outputs" / path.relative_to(tmp_path)).read_bytes()
