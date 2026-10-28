"""Samplers for the forecast kinds, vectorized over draws.

Every sampler takes uniforms drawn by the caller, so two simulations that draw the same uniforms in
the same order share their random numbers (the cutoff contrast relies on this).

- quantity: a piecewise-linear inverse CDF through the forecast quantiles. Below the lowest and above
  the highest quantile it continues the neighbouring segment's slope to probability 0 and 1, clipped
  to the node's bounds.
- share_cdf: a piecewise-linear CDF through the grid, falling to 0 at `share_floor` and rising to 1 at
  `share_ceiling`.
- pmf: a categorical draw.
- binary: u < p.
"""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np

_EPS = 1e-12


def quantity_knots(levels: np.ndarray, xs: np.ndarray, lo: float, hi: float):
    """Knot probabilities and values per row. xs has shape (n, k) for k quantile levels."""
    levels = np.asarray(levels, dtype=float)
    xs = np.atleast_2d(np.asarray(xs, dtype=float))
    left = xs[:, 0] - (xs[:, 1] - xs[:, 0]) * levels[0] / (levels[1] - levels[0])
    right = xs[:, -1] + (xs[:, -1] - xs[:, -2]) * (1 - levels[-1]) / (levels[-1] - levels[-2])
    left = np.clip(left, lo, xs[:, 0])
    right = np.clip(right, xs[:, -1], hi)
    probs = np.concatenate([[0.0], levels, [1.0]])
    values = np.column_stack([left, xs, right])
    return probs, values


def interp_rows(probs: np.ndarray, values: np.ndarray, u: np.ndarray) -> np.ndarray:
    """Row-wise linear interpolation of values (n, k) at u (n,) on shared, increasing probs (k,)."""
    j = np.clip(np.searchsorted(probs, u, side="right") - 1, 0, len(probs) - 2)
    p0, p1 = probs[j], probs[j + 1]
    rows = np.arange(len(u))
    v0, v1 = values[rows, j], values[rows, j + 1]
    w = np.where(p1 > p0, (u - p0) / np.where(p1 > p0, p1 - p0, 1.0), 0.0)
    return v0 + w * (v1 - v0)


def sample_quantity(levels, xs, lo, hi, u, integer=False) -> np.ndarray:
    xs = np.atleast_2d(np.asarray(xs, dtype=float))
    if xs.shape[0] == 1 and len(u) > 1:
        xs = np.repeat(xs, len(u), axis=0)
    probs, values = quantity_knots(levels, xs, lo, hi)
    out = interp_rows(probs, values, np.asarray(u, dtype=float))
    return np.rint(out) if integer else out


def share_knots(grid, cdf, floor, ceiling):
    xs = np.concatenate([[floor], np.asarray(grid, dtype=float), [ceiling]])
    fs = np.concatenate([[0.0], np.asarray(cdf, dtype=float), [1.0]])
    return xs, fs


def sample_share(grid, cdf, floor, ceiling, u) -> np.ndarray:
    xs, fs = share_knots(grid, cdf, floor, ceiling)
    # Flat stretches of the CDF hold no mass; a tiny tilt keeps the inverse well defined.
    tilted = fs + np.arange(len(fs)) * _EPS
    tilted = (tilted - tilted[0]) / (tilted[-1] - tilted[0])
    return np.interp(np.asarray(u, dtype=float), tilted, xs)


def share_cdf_at(grid, cdf, floor, ceiling, x) -> np.ndarray:
    xs, fs = share_knots(grid, cdf, floor, ceiling)
    return np.interp(x, xs, fs)


def share_segments(grid, cdf, floor, ceiling, lo, hi, breaks=()):
    """The band (lo, hi] cut at the CDF's knots, and at `breaks`, inside it: each segment's ends a and
    b and the forecaster's probability on (a, b]. The CDF is linear between knots, so the share is
    uniform within a segment. The samplers draw only from segments whose probability is positive,
    and only shares in (a, b] (see `_inside`)."""
    xs, fs = share_knots(grid, cdf, floor, ceiling)
    inner = np.concatenate([xs, np.asarray(breaks, dtype=float)])
    pts = np.unique(np.concatenate([[lo, hi], inner[(inner > lo) & (inner < hi)]]))
    return pts[:-1], pts[1:], np.diff(np.interp(pts, xs, fs))


def _inside(a, b, x):
    """Draws `x` of segments (a, b], held there: a draw at the first fraction of a segment, or one a
    segment a few floats wide rounds to its left end, would otherwise land on a, which belongs to
    the segment before (at 50%, a failing share drawn for a passing one), and rounding can take a
    draw at the last fraction just past b."""
    return np.clip(x, np.nextafter(a, np.inf), b)


def sample_share_band(grid, cdf, floor, ceiling, lo, hi, u, defensive: float = 0.0):
    """Shares in (lo, hi] from the forecaster's CDF truncated to the band, and each draw's weight.

    The CDF is linear between knots, so the band splits at the knots into segments within which the
    share is uniform. A draw picks a segment, then a point in it. With `defensive` d, the segment is
    picked with probability (1 - d) times the forecaster's own probability plus d spread evenly over
    every segment the forecaster gives any probability (a defensive mixture), and the weight
    p/q undoes the mixture: weighted means are exact, and no segment with probability goes unsampled
    however small that probability. With d = 0 every weight is 1.
    """
    a, b, mass = share_segments(grid, cdf, floor, ceiling, lo, hi)
    keep = mass > 0
    if not keep.any():
        raise ValueError(f"no probability on Yes shares in ({lo}, {hi}]")
    a, b, m = a[keep], b[keep], mass[keep]
    p = m / m.sum()
    q = (1 - defensive) * p + defensive / len(m)
    cq = np.cumsum(q)
    cq[-1] = 1.0
    u = np.asarray(u, dtype=float)
    seg = np.minimum(np.searchsorted(cq, u, side="right"), len(m) - 1)
    frac = np.clip((u - (cq[seg] - q[seg])) / q[seg], 0.0, 1.0)
    return _inside(a[seg], b[seg], a[seg] + frac * (b[seg] - a[seg])), p[seg] / q[seg]


# A segment with at most this many floats in it is drawn over its floats (see sample_share_tilted).
NARROW_FLOATS = 1024


def _floats_in(a: float, b: float) -> np.ndarray:
    """The floats in (a, b], for 0 <= a < b: for nonnegative floats, the order of their bits is
    their order."""
    first, last = (np.array([a, b], dtype=np.float64) + 0.0).view(np.int64)  # + 0.0: -0.0 is 0.0
    return np.arange(first + 1, last + 1, dtype=np.int64).view(np.float64)


def _float_counts(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """How many floats lie in each (a, b], for nonnegative ends (NARROW_FLOATS + 1 for a negative a)."""
    a, b = np.ascontiguousarray(a, dtype=np.float64), np.ascontiguousarray(b, dtype=np.float64)
    return np.where(a >= 0, (b + 0.0).view(np.int64) - (np.where(a >= 0, a, 0.0) + 0.0).view(np.int64),
                    NARROW_FLOATS + 1)


def sample_share_tilted(grid, cdf, floor, ceiling, lo, hi, u, tilt, breaks, log2_scale: int = 0):
    """Shares in (lo, hi] drawn in proportion to the forecaster's density times `tilt`, never where
    the tilt is 0, and the tilt's mass Z, the integral of density times tilt over the band.

    `tilt(x)` is vectorized, nonnegative and linear between consecutive points of `breaks` (it may
    jump at them). The band splits at the CDF's knots and those points into segments where the
    density is constant and the tilt linear, from s_a at the left end to s_b at the right, so a
    segment's mass is its share mass times (s_a + s_b) / 2 and, within it, the draw's position t in
    [0, 1] inverts t (s_a + (s_b - s_a) t / 2) / ((s_a + s_b) / 2) = u, rounded to a float and kept
    off a float at either end where the tilt is 0 (rounding can reach such a float only from within
    one float of it). A segment with at most NARROW_FLOATS floats in it, where that rounding would
    matter, is drawn exactly over its floats: each float x stands for the shares in (the float
    before x, x], and has that part of the segment's share mass times tilt(x). Every draw then counts
    equally under the tilted distribution.

    Each segment's tilted mass is held as a mantissa and a power of two (frexp), so no product
    underflows however small its factors: the segments are drawn in proportion to their masses
    relative to the largest. Each segment's inversion runs on its ends scaled by the larger. A segment
    whose tilted mass is more than 2^1074 times smaller than the largest gets no draws.

    `tilt` may return the probability times 2^log2_scale (see simulate._Tilt); Z is then divided by
    it. Z is the segments' masses times (s_a + s_b) / 2, summed exactly as fractions and rounded once,
    so it is 0 only if that sum is below about 2.5e-324; the draws are exact all the same. Raises
    ValueError only if no segment has both share mass and tilt.
    """
    a, b, mass = share_segments(grid, cdf, floor, ceiling, lo, hi, breaks)
    mass = np.clip(mass, 0.0, None)
    narrow = _float_counts(a, b) <= NARROW_FLOATS
    # The tilt's ends on a wide segment, from two interior points (exact for a linear function, and
    # blind to a jump at either end), extrapolated from where those points rounded to.
    x1, x2 = a + (b - a) / 3, a + 2 * (b - a) / 3
    x1, x2 = np.where(narrow, a + (b - a) / 2, x1), np.where(narrow, b, x2)  # replaced below
    f1, f2 = np.asarray(tilt(x1), dtype=float), np.asarray(tilt(x2), dtype=float)
    slope = np.where(x2 > x1, (f2 - f1) / np.where(x2 > x1, x2 - x1, 1.0), 0.0)
    sa = np.clip(f1 - slope * (x1 - a), 0.0, None)
    sb = np.clip(f2 + slope * (b - x2), 0.0, None)
    # A narrow segment's floats, each with its part of the segment's share mass times its tilt; the
    # segment's mean tilt, exactly as a fraction, stands for (s_a + s_b) / 2.
    cells, means = {}, {}
    for j in np.flatnonzero(narrow & (mass > 0)):
        xs = _floats_in(float(a[j]), float(b[j]))
        ts = np.clip(np.asarray(tilt(xs), dtype=float), 0.0, None)
        widths = np.diff(np.concatenate([[a[j]], xs]))  # exact: neighbouring floats
        cells[j] = (xs, widths * ts)
        means[j] = (sum((Fraction(float(w)) * Fraction(float(t)) for w, t in zip(widths, ts) if t > 0), Fraction(0))
                    / (Fraction(float(b[j])) - Fraction(float(a[j]))))
        sa[j] = sb[j] = float(means[j])
    # mass * (s_a + s_b) as mantissa * 2^expo; rel is each relative to the largest.
    fm, em = np.frexp(mass)
    ft, et = np.frexp(sa + sb)
    mant, expo = fm * ft, em + et
    pos = mant > 0
    if not pos.any():
        raise ValueError(f"no probability on Yes shares in ({lo}, {hi}] where the condition can hold")
    top = int(expo[pos].max())
    rel = np.where(pos, np.ldexp(mant, np.where(pos, expo - top, 0)), 0.0)
    total = math.fsum(rel)
    exact = sum((Fraction(float(mass[j])) * (2 * means[j] if j in means else Fraction(float(sa[j])) + Fraction(float(sb[j])))
                 for j in np.flatnonzero(pos)), Fraction(0))
    z = float(exact / 2 / Fraction(2) ** log2_scale)  # Fraction -> float rounds once, to nearest
    kept = np.flatnonzero(rel > 0)
    a, b, sa, sb, rel = a[kept], b[kept], sa[kept], sb[kept], rel[kept]
    # Correctly rounded partial sums: a running sum's rounding could leave the bulk of the mass an ulp
    # short of 1 and hand u = 1 - 2^-52 to a segment of negligible weight.
    cq = np.array([math.fsum(rel[: i + 1]) for i in range(len(rel))]) / total
    cq[-1] = 1.0
    prev = np.concatenate([[0.0], cq[:-1]])
    u = np.asarray(u, dtype=float)
    seg = np.minimum(np.searchsorted(cq, u, side="right"), len(rel) - 1)
    r = np.clip((u - prev[seg]) / (cq[seg] - prev[seg]), 0.0, 1.0)
    end = np.maximum(sa[seg], sb[seg])  # positive: a kept segment has positive tilt somewhere
    s0, s1 = sa[seg] / end, sb[seg] / end
    den = s0 + np.sqrt(s0 * s0 + r * (s1 * s1 - s0 * s0))
    t = np.where(den > 0, r * (s0 + s1) / np.where(den > 0, den, 1.0), 0.0)
    x = _inside(a[seg], b[seg], a[seg] + np.clip(t, 0.0, 1.0) * (b[seg] - a[seg]))
    # Off an end float where the tilt is 0 (a wide segment has floats to spare).
    first = np.nextafter(a, np.inf)
    low = np.where(np.asarray(tilt(first), dtype=float) > 0, first, np.nextafter(first, np.inf))
    high = np.where(np.asarray(tilt(b), dtype=float) > 0, b, np.nextafter(b, -np.inf))
    x = np.clip(x, low[seg], high[seg])
    for i, j in enumerate(kept):
        if j in cells:
            xs, weights = cells[j]
            xs, weights = xs[weights > 0], weights[weights > 0]
            here = seg == i
            cum = np.array([math.fsum(weights[: k + 1]) for k in range(len(weights))]) / math.fsum(weights)
            cum[-1] = 1.0
            x[here] = xs[np.minimum(np.searchsorted(cum, r[here], side="right"), len(xs) - 1)]
    return x, z


def share_density_at_half(grid, cdf) -> float:
    """Density of the Yes share at 50%, from the 49% and 51% grid points."""
    grid = list(grid)
    return (cdf[grid.index(0.51)] - cdf[grid.index(0.49)]) / 0.02


def sample_pmf(probs, u) -> np.ndarray:
    """probs has shape (n, k) or (k,); returns category indices."""
    probs = np.atleast_2d(np.asarray(probs, dtype=float))
    if probs.shape[0] == 1 and len(u) > 1:
        probs = np.repeat(probs, len(u), axis=0)
    cum = np.cumsum(probs, axis=1)
    cum[:, -1] = 1.0
    return (np.asarray(u)[:, None] >= cum).sum(axis=1)


def pmf_values(labels) -> np.ndarray:
    """Numeric value of each pmf label; 'k+' counts as k."""
    return np.array([float(label.rstrip("+")) for label in labels])
