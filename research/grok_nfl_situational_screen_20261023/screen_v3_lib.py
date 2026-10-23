"""Naive largest-lead baseline for screen v3: earlier seasons only, incl. fallback."""


def naive_largest_lead(rows, season):
    """(pmf over 0..max+10 with +0.5 Laplace, out-of-support fallback mass).

    Both use only rows with season < `season`; v1/v2 used the size of the full
    table (all seasons) for the out-of-support fallback.
    """
    pool = [r["largest_lead"] for r in rows if r["season"] < season]
    if not pool:
        raise ValueError("EMPTY_NAIVE_POOL")
    c = {}
    for v in pool:
        c[v] = c.get(v, 0) + 1
    mx = max(c) + 10
    t = len(pool) + 0.5 * (mx + 1)
    return {k: (c.get(k, 0) + 0.5) / t for k in range(mx + 1)}, 0.5 / t
