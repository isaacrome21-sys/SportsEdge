"""CFB QB interceptions thrown remain distinct from defensive INTs caught.

Tests use synthetic gamelogs, never actual sportsbook odds or verified bets.
"""
from datetime import datetime, timezone

from sportsedge import cfb_phone_player_pricing as phone
from sportsedge.family_market_registry import family_market_decision


def _fixture(market):
    return {"sport": "CFB", "market": market,
            "away": "School A", "home": "School B",
            "player_name": "Test QB", "side": "OVER", "line": 0.5,
            "kickoff": "2026-10-17T22:00:00Z"}


def test_bare_market_and_defence_market_refuse_before_history_fetch(monkeypatch):
    calls = []

    class Source:
        def __init__(self, getter=None):
            pass

        def prior_games(self, **kwargs):
            calls.append(kwargs)
            raise AssertionError("bare or defensive INT must not fetch QB history")

    monkeypatch.setattr(phone, "CFBPlayerPublicSource", Source)
    rows, receipts = phone.phone_cfb_player_rows(
        [_fixture("PLAYER_INTERCEPTIONS"),
         _fixture("PLAYER_DEF_INTERCEPTIONS")],
        now=datetime(2026, 10, 14, 20, tzinfo=timezone.utc))
    assert receipts == [] and calls == []
    assert rows[0]["reason"] == "CFB_PLAYER_INTERCEPTIONS_AMBIGUOUS"
    assert rows[1]["reason"] == "MARKET_NOT_SUPPORTED_BY_CFB_EMPIRICAL"
    assert all(r["model_p_authority"] is False and
               r["official_authority"] is False and
               r["staking_authority"] is False for r in rows)


def test_pass_ints_route_only_to_qb_thrown_empirical_field(monkeypatch):
    seen = {}
    history = [{"interceptions": x} for x in (0, 1, 2, 0, 1)]

    class Source:
        def __init__(self, getter=None):
            pass

        def prior_games(self, **kwargs):
            return {"game_id": "synthetic-game",
                    "features": {"game_history": history},
                    "player_name": "Test QB", "player_id": "espn-qb-42",
                    "prior_game_count": 5,
                    "kickoff_utc": "2026-10-17T22:00:00+00:00",
                    "source_endpoint": "synthetic://not-verified",
                    "explicit_stat_fields": ["interceptions"],
                    "schema_rejected_prior_events": 0}

    def research_bridge(rows, quotes, *, as_of):
        seen["rows"] = rows
        seen["quotes"] = quotes
        return {"rows": [
            {"status": "RESEARCH_CANDIDATE_NOT_VALIDATED",
             "research_only": True, "model_p_authority": False,
             "official_authority": False, "staking_authority": False}]}

    monkeypatch.setattr(phone, "CFBPlayerPublicSource", Source)
    monkeypatch.setattr(phone, "price_three_sport_research", research_bridge)
    rows, receipts = phone.phone_cfb_player_rows(
        [_fixture("PLAYER_PASS_INTERCEPTIONS")],
        now=datetime(2026, 10, 14, 20, tzinfo=timezone.utc))
    assert len(rows) == 1 and len(receipts) == 1
    assert rows[0]["status"] == "WATCH_PLAYER_PARTICIPATION_UNVERIFIED"
    assert rows[0]["participation_status"] == "STARTING_ROLE_NOT_VERIFIED_FROM_GAMELOG"
    assert rows[0]["official_authority"] is False
    assert rows[0]["staking_authority"] is False
    assert seen["rows"][0]["market"] == "PLAYER_PASS_INTERCEPTIONS"
    assert seen["rows"][0]["estimate_p"] == 3 / 5
    assert seen["quotes"][0]["market"] == "PLAYER_PASS_INTERCEPTIONS"
    assert family_market_decision("CFB", "PLAYER_PASS_INTERCEPTIONS")["state"] == "BLOCKED"


def test_taxonomy_blocks_bare_defense_and_no_validation_promotion():
    for m in ("PLAYER_INTERCEPTIONS", "PLAYER_DEF_INTERCEPTIONS"):
        d = family_market_decision("CFB", m)
        assert d["blocker"] == "NO_ENGINE"
        assert d["evaluation_scope"] == "UNREGISTERED"
    qb = family_market_decision("CFB", "PLAYER_PASS_INTERCEPTIONS")
    assert qb["blocker"] == "NO_VALIDATION"
    assert qb["evaluation_scope"] == "FORWARD_ONLY"
    assert qb["official_authority"] is False
    assert qb["model_p_authority"] is False
    assert qb["staking_authority"] is False
