"""t126: family-level canonical registry for CFB / NBA / CBB.

Offline, synthetic rows only (no real quotes, no fetches). Asserts:
* every CFB/NBA/CBB family entry is unvalidated (CFB UNVALIDATED,
  NBA/CBB RESEARCH_ONLY_UNVALIDATED) and only engine-backed, governance-
  permitted families are PRICED_PATH;
* the 89-market Phase 1 matrix is unchanged (families live separately);
* the SPORT_NOT_IN_REGISTRY stopgap is gone from the gate;
* Illinois exclusion and NBA rest_adj=0 are untouched.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from artifacts.run_it_full import run_full
from sportsedge import canonical_coverage as C
from sportsedge import registry_gate as G

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)


def _pair(sport, market, home, away="Purdue"):
    base = {"sport": sport, "market": market, "away": away, "home": home,
            "price": -110, "book": "DK", "captured_at": NOW.isoformat(),
            "kickoff": "2026-10-17T19:00:00Z"}
    return [dict(base, side="HOME", line=-3.5), dict(base, side="AWAY", line=3.5)]


def test_matrix_unchanged_and_families_separate():
    assert len(C.MARKET_RESOLUTIONS) == 89
    assert {s for s, _ in C.MARKET_RESOLUTIONS} == {"MLB", "NFL"}
    assert {s for s, _ in C.FAMILY_RESOLUTIONS} == {"CFB", "NBA", "CBB"}
    assert G.REGISTERED_SPORTS == {"MLB", "NFL", "CFB", "NBA", "CBB"}


def test_every_family_unvalidated_and_priced_only_where_engine_exists():
    priced = set()
    for (sport, fam), res in C.FAMILY_RESOLUTIONS.items():
        assert res["validation_status"] in {
            "UNVALIDATED", "NOT_RUN", "RESEARCH_ONLY_UNVALIDATED"}, fam
        if sport in {"NBA", "CBB"}:
            assert res["validation_status"] == "RESEARCH_ONLY_UNVALIDATED"
        if res["state"] == C.PRICED_PATH:
            priced.add(fam)
        else:
            assert res["blocker"] in C.BLOCKER_TAXONOMY
    assert priced == {"CFB_GAME", "NBA_GAME"}


def test_priced_families_match_governance_and_engine():
    surf = json.loads((ROOT / "config/football_market_surface.json").read_text())
    states = {m["market"]: m["engine_state_by_sport"]["CFB"]
              for m in surf["markets"]}
    assert all(states[m] == "IMPLEMENTED" for m in ("moneyline", "spread", "total"))
    props = json.loads((ROOT / "config/football_prop_engine_surface.json").read_text())
    assert props["sports"]["CFB"]["engine_state"] == "NO_ENGINE"
    from artifacts import free_models
    assert "CBB" not in free_models.PRIORS  # no CBB engine -> CBB_GAME blocked
    assert {"CFB", "NBA"} <= set(free_models.PRIORS)


@pytest.mark.parametrize("sport,market,family,state", [
    ("CFB", "ML", "CFB_GAME", C.PRICED_PATH),
    ("CFB", "moneyline", "CFB_GAME", C.PRICED_PATH),
    ("CFB", "TEAM_TOTAL", "CFB_GAME_DERIVATIVES", C.BLOCKED),
    ("CFB", "PLAYER_RUSHING_YARDS", "CFB_PLAYER_PROPS", C.BLOCKED),
    ("CFB", "ANYTIME_TD", "CFB_PLAYER_PROPS", C.BLOCKED),
    ("NBA", "TOTAL", "NBA_GAME", C.PRICED_PATH),
    ("NBA", "FIRST_HALF_SPREAD", "NBA_GAME_DERIVATIVES", C.BLOCKED),
    ("NBA", "PLAYER_POINTS", "NBA_PLAYER_PROPS", C.BLOCKED),
    ("CBB", "SPREAD", "CBB_GAME", C.BLOCKED),
    ("CBB", "PLAYER_POINTS", "CBB_PLAYER_PROPS", C.BLOCKED),
])
def test_family_resolution(sport, market, family, state):
    res = C.resolve_market(sport, market)
    assert res["family"] == family and res["state"] == state
    assert res["registry_level"] == "FAMILY"


@pytest.mark.parametrize("sport", ["CFB", "NBA", "CBB"])
def test_unmatched_market_in_family_sport_is_unregistered(sport):
    assert C.resolve_market(sport, "MADE_UP_MARKET") is None
    row = G.registry_blocked_row(sport, ["MADE_UP_MARKET"], {"market": "X"})
    assert row["blocker"] == "UNREGISTERED" and row["registry_state"] == "UNKNOWN"


def test_stopgap_removed_from_gate():
    src = (ROOT / "sportsedge/registry_gate.py").read_text()
    assert "CORE_GAME_MARKETS for n in names" not in src
    # Priced core-game row of a sport with no registry is now blocked.
    row = G.registry_blocked_row("PGA", ["ML"], {"market": "ML"})
    assert row["blocker"] == "UNREGISTERED"


def test_illinois_exclusion_untouched_on_canonical_card():
    card = run_full({"lines": _pair("CFB", "ML", "Illinois Fighting Illini")},
                    now=NOW, auto_context=False)
    for row in card["evaluated_rows"]:
        assert "IL_COLLEGE" in str(row.get("reason")) + str(row.get("status"))
        assert not G.is_priced(row)


def test_nba_rest_adj_untouched():
    src = (ROOT / "artifacts/free_models.py").read_text()
    assert "rest_adj is NOT applied: contribution exactly zero" in src
    assert "rest_adj" in C.FAMILY_RESOLUTIONS[("NBA", "NBA_GAME")]["detail"]


def test_cbb_game_blocked_on_canonical_card():
    card = run_full({"lines": _pair("CBB", "ML", "Duke")}, now=NOW,
                    auto_context=False)
    for row in card["evaluated_rows"]:
        assert row["blocker"] == "NO_ENGINE" and not G.is_priced(row)
