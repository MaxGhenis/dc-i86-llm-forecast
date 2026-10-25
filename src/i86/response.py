"""The response template forecasters fill in, and the checks a filled response must pass.

A forecaster returns one JSON object. `template(graph)` lists every number it must supply, as nulls;
`parse(graph, obj)` checks a filled copy and returns it in a normalized form for the simulator, or
raises `ResponseError` listing every problem found.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

from .graph import Graph, Node

PMF_TOLERANCE = 0.02


class ResponseError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__(f"{len(problems)} problem(s):\n" + "\n".join(f"- {p}" for p in problems))
        self.problems = problems


def quantile_key(q: float) -> str:
    return f"p{round(q * 100):02d}"


def share_key(x: float) -> str:
    return f"le_{x * 100:g}"


def value_template(graph: Graph, node: Node) -> dict:
    if node.kind == "binary":
        return {"p": None}
    if node.kind == "quantity":
        return {quantile_key(q): None for q in graph.quantiles}
    if node.kind == "pmf":
        return {label: None for label in node.labels}
    if node.kind == "categorical":
        return {option: None for option in node.options}
    if node.kind == "share_cdf":
        return {share_key(x): None for x in graph.share_grid}
    raise ValueError(node.kind)


def template(graph: Graph) -> dict:
    nodes = {}
    for node in graph.forecast_nodes():
        item: dict = {}
        if node.baseline:
            item["baseline"] = {"value": None, "as_of": None, "source": None}
        item["forecasts"] = {e.key: value_template(graph, node) for e in graph.entries(node)}
        item["reasoning"] = None
        item["sources"] = []
        nodes[node.id] = item
    return {
        "forecaster": {"model": None, "prior_context": None, "notes": None},
        "research_summary": None,
        "nodes": nodes,
    }


@dataclass
class Forecasts:
    """A checked response. `values[node][entry_key]` is a float (binary), a list of floats in
    quantile, label, option or grid order (quantity, pmf, categorical, share_cdf)."""

    values: dict[str, dict[str, object]]
    baselines: dict[str, dict] = field(default_factory=dict)
    reasoning: dict[str, str] = field(default_factory=dict)
    sources: dict[str, list[str]] = field(default_factory=dict)
    forecaster: dict = field(default_factory=dict)
    research_summary: str = ""


def _number(x) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)) and math.isfinite(x):
        return float(x)
    if isinstance(x, str):
        try:
            v = float(x.replace(",", ""))
        except ValueError:
            return None
        return v if math.isfinite(v) else None
    return None


def parse(graph: Graph, obj: dict) -> Forecasts:
    problems: list[str] = []
    if not isinstance(obj, dict) or not isinstance(obj.get("nodes"), dict):
        raise ResponseError(["the response must be an object with a 'nodes' object"])
    out = Forecasts(values={})
    out.forecaster = obj.get("forecaster") or {}
    prior = out.forecaster.get("prior_context") if isinstance(out.forecaster, dict) else None
    if not isinstance(prior, str) or not prior.strip():
        problems.append("forecaster.prior_context: required; quote anything beyond the brief, or write 'none'")
    out.research_summary = obj.get("research_summary") or ""
    given_nodes = obj["nodes"]
    for node in graph.forecast_nodes():
        item = given_nodes.get(node.id)
        if not isinstance(item, dict):
            problems.append(f"{node.id}: missing")
            continue
        forecasts = item.get("forecasts")
        if not isinstance(forecasts, dict):
            problems.append(f"{node.id}: 'forecasts' missing")
            continue
        vals: dict[str, object] = {}
        for entry in graph.entries(node):
            where = f"{node.id}[{entry.key}]"
            v = forecasts.get(entry.key)
            if not isinstance(v, dict):
                problems.append(f"{where}: missing")
                continue
            checked = _check_value(graph, node, v, where, problems)
            if checked is not None:
                vals[entry.key] = checked
        extra = set(forecasts) - {e.key for e in graph.entries(node)}
        if extra:
            problems.append(f"{node.id}: unexpected forecast keys {sorted(extra)}")
        out.values[node.id] = vals
        if node.baseline:
            out.baselines[node.id] = item.get("baseline") or {}
        out.reasoning[node.id] = item.get("reasoning") or ""
        out.sources[node.id] = [s for s in (item.get("sources") or []) if isinstance(s, str)]
    unknown = set(given_nodes) - {n.id for n in graph.forecast_nodes()}
    if unknown:
        problems.append(f"unexpected nodes {sorted(unknown)}")
    if problems:
        raise ResponseError(problems)
    return out


def _check_value(graph: Graph, node: Node, v: dict, where: str, problems: list[str]):
    if node.kind == "binary":
        p = _number(v.get("p"))
        if p is None or not 0.0 <= p <= 1.0:
            problems.append(f"{where}: p must be a probability, got {v.get('p')!r}")
            return None
        return p
    if node.kind == "quantity":
        keys = [quantile_key(q) for q in graph.quantiles]
        xs = [_number(v.get(k)) for k in keys]
        if any(x is None for x in xs):
            problems.append(f"{where}: quantiles {keys} must all be numbers, got {v}")
            return None
        lo, hi = node.bounds
        if any(b < a for a, b in zip(xs, xs[1:])):
            problems.append(f"{where}: quantiles must not decrease, got {xs}")
            return None
        if xs[0] < lo or xs[-1] > hi:
            problems.append(f"{where}: quantiles must lie in [{lo}, {hi}], got {xs}")
            return None
        return xs
    if node.kind in {"pmf", "categorical"}:
        names = node.labels if node.kind == "pmf" else list(node.options)
        ps = [_number(v.get(name)) for name in names]
        if any(p is None or p < 0 for p in ps):
            problems.append(f"{where}: probabilities for {names} must be numbers >= 0, got {v}")
            return None
        total = sum(ps)
        if abs(total - 1.0) > PMF_TOLERANCE:
            problems.append(f"{where}: probabilities must sum to 1, got {total:.3f}")
            return None
        return [p / total for p in ps]
    if node.kind == "share_cdf":
        keys = [share_key(x) for x in graph.share_grid]
        fs = [_number(v.get(k)) for k in keys]
        if any(f is None or not 0.0 <= f <= 1.0 for f in fs):
            problems.append(f"{where}: cumulative probabilities {keys} must lie in [0, 1], got {v}")
            return None
        if any(b < a for a, b in zip(fs, fs[1:])):
            problems.append(f"{where}: cumulative probabilities must not decrease, got {fs}")
            return None
        return fs
    raise ValueError(node.kind)


_FENCE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.S)


def extract_json(text: str) -> dict:
    """The last fenced JSON block in an agent's final message, else the outermost object."""
    blocks = _FENCE.findall(text)
    for block in reversed(blocks):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "nodes" in obj:
            return obj
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ResponseError(["no JSON object found in the response"])
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ResponseError([f"the response's JSON does not parse: {exc}"]) from exc
