"""NFL phone ticket -> canonical RUN IT props -> phone props card (#2).

Pure functions; ``scripts/run_nfl_props_card.py`` does the I/O.

* ``ticket_to_run_it_lines``: the [NFL LINES] intake ticket
  (sportsedge.nfl_lines_intake.tickets_to_dict) becomes run_it_full input
  rows. DK quotes, player names, lines and capture timestamps are copied
  exactly; each offered side becomes one row; a side without a price is
  not invented (the row is skipped and named). Team identity is the full
  ESPN display name from sportsedge.nfl_team_aliases.NFL_TEAMS; kickoff
  comes only from an independent schedule (never the ticket).
* ``render_props_card``: rows the canonical runner admitted through the NFL
  research lane (sportsedge.nfl_prop_research_admission), placed with the
  shared card gates (sportsedge.lane_a_card_gates: price cap -165,
  overconfidence EV >= 40%, headline EV >= 3%), ranked by EV with stars.
  One banner on every card (owner ruling Option A, Nov 1 2026).
"""
from __future__ import annotations

from sportsedge.lane_a_card_gates import (
    HEADLINE_FLOOR_EV, OVERCONFIDENCE_EV, PRICE_CAP_AMERICAN)
from sportsedge.nfl_prop_research_admission import ADMISSION_DISPOSITION
from sportsedge.nfl_team_aliases import NFL_TEAMS

BANNER = "**🏈 NFL Research Props — NOT COUNTED · PAPER / 0u · NO PLAY**"
STAR_CUTS = (0.03, 0.06, 0.10, 0.15)
FRESH = "RECENT_CAPTURED_QUOTE"

PHONE_TO_CANONICAL = {
    "passing_yards": "PLAYER_PASSING_YARDS",
    "pass_tds": "PLAYER_PASS_TDS",
    "interceptions": "PLAYER_INTERCEPTIONS",
    "pass_attempts": "PLAYER_PASS_ATTEMPTS",
    "completions": "PLAYER_COMPLETIONS",
    "rushing_yards": "PLAYER_RUSHING_YARDS",
    "rush_attempts": "PLAYER_RUSH_ATTEMPTS",
    "receiving_yards": "PLAYER_RECEIVING_YARDS",
    "receptions": "PLAYER_RECEPTIONS",
    "rush_receiving_yards": "PLAYER_RUSH_PLUS_REC_YARDS",
}
LABEL = {
    "PLAYER_PASSING_YARDS": "Pass Yds", "PLAYER_PASS_TDS": "Pass TDs",
    "PLAYER_INTERCEPTIONS": "INTs", "PLAYER_PASS_ATTEMPTS": "Pass Att",
    "PLAYER_COMPLETIONS": "Completions", "PLAYER_RUSHING_YARDS": "Rush Yds",
    "PLAYER_RUSH_ATTEMPTS": "Rush Att", "PLAYER_RECEIVING_YARDS": "Rec Yds",
    "PLAYER_RECEPTIONS": "Receptions", "PLAYER_RUSH_PLUS_REC_YARDS": "Rush+Rec Yds",
}


def team_name(code: object) -> str | None:
    entry = NFL_TEAMS.get(str(code or "").upper())
    return entry[0] if entry else None


def ticket_to_run_it_lines(ticket: dict, kickoffs: dict[str, str]) -> tuple[list[dict], list[str]]:
    """Return (run_it_full rows, skip notes). ``kickoffs`` maps
    "AWAY@HOME" codes -> ISO kickoff from the independent schedule."""
    rows: list[dict] = []
    notes: list[str] = []
    for game in ticket.get("games") or []:
        away_code, home_code = str(game.get("away")), str(game.get("home"))
        key = f"{away_code}@{home_code}"
        away, home = team_name(away_code), team_name(home_code)
        kickoff = kickoffs.get(key)
        props = [m for m in game.get("markets") or [] if m.get("player")]
        if not props:
            continue
        if not away or not home:
            notes.append(f"{key}: TEAM_IDENTITY_UNRESOLVED")
            continue
        if not kickoff:
            notes.append(f"{key}: SCHEDULE_KICKOFF_UNAVAILABLE")
            continue
        for m in props:
            phone = str(m.get("market") or "")
            market = PHONE_TO_CANONICAL.get(phone, phone.upper())
            captured = m.get("quote_retrieved_at") or game.get("captured_at")
            for side, price in (("OVER", m.get("away_or_over_price")),
                                ("UNDER", m.get("home_or_under_price"))):
                if price in (None, ""):
                    notes.append(f"{m.get('player')} {phone} {side}: NO_PRICE_IN_PASTE")
                    continue
                rows.append({
                    "sport": "NFL", "away": away, "home": home, "kickoff": kickoff,
                    "market": market, "side": side, "line": m.get("line"),
                    "odds": int(price), "book": "draftkings",
                    "player_name": str(m["player"]),
                    "quote_captured_at": captured,
                    "phone_raw": m.get("raw"),
                })
    return rows, notes


def stars(ev: float) -> int:
    return 1 + sum(ev >= cut for cut in STAR_CUTS)


def card_rows(card: dict) -> list[dict]:
    """Admitted NFL research prop rows, bucketed by the shared gates, EV-ranked."""
    out = []
    for r in card.get("evaluated_rows") or []:
        if r.get("registry_disposition") != ADMISSION_DISPOSITION:
            continue
        ev = r.get("ev_per_dollar")
        price = r.get("dk_odds")
        if not isinstance(ev, (int, float)) or isinstance(ev, bool) or not isinstance(price, int):
            continue
        if r.get("quote_status") != FRESH:
            bucket = "STALE_QUOTE"
        elif price < PRICE_CAP_AMERICAN:
            bucket = "EXCLUDED_PRICE_CAP"
        elif ev >= OVERCONFIDENCE_EV:
            bucket = "OVERCONFIDENCE"
        elif ev >= HEADLINE_FLOOR_EV:
            bucket = "HEADLINE"
        else:
            bucket = "BELOW_FLOOR"
        out.append({**r, "bucket": bucket, "stars": stars(float(ev))})
    out.sort(key=lambda r: -float(r["ev_per_dollar"]))
    return out


def _fmt_price(p: int) -> str:
    return f"+{p}" if p > 0 else str(p)


def _pick(r: dict) -> str:
    side = "Over" if r.get("selection") == "OVER" else "Under"
    return f"{r.get('player_name')} {side} {r.get('line'):g} {LABEL.get(r.get('market'), r.get('market'))}"


def render_props_card(card: dict, *, title: str, notes: list[str] | None = None) -> str:
    rows = card_rows(card)
    heads = [r for r in rows if r["bucket"] == "HEADLINE"]
    out = [f"## 🏈 NFL props — {title}", "", BANNER, ""]
    if not heads:
        out.append("No research candidates clear +3% EV at a price of -165 or longer on fresh lines.")
    if any(r["bucket"] == "STALE_QUOTE" for r in rows):
        out.append("Lines older than 180s when priced aren't headlined — repost fresh lines to price them.")
    for r in heads:
        flame = "🔥 " if r["stars"] >= 4 else ""
        out.append(f"{flame}**{_pick(r)}** ({_fmt_price(r['dk_odds'])}) · EV {float(r['ev_per_dollar']):+.1%} · "
                   f"{'★' * r['stars']}{'☆' * (5 - r['stars'])}")
        out.append(f"  model {float(r['model_probability']):.0%} vs DK no-vig {float(r['dk_no_vig_p']):.0%}"
                   f" · last {r.get('prior_game_count')} games (ESPN)")
    quarantined = [r for r in rows if r["bucket"] == "OVERCONFIDENCE"]
    if quarantined:
        out += ["", "⚠️ Too-good-to-be-true (EV ≥ 40%, not headlined — check the line and injuries):"]
        out += [f"- {_pick(r)} ({_fmt_price(r['dk_odds'])})" for r in quarantined]
    priced = len(rows)
    blocked = [r for r in card.get("evaluated_rows") or []
               if r.get("registry_disposition") != ADMISSION_DISPOSITION]
    out += ["", f"Priced {priced} prop sides from ESPN game logs; {len(heads)} research candidates. "
            "Check inactives ~90 min before kickoff. 21+."]
    skipped = list(notes or [])
    for r in blocked:
        why = r.get("nfl_prop_engine_reason") or r.get("reason") or r.get("status")
        skipped.append(f"{r.get('player_name') or ''} {r.get('market')} {r.get('selection') or ''}: {str(why)[:90]}".strip())
    skipped += [f"{_pick(r)} ({_fmt_price(r['dk_odds'])}): price shorter than {PRICE_CAP_AMERICAN}"
                for r in rows if r["bucket"] == "EXCLUDED_PRICE_CAP"]
    skipped += [f"{_pick(r)}: {r.get('quote_status')}" for r in rows if r["bucket"] == "STALE_QUOTE"]
    if skipped:
        out += ["", f"<details><summary>Not on card ({len(skipped)})</summary>", ""]
        out += [f"- {s}" for s in skipped] + ["", "</details>"]
    return "\n".join(out) + "\n"
