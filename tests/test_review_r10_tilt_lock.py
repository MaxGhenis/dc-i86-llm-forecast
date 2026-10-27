"""Round-10 tilt endpoint probes, with invented MOCK forecasts only."""

import numpy as np
import pytest
from mock import MOCK_response

from i86.response import parse, share_key
from i86.simulate import exact_tilt, simulate


def _endpoint_forecasts(graph, middle, later):
    obj = MOCK_response(graph)
    probs = {'yes_50.5': 0., 'yes_60.0': middle, 'yes_72.0': later}
    for key, row in obj['nodes']['ban_status']['forecasts'].items():
        p = probs[key]
        row.update(repealed=1-p, congress=0., court=0., not_certified=0., certified=p)
    for x in graph.share_grid:
        obj['nodes']['yes_share']['forecasts']['all'][share_key(x)] = float(np.clip((x-.5)/.3, 0., 1.))
    return parse(graph, obj)


def test_upper_endpoint_unused_answer_preserves_tilt_scale(graph):
    restrict = {'ban_status': {'certified'}}
    band = (.5, .6)
    quiet = _endpoint_forecasts(graph, 5e-324, 5e-324)
    loud = _endpoint_forecasts(graph, 5e-324, 1.)
    a = exact_tilt(graph, quiet, restrict, band)[1]
    b = exact_tilt(graph, loud, restrict, band)[1]
    assert a.scale == b.scale


def test_upper_endpoint_unused_answer_does_not_drop_positive_draws(graph):
    restrict = {'ban_status': {'certified'}}
    draws = simulate(graph, _endpoint_forecasts(graph, 5e-324, 1.), 64, 34,
                     share_band=(.5, .6), restrict=restrict)
    assert np.all(draws['_weight'] == 1.)


def test_upper_endpoint_control_without_loud_unused_answer(graph):
    restrict = {'ban_status': {'certified'}}
    draws = simulate(graph, _endpoint_forecasts(graph, 5e-324, 5e-324), 64, 34,
                     share_band=(.5, .6), restrict=restrict)
    assert np.all(draws['_weight'] == 1.)
