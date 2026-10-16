"""Present every declared MLB market on the free RUN IT research card.

This is a lossy PRESENTATION adapter, not an engine or a quote acquirer.
Every original input and full-precision pricing result is retained in the
parent card. A missing market remains an explicit no-quote/no-engine blocker.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from sportsedge.mlb_full_board import build_mlb_full_board, catalog_markets
from sportsedge.pricing_provenance import LANE_A_RETIRED_STATUS, is_lane_a_label

ALIASES = {
    "ML": "MONEYLINE", "MONEYLINE": "MONEYLINE",
    "SPREAD": "RUN_LINE", "RUN_LINE": "RUN_LINE",
    "TOTAL": "TOTALS", "TOTALS": "TOTALS",
    "BATTER_HITS": "HITS", "BATTER_TOTAL_BASES": "TOTAL_BASES",
    "BATTER_RBI": "RBI", "BATTER_RBIS": "RBI",
    "BATTER_RUNS": "RUNS", "BATTER_HRS": "HOME_RUNS",
    "BATTER_HOME_RUNS": "HOME_RUNS",
    "BATTER_STOLEN_BASES": "STOLEN_BASES",
    "BATTER_BB": "BATTER_BB", "BATTER_WALKS": "BATTER_BB",
    "BATTER_K": "BATTER_K", "BATTER_STRIKEOUTS": "BATTER_K",
    "BATTER_SINGLES": "SINGLES", "BATTER_DOUBLES": "DOUBLES",
    "HITS_RUNS_RBIS": "HITS_RUNS_RBIS", "H_R_RBI": "HITS_RUNS_RBIS",
    "TEAM_TOTAL": "TEAM_TOTALS", "TEAM_TOTALS": "TEAM_TOTALS",
}
# These paths return research prices only when supplied exact inputs and
# independently verified history. Declaring a market here cannot price it.
RESEARCH_DISPLAY_STATUSES = frozenset({
    "RESEARCH_POSITIVE_EV_UNVALIDATED", "BELOW_THRESHOLD",
    "RESEARCH_CANDIDATE_NOT_VALIDATED", "PRICE_CAP",
})

def _market(market: str, side: str) -> tuple[str, str]:
    key = str(market or "").upper().strip()
    side = str(side or "").upper().strip()
    if key in {"FIRST_INNING_RUNS", "INNING_1_RUNS", "RUNS_1ST_INNING",
               "1ST_INNING_RUNS"}:
        # Over .5 = YRFI YES; Under .5 = NRFI YES, distinct market identities.
        # The board-form spellings (INNING_1_RUNS et al.) are the same
        # market in DraftKings "Runs - 1st Inning" dress.
        return ("YRFI", "YES") if side == "OVER" else ("NRFI", "YES") if side == "UNDER" else (key, side)
    return ALIASES.get(key, key), side


def phone_market_board(inputs: Sequence[Mapping[str, Any]],
                       evaluated: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Full catalog visibility without inventing unquoted probabilities/odds."""
    if len(inputs) != len(evaluated):
        raise ValueError("MLB_PHONE_BOARD_INPUT_RESULT_COUNT_MISMATCH")
    all_markets = set(catalog_markets())
    normalized = []
    lane_a_markets = set()
    for i, (source, result) in enumerate(zip(inputs, evaluated)):
        if str(source.get("sport") or "").upper() != "MLB":
            continue
        original = str(source.get("market") or "").upper().strip()
        side = str(source.get("side") or source.get("selection") or "").strip()
        away = str(source.get("away") or "").strip()
        home = str(source.get("home") or "").strip()
        if side.casefold() == home.casefold() and home:
            side = "HOME"
        elif side.casefold() == away.casefold() and away:
            side = "AWAY"
        market, side = _market(original, side)
        if market == "TEAM_TOTALS":
            if side.endswith(" OVER"):
                side = "OVER"
            elif side.endswith(" UNDER"):
                side = "UNDER"
        if market not in all_markets:
            continue
        status = str(result.get("status") or "")
        prob = result.get("estimate_p", result.get("model_p", result.get("research_p")))
        _prov = result.get("pricing_provenance")
        lane_a = (status == LANE_A_RETIRED_STATUS
                  or is_lane_a_label(result.get("pricing_lane"))
                  or (isinstance(_prov, dict)
                      and is_lane_a_label(_prov.get("engine_lane"))))
        if lane_a:
            # t207u: Lane A retired -- labeled diagnostic, no probability,
            # EV or fair odds on the board (mirrors phone_display).
            lane_a_markets.add(market)
            normalized.append({
                "market": market,
                "game_id": source.get("game_pk") or source.get("game_id") or
                           f"{away}@{home}:{source.get('commence_time') or source.get('kickoff')}",
                "entity_id": (source.get("player_name") or source.get("player") or
                              result.get("team_totals_team") or source.get("team") or "GAME"),
                "side": side, "line": source.get("line"),
                "american_odds": source.get("odds", source.get("price")),
                "model_p": None,
                "status": "BLOCKED",
                "reason": LANE_A_RETIRED_STATUS,
                "research_diagnostic": "LANE_A_RETIRED_DIAGNOSTIC",
                "input_index": i,
            })
            continue
        if status not in RESEARCH_DISPLAY_STATUSES or not isinstance(prob, (int, float)) or isinstance(prob, bool) or not 0 < float(prob) < 1:
            prob = None
        quote = source.get("odds", source.get("price"))
        normalized.append({
            "market": market,
            "game_id": source.get("game_pk") or source.get("game_id") or
                       f"{away}@{home}:{source.get('commence_time') or source.get('kickoff')}",
            "entity_id": (source.get("player_name") or source.get("player") or
                          source.get("pitcher_name") or source.get("batter_name") or
                          result.get("team_totals_team") or source.get("team") or "GAME"),
            "side": side,
            "line": source.get("line"),
            "american_odds": quote,
            "model_p": prob,
            "status": status if prob is not None else "BLOCKED",
            "reason": status if prob is not None else
                      str(result.get("reason") or status or "NO_MODEL_RESULT"),
            "input_index": i,
        })
    board = build_mlb_full_board(normalized)
    present = set(item["market"] for item in normalized)
    priced = set(item["market"] for item in normalized if item["model_p"] is not None)
    board["input_coverage"] = {
        "catalog_market_count": len(all_markets),
        "supplied_market_count": len(present),
        "priced_research_market_count": len(priced),
        "lane_a_diagnostic_market_count": len(lane_a_markets),
        "supplied_markets": sorted(present),
        "priced_research_markets": sorted(priced),
        "not_supplied_markets": sorted(all_markets - present),
        "supplied_but_unpriced_markets": sorted(present - priced),
        "unrouted_input_markets": sorted({
            str(s.get("market") or "").upper() for s in inputs
            if str(s.get("sport") or "").upper() == "MLB" and
            _market(s.get("market"), s.get("side") or s.get("selection"))[0] not in all_markets
        }),
        "no_auto_quote_claim": True,
        "validation_status": "RESEARCH_ONLY_UNVALIDATED",
    }
    return board
