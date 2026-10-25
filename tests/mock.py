"""MOCK forecaster responses for tests only. These numbers are invented, not forecasts."""

from __future__ import annotations

import math
import random

from i86.graph import Graph
from i86.response import quantile_key, share_key, template


def _phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def MOCK_response(graph: Graph, seed: int = 0, share_mean: float = 0.62, share_sd: float = 0.08,
                  pass_bump: float = 0.1) -> dict:
    """A valid response: normal Yes share, flat quantities, probabilities that rise after passage."""
    rng = random.Random(seed)
    obj = template(graph)
    obj["forecaster"]["model"] = "MOCK"
    obj["forecaster"]["prior_context"] = "none"
    obj["research_summary"] = "MOCK response for tests; not a forecast."
    for node in graph.forecast_nodes():
        item = obj["nodes"][node.id]
        if node.baseline:
            item["baseline"] = {"value": 1, "as_of": "2026-10", "source": "MOCK"}
        item["reasoning"] = "MOCK"
        for entry in graph.entries(node):
            passed = entry.cell is not None and entry.cell > 0.5
            if node.kind == "share_cdf":
                value = {share_key(x): _phi((x - share_mean) / share_sd) for x in graph.share_grid}
            elif node.kind == "binary":
                base = rng.uniform(0.05, 0.6)
                value = {"p": min(1.0, base + (pass_bump if passed else 0.0))}
            elif node.kind == "quantity":
                lo, hi = node.bounds
                mid = rng.uniform(lo + 0.3 * (hi - lo), lo + 0.5 * (hi - lo))
                if entry.state and entry.state.startswith("applies"):
                    mid = lo + 0.8 * (mid - lo)
                spread = 0.25 * (mid - lo)
                xs = [mid - 2 * spread, mid - spread, mid, mid + spread, mid + 2 * spread]
                value = {quantile_key(q): min(hi, max(lo, x)) for q, x in zip(graph.quantiles, xs)}
            elif node.kind in {"pmf", "categorical"}:
                names = node.labels if node.kind == "pmf" else list(node.options)
                ws = [rng.random() + 0.01 for _ in names]
                total = sum(ws)
                value = {name: w / total for name, w in zip(names, ws)}
            item["forecasts"][entry.key] = value
    return obj
