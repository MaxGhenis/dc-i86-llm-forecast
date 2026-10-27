"""Round-12 probes: a band's last positive CDF sliver must survive lower-end clipping.

All responses are invented MOCK forecasts. The last supported share is 55%; the
band starts one representable float below it, so simulate clips every draw to 55%.
The 72% answer cannot affect those draws or the scale needed for their tiny tilt.
"""

import numpy as np

from i86.simulate import exact_tilt, simulate
from test_review_r11_tilt import RESTRICT, _forecasts


BAND = (float(np.nextafter(0.55, 0.0)), 0.97)


def test_last_supported_sliver_does_not_use_an_unreachable_answer(graph):
    quiet = exact_tilt(graph, _forecasts(graph, 5e-324), RESTRICT, BAND)[1]
    loud = exact_tilt(graph, _forecasts(graph, 1.0), RESTRICT, BAND)[1]
    assert quiet.scale == loud.scale > 0


def test_last_supported_sliver_keeps_positive_draws(graph):
    for later in (5e-324, 1.0):
        draws = simulate(graph, _forecasts(graph, later), 64, 34,
                         share_band=BAND, restrict=RESTRICT)
        assert np.all(draws["yes_share"] == 0.55), later
        assert np.all(draws["_weight"] == 1.0), later
