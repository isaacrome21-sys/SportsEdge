#!/usr/bin/env python3
"""Durable CFB probation ledger: record pregame, grade postgame, summarize.

  record  --card cfb_sdv_card.json --output ledger/cfb_probation/<date>.json
  grade   --ledger <file> --scores cfb_schedules_<year>.csv.gz [--closing close_board.json]
  summary --ledger-dir ledger/cfb_probation [--policy config/cfb_probation_policy_v1.json]

Rules (match config/cfb_probation_policy_v1.json):
- record refuses any play whose kickoff is not strictly after the recording
  time (no backfill) and never overwrites an existing ledger file.
- grade settles only from final scores; the recorded pregame price is never
  replaced. CLV is computed only on the exact original contract (same market,
  side and line) from a two-sided closing quote; otherwise CLV is UNAVAILABLE.
- summary applies the frozen kill/promotion rules per market; ROI is shown as
  a sanity check only. Nothing here is OFFICIAL or validated.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "CFB_PROBATION_LEDGER_V1"
SUMMARY_SCHEMA = "CFB_PROBATION_SUMMARY_V1"
ROOT = Path(__file__).resolve().parents[1]
ALIASES = {
    "mississippi": "ole miss", "umass": "massachusetts", "miami oh": "miami (oh)",
    "uconn": "connecticut", "usf": "south florida", "fiu": "florida international",
    "hawai i": "hawaii", "app state": "appalachian state",
}


def _norm(name: str) -> str:
    t = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    t = " ".join(re.sub(r"[^a-z0-9() ]", " ", t.lower()).split())
    t = ALIASES.get(t, t)
    return t.replace("(", "").replace(")", "")


def _utc(value) -> datetime:
    out = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if out.tzinfo is None or out.utcoffset() is None:
        raise ValueError("CFB_LEDGER_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def implied(odds: float) -> float:
    return abs(odds) / (abs(odds) + 100.0) if odds < 0 else 100.0 / (odds + 100.0)


def profit_per_unit(odds: float) -> float:
    return odds / 100.0 if odds > 0 else 100.0 / abs(odds)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# ---------------------------------------------------------------- record
def record(card: dict, *, card_sha256: str, recorded_at: datetime) -> dict:
    if card.get("schema") != "CFB_SDV_CARD_V2":
        raise ValueError("CFB_LEDGER_CARD_SCHEMA_INVALID")
    prob = card.get("probation") or {}
    if not prob.get("policy_sha256"):
        raise ValueError("CFB_LEDGER_PROBATION_BLOCK_MISSING")
    plays = []
    for r in card.get("results") or []:
        if not r.get("probation"):
            continue
        if r.get("bet_status") != "LEAN":
            raise ValueError("CFB_LEDGER_PROBATION_ROW_NOT_LEAN")
        kickoff = _utc(r["start_ts"])
        if kickoff <= recorded_at:
            raise ValueError("CFB_LEDGER_NO_BACKFILL:" + str(r.get("matchup")))
        away, home = [s.strip() for s in str(r["matchup"]).split(" @ ")]
        plays.append({
            "play_id": hashlib.sha256(
                f"{r['game_id']}|{r['market']}|{r['side']}|{r.get('line')}|{r['american_odds']}".encode()
            ).hexdigest()[:16],
            "game_id": str(r["game_id"]),
            "away": away, "home": home,
            "start_ts": kickoff.isoformat(),
            "market": r["market"], "side": r["side"],
            "line": None if r.get("line") in (None, "") else float(r["line"]),
            "american_odds": float(r["american_odds"]),
            "stake_units": float(r["stake_units"]),
            "model_p": float(r["model_p"]),
            "market_p_novig": float(r["market_p"]),
            "edge": float(r["edge"]),
            "home_mean": r.get("home_mean"), "away_mean": r.get("away_mean"),
            "result": None, "units": None,
            "close_odds": None, "close_opposite_odds": None, "clv_novig_pp": None,
            "clv_status": "PENDING",
        })
    return {
        "schema": SCHEMA,
        "recorded_at_utc": recorded_at.isoformat(),
        "source_card_sha256": card_sha256,
        "source_card_scored_at_utc": card.get("scored_at_utc"),
        "policy": prob.get("policy"),
        "policy_sha256": prob.get("policy_sha256"),
        "slate_total_bias_signal": prob.get("slate_total_bias_signal"),
        "official": False, "validated": False,
        "plays": plays,
    }


# ---------------------------------------------------------------- grade
def load_final_scores(schedule_csv_gz: Path) -> dict:
    """(away_norm, home_norm) -> (away_points, home_points) for completed games."""
    out = {}
    with gzip.open(schedule_csv_gz, "rt", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("completed", "")).lower() not in {"true", "1"}:
                continue
            try:
                ap, hp = float(row["away_points"]), float(row["home_points"])
            except (TypeError, ValueError, KeyError):
                continue
            out[(_norm(row["away_team"]), _norm(row["home_team"]))] = (ap, hp)
    return out


def settle(play: dict, away_pts: float, home_pts: float) -> str:
    margin = home_pts - away_pts
    total = home_pts + away_pts
    m, s, line = play["market"], play["side"], play["line"]
    if m == "MONEYLINE":
        if margin == 0:
            return "PUSH"
        return "WIN" if (margin > 0) == (s == "HOME") else "LOSS"
    if m == "SPREAD":
        diff = (margin if s == "HOME" else -margin) + line
    elif m == "TOTAL":
        diff = (total - line) if s == "OVER" else (line - total)
    else:
        raise ValueError("CFB_LEDGER_MARKET_UNSUPPORTED:" + m)
    return "PUSH" if abs(diff) < 1e-9 else ("WIN" if diff > 0 else "LOSS")


def _closing_quote(play: dict, closing_board: list):
    """Return (odds, opposite_odds) for the exact original contract, else None."""
    for g in closing_board:
        if {_norm(g.get("away", "")), _norm(g.get("home", ""))} != {_norm(play["away"]), _norm(play["home"])}:
            continue
        flipped = _norm(g.get("away", "")) != _norm(play["away"])
        m, s = play["market"], play["side"]
        if m == "TOTAL" and g.get("total"):
            line, over, under = g["total"]
            if abs(float(line) - play["line"]) > 1e-9:
                return None
            return (over, under) if s == "OVER" else (under, over)
        if m == "SPREAD" and g.get("spread"):
            away_line, away_odds, home_odds = g["spread"]
            if flipped:
                away_line, away_odds, home_odds = -float(away_line), home_odds, away_odds
            my_line = float(away_line) if s == "AWAY" else -float(away_line)
            if abs(my_line - play["line"]) > 1e-9:
                return None
            return (away_odds, home_odds) if s == "AWAY" else (home_odds, away_odds)
        if m == "MONEYLINE" and g.get("ml"):
            a, h = g["ml"]
            if flipped:
                a, h = h, a
            return (a, h) if s == "AWAY" else (h, a)
    return None


def grade(ledger: dict, scores: dict, closing_board: list | None = None) -> dict:
    for p in ledger["plays"]:
        if p["result"] is None:
            key = (_norm(p["away"]), _norm(p["home"]))
            pts = scores.get(key)
            flipped = False
            if pts is None:
                pts = scores.get((key[1], key[0]))
                flipped = pts is not None
            if pts is not None:
                away_pts, home_pts = (pts[1], pts[0]) if flipped else pts
                p["result"] = settle(p, away_pts, home_pts)
                p["final_score"] = {"away": away_pts, "home": home_pts}
                p["units"] = round({
                    "WIN": p["stake_units"] * profit_per_unit(p["american_odds"]),
                    "LOSS": -p["stake_units"], "PUSH": 0.0,
                }[p["result"]], 4)
        if closing_board is not None and p["clv_status"] == "PENDING":
            q = _closing_quote(p, closing_board)
            if q is None:
                p["clv_status"] = "UNAVAILABLE_LINE_MOVED_OR_MISSING"
            else:
                mine, opp = float(q[0]), float(q[1])
                close_p = implied(mine) / (implied(mine) + implied(opp))
                p.update(close_odds=mine, close_opposite_odds=opp,
                         clv_novig_pp=round(100 * (close_p - p["market_p_novig"]), 3),
                         clv_status="EXACT_CONTRACT")
    return ledger


# ---------------------------------------------------------------- summary
def _tstat(xs):
    n = len(xs)
    if n < 2:
        return None
    mu = sum(xs) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in xs) / (n - 1))
    return None if sd == 0 else mu / (sd / math.sqrt(n))


def summarize(ledgers: list, policy: dict | None = None) -> dict:
    by_market = {}
    for led in ledgers:
        for p in led["plays"]:
            by_market.setdefault(p["market"], []).append(p)
    out = {}
    for market, plays in sorted(by_market.items()):
        graded = [p for p in plays if p["result"] in {"WIN", "LOSS", "PUSH"}]
        clvs = [p["clv_novig_pp"] for p in plays if p["clv_status"] == "EXACT_CONTRACT"]
        staked = sum(p["stake_units"] for p in graded if p["result"] != "PUSH")
        units = sum(p["units"] for p in graded)
        mean_clv = sum(clvs) / len(clvs) if clvs else None
        t = _tstat(clvs)
        decision = "CONTINUE"
        if len(graded) >= 50 and mean_clv is not None and mean_clv < 0 and t is not None and t <= -1.5:
            decision = "KILL"
        elif len(graded) >= 100 and (mean_clv is None or mean_clv <= 0):
            decision = "KILL"
        elif len(graded) >= 100 and mean_clv is not None and mean_clv > 0 and t is not None and t >= 2.0:
            decision = "PROMOTION_REVIEW"
        out[market] = {
            "plays": len(plays), "graded": len(graded),
            "wins": sum(p["result"] == "WIN" for p in graded),
            "losses": sum(p["result"] == "LOSS" for p in graded),
            "pushes": sum(p["result"] == "PUSH" for p in graded),
            "units": round(units, 3),
            "roi_sanity_only": round(units / staked, 4) if staked else None,
            "clv_n": len(clvs),
            "mean_clv_novig_pp": None if mean_clv is None else round(mean_clv, 3),
            "clv_t": None if t is None else round(t, 2),
            "decision": decision,
        }
    return {"schema": SUMMARY_SCHEMA, "official": False, "validated": False,
            "policy_sha256": None if policy is None else policy.get("_sha256"),
            "markets": out}


# ---------------------------------------------------------------- cli
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record")
    r.add_argument("--card", type=Path, required=True)
    r.add_argument("--output", type=Path, required=True)
    r.add_argument("--recorded-at")
    g = sub.add_parser("grade")
    g.add_argument("--ledger", type=Path, required=True)
    g.add_argument("--scores", type=Path, required=True)
    g.add_argument("--closing", type=Path)
    s = sub.add_parser("summary")
    s.add_argument("--ledger-dir", type=Path, required=True)
    s.add_argument("--policy", type=Path, default=ROOT / "config" / "cfb_probation_policy_v1.json")
    args = ap.parse_args(argv)

    if args.cmd == "record":
        if args.output.exists():
            raise SystemExit("CFB_LEDGER_EXISTS_REFUSING_OVERWRITE:" + str(args.output))
        when = _utc(args.recorded_at) if args.recorded_at else datetime.now(timezone.utc)
        led = record(json.loads(args.card.read_text()), card_sha256=_sha256(args.card), recorded_at=when)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(led, indent=2) + "\n")
        print(f"CFB_PROBATION_RECORDED {len(led['plays'])} plays -> {args.output}")
        for p in led["plays"]:
            print(f"  {p['away']} @ {p['home']}: {p['market']} {p['side']} {p['line'] or ''} "
                  f"{p['american_odds']:+.0f} {p['stake_units']}u")
        return 0
    if args.cmd == "grade":
        led = json.loads(args.ledger.read_text())
        closing = json.loads(args.closing.read_text()) if args.closing else None
        grade(led, load_final_scores(args.scores), closing)
        args.ledger.write_text(json.dumps(led, indent=2) + "\n")
        for p in led["plays"]:
            print(f"{p['away']} @ {p['home']} {p['market']} {p['side']} {p['line'] or ''}: "
                  f"{p['result'] or 'PENDING'} {p['units'] if p['units'] is not None else ''} "
                  f"CLV {p['clv_novig_pp'] if p['clv_novig_pp'] is not None else p['clv_status']}")
        return 0
    ledgers = [json.loads(f.read_text()) for f in sorted(args.ledger_dir.glob("*.json"))]
    policy = None
    if args.policy.exists():
        policy = json.loads(args.policy.read_text())
        policy["_sha256"] = _sha256(args.policy)
    print(json.dumps(summarize(ledgers, policy), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
