"""Plate-umpire walk index -> PITCHER_BB in production (#1482 D2b), validated in #1528.

The engine's adjusted BB price must equal the research ``predict("bb", ...)`` that passed
the pre-registered held-out test. PITCHER_K is untouched (the K sub-lane did not ship).
Missing inputs (no umpire assigned yet, schedule failure, thin history) keep the
unadjusted price and say why.
"""
from __future__ import annotations

import hashlib
import io
import json
import random
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from sportsedge import mlb_umpire_bb_context as C
from sportsedge import mlb_umpire_context_research as R
from sportsedge.mlb_empirical_support import support_evidence
from sportsedge.mlb_generic_features import MLBGenericHistorySource
from sportsedge.pitcher_joint_engine import price_pitcher_market

ROOT = Path(__file__).resolve().parents[1]
TEAMS = list(range(101, 131))
UMPS = list(range(5001, 5061))
SEASONS = (2024, 2025, 2026)
TARGET = date(2026, 5, 20)
TONIGHT_PK = 999_001
TONIGHT_UMP = UMPS[7]


@lru_cache(maxsize=None)
def _league():
    """Synthetic league: every team plays daily; each game has a plate umpire with its own walk tendency."""
    rnd = random.Random(20261004)
    team_splits = {(t, s): [] for t in TEAMS for s in SEASONS}
    sched: list[tuple[str, int, int]] = []
    for season in SEASONS:
        start = date(season, 3, 28)
        for day in range(150):
            d = (start + timedelta(days=day)).isoformat()
            order = TEAMS[:]
            rnd.shuffle(order)
            for slot in range(15):
                pk = season * 100_000 + day * 100 + slot
                ump = UMPS[(day * 15 + slot + season) % len(UMPS)]
                bb_rate = 0.06 + 0.05 * ((ump * 13) % 60) / 59
                for team in order[2 * slot:2 * slot + 2]:
                    pa = rnd.randint(33, 42)
                    bb = sum(rnd.random() < bb_rate for _ in range(pa))
                    ks = sum(rnd.random() < 0.22 for _ in range(pa))
                    team_splits[(team, season)].append({"date": d, "game": {"gamePk": pk},
                                                        "stat": {"strikeOuts": ks, "baseOnBalls": bb, "plateAppearances": pa}})
                sched.append((d, pk, ump))
    return team_splits, sched


def _fetch_team(team: int, season: int) -> dict:
    return {"stats": [{"splits": _league()[0][(team, season)]}]}


def _officials(ump: int) -> list[dict]:
    return [{"officialType": "First Base", "official": {"id": 1, "fullName": "Someone Else"}},
            {"officialType": "Home Plate", "official": {"id": ump, "fullName": f"Ump {ump}"}}]


def _fetch_schedule(start: date, end: date) -> dict:
    by_date: dict[str, list] = {}
    for d, pk, ump in _league()[1]:
        if start.isoformat() <= d <= end.isoformat():
            by_date.setdefault(d, []).append({"gamePk": pk, "officials": _officials(ump)})
    return {"dates": [{"date": d, "games": g} for d, g in sorted(by_date.items())]}


@lru_cache(maxsize=None)
def _index() -> C.UmpireBBIndex:
    return C.build_index(_fetch_team, TEAMS, _fetch_schedule, TARGET)


def _own(n: int, seed: int, unknown: int = 0) -> list[tuple[dict, date, int | None]]:
    """n prior starts on real synthetic games (the last ``unknown`` on games with no umpire record)."""
    rnd = random.Random(seed)
    games = [(d, pk) for d, pk, _ in _league()[1] if "2025-04-01" <= d < TARGET.isoformat()]
    picks = sorted(rnd.sample(games, n))
    out = []
    for i, (d, pk) in enumerate(picks):
        if i >= n - unknown:
            pk = 888_000 + i
        out.append(({"strikeouts": 5, "outs": 16, "earned_runs": 2, "hits_allowed": 5,
                     "walks_allowed": rnd.randint(0, 6)}, date.fromisoformat(d), pk))
    return out


def test_prereg_binding_and_frozen_candidate():
    sha = hashlib.sha256((ROOT / "docs/MLB_UMPIRE_CONTEXT_PREREG.md").read_bytes()).hexdigest()
    assert sha.startswith(C.PREREG_SHA256_PREFIX)
    assert (C.W, C.BETA) == (6000.0, 2.0) and (C.W, C.BETA) in R.CANDIDATES
    assert C.CAP == R.CAPS["bb"] and C.STAT == "bb"


def test_schedule_windows_cover_lookback_and_stop_before_target():
    wins = C.schedule_windows(TARGET)
    assert wins[0][0] == date(2024, 3, 1)
    assert wins[-1][1] == TARGET - timedelta(days=1)
    assert all(a <= b for a, b in wins) and all(a.month in range(3, 11) for a, _ in wins)


@pytest.mark.parametrize("n,seed,unknown", [(5, 1, 0), (7, 2, 0), (10, 3, 0), (10, 4, 2), (6, 5, 1)])
def test_engine_equals_validated_research_predict_bb(n, seed, unknown):
    index = _index()
    own = _own(n, seed, unknown)
    feats = {"history_pool": [r for r, _, _ in own],
             "ump_bb_adjustment": C.adjustment_features(index, target_umpire={"umpire_id": TONIGHT_UMP, "umpire_name": "X"},
                                                        target_date=TARGET, history=[(d, pk) for _, d, pk in own])}
    # Research index over ALL synthetic games (including after the target): the window makes it identical.
    team_rows = [row for t in TEAMS for s in SEASONS for row in R.team_game_rows(_fetch_team(t, s))]
    umps = {pk: u for _, pk, u in _league()[1]}
    research_idx = R.UmpIndex(R.game_totals(team_rows), umps)
    umps_t = {**umps, TONIGHT_PK: TONIGHT_UMP}
    starts = [R.UStart(1, d.year, d.isoformat(), pk, 1, 2, 0, r["walks_allowed"]) for r, d, pk in own]
    target = R.UStart(1, 2026, TARGET.isoformat(), TONIGHT_PK, 1, 2, 0, 0)
    research = R.predict("bb", starts, target, umps_t, research_idx, None, (C.W, C.BETA))
    baseline = R.predict("bb", starts, target, umps_t, research_idx, None, R.BASELINE)
    moved = False
    for i, line in enumerate(R.THRESH["bb"]):
        for side in ("OVER", "UNDER"):
            out = price_pitcher_market({"market": "PITCHER_BB", "side": side, "line": float(line), "features": feats})
            expected = research[i] if side == "OVER" else 1 - research[i]
            assert out["model_p"] == pytest.approx(float(expected), abs=1e-12)
            assert out["meta"]["effective_history_starts"] == n
            plain = price_pitcher_market({"market": "PITCHER_BB", "side": side, "line": float(line),
                                          "features": {"history_pool": feats["history_pool"]}})
            base = baseline[i] if side == "OVER" else 1 - baseline[i]
            assert plain["model_p"] == pytest.approx(float(base), abs=1e-12)
            moved = moved or abs(out["model_p"] - plain["model_p"]) > 1e-6
    assert moved
    assert feats["ump_bb_adjustment"]["history_umpires_known"] == n - unknown


def test_scope_is_exactly_what_was_validated():
    index = _index()
    own = _own(8, 9)
    pool = [r for r, _, _ in own]
    adj = C.adjustment_features(index, target_umpire={"umpire_id": TONIGHT_UMP}, target_date=TARGET,
                                history=[(d, pk) for _, d, pk in own])
    feats = {"history_pool": pool, "ump_bb_adjustment": adj}
    plain = {"history_pool": pool}
    for market, line in (("PITCHER_BB", 2.0), ("PITCHER_K", 5.5), ("PITCHER_OUTS", 15.5), ("PITCHER_ER", 2.5)):
        a = price_pitcher_market({"market": market, "side": "OVER", "line": line, "features": feats})
        b = price_pitcher_market({"market": market, "side": "OVER", "line": line, "features": plain})
        assert a["model_p"] == b["model_p"] and "ump_bb_adjustment" not in a["meta"]
    with pytest.raises(C.UmpireBBContextError):
        C.adjustment_features(index, target_umpire={"umpire_id": TONIGHT_UMP}, target_date=TARGET,
                              history=[(d, pk) for _, d, pk in own[:4]])
    with pytest.raises(ValueError, match="align"):
        price_pitcher_market({"market": "PITCHER_BB", "side": "OVER", "line": 1.5,
                              "features": {"history_pool": pool, "ump_bb_adjustment": dict(adj, history_rel=adj["history_rel"][:-1])}})


def test_incomplete_officials_fail_closed():
    def sparse(start, end):
        payload = _fetch_schedule(start, end)
        for block in payload["dates"]:
            for i, g in enumerate(block["games"]):
                if i % 4 == 0:
                    g["officials"] = []
        return payload
    with pytest.raises(C.UmpireBBContextError, match="officials incomplete"):
        C.build_index(_fetch_team, TEAMS, sparse, TARGET)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Source(MLBGenericHistorySource):
    def __init__(self, n: int, *, assigned: bool = True, schedule_ok: bool = True):
        self.calls: list[str] = []
        self.assigned, self.schedule_ok = assigned, schedule_ok
        super().__init__(opener=self._open)
        self.own = _own(n, 11)

    def _open(self, req, timeout=None):
        url = req.full_url
        self.calls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        assert "/schedule" in url
        if "date" in q:
            games = [{"gamePk": TONIGHT_PK, "officials": _officials(TONIGHT_UMP) if self.assigned else []}]
            body = {"dates": [{"date": q["date"], "games": games}]}
        else:
            if not self.schedule_ok:
                raise OSError("statsapi down")
            assert q.get("gameType") == "R" and q.get("hydrate") == "officials"
            body = _fetch_schedule(date.fromisoformat(q["startDate"]), date.fromisoformat(q["endDate"]))
        return _Resp(json.dumps(body).encode())

    def player_rows(self, *, player_id, group, target_date):
        return [{"date": d, "opponent_id": TEAMS[i % 30], "game_pk": pk,
                 "stat": {"gamesStarted": 1, "inningsPitched": "5.1", "strikeOuts": 4,
                          "earnedRuns": 2, "hits": 4, "baseOnBalls": r["walks_allowed"]}}
                for i, (r, d, pk) in enumerate(self.own)]

    def _team_season(self, team_id, season):
        return _fetch_team(team_id, season)

    def _mlb_team_ids(self, season):
        return list(TEAMS)


def _row(src, market):
    return src.feature_row(game_pk=TONIGHT_PK, market=market, entity_id="9", target_date=TARGET,
                           away_team_id=TEAMS[2], home_team_id=TEAMS[0], player_id=9, team_id=TEAMS[2])


def test_feature_payload_attaches_only_to_bb_and_matches_direct_build():
    src = _Source(8)
    bb = _row(src, "PITCHER_BB")
    assert bb["joint_feature_version"] == "mlb_pitcher_joint_history_ump_bb_v1"
    adj = bb["features"]["ump_bb_adjustment"]
    assert adj["market"] == "PITCHER_BB" and adj["W"] == 6000.0 and adj["beta"] == 2.0
    assert adj["umpire_id"] == TONIGHT_UMP and adj["umpire_name"] == f"Ump {TONIGHT_UMP}"
    direct = C.adjustment_features(_index(), target_umpire={"umpire_id": TONIGHT_UMP}, target_date=TARGET,
                                   history=[(d, pk) for _, d, pk in src.own])
    assert adj["history_rel"] == direct["history_rel"] and adj["target_rel"] == direct["target_rel"]
    k = _row(src, "PITCHER_K")
    assert "ump_bb_adjustment" not in k["features"] and "ump_bb_unadjusted" not in k
    sched_calls = [c for c in src.calls if "startDate" in c]
    _row(src, "PITCHER_BB")
    assert [c for c in src.calls if "startDate" in c] == sched_calls  # index memoized per slate


@pytest.mark.parametrize("kwargs,why", [({"assigned": False}, "not assigned yet"),
                                        ({"schedule_ok": False}, "umpire walk index unavailable")])
def test_missing_input_keeps_unadjusted_price(kwargs, why):
    src = _Source(8, **kwargs)
    row = _row(src, "PITCHER_BB")
    assert "ump_bb_adjustment" not in row["features"]
    assert why in row["ump_bb_unadjusted"]
    out = price_pitcher_market({"market": "PITCHER_BB", "side": "OVER", "line": 1.5, "features": row["features"]})
    ref = price_pitcher_market({"market": "PITCHER_BB", "side": "OVER", "line": 1.5,
                                "features": {"history_pool": row["features"]["history_pool"]}})
    assert out["model_p"] == ref["model_p"]
    ev = support_evidence(row, {**out, "american_odds": -110, "engine_version": "mlb_pitcher_joint_empirical_v1"})
    assert why in ev["ump_bb_unadjusted"]
    notes = C.ump_bb_notes({"results": [{"entity_id": "9", "market": "PITCHER_BB", "empirical_evidence": ev}]}, {"9": "Tarik Skubal"})
    assert notes == [f"UMP-BB UNADJUSTED Tarik Skubal Pitcher BB: {ev['ump_bb_unadjusted']}; priced from own starts only (as before)."]


def test_unassigned_umpire_skips_heavy_fetch():
    src = _Source(8, assigned=False)
    _row(src, "PITCHER_BB")
    assert not [c for c in src.calls if "startDate" in c]


def test_card_note_and_integer_line():
    src = _Source(8)
    row = _row(src, "PITCHER_BB")
    half = price_pitcher_market({"market": "PITCHER_BB", "side": "OVER", "line": 1.5, "features": row["features"]})
    whole = price_pitcher_market({"market": "PITCHER_BB", "side": "OVER", "line": 2.0, "features": row["features"]})
    ev = support_evidence(row, {**half, "american_odds": -110, "engine_version": "mlb_pitcher_joint_empirical_v1"})
    assert ev["ump_bb_adjustment"]["own_starts"] == 8
    assert ev["ump_bb_adjustment"]["factor"] == pytest.approx(half["meta"]["ump_bb_adjustment"]["factor"], abs=1e-12)
    assert "integer line" in support_evidence(row, {**whole, "american_odds": -110, "engine_version": "mlb_pitcher_joint_empirical_v1"})["ump_bb_unadjusted"]
    notes = C.ump_bb_notes({"results": [{"entity_id": "9", "market": "PITCHER_BB", "empirical_evidence": ev}]}, {"9": "Tarik Skubal"})
    assert notes[0].startswith(f"UMP-BB ADJ x{ev['ump_bb_adjustment']['factor']:.2f} Tarik Skubal Pitcher BB: plate umpire Ump {TONIGHT_UMP}")
    assert "LEAN max" in notes[0] and "#1528" in notes[0]
