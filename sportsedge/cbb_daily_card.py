"""CBB daily card — the glue from a [CBB LINES] capture to a phone card.

Pipeline (NON_COUNTED; nothing here counts, freezes, or grants PLAY):

  [CBB LINES] body --parse_cbb_lines--> board
  ESPN scoreboard  --fixtures_from_espn--> fixture identity table
  morning Torvik vintage + CbbEfficiencyForwardRunner.price_slate
      --> priced rows (Amendment 2 gap / designated side / PICKED)
  card_rows() --> EV + stars per PICKED row, ranked by EV
  render_card_markdown() --> phone text

Pure functions only; ``scripts/run_cbb_daily_card.py`` does the I/O.

EV is a CARD presentation figure, not a preregistration term. The win
probability of a designated side is APPROXIMATED as Phi(|gap| / sigma),
ASSUMING centered Gaussian model error, with sigma derived from the
family's design-screen pooled MAE (attempt 4, PR #2891: 8.899 spread,
13.812 total; sigma = MAE * sqrt(pi/2)). This is an assumption, not
calibration evidence for conditional win probabilities, least of all
at extreme gaps; it stays research output pending independent
calibration.

Placement uses the repo's adopted shared card-gate constants (imported
from sportsedge.lane_a_card_gates, never copied): price shorter than
-165 excluded; EV >= +40% to the overconfidence bucket (never
headlined); EV >= +3% headlines; else not shown. Every row carries the
priced record's status (counted / verified_play / freeze_state /
label) in card JSON.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from sportsedge.cbb_torvik_efficiency_v1 import parse_ts, price_ok
from sportsedge.lane_a_card_gates import (
    HEADLINE_FLOOR_EV,
    OVERCONFIDENCE_EV,
    PRICE_CAP_AMERICAN,
)

CT = ZoneInfo("America/Chicago")

SCREEN_MAE = {"SPREAD": 8.899, "TOTAL": 13.812}
SIGMA = {m: mae * math.sqrt(math.pi / 2) for m, mae in SCREEN_MAE.items()}
STAR_CUTS = (0.03, 0.06, 0.10, 0.15)   # EV < 3% = 1 star ... >= 15% = 5 stars


# ------------------------------------------------------------------ identity
def _norm(s: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = re.sub(r"\bst\b", "state", s)
    return re.sub(r"\s+", " ", s).strip()


def _names(comp: dict) -> list[str]:
    t = comp.get("team", {})
    return [_norm(t.get(k, "")) for k in
            ("displayName", "shortDisplayName", "location", "abbreviation")]


def _hit(dk_name: str, comp: dict) -> int:
    """Match strength: 3 exact displayName, 2 exact other name,
    1 prefix match, 0 none."""
    u = _norm(dk_name)
    names = _names(comp)
    if u and u == names[0]:
        return 3
    if u in names[1:]:
        return 2
    if any(n and len(n) >= 4 and (u.startswith(n + " ") or n.startswith(u + " "))
           for n in names):
        return 1
    return 0


def _sides(ev: dict):
    comps = (ev.get("competitions") or [{}])[0].get("competitors") or []
    away = next((c for c in comps if c.get("homeAway") == "away"), None)
    home = next((c for c in comps if c.get("homeAway") == "home"), None)
    return away, home


def _local_date(ev: dict) -> str | None:
    tip = parse_ts(str(ev.get("date", "")).replace("Z", "+00:00"))
    return tip.astimezone(CT).strftime("%Y-%m-%d") if tip and tip.tzinfo else None


def fixtures_from_espn(board: dict, events: list[dict], slate_date: str) -> tuple[dict, list[str]]:
    """Build the runners' fixture table keyed "AWAY@HOME" (DK display
    names) from ESPN scoreboard events.

    Fail-closed identity: only events whose local (CT) date is the slate
    date are eligible. A comment-carried ESPN event id is honored ONLY
    when that event's away AND home teams both corroborate the captured
    names; a supplied id that is unknown, off-date, or names other teams
    REFUSES the game (no silent fallback to a name match). Without an
    id, the single best name match is used; ambiguity or no match
    leaves the game out. Refused/skipped games are never priced."""
    on_date = [ev for ev in events if _local_date(ev) == slate_date]
    by_id = {str(ev.get("id")): ev for ev in events}
    fixtures, notes = {}, []
    for g in board.get("games", []):
        key = f"{g['away']}@{g['home']}"
        label = f"{g['away']} @ {g['home']}"
        supplied = g.get("espn_event_id")
        if supplied:
            ev = by_id.get(str(supplied))
            if ev is None:
                notes.append(f"{label}: ESPN_EVENT_ID_UNKNOWN {supplied}, refused")
                continue
            if _local_date(ev) != slate_date:
                notes.append(f"{label}: ESPN_EVENT_DATE_MISMATCH {supplied}, refused")
                continue
            away, home = _sides(ev)
            if not away or not home or not (_hit(g["away"], away) and _hit(g["home"], home)):
                notes.append(f"{label}: ESPN_EVENT_ID_TEAM_CONFLICT {supplied}, refused")
                continue
        else:
            scored = []
            for cand in on_date:
                away, home = _sides(cand)
                if not away or not home:
                    continue
                s_a, s_h = _hit(g["away"], away), _hit(g["home"], home)
                if s_a and s_h:
                    scored.append((s_a + s_h, cand))
            scored.sort(key=lambda t: -t[0])
            if not scored:
                notes.append(f"{label}: no ESPN game found on {slate_date}")
                continue
            if len(scored) > 1 and scored[0][0] == scored[1][0]:
                notes.append(f"{label}: ambiguous ESPN match, skipped")
                continue
            ev = scored[0][1]
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c for c in comp["competitors"]}
        fixtures[key] = {
            "espn_event_id": str(ev["id"]),
            "away_espn_id": str(teams["away"]["team"]["id"]),
            "home_espn_id": str(teams["home"]["team"]["id"]),
            "neutral_site": bool(comp.get("neutralSite")),
            "tip_utc": ev["date"].replace("Z", "+00:00") if ev["date"].endswith("Z") else ev["date"],
            "slate_date": slate_date,
            "display": f"{teams['away']['team'].get('shortDisplayName', g['away'])} @ "
                       f"{teams['home']['team'].get('shortDisplayName', g['home'])}",
        }
    return fixtures, notes


# ------------------------------------------------------------------ EV
def phi(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def payout(price: float) -> float:
    price = float(price)
    return 100.0 / -price if price < 0 else price / 100.0


def stars(ev: float) -> int:
    return 1 + sum(ev >= cut for cut in STAR_CUTS)


def _fmt_line(x: float) -> str:
    return f"{x:+g}" if x else "PK"


def describe(rec: dict, fixture: dict | None) -> dict:
    """Human pick text + price for a priced row's designated side."""
    side = rec["designated_side"]
    away, home = rec["away_team"], rec["home_team"]
    if fixture and " @ " in fixture.get("display", ""):
        away, home = fixture["display"].split(" @ ", 1)
    if rec["market"] == "SPREAD":
        # line is the away spread as captured
        if side == "AWAY":
            text, price = f"{away} {_fmt_line(rec['line'])}", rec["side_a_price"]
        else:
            text, price = f"{home} {_fmt_line(-rec['line'])}", rec["side_b_price"]
        model = rec["model_margin_home_candidate"]
        # the captured away spread IS the market's home-minus-away margin
        why = f"{home} margin: model {model:+.1f} vs market {rec['line']:+.1f}"
    else:
        price = rec["side_a_price"] if side == "OVER" else rec["side_b_price"]
        text = f"{'Over' if side == 'OVER' else 'Under'} {rec['line']:g}"
        why = f"model total {rec['model_total_candidate']:.1f} vs {rec['line']:g}"
    return {"game": f"{away} @ {home}", "pick": text, "price": int(price), "why": why}


STATUS_KEYS = ("counted", "verified_play", "freeze_state", "label", "engine_id")


def _admit(rec: dict) -> str | None:
    """Strict admission of a priced record onto a card; returns a
    refusal code or None. Self-declared PICKED is never enough."""
    if rec.get("engine_id") != "CBB_TORVIK_EFFICIENCY_V1" or rec.get("counted") is not False:
        return "CARD_RECORD_NOT_RUNNER_OUTPUT"
    if rec.get("market") not in SIGMA or rec.get("designated_side") is None:
        return "CARD_RECORD_INVALID"
    gap = rec.get("gap")
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not math.isfinite(gap):
        return "CARD_RECORD_INVALID"
    if not (price_ok(rec.get("side_a_price")) and price_ok(rec.get("side_b_price"))):
        return "PRICE_INVALID"
    if not (rec.get("side_a_captured_at") and rec.get("side_b_captured_at")
            and rec.get("capture_source")):
        return "QUOTE_PROVENANCE_MISSING"
    return None


def card_rows(priced: dict, fixtures: dict) -> list[dict]:
    """All admitted PICKED rows with EV, bucketed by the shared gates:
    HEADLINE (+3% <= EV < +40%, price no shorter than -165),
    OVERCONFIDENCE (EV >= +40%, never headlined), EXCLUDED_PRICE_CAP,
    BELOW_FLOOR, or REFUSED (failed admission). Sorted by EV."""
    by_event = {f["espn_event_id"]: f for f in fixtures.values()}
    rows = []
    for rec in priced.get("records", []):
        if rec.get("classification") != "PICKED":
            continue
        status = {k: rec.get(k) for k in STATUS_KEYS}
        refusal = _admit(rec)
        if refusal:
            rows.append({"bucket": "REFUSED", "reason": refusal,
                         "row_id": rec.get("row_id"), "ev": None, **status})
            continue
        p = phi(abs(rec["gap"]) / SIGMA[rec["market"]])
        d = describe(rec, by_event.get(rec["espn_event_id"]))
        ev = p * payout(d["price"]) - (1 - p)
        if d["price"] < PRICE_CAP_AMERICAN:
            bucket = "EXCLUDED_PRICE_CAP"
        elif ev >= OVERCONFIDENCE_EV:
            bucket = "OVERCONFIDENCE"
        elif ev >= HEADLINE_FLOOR_EV:
            bucket = "HEADLINE"
        else:
            bucket = "BELOW_FLOOR"
        rows.append({**d, "bucket": bucket, "market": rec["market"], "gap": rec["gap"],
                     "win_prob_approx": p, "ev": ev, "stars": stars(ev),
                     "tip_utc": rec["tip_utc"], "row_id": rec["row_id"], **status})
    rows.sort(key=lambda r: -r["ev"] if r["ev"] is not None else float("inf"))
    return rows


# ------------------------------------------------------------------ render
def render_card_markdown(rows: list[dict], slate_date: str, priced: dict,
                         notes: list[str], vintage_note: str) -> str:
    heads = [r for r in rows if r["bucket"] == "HEADLINE"]
    out = [f"## 🏀 CBB card — {slate_date}", ""]
    if not heads:
        out += ["No plays clear the pick rule (spread gap ≥ 2.2, total gap ≥ 3.5) and the card gates today."]
    for r in heads:
        tip = datetime.fromisoformat(r["tip_utc"]).astimezone(CT).strftime("%-I:%M %p")
        flame = "🔥 " if r["stars"] >= 4 else ""
        out.append(f"{flame}**{r['pick']}** ({r['price']:+d}) · EV {r['ev']:+.1%} · "
                   f"{'★' * r['stars']}{'☆' * (5 - r['stars'])}")
        out.append(f"  {r['game']} · {tip} CT · {r['why']}")
    quarantined = [r for r in rows if r["bucket"] == "OVERCONFIDENCE"]
    if quarantined:
        out += ["", "⚠️ Too-good-to-be-true (EV ≥ 40%, not headlined — check the line and injuries):"]
        out += [f"- {r['pick']} ({r['price']:+d}) · {r['game']}" for r in quarantined]
    n_rec = len(priced.get("records", []))
    out += ["", f"Priced {n_rec} lines; {len(heads)} plays. {vintage_note}",
            "EV approximates win chance from the model's average historical miss "
            f"(spread σ {SIGMA['SPREAD']:.1f}, total σ {SIGMA['TOTAL']:.1f} pts), "
            "assuming normal errors. 21+."]
    skipped = [f"{r.get('market') or 'game'} {r['espn_event_id']}: {r['reason']}"
               for r in priced.get("refusals", [])] + notes
    skipped += [f"{r.get('row_id')}: {r['reason']}" for r in rows if r["bucket"] == "REFUSED"]
    skipped += [f"{r['pick']} ({r['price']:+d}): price shorter than {PRICE_CAP_AMERICAN}"
                for r in rows if r["bucket"] == "EXCLUDED_PRICE_CAP"]
    if skipped:
        out += ["", f"<details><summary>Not on card ({len(skipped)})</summary>", ""]
        out += [f"- {s}" for s in skipped] + ["", "</details>"]
    return "\n".join(out) + "\n"
