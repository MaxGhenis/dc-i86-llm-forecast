import copy
import json

import pytest

from i86 import graph as graph_mod
from i86.graph import Condition, GraphError, assignments, boolean_scope
from i86.prompt import build, sha256
from i86.response import ResponseError, extract_json, parse, quantile_key, template
from mock import MOCK_response


def test_order_puts_parents_first(graph):
    position = {nid: i for i, nid in enumerate(graph.order)}
    for node in graph.nodes.values():
        for parent in node.parents:
            assert position[parent] < position[node.id], (parent, node.id)


def test_states_are_exclusive_and_exhaustive_wherever_the_node_exists(graph):
    # load() enforces this; re-check every node explicitly so a regression in load() is caught here.
    for node in graph.nodes.values():
        if not node.states:
            continue
        names = set().union(*(c.names for c in node.states.values()))
        if node.exists_if is not None:
            names |= node.exists_if.names
        for values in assignments(graph, boolean_scope(graph, names)):
            if node.exists_if is not None and not node.exists_if.evaluate(values):
                continue
            assert sum(c.evaluate(values) for c in node.states.values()) == 1, (node.id, values)


def test_overlapping_states_are_rejected(tmp_path):
    text = (graph_mod.GRAPH_PATH).read_text().replace(
        'certified: "ban_certified"', 'certified: "passes"'
    )
    path = tmp_path / "graph.yaml"
    path.write_text(text)
    with pytest.raises(GraphError, match="not exclusive and exhaustive"):
        graph_mod.load(path)


@pytest.mark.parametrize("bad", ["__import__('os')", "a + b", "x == 1", "f(x)", "x.y.z", "f(x).y"])
def test_conditions_accept_only_boolean_names(bad):
    with pytest.raises(GraphError):
        Condition.parse(bad)


def test_cycles_are_rejected(tmp_path):
    old = "    kind: categorical\n    module: implementation\n    exists_if: passes\n"
    text = graph_mod.GRAPH_PATH.read_text()
    assert old in text
    text = text.replace(old, old.replace("exists_if: passes", "exists_if: passes and not pate_treated_banned"))
    path = tmp_path / "graph.yaml"
    path.write_text(text)
    with pytest.raises(GraphError, match="cycle"):
        graph_mod.load(path)


def test_mock_response_parses_and_covers_every_entry(graph):
    fc = parse(graph, MOCK_response(graph))
    for node in graph.forecast_nodes():
        assert set(fc.values[node.id]) == {e.key for e in graph.entries(node)}


def test_template_lists_every_entry_as_null(graph):
    t = template(graph)
    for node in graph.forecast_nodes():
        for entry in graph.entries(node):
            assert all(v is None for v in t["nodes"][node.id]["forecasts"][entry.key].values())


def _first_entry(obj, node_id):
    return next(iter(obj["nodes"][node_id]["forecasts"].values()))


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda o: _first_entry(o, "lawsuit_filed").update(p=1.2), "probability"),
        (lambda o: _first_entry(o, "foie_gras_menus").update(p05=500), "not decrease|bounds|lie in"),
        (lambda o: _first_entry(o, "foie_gras_menus").update(p95=1), "not decrease"),
        (lambda o: _first_entry(o, "yes_share").update(le_90=0.1), "not decrease"),
        (lambda o: _first_entry(o, "paf_measures_2027_2028").update({"0": 5.0}), "sum to 1"),
        (lambda o: o["nodes"]["lawsuit_filed"]["forecasts"].clear(), "missing"),
        (lambda o: o["nodes"]["lawsuit_filed"]["forecasts"].update(extra={"p": 0.1}), "unexpected"),
        (lambda o: o["nodes"]["ban_status"]["forecasts"]["yes_60.0"].update(certified=5.0), "sum to 1"),
        (lambda o: o["nodes"].pop("turnout"), "turnout: missing"),
        (lambda o: _first_entry(o, "turnout").update(p50=None), "numbers"),
    ],
)
def test_parse_rejects_bad_values(graph, mutate, message):
    obj = MOCK_response(graph)
    mutate(obj)
    with pytest.raises(ResponseError, match=message):
        parse(graph, obj)


def test_numbers_given_as_strings_with_commas_are_read(graph):
    obj = MOCK_response(graph)
    entry = _first_entry(obj, "turnout")
    entry.update({quantile_key(q): f"{v:,.0f}" for q, v in zip(graph.quantiles, [150000, 180000, 200000, 220000, 260000])})
    fc = parse(graph, obj)
    assert fc.values["turnout"]["all"] == [150000, 180000, 200000, 220000, 260000]


def test_extract_json_takes_the_last_fenced_response(graph):
    obj = MOCK_response(graph)
    other = copy.deepcopy(obj)
    other["forecaster"]["model"] = "draft"
    text = f"notes\n```json\n{json.dumps(other)}\n```\nfinal:\n```json\n{json.dumps(obj)}\n```\n"
    assert extract_json(text)["forecaster"]["model"] == "MOCK"


def test_committed_prompt_matches_the_graph(graph):
    from i86.graph import ROOT

    text = build(graph)
    assert (ROOT / "prompts" / "forecaster.md").read_text() == text, "run `i86 prompt`"
    recorded = (ROOT / "prompts" / "forecaster.md.sha256").read_text().split()[0]
    assert recorded == sha256(text)
    assert json.loads((ROOT / "schemas" / "template.json").read_text()) == template(graph)


def _load_edited(tmp_path, old, new):
    text = graph_mod.GRAPH_PATH.read_text()
    assert old in text
    path = tmp_path / "graph.yaml"
    path.write_text(text.replace(old, new))
    return graph_mod.load(path)


def test_option_tests_must_name_a_real_option_of_a_categorical_node(tmp_path):
    with pytest.raises(GraphError, match="unknown option"):
        _load_edited(tmp_path, 'rule: "ban_status.certified"', 'rule: "ban_status.in_force"')
    with pytest.raises(GraphError, match="not categorical"):
        _load_edited(tmp_path, 'rule: "ban_status.certified"', 'rule: "lawsuit_filed.certified"')
    with pytest.raises(GraphError, match="not boolean"):
        _load_edited(tmp_path, 'rule: "ban_status.certified"', 'rule: "ban_status"')


def test_pass_only_cells_need_an_exists_if_that_implies_passes(tmp_path):
    old = "    kind: categorical\n    module: implementation\n    exists_if: passes\n"
    with pytest.raises(GraphError, match="cells: pass"):
        _load_edited(tmp_path, old, old.replace("    exists_if: passes\n", ""))


def test_categorical_states_cover_every_option(graph):
    # foie_gras_menus splits the passing worlds by ban_status; every option lands in exactly one state.
    node = graph.nodes["foie_gras_menus"]
    for option in [None, *graph.nodes["ban_status"].options]:
        values = {"passes": option is not None, "ban_status": option,
                  "ban_standing": option in {"certified", "not_certified"}, "ban_certified": option == "certified"}
        assert sum(c.evaluate(values) for c in node.states.values()) == 1, option


def test_entries_are_only_the_pairs_that_can_occur(graph):
    keys = [e.key for e in graph.entries(graph.nodes["foie_gras_menus"])]
    assert keys == ["yes_49.5|failed", "yes_50.5|removed", "yes_50.5|not_certified", "yes_50.5|certified"]
    assert [e.key for e in graph.entries(graph.nodes["fattened_narrowed"])] == [
        "yes_50.5|certified", "yes_50.5|not_certified"]
    for node in graph.forecast_nodes():
        for e in graph.entries(node):
            if e.state == "failed":
                assert e.cell is not None and e.cell < 0.5, (node.id, e.key)


def test_prior_context_is_required(graph):
    obj = MOCK_response(graph)
    obj["forecaster"]["prior_context"] = None
    with pytest.raises(ResponseError, match="prior_context"):
        parse(graph, obj)
