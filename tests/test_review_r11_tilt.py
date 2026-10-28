"""Round-11 finding 39: answers read only at shares the forecaster gives no probability must not
set the tilt's scale. Invented MOCK forecasts only."""

import numpy as np
from mock import MOCK_response

from i86.response import parse, share_key
from i86.simulate import exact_tilt, simulate

RESTRICT = {"ban_status": {"certified", "not_certified"}}
BAND = (0.5, 0.97)


def _forecasts(graph, later):
    """MOCK: certified 0 at 50.5%, 5e-324 at 60% and `later` at 72%; every Yes share in (50%, 55%]."""
    obj = MOCK_response(graph)
    probs = {"yes_50.5": 0.0, "yes_60.0": 5e-324, "yes_72.0": later}
    for key, row in obj["nodes"]["ban_status"]["forecasts"].items():
        p = probs[key]
        row.update(repealed=1 - p, congress=0.0, court=0.0, not_certified=0.0, certified=p)
    for x in graph.share_grid:
        obj["nodes"]["yes_share"]["forecasts"]["all"][share_key(x)] = float(np.clip((x - 0.5) / 0.05, 0.0, 1.0))
    return parse(graph, obj)


def test_answer_at_shares_with_no_probability_leaves_the_scale(graph):
    quiet = exact_tilt(graph, _forecasts(graph, 5e-324), RESTRICT, BAND)[1]
    loud = exact_tilt(graph, _forecasts(graph, 1.0), RESTRICT, BAND)[1]
    assert quiet.scale == loud.scale > 0


def test_answer_at_shares_with_no_probability_keeps_the_draws(graph):
    for later in [5e-324, 1.0]:
        draws = simulate(graph, _forecasts(graph, later), 64, 34, share_band=BAND, restrict=RESTRICT)
        assert np.all(draws["_weight"] == 1.0), later
        assert np.all(draws["yes_share"] <= 0.55), later  # the condition's mass, under 2.5e-324, is 0
