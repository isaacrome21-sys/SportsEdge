import json
from datetime import datetime, timedelta, timezone

import pytest

from sportsedge import mlb_f5_team_total_ladder as m

T0 = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _games(n, f5=2, reg=5, start=T0):
    return [{"game_id": str(i), "start": start + timedelta(days=i), "away_f5": f5, "home_f5": f5,
             "away_reg": reg, "home_reg": reg, "completed_innings": 9} for i in range(n)]


def test_f5_nb_plus_late_reproduces_full_game_nb():
    r, mu, s = m.V8_INDEPENDENT_TEAM_DISPERSION_R, 4.6, 0.55
    n, f5, tot = 60000, [0] * 40, [0] * 40
    import numpy as np
    g = np.random.default_rng(7)
    lam = g.gamma(r, mu / r, n)
    a, b = g.poisson(s * lam), g.poisson((1 - s) * lam)
    for x, y in zip(a, b):
        f5[min(x, 39)] += 1
        tot[min(x + y, 39)] += 1
    for emp, pmf in ((f5, m.nb_pmf(s * mu)), (tot, m.nb_pmf(mu))):
        assert max(abs(e / n - p) for e, p in zip(emp, pmf)) < 0.006


def test_ladder_two_sided_monotone_and_main_line():
    out = m.price_f5_team_totals({"away_mean_runs": 4.4, "home_mean_runs": 4.8, "f5_share": 0.55})
    assert out["main_line"] == 1.5 and out["play_authority"] is False
    for side in ("AWAY", "HOME"):
        lad = out["teams"][side]["ladder"]
        assert [x["line"] for x in lad] == [0.5, 1.5, 2.5, 3.5, 4.5]
        assert all(abs(x["over"] + x["under"] + x["push"] - 1) < 1e-12 and x["push"] == 0 for x in lad)
        assert all(lad[i]["over"] > lad[i + 1]["over"] for i in range(4))
    assert out["teams"]["HOME"]["ladder"][1]["over"] > out["teams"]["AWAY"]["ladder"][1]["over"]


def test_whole_line_push_mass():
    out = m.price_f5_team_totals({"away_mean_runs": 4.4, "home_mean_runs": 4.4, "f5_share": 0.55, "lines": [2]})
    row = out["teams"]["AWAY"]["ladder"][0]
    assert row["push"] > 0 and abs(row["over"] + row["under"] + row["push"] - 1) < 1e-12


def _ledger(avail, event_id="777"):
    variants = ([{"period": "F5", "phase": "PREGAME", "offer_shape": "OVER_UNDER",
                  "settlement": "DK_STANDARD", "line_variant": "MAIN"}]
                if avail == "OFFERED_ON_THIS_EVENT" else [])
    return {"schema": "DK_EVENT_COVERAGE_RECONCILIATION_V1", "sport": "MLB", "book": "draftkings",
            "event_id": event_id, "observed_at_utc": "2026-10-13T12:00:00+00:00",
            "rows": [{"market": "F5_TOTALS", "availability": avail, "offer_variants": variants}]}


def test_f5_game_total_offering_is_per_event_and_unknown_by_default():
    assert m.f5_game_total_offering(None, event_id="777")["availability"] == "UNKNOWN"
    assert m.f5_game_total_offering(_ledger("NOT_OFFERED_ON_THIS_EVENT"), event_id="777")["availability"] \
        == "NOT_OFFERED_ON_THIS_EVENT"
    assert m.f5_game_total_offering(_ledger("NOT_OFFERED_ON_THIS_EVENT"), event_id="888")["availability"] == "UNKNOWN"
    assert m.f5_game_total_offering(_ledger("NOT_VERIFIED_ON_THIS_EVENT"), event_id="777")["availability"] == "UNKNOWN"
    assert m.f5_game_total_offering(_ledger("OFFERED_ON_THIS_EVENT"), event_id="777")["availability"] \
        == "OFFERED_ON_THIS_EVENT"
    bad = _ledger("NOT_OFFERED_ON_THIS_EVENT")
    bad["book"] = "fanduel"  # rejected by #2143's audit -> UNKNOWN, never NOT_OFFERED
    r = m.f5_game_total_offering(bad, event_id="777")
    assert r["availability"] == "UNKNOWN" and r["reason"].startswith("LEDGER_INVALID")
    assert r["source"] == "PROVIDER_BOOK_EVIDENCE_AUDIT_2143"
    off = m.f5_game_total_offering(_ledger("OFFERED_ON_THIS_EVENT"), event_id="777")
    assert "over" not in off and off["market_baseline"] == "MISSING"


def test_model_output_separate_from_market_and_disabled_factors_rejected():
    out = m.price_f5_team_totals({"away_mean_runs": 4, "home_mean_runs": 4, "f5_share": .5})
    assert out["kind"] == "MODEL_PROBABILITY_ONLY" and out["market_baseline"] == "MISSING"
    assert not {"odds", "price", "edge", "ev"} & set(out)
    with pytest.raises(m.F5LadderError):
        m.price_f5_team_totals({"market": "F5_TOTALS", "away_mean_runs": 4, "home_mean_runs": 4, "f5_share": .5})
    with pytest.raises(m.F5LadderError, match="disabled"):
        m.price_f5_team_totals({"away_mean_runs": 4, "home_mean_runs": 4, "f5_share": .5, "rest_adj": 0.1})


def test_settlement_is_fail_closed_unverified_dk_rules():
    cases = [
        (m.settle_f5_team_total(team_f5_runs=2, line=2, side="OVER", completed_innings=5), "PUSH"),
        (m.settle_f5_team_total(team_f5_runs=2, line=1.5, side="OVER", completed_innings=9), "WIN"),
        (m.settle_f5_team_total(team_f5_runs=1, line=1.5, side="OVER", completed_innings=9), "LOSS"),
        (m.settle_f5_team_total(team_f5_runs=5, line=1.5, side="OVER", completed_innings=4.2),
         "SHORTENED_RULE_UNVERIFIED"),
        (m.settle_either_pitcher_max(away_value=5, home_value=3, line=5, side="OVER"), "PUSH"),
        (m.settle_either_pitcher_max(away_value=7, home_value=3, line=5.5, side="UNDER"), "LOSS"),
        (m.settle_either_pitcher_max(away_value=7, home_value=3, line=5.5, side="OVER", both_started=False),
         "PITCHER_DID_NOT_START_RULE_UNVERIFIED"),
    ]
    for res, structural in cases:
        assert res["settlement_status"] == "UNVERIFIED_DK_RULES" and res["grade"] is None
        assert res["authoritative"] is False and res["structural_outcome"] == structural
    assert len(m.DK_RULES_REQUIRED) >= 4


def test_share_is_point_in_time():
    games = _games(40)
    late = _games(40, f5=9, reg=9, start=T0 + timedelta(days=100))
    as_of = T0 + timedelta(days=50)
    a = m.fit_f5_share(games, as_of=as_of)
    assert a == m.fit_f5_share(list(reversed(games + late)), as_of=as_of)
    assert a["share"] == pytest.approx(0.4)
    with pytest.raises(m.F5LadderError):
        m.fit_f5_share(games, as_of=T0 + timedelta(days=10))


def test_started_but_not_final_before_cutoff_is_excluded():
    games = _games(30)
    cutoff = games[-1]["start"] + timedelta(hours=2)  # last game started but not final
    with pytest.raises(m.F5LadderError):
        m.fit_f5_share(games, as_of=cutoff)
    assert m.fit_f5_share(games, as_of=games[-1]["start"] + timedelta(hours=6))["games"] == 30
    ended = [dict(g, final_at=g["start"] + timedelta(hours=3)) for g in games]
    assert m.fit_f5_share(ended, as_of=cutoff + timedelta(hours=1))["games"] == 30
    live = [dict(g, status="IN_PROGRESS") if i == 29 else g for i, g in enumerate(games)]
    with pytest.raises(m.F5LadderError):
        m.fit_f5_share(live, as_of=cutoff + timedelta(days=5))


def test_either_pitcher_max_ladder():
    a, b = [0.2, 0.3, 0.5], [0.6, 0.4]
    out = m.either_pitcher_ladder(a, b, [0.5, 1, 1.5])
    # P(max <= 0) = .2*.6 ; P(max <= 1) = .5*1.0
    assert out["ladder"][0]["over"] == pytest.approx(1 - 0.12)
    assert out["ladder"][1]["push"] == pytest.approx(0.5 - 0.12)
    assert out["ladder"][2]["over"] == pytest.approx(0.5)
    assert out["status"] == "RESEARCH_ONLY" and out["play_authority"] is False


def _find(node, key):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == key:
                yield v
            yield from _find(v, key)
    elif isinstance(node, list):
        for v in node:
            yield from _find(v, key)


def test_f5_markets_remain_ineligible_in_deployments():
    cfg = json.load(open("config/deployments.json"))
    for mk in ("F5_MONEYLINE", "F5_RUN_LINE", "F5_TOTALS", "F5_TEAM_TOTALS"):
        hits = list(_find(cfg, mk))
        assert hits and all(h.get("eligible") is False for h in hits if isinstance(h, dict))
