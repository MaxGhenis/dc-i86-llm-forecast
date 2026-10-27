"""Round-9 scale checks. All forecasts are invented MOCK inputs."""
from fractions import Fraction

import numpy as np
import pytest
from mock import MOCK_response

from i86.response import parse, share_key
from i86.simulate import simulate


class NumericalDefect(AssertionError):
    """A completed simulation lost a positive restricted draw."""


def categorical_forecaster(graph, k):
    obj = MOCK_response(graph)
    for key, row in obj['nodes']['ban_status']['forecasts'].items():
        j = {'yes_50.5': 0, 'yes_60.0': 1, 'yes_72.0': 1}[key]
        p = float(Fraction(j, 2) / Fraction(2) ** k)
        row.update(repealed=1-p, congress=0., court=0., not_certified=0., certified=p)
    for x in graph.share_grid:
        obj['nodes']['yes_share']['forecasts']['all'][share_key(x)] = float(np.clip((x-.5)/.3, 0., 1.))
    return parse(graph, obj)


@pytest.mark.parametrize('allowed', [{'certified'}, {'certified', 'court'}])
@pytest.mark.parametrize('k', [1, 1000, 1073])
def test_categorical_scaling_controls(graph, allowed, k):
    base = simulate(graph, categorical_forecaster(graph, 0), 64, 34,
                    share_band=(.5, .8), restrict={'ban_status': allowed})
    small = simulate(graph, categorical_forecaster(graph, k), 64, 34,
                     share_band=(.5, .8), restrict={'ban_status': allowed})
    for key in ('yes_share', 'ban_status', '_weight'):
        np.testing.assert_array_equal(small[key], base[key])


@pytest.mark.parametrize('allowed', [{True}, {False}])
def test_binary_scaling_controls(graph, allowed):
    node = 'dc_animal_initiative_filed'
    def forecasts(k):
        obj = MOCK_response(graph)
        for i, row in enumerate(obj['nodes'][node]['forecasts'].values()):
            p = (i+1)/16 * 2.**(-k)
            row['p'] = 1-p if allowed == {False} else p
        return parse(graph, obj)
    k = 48 if allowed == {False} else 1070
    base = simulate(graph, forecasts(0), 64, 34, restrict={node: allowed})
    small = simulate(graph, forecasts(k), 64, 34, restrict={node: allowed})
    for key in ('yes_share', node, '_weight'):
        np.testing.assert_array_equal(small[key], base[key])


def test_impossible_absence_does_not_disable_scale(graph):
    restrict = {'ban_status': {'certified', None}}
    base = simulate(graph, categorical_forecaster(graph, 0), 1, 34,
                    share_band=(.5, .8), restrict=restrict)
    small = simulate(graph, categorical_forecaster(graph, 1073), 1, 34,
                     share_band=(.5, .8), restrict=restrict)
    assert base['_weight'][0] == 1.
    if small['_weight'][0] != 1. or not np.array_equal(base['yes_share'], small['yes_share']):
        raise NumericalDefect({k: small[k].tolist() for k in ('yes_share', '_weight', '_mass')})


def test_unused_cells_do_not_disable_scale(graph):
    node = 'dc_animal_initiative_filed'
    obj = MOCK_response(graph)
    for key, row in obj['nodes'][node]['forecasts'].items():
        row['p'] = 1. if float(key.split('_')[1]) < 50 else (0. if key == 'yes_50.5' else 5e-324)
    for x in graph.share_grid:
        obj['nodes']['yes_share']['forecasts']['all'][share_key(x)] = float(np.clip((x-.5)/.3, 0., 1.))
    draws = simulate(graph, parse(graph, obj), 1, 34, share_band=(.5, .8), restrict={node: {True}})
    if draws['_weight'][0] != 1.:
        raise NumericalDefect({k: draws[k].tolist() for k in ('yes_share', '_weight', '_mass')})
