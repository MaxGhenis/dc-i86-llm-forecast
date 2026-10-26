"""The write-up charts, drawn from pooled MOCK forecasts."""

import re

from mock import MOCK_response

from i86 import plots
from i86.response import parse
from i86.summarize import pool


def _result(graph):
    return pool(graph, {"MOCK-a": parse(graph, MOCK_response(graph))}, n=2000, seed=0)


def test_dot_chart_draws_both_pairs_for_every_question(graph):
    result = _result(graph)
    svg = plots.dot_chart(graph, result, "spillover", "MOCK title")
    rows = [nid for nid in graph.order if graph.nodes[nid].module == "spillover"
            and graph.nodes[nid].kind in {"binary", "derived"} and graph.nodes[nid].exists_if is None]
    # Per question: two filled dots (fails, passes) and two rings (49.5% and 50.5%), plus one of each
    # in the legend.
    assert svg.count('r="5"') == 2 * len(rows) + 2
    assert svg.count('r="4"') == 2 * len(rows) + 2
    for nid in rows:
        e = result["nodes"][nid]
        assert f"{e['cutoff_fail']['p']:.0%} at 49.5% Yes, {e['cutoff_pass']['p']:.0%} at 50.5% Yes" in svg


def test_status_chart_names_each_option_in_words(graph):
    svg = plots.status_chart(graph, _result(graph))
    labels = re.findall(r'text-anchor="end">([^<]+)</text>', svg)
    assert labels == [plots.STATUS_LABELS[o] for o in graph.nodes["ban_status"].options]
