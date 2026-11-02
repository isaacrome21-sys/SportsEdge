"""#2: NFL props from the phone workflow through the canonical RUN IT path."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from artifacts import run_it_full as R
from sportsedge.nfl_lines_intake import parse_nfl_lines, tickets_to_dict
from sportsedge.nfl_prop_research_admission import (
    ADMISSION_DISPOSITION, NFL_PROP_MIN_PRIOR_GAMES, admit, sufficiency_met)
from sportsedge.nfl_props_card import (
    BANNER, card_rows, render_props_card, ticket_to_run_it_lines)

BODY = '''Philadelphia Eagles @ Washington Commanders
Captured: 2026-11-01T18:34:50-06:00
ML +225 -278
Spread +6 -108 -112
Total 40.5 -110 -110
Prop "Tanner McKee" PassYards 206.5 -112 -112
Prop "Dallas Goedert" ReceivingYards 45.5 -112 -112
Prop "Saquon Barkley" RushReceivingYards 63.5 -111 -115
Prop "Jayden Daniels" Interceptions 0.5 +141 -181
'''
KICK = {"PHI@WAS": "2026-11-02T01:20:00+00:00"}
AS_OF = "2026-11-02T00:36:00+00:00"            # 70 s after capture


def _ticket():
    return tickets_to_dict(parse_nfl_lines(BODY), observed_at="2026-11-01T18:44:30-06:00")


def test_adapter_preserves_quotes_names_lines_and_timestamps():
    rows, notes = ticket_to_run_it_lines(_ticket(), KICK)
    assert notes == []
    assert len(rows) == 8                      # 4 props x 2 sides; game lines stay on the phone card
    by = {(r["player_name"], r["market"], r["side"]): r for r in rows}
    r = by[("Tanner McKee", "PLAYER_PASSING_YARDS", "OVER")]
    assert (r["away"], r["home"], r["line"], r["odds"]) == (
        "Philadelphia Eagles", "Washington Commanders", 206.5, -112)
    assert r["quote_captured_at"] == "2026-11-01T18:34:50-06:00"
    assert r["kickoff"] == KICK["PHI@WAS"] and r["book"] == "draftkings"
    assert by[("Saquon Barkley", "PLAYER_RUSH_PLUS_REC_YARDS", "UNDER")]["odds"] == -115
    assert by[("Jayden Daniels", "PLAYER_INTERCEPTIONS", "OVER")]["odds"] == 141


def test_adapter_fails_closed_without_independent_kickoff():
    rows, notes = ticket_to_run_it_lines(_ticket(), {})
    assert rows == [] and notes == ["PHI@WAS: SCHEDULE_KICKOFF_UNAVAILABLE"]


def test_adapter_never_invents_a_missing_side():
    t = _ticket()
    t["games"][0]["markets"][3]["home_or_under_price"] = None
    rows, notes = ticket_to_run_it_lines(t, KICK)
    assert len(rows) == 7 and any("NO_PRICE_IN_PASTE" in n for n in notes)


def _priced(r, p, ev, n=12, fresh=True):
    return {"sport": "NFL", "market": r["market"], "selection": r["side"],
            "player_name": r["player_name"], "line": float(r["line"]),
            "status": "WATCH_PLAYER_PARTICIPATION_UNVERIFIED",
            "model_probability": p, "dk_no_vig_p": 0.5, "ev_per_dollar": ev,
            "dk_odds": r["odds"], "prior_game_count": n,
            "source": "FREE_ESPN_NFL_GAMELOG",
            "quote_status": "RECENT_CAPTURED_QUOTE" if fresh else "STALE_QUOTE",
            "research_only": True}


EVS = {("Tanner McKee", "OVER"): (0.60, 0.13), ("Dallas Goedert", "UNDER"): (0.56, 0.05),
       ("Saquon Barkley", "OVER"): (0.80, 0.52), ("Jayden Daniels", "UNDER"): (0.70, 0.01)}


def _run(monkeypatch, n=12, fresh=True):
    seen = []

    def lane(rows, *a, **k):
        seen.extend(rows)
        out = []
        for r in rows:
            p, ev = EVS.get((r["player_name"], r["side"]), (0.40, -0.25))
            out.append(_priced(r, p, ev, n=n, fresh=fresh))
        return out, []
    monkeypatch.setattr(R, "phone_nfl_player_rows", lane)
    rows, _ = ticket_to_run_it_lines(_ticket(), KICK)
    card = R.run_full({"sport": "NFL", "lines": rows}, now=datetime(2026, 11, 2, 0, 36, tzinfo=timezone.utc),
                      as_of=AS_OF, auto_context=False)
    return card, seen


def test_end_to_end_props_reach_empirical_lane_and_render_ranked(monkeypatch):
    card, seen = _run(monkeypatch)
    assert len(seen) == 8
    admitted = [r for r in card["evaluated_rows"] if r.get("registry_disposition") == ADMISSION_DISPOSITION]
    assert len(admitted) == 8
    assert all(r["research_only"] and r["counted"] is False and r["official_authority"] is False
               and r["staking_authority"] is False for r in admitted)
    md = render_props_card(card, title="PHI @ WAS")
    assert md.count(BANNER) == 1 and md.index(BANNER) < md.index("Tanner McKee")
    assert "**Tanner McKee Over 206.5 Pass Yds** (-112) · EV +13.0% · ★★★★☆" in md
    assert md.index("Tanner McKee Over") < md.index("Dallas Goedert Under")      # EV-ranked
    assert "🔥 **Tanner McKee" in md
    assert "Too-good-to-be-true" in md and "Saquon Barkley Over 63.5" in md.split("Too-good")[1]
    assert "Jayden Daniels Under 0.5 INTs" not in md.split("Priced")[0]          # -181: price cap / below floor
    rows = {(_r["player_name"], _r["selection"]): _r for _r in card_rows(card)}
    assert rows[("Jayden Daniels", "UNDER")]["bucket"] == "EXCLUDED_PRICE_CAP"
    assert rows[("Saquon Barkley", "OVER")]["bucket"] == "OVERCONFIDENCE"


def test_insufficient_history_restores_blocker_and_never_shows_ev(monkeypatch):
    card, _ = _run(monkeypatch, n=NFL_PROP_MIN_PRIOR_GAMES - 1)
    assert all(r["status"] == "NO_MODEL_OR_MARKET" and r["blocker"] == "NO_ENGINE"
               and r.get("ev_per_dollar") is None for r in card["evaluated_rows"])
    md = render_props_card(card, title="t")
    assert "No research candidates" in md and "SUFFICIENCY_NOT_MET" in md and "EV +" not in md


def test_stale_quotes_are_not_headlined(monkeypatch):
    card, _ = _run(monkeypatch, fresh=False)
    md = render_props_card(card, title="t")
    assert "EV +" not in md and "repost fresh lines" in md


def test_sufficiency_requires_engine_source_and_pricing_fields():
    good = {"model_probability": 0.6, "ev_per_dollar": 0.1, "dk_odds": -110,
            "prior_game_count": 10, "source": "FREE_ESPN_NFL_GAMELOG"}
    assert sufficiency_met(good)
    for bad in ({**good, "source": "INTAKE"}, {**good, "prior_game_count": True},
                {**good, "model_probability": None}, {**good, "status": "NO_MODEL_OR_MARKET"}):
        assert not sufficiency_met(bad)
    gate = {"status": "NO_MODEL_OR_MARKET", "blocker": "NO_ENGINE", "reason": "NO_ENGINE: x"}
    assert admit({**good, "source": "INTAKE"}, gate)["blocker"] == "NO_ENGINE"


def test_props_card_json_is_strict(monkeypatch):
    card, _ = _run(monkeypatch)
    json.loads(json.dumps(card_rows(card), default=str, allow_nan=False))


@pytest.mark.parametrize("market", ["ANYTIME_TDS", "RECEIVING_TDS"])
def test_unadmitted_prop_markets_stay_blocked(monkeypatch, market):
    called = []
    monkeypatch.setattr(R, "phone_nfl_player_rows", lambda rows, *a, **k: (called.extend(rows) or [], []))
    row = {"sport": "NFL", "away": "Philadelphia Eagles", "home": "Washington Commanders",
           "kickoff": KICK["PHI@WAS"], "market": market, "side": "OVER", "line": 0.5,
           "odds": 150, "player_name": "Saquon Barkley", "quote_captured_at": "2026-11-02T00:34:50Z"}
    card = R.run_full({"sport": "NFL", "lines": [row]}, now=datetime(2026, 11, 2, 0, 36, tzinfo=timezone.utc),
                      auto_context=False)
    assert called == []
    assert card["evaluated_rows"][0]["status"] == "NO_MODEL_OR_MARKET"
