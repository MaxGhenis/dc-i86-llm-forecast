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


def sample_share_band(grid, cdf, floor, ceiling, lo, hi, u, defensive: float = 0.0):
    """Shares in (lo, hi] from the forecaster's CDF truncated to the band, and each draw's weight.

    The CDF is linear between knots, so the band splits at the knots into segments within which the
    share is uniform. A draw picks a segment, then a point in it. With `defensive` d, the segment is
    picked with probability (1 - d) times the forecaster's own probability plus d spread evenly over
    every segment the forecaster gives any probability (a defensive mixture), and the weight
    p/q undoes the mixture: weighted means are exact, and no segment with probability goes unsampled
    however small that probability. With d = 0 every weight is 1.
    """
    xs, fs = share_knots(grid, cdf, floor, ceiling)
    pts = np.unique(np.concatenate([[lo, hi], xs[(xs > lo) & (xs < hi)]]))
    mass = np.diff(np.interp(pts, xs, fs))
    keep = mass > 0
    if not keep.any():
        raise ValueError(f"no probability on Yes shares in ({lo}, {hi}]")
    a, b, m = pts[:-1][keep], pts[1:][keep], mass[keep]
    p = m / m.sum()
    q = (1 - defensive) * p + defensive / len(m)
    cq = np.cumsum(q)
    cq[-1] = 1.0
    u = np.asarray(u, dtype=float)
    seg = np.minimum(np.searchsorted(cq, u, side="right"), len(m) - 1)
    frac = np.clip((u - (cq[seg] - q[seg])) / q[seg], 0.0, 1.0)
    return a[seg] + frac * (b[seg] - a[seg]), p[seg] / q[seg]


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
