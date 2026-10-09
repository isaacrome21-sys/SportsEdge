"""Regression: indexed MLB quote pairing must preserve exhaustive unique-match semantics."""
import random

from sportsedge.mlb_quote_pairing import (
    MAX_PAIRED_SKEW_SECONDS, N_WAY_MARKETS, _is_complement, _norm_market,
    _period, _retrieved_at, pair_opposite_odds,
)

T0 = "2026-10-09T10:00:00+00:00"
T10 = "2026-10-09T10:00:10+00:00"
T40 = "2026-10-09T10:00:40+00:00"


def _row(side, line, **kw):
    return dict(game_id="g", market="TOTALS", entity_id="game", book_key="dk",
                period="FG", side=side, line=line, american_odds=-110,
                retrieved_at=T0, **kw)


def _reference(rows):
    out = [dict(row) for row in rows]
    for i, row in enumerate(out):
        if _norm_market(row) in N_WAY_MARKETS or row.get("opposite_odds") is not None:
            continue
        stamp = _retrieved_at(row)
        if stamp is None:
            continue
        matches = []
        for j, other in enumerate(out):
            if i == j or _period(row) != _period(other):
                continue
            if not _is_complement(row, other) or other.get("american_odds") is None:
                continue
            other_stamp = _retrieved_at(other)
            if other_stamp is None or abs((other_stamp - stamp).total_seconds()) > MAX_PAIRED_SKEW_SECONDS:
                continue
            matches.append(other)
        if len(matches) == 1:
            row["opposite_odds"] = matches[0]["american_odds"]
    return out


def test_unhashable_lines_and_cross_type_set_equality():
    for first, second in [([1, 2], [1, 2]), ({"x": [1]}, {"x": [1]}),
                          ({1, 2}, frozenset({1, 2}))]:
        rows = [_row("OVER", first), _row("UNDER", second)]
        assert pair_opposite_odds(rows) == _reference(rows)


def test_ambiguous_quotes_fail_closed():
    rows = [_row("OVER", 7.5), _row("UNDER", 7.5),
            _row("UNDER", 7.5)]
    assert pair_opposite_odds(rows) == _reference(rows)
    assert "opposite_odds" not in pair_opposite_odds(rows)[0]


def test_seeded_randomized_index_equivalence():
    rng = random.Random(1903)
    lines = [None, 7.5, -1.5, 0, "x", "8.5", [1, 2], {"x": 1}, {1, 2},
             frozenset({1, 2})]
    for _ in range(300):
        rows = []
        for _ in range(rng.randrange(2, 30)):
            row = _row(rng.choice(["OVER", "UNDER", "YES", "NO", "HOME", "AWAY"]),
                       rng.choice(lines))
            row["game_id"] = rng.choice(["g", "h"])
            row["market"] = rng.choice(["TOTALS", "RUN_LINE", "FIRST_HOME_RUN"])
            row["entity_id"] = rng.choice(["game", "team"])
            row["book_key"] = rng.choice(["dk", "fd"])
            row["period"] = rng.choice(["FG", "F5"])
            row["retrieved_at"] = rng.choice([T0, T10, T40, None])
            rows.append(row)
        assert pair_opposite_odds(rows) == _reference(rows)
