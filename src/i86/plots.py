"""Static SVG charts of the pooled forecasts, for the write-up.

- One interval chart per quantity: rows for 'fails', 'passes', and the fixed 49.5% and 50.5% cells.
  Each row is a mean dot on a thick 25th-75th percentile bar and a thin 5th-95th whisker.
- One dot chart per module of yes/no questions: the probability if the measure fails and if it
  passes, joined by a line.
- One chart of the sale ban's status on 2028-12-01 if the measure passes: each option's probability
  across all passing margins and at a bare 50.5% pass.

Colors are the dataviz reference palette's first two categorical slots, validated as a pair (light).
Text uses ink tokens, never the series color; marks carry <title> tooltips.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from .graph import Graph

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e6e5e1"
FAIL = "#eb6834"  # categorical slot 2, orange
PASS = "#2a78d6"  # categorical slot 1, blue
FONT = "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"


def _ticks(lo: float, hi: float, n: int = 5) -> list[float]:
    """Round ticks whose first is at or below lo and whose last is at or above hi."""
    import math

    span = hi - lo or 1.0
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
    start = math.floor(lo / step) * step
    out = [start]
    while out[-1] < hi - 1e-9:
        out.append(round(out[-1] + step, 10))
    return out


def _fmt(x: float) -> str:
    a = abs(x)
    if a >= 1e6:
        return f"{x / 1e6:g}M"
    if a >= 1e3:
        return f"{x / 1e3:g}K"
    return f"{x:g}"


def interval_chart(graph: Graph, nid: str, entry: dict) -> str:
    node = graph.nodes[nid]
    rows = [("Fails", "N", FAIL, True), ("Passes", "Y", PASS, True),
            ("At 49.5% Yes", "cutoff_fail", FAIL, False), ("At 50.5% Yes", "cutoff_pass", PASS, False)]
    rows = [r for r in rows if entry.get(r[1])]
    lo = min(min(entry[r[1]]["p05"], entry[r[1]]["mean"]) for r in rows)
    hi = max(max(entry[r[1]]["p95"], entry[r[1]]["mean"]) for r in rows)
    pad = (hi - lo) * 0.06 or 1.0
    ticks = [t for t in _ticks(max(node.bounds[0], lo - pad), hi + pad) if t >= node.bounds[0]]
    x0, x1 = ticks[0], ticks[-1]
    width, left, right, top, row_h = 640, 120, 24, 64, 34
    height = top + row_h * len(rows) + 44
    sx = lambda x: left + (x - x0) / (x1 - x0 or 1) * (width - left - right)  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" font-family="{FONT}" role="img" aria-label="{escape(node.question)}">',
           f'<rect width="100%" height="100%" fill="{SURFACE}"/>',
           f'<text x="16" y="24" font-size="15" font-weight="600" fill="{INK}">{escape(node.question)}</text>',
           f'<text x="16" y="44" font-size="12" fill="{INK_2}">{escape(node.unit)}. Dot: mean; thick bar: '
           f'middle half; whisker: 90% interval.</text>']
    for t in ticks:
        out.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{top - 6}" y2="{height - 36}" stroke="{GRID}"/>')
        out.append(f'<text x="{sx(t):.1f}" y="{height - 18}" font-size="11" fill="{INK_2}" '
                   f'text-anchor="middle">{_fmt(t)}</text>')
    for i, (label, cond, color, solid) in enumerate(rows):
        d = entry[cond]
        y = top + row_h * i + row_h / 2
        tip = escape(f"{label}: mean {d['mean']:,.4g}; median {d['p50']:,.4g}; 50% {d['p25']:,.4g}–{d['p75']:,.4g}; "
                     f"90% {d['p05']:,.4g}–{d['p95']:,.4g}")
        out.append(f'<text x="{left - 10}" y="{y + 4:.1f}" font-size="12" fill="{INK}" text-anchor="end">{label}</text>')
        out.append(f'<g><title>{tip}</title>')
        out.append(f'<line x1="{sx(d["p05"]):.1f}" x2="{sx(d["p95"]):.1f}" y1="{y:.1f}" y2="{y:.1f}" '
                   f'stroke="{color}" stroke-width="2" stroke-linecap="round"/>')
        out.append(f'<rect x="{sx(d["p25"]):.1f}" y="{y - 5:.1f}" width="{max(2, sx(d["p75"]) - sx(d["p25"])):.1f}" '
                   f'height="10" rx="4" fill="{color}" fill-opacity="{1 if solid else 0.35}"/>')
        fill = color if solid else SURFACE
        out.append(f'<circle cx="{sx(d["mean"]):.1f}" cy="{y:.1f}" r="5" fill="{fill}" stroke="{SURFACE}" '
                   f'stroke-width="2"/>')
        if not solid:
            out.append(f'<circle cx="{sx(d["mean"]):.1f}" cy="{y:.1f}" r="4" fill="{SURFACE}" stroke="{color}" '
                       f'stroke-width="2"/>')
        out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


def _wrap(text: str, width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            lines.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    lines.append(line)
    return lines


def dot_chart(graph: Graph, result: dict, module: str, title: str) -> str | None:
    rows = []
    for nid in graph.order:
        node = graph.nodes[nid]
        if node.module != module or node.kind not in {"binary", "derived"} or node.exists_if is not None:
            continue
        e = result["nodes"][nid]
        if e.get("N") and e.get("Y"):
            rows.append((node.question, e["N"]["p"], e["Y"]["p"]))
    if not rows:
        return None
    width, left, right, top, row_h = 760, 330, 30, 76, 40
    height = top + row_h * len(rows) + 40
    sx = lambda p: left + p * (width - left - right)  # noqa: E731
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" font-family="{FONT}" role="img" aria-label="{escape(title)}">',
           f'<rect width="100%" height="100%" fill="{SURFACE}"/>',
           f'<text x="16" y="24" font-size="15" font-weight="600" fill="{INK}">{escape(title)}</text>',
           f'<circle cx="22" cy="46" r="5" fill="{FAIL}"/><text x="32" y="50" font-size="12" fill="{INK}">If it fails</text>',
           f'<circle cx="122" cy="46" r="5" fill="{PASS}"/><text x="132" y="50" font-size="12" fill="{INK}">If it passes</text>']
    for t in [0, 0.25, 0.5, 0.75, 1.0]:
        out.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{top - 8}" y2="{height - 32}" stroke="{GRID}"/>')
        out.append(f'<text x="{sx(t):.1f}" y="{height - 14}" font-size="11" fill="{INK_2}" text-anchor="middle">{t:.0%}</text>')
    for i, (q, pn, py) in enumerate(rows):
        y = top + row_h * i + row_h / 2
        lines = _wrap(q, 46)
        for k, text in enumerate(lines):
            dy = (k - (len(lines) - 1) / 2) * 14 + 4
            out.append(f'<text x="{left - 12}" y="{y + dy:.1f}" font-size="12" fill="{INK}" text-anchor="end">{escape(text)}</text>')
        out.append(f'<g><title>{escape(q)}: {pn:.0%} if it fails, {py:.0%} if it passes</title>')
        out.append(f'<line x1="{sx(pn):.1f}" x2="{sx(py):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK_2}" stroke-width="2"/>')
        out.append(f'<circle cx="{sx(pn):.1f}" cy="{y:.1f}" r="5" fill="{FAIL}" stroke="{SURFACE}" stroke-width="2"/>')
        out.append(f'<circle cx="{sx(py):.1f}" cy="{y:.1f}" r="5" fill="{PASS}" stroke="{SURFACE}" stroke-width="2"/></g>')
    out.append("</svg>")
    return "\n".join(out)


def status_chart(graph: Graph, result: dict, nid: str = "ban_status") -> str | None:
    """Probability of each option of a categorical node defined only if the measure passes."""
    node = graph.nodes.get(nid)
    if node is None or node.kind != "categorical":
        return None
    rows = []
    for option, text in node.options.items():
        e = result["nodes"][f"{nid}.{option}"]
        y, c = e.get("Y|given") or e.get("Y"), e.get("cutoff_pass|given") or e.get("cutoff_pass")
        if y and c:
            rows.append((option, text, y["p"], c["p"]))
    if not rows:
        return None
    width, left, right, top, row_h = 760, 160, 30, 76, 34
    height = top + row_h * len(rows) + 40
    sx = lambda p: left + p * (width - left - right)  # noqa: E731
    title = "If it passes: the sale ban's status on 2028-12-01"
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
           f'height="{height}" font-family="{FONT}" role="img" aria-label="{escape(title)}">',
           f'<rect width="100%" height="100%" fill="{SURFACE}"/>',
           f'<text x="16" y="24" font-size="15" font-weight="600" fill="{INK}">{escape(title)}</text>',
           f'<circle cx="22" cy="46" r="5" fill="{PASS}"/><text x="32" y="50" font-size="12" fill="{INK}">Passes, any margin</text>',
           f'<circle cx="172" cy="46" r="4" fill="{SURFACE}" stroke="{PASS}" stroke-width="2"/>'
           f'<text x="182" y="50" font-size="12" fill="{INK}">At 50.5% Yes</text>']
    for t in [0, 0.25, 0.5, 0.75, 1.0]:
        out.append(f'<line x1="{sx(t):.1f}" x2="{sx(t):.1f}" y1="{top - 8}" y2="{height - 32}" stroke="{GRID}"/>')
        out.append(f'<text x="{sx(t):.1f}" y="{height - 14}" font-size="11" fill="{INK_2}" text-anchor="middle">{t:.0%}</text>')
    for i, (option, text, py, pc) in enumerate(rows):
        y = top + row_h * i + row_h / 2
        out.append(f'<text x="{left - 12}" y="{y + 4:.1f}" font-size="12" fill="{INK}" text-anchor="end">{escape(option)}</text>')
        out.append(f'<g><title>{escape(text)} {py:.0%} if it passes; {pc:.0%} at 50.5%</title>')
        out.append(f'<line x1="{sx(min(py, pc)):.1f}" x2="{sx(max(py, pc)):.1f}" y1="{y:.1f}" y2="{y:.1f}" stroke="{INK_2}" stroke-width="2"/>')
        out.append(f'<circle cx="{sx(py):.1f}" cy="{y:.1f}" r="5" fill="{PASS}" stroke="{SURFACE}" stroke-width="2"/>')
        out.append(f'<circle cx="{sx(pc):.1f}" cy="{y:.1f}" r="4" fill="{SURFACE}" stroke="{PASS}" stroke-width="2"/></g>')
    out.append("</svg>")
    return "\n".join(out)


def write(graph: Graph, result: dict, outdir: Path) -> list[Path]:
    plots = outdir / "plots"
    plots.mkdir(parents=True, exist_ok=True)
    written = []
    for nid in graph.order:
        node = graph.nodes[nid]
        if node.kind == "quantity" and nid != "turnout":
            path = plots / f"{nid}.svg"
            path.write_text(interval_chart(graph, nid, result["nodes"][nid]))
            written.append(path)
    svg = status_chart(graph, result)
    if svg:
        path = plots / "ban-status.svg"
        path.write_text(svg)
        written.append(path)
    for module, title in [("spillover", "Political spillovers: probability by result"),
                          ("vote", "Denver's foie gras measure passes")]:
        svg = dot_chart(graph, result, module, title)
        if svg:
            path = plots / f"probabilities-{module}.svg"
            path.write_text(svg)
            written.append(path)
    return written
