"""Independent round-three review: all inputs are invented MOCK responses.

Cases from the round-3 independent review (GPT-6.1 Sol, 2026-10-25), kept as regression tests.
They first ran as strict expected failures against aa6fbad; the fixes made them pass.
"""

from copy import deepcopy

from i86.report import markdown
from i86.response import parse
from i86.summarize import pool
from mock import MOCK_response


def margin_footnote_evidence(graph):
    """Only larger-margin parent forecasts change; the direct cutoff answer stays 100."""
    a = MOCK_response(graph)
    for e in a["nodes"]["ban_status"]["forecasts"].values():
        e.update({key: float(key == "repealed") for key in e})
    for key, e in a["nodes"]["foie_gras_menus"]["forecasts"].items():
        e.update({q: 0.0 if key.endswith("|certified") else 100.0 for q in e})
    b = deepcopy(a)
    for cell in ("yes_60.0", "yes_72.0"):
        e = b["nodes"]["ban_status"]["forecasts"][cell]
        e.update({key: float(key == "certified") for key in e})
    evidence = {}
    for label, obj in (("large_wins_repealed", a), ("large_wins_certified", b)):
        result = pool(graph, {"MOCK": parse(graph, obj)}, n=2000, seed=86)
        node = result["nodes"]["foie_gras_menus"]
        evidence[label] = {
            "Passes": node["Y"]["mean"],
            "At 50.5%": node["cutoff_pass"]["mean"],
            "footnote": next(line for line in markdown(graph, result, {}).splitlines()
                             if line.startswith("† ")),
        }
    return evidence


def test_near_cell_report_does_not_deny_upstream_margin_information(graph):
    evidence = margin_footnote_evidence(graph)
    a, b = evidence["large_wins_repealed"], evidence["large_wins_certified"]
    assert a["At 50.5%"] == b["At 50.5%"] == 100
    assert abs(a["Passes"] - b["Passes"]) > 50
    assert "carry no information about larger margins" not in b["footnote"]
