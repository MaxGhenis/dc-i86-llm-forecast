"""Independent round-3 map checks; no real forecasts or implementation changes.

Cases from the round-3 independent review (GPT-6.1 Sol, 2026-10-25), kept as regression tests.
They first ran as strict expected failures against aa6fbad; the fixes made them pass.
"""

from itertools import product

from i86.graph import Entry


def _worlds():
    """Enumerate this map's legal boolean worlds without graph.assignments()."""
    independent = [
        "denver_io311_passes",
        "lawsuit_filed",
        "fattened_narrowed",
        "pate_treated_banned",
        "dc_animal_initiative_filed",
        "dc_another_animal_law",
        "paf_statewide_2028",
        "federal_preemption_2030",
        "dc_bans_other_food_2030",
    ]
    for status, flags in product(
        [None, "repealed", "congress", "court", "not_certified", "certified"],
        product([False, True], repeat=len(independent)),
    ):
        values = dict(zip(independent, flags))
        values.update(
            passes=status is not None,
            ban_status=status,
            ban_standing=status in {"not_certified", "certified"},
            ban_certified=status == "certified",
        )
        if status is None and values["lawsuit_filed"]:
            continue
        if not values["ban_standing"] and (
            values["fattened_narrowed"] or values["pate_treated_banned"]
        ):
            continue
        yield values


def test_review_r3_states_partition_every_hand_enumerated_world(graph):
    worlds = list(_worlds())
    assert len(worlds) == 1472
    for node in graph.forecast_nodes():
        if not node.states:
            continue
        for values in worlds:
            if node.exists_if and not node.exists_if.evaluate(values):
                continue
            hits = [key for key, cond in node.states.items() if cond.evaluate(values)]
            assert len(hits) == 1, (node.id, values, hits)


def test_review_r3_entries_match_hand_enumerated_possible_worlds(graph):
    worlds = list(_worlds())
    total = 0
    for node in graph.forecast_nodes():
        expected = []
        for cell, state in product(graph.cells_for(node), list(node.states) or [None]):
            feasible = any(
                (cell is None or values["passes"] == (cell > 0.5))
                and (node.exists_if is None or node.exists_if.evaluate(values))
                and (state is None or node.states[state].evaluate(values))
                for values in worlds
            )
            if feasible:
                expected.append(Entry(cell, state))
        assert graph.entries(node) == expected, node.id
        total += len(expected)
    assert total == 98
