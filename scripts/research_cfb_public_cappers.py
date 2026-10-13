#!/usr/bin/env python3
"""Research-only CFB public handicapper picks: timestamp, compare, and grade.

Never infer model probabilities from a handicapper's unit rating or win claims.
User-entered post/capture timestamps and quoted prices are NOT independently
attested; this cannot prove an executable edge or authorize any wager.
Only publicly disclosed plays belong here. No VIP/private content or scraping.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from pathlib import Path
import re
from urllib.parse import urlparse

SCHEMA = "CFB_PUBLIC_HANDICAPPER_RESEARCH_V1"
HANDLE = "@BeatinTheBookie"
SNAPSHOT_SCHEMA = "CFB_SDV_FORWARD_SCORE_SNAPSHOT_V1"
RESULT_SCHEMA = "CFB_PUBLIC_HANDICAPPER_AUDIT_V1"
HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com",
         "beatinthebookie.com", "www.beatinthebookie.com"}
MARKET_SIDES = {"SPREAD": {"HOME", "AWAY"}, "TOTAL": {"OVER", "UNDER"}}


def utc(value: object, field: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("timezone required")
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("CFB_CAPPPER_TIME_INVALID:" + field) from exc


def number(value: object, field: str) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError("bool")
        n = float(value)
        if not isfinite(n):
            raise ValueError("nonfinite")
        return n
    except (ValueError, TypeError) as exc:
        raise ValueError("CFB_CAPPER_NUMBER_INVALID:" + field) from exc


def valid_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    if p.scheme != "https" or p.hostname not in HOSTS or p.username or p.password or p.port:
        return False
    if p.hostname in {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}:
        return bool(re.fullmatch(r"/BeatinTheBookie/status/[0-9]+/?", p.path, flags=re.I))
    # The site contains mutable pages; their SHA receipts do not prove vintage.
    return p.path.startswith(("/free-play", "/articles"))


def payout(odds: float) -> float:
    if -100 < odds < 100:
        raise ValueError("CFB_CAPPER_AMERICAN_ODDS_INVALID")
    return odds / 100.0 if odds > 0 else 100.0 / -odds


def grade(market: str, side: str, line: float, home: int, away: int) -> str:
    if market == "SPREAD":
        advantage = (home - away if side == "HOME" else away - home) + line
    else:
        advantage = (home + away - line) * (1 if side == "OVER" else -1)
    return "WIN" if advantage > 0 else "LOSS" if advantage < 0 else "PUSH"


def _model_selection(record: dict, snapshots: list[dict]) -> dict:
    matching = [g for snap in snapshots for g in snap.get("games", [])
                if str(g.get("game_id")) == str(record["game_id"])]
    if not matching:
        return {"comparison": "NO_SPORTSEDGE_PREGAME_FORECAST"}
    if len(matching) != 1:
        raise ValueError("CFB_CAPPER_DUPLICATE_MODEL_GAME")
    game = matching[0]
    if utc(game.get("scored_at"), "model_scored_at") >= utc(game.get("kickoff_at"), "model_kickoff"):
        raise ValueError("CFB_CAPPER_MODEL_NOT_PREGAME")
    if utc(game.get("kickoff_at"), "model_kickoff") != utc(record["kickoff_at"], "pick_kickoff"):
        raise ValueError("CFB_CAPPER_MODEL_GAME_IDENTITY_MISMATCH")
    quotes = game.get("quoted_selections") or []
    same = [q for q in quotes if q.get("market") == record["market"]
            and q.get("side") == record["side"] and q.get("line") == record["line"]]
    if len(same) != 1:
        return {"comparison": "NO_EXACT_LINE_AND_SIDE_MATCH"}
    quote = same[0]
    if quote.get("quote_evidence") != "UNATTESTED_MANUAL_BOARD":
        raise ValueError("CFB_CAPPER_UNEXPECTED_QUOTE_AUTHORITY")
    return {
        "comparison": "MATCHED_SPORTSEDGE_UNVALIDATED_QUOTE",
        "model_probability_unvalidated": quote.get("model_p"),
        "original_model_status": quote.get("original_status"),
        "independent_projections_certified": False,
    }


def audit(payload: dict, *, settlements: list[dict] | None = None,
          snapshots: list[dict] | None = None) -> dict:
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ValueError("CFB_CAPPER_CAPTURE_SCHEMA_INVALID")
    if payload.get("handle") != HANDLE:
        raise ValueError("CFB_CAPPER_HANDLE_INVALID")
    records = payload.get("picks")
    if not isinstance(records, list):
        raise ValueError("CFB_CAPPER_PICKS_ARRAY_REQUIRED")
    snaps = snapshots or []
    if any(s.get("schema") != SNAPSHOT_SCHEMA or s.get("bets_enabled") is not False
           or s.get("positive_ev_proven") is not False for s in snaps):
        raise ValueError("CFB_CAPPER_RESEARCH_SNAPSHOT_ONLY")
    final = {}
    for s in settlements or []:
        key = str(s.get("game_id") or "")
        if not key or key in final:
            raise ValueError("CFB_CAPPER_SETTLEMENT_DUPLICATE_OR_MISSING")
        kick = utc(s.get("kickoff_at"), "settlement_kickoff")
        finished = utc(s.get("settled_at"), "settled_at")
        h = number(s.get("home_points"), "home_points")
        a = number(s.get("away_points"), "away_points")
        if finished <= kick or not (h.is_integer() and a.is_integer()) or min(h, a) < 0 or max(h, a) > 100:
            raise ValueError("CFB_CAPPER_SETTLEMENT_INVALID")
        final[key] = (kick, int(h), int(a))
    seen = set()
    outputs = []
    for row in records:
        if not isinstance(row, dict):
            raise ValueError("CFB_CAPPER_PICK_INVALID")
        gid = str(row.get("game_id") or "")
        market = str(row.get("market") or "").upper()
        side = str(row.get("side") or "").upper()
        if not gid or market not in MARKET_SIDES or side not in MARKET_SIDES[market]:
            raise ValueError("CFB_CAPPER_SELECTION_INVALID")
        # One predeclared choice per market/game, no hindsight cherry-picking.
        identity = (gid, market)
        if identity in seen:
            raise ValueError("CFB_CAPPER_GAME_MARKET_DUPLICATE")
        seen.add(identity)
        url = str(row.get("source_url") or "")
        if not valid_url(url):
            raise ValueError("CFB_CAPPER_PUBLIC_SOURCE_URL_INVALID")
        body = row.get("source_text")
        if not isinstance(body, str) or not body.strip():
            raise ValueError("CFB_CAPPER_SOURCE_TEXT_REQUIRED")
        digest = sha256(body.encode("utf-8")).hexdigest()
        if row.get("source_text_sha256") != digest:
            raise ValueError("CFB_CAPPER_SOURCE_TEXT_HASH_MISMATCH")
        posted = utc(row.get("published_at"), "published_at")
        captured = utc(row.get("captured_at"), "captured_at")
        kick = utc(row.get("kickoff_at"), "kickoff_at")
        if not posted <= captured < kick:
            raise ValueError("CFB_CAPPER_NO_PREGAME_CAPTURE")
        line = number(row.get("line"), "line")
        odds = number(row.get("american_odds"), "american_odds")
        payout_units = payout(odds)
        stake = number(row.get("units", 1), "units")
        if not 0 < stake <= 5 or (market == "TOTAL" and not 0 < line <= 150) or abs(line * 2 - round(line * 2)) > 1e-9:
            raise ValueError("CFB_CAPPER_LINE_OR_UNITS_INVALID")
        o = final.get(gid)
        if o is not None and o[0] != kick:
            raise ValueError("CFB_CAPPER_SETTLEMENT_KICKOFF_MISMATCH")
        result = None if o is None else grade(market, side, line, o[1], o[2])
        net_units = None if result is None else (
            round(stake * payout_units, 6) if result == "WIN" else
            -stake if result == "LOSS" else 0.0)
        record = {
            "game_id": gid, "matchup": row.get("matchup"),
            "market": market, "side": side, "line": line,
            "american_odds": odds, "claimed_units": stake,
            "source_url": url, "source_text_sha256": digest,
            "published_at": posted.isoformat(), "captured_at": captured.isoformat(),
            "kickoff_at": kick.isoformat(), "result": result,
            "net_units_at_claimed_price": net_units,
            "straight_price_under_minus_165_cap": odds >= -165,
            "source_post_vintage_independently_attested": False,
            "book_price_independently_verified": False,
            **_model_selection(row, snaps),
        }
        outputs.append(record)
    settled = [o for o in outputs if o["result"] is not None]
    risked = sum(o["claimed_units"] for o in settled)
    net = sum(o["net_units_at_claimed_price"] for o in settled)
    return {
        "schema": RESULT_SCHEMA, "handle": HANDLE,
        "records": outputs, "captured_picks": len(outputs),
        "settled_picks": len(settled),
        "pending_picks": len(outputs) - len(settled),
        "wins": sum(o["result"] == "WIN" for o in settled),
        "losses": sum(o["result"] == "LOSS" for o in settled),
        "pushes": sum(o["result"] == "PUSH" for o in settled),
        "claimed_price_unit_roi": round(net / risked, 6) if risked else None,
        "claimed_price_net_units": round(net, 6),
        "evidence_role": "THIRD_PARTY_PUBLIC_CONTEXT_RESEARCH_ONLY",
        "claim_verification": "MANUAL_UNATTESTED_DO_NOT_BACKFILL",
        "independent_publication_time_attested": False,
        "independent_book_price_attested": False,
        "model_probabilities_imported": False,
        "positive_ev_proven": False,
        "validated_markets": [],
        "bets_enabled": False, "staking_authority": False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--capture", type=Path, required=True)
    p.add_argument("--settlements", type=Path)
    p.add_argument("--snapshot", action="append", type=Path, default=[])
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    raw = json.loads(args.capture.read_text(encoding="utf-8"))
    settled = json.loads(args.settlements.read_text(encoding="utf-8")) if args.settlements else []
    snaps = [json.loads(path.read_text(encoding="utf-8")) for path in args.snapshot]
    result = audit(raw, settlements=settled, snapshots=snaps)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("CFB_CAPPER_PUBLIC_AUDIT captured=%d settled=%d authority=NONE" %
          (result["captured_picks"], result["settled_picks"]))


if __name__ == "__main__":
    main()
