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
probability of a designated side is Phi(|gap| / sigma), with sigma taken
from the family's own design screen (attempt 4, PR #2891): pooled MAE
8.899 (spread) and 13.812 (total) converted to a normal SD by
MAE * sqrt(pi/2). That is the model's demonstrated historical error,
not a fitted calibration of the forward season.
"""

from __future__ import annotations

import math
import re
from datetime import datetime
from zoneinfo import ZoneInfo

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


def fixtures_from_espn(board: dict, events: list[dict], slate_date: str) -> tuple[dict, list[str]]:
    """Build the runners' fixture table keyed "AWAY@HOME" (DK display
    names) from ESPN scoreboard events. A comment-carried ESPN event id
    wins; otherwise the best unambiguous name match. Ambiguity or no
    match leaves the game out (never priced) and is reported."""
    by_id = {str(ev.get("id")): ev for ev in events}
    fixtures, notes = {}, []
    for g in board.get("games", []):
        key = f"{g['away']}@{g['home']}"
        ev = by_id.get(str(g.get("espn_event_id"))) if g.get("espn_event_id") else None
        if ev is None:
            scored = []
            for cand in events:
                comps = (cand.get("competitions") or [{}])[0].get("competitors") or []
                away = next((c for c in comps if c.get("homeAway") == "away"), None)
                home = next((c for c in comps if c.get("homeAway") == "home"), None)
                if not away or not home:
                    continue
                s_a, s_h = _hit(g["away"], away), _hit(g["home"], home)
                if s_a and s_h:
                    scored.append((s_a + s_h, cand))
            scored.sort(key=lambda t: -t[0])
            if not scored:
                notes.append(f"{g['away']} @ {g['home']}: no ESPN game found")
                continue
            if len(scored) > 1 and scored[0][0] == scored[1][0]:
                notes.append(f"{g['away']} @ {g['home']}: ambiguous ESPN match, skipped")
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


def card_rows(priced: dict, fixtures: dict) -> list[dict]:
    by_event = {f["espn_event_id"]: f for f in fixtures.values()}
    rows = []
    for rec in priced.get("records", []):
        if rec.get("classification") != "PICKED":
            continue
        p = phi(abs(rec["gap"]) / SIGMA[rec["market"]])
        d = describe(rec, by_event.get(rec["espn_event_id"]))
        ev = p * payout(d["price"]) - (1 - p)
        if ev <= 0:
            continue
        rows.append({**d, "market": rec["market"], "gap": rec["gap"],
                     "win_prob": p, "ev": ev, "stars": stars(ev),
                     "tip_utc": rec["tip_utc"], "row_id": rec["row_id"]})
    rows.sort(key=lambda r: -r["ev"])
    return rows


# ------------------------------------------------------------------ render
def render_card_markdown(rows: list[dict], slate_date: str, priced: dict,
                         notes: list[str], vintage_note: str) -> str:
    out = [f"## 🏀 CBB card — {slate_date}", ""]
    if not rows:
        out += ["No plays clear the pick rule today (spread gap ≥ 2.2, total gap ≥ 3.5) with positive EV."]
    for r in rows:
        tip = datetime.fromisoformat(r["tip_utc"]).astimezone(CT).strftime("%-I:%M %p")
        flame = "🔥 " if r["stars"] >= 4 else ""
        out.append(f"{flame}**{r['pick']}** ({r['price']:+d}) · EV {r['ev']:+.1%} · "
                   f"{'★' * r['stars']}{'☆' * (5 - r['stars'])}")
        out.append(f"  {r['game']} · {tip} CT · {r['why']} · win {r['win_prob']:.0%}")
    n_rec = len(priced.get("records", []))
    out += ["", f"Priced {n_rec} lines; {len(rows)} plays. {vintage_note}",
            "EV uses the model's historical error (spread σ "
            f"{SIGMA['SPREAD']:.1f}, total σ {SIGMA['TOTAL']:.1f} pts). 21+ · bet small."]
    skipped = [f"{r.get('market') or 'game'} {r['espn_event_id']}: {r['reason']}"
               for r in priced.get("refusals", [])] + notes
    if skipped:
        out += ["", f"<details><summary>Not priced ({len(skipped)})</summary>", ""]
        out += [f"- {s}" for s in skipped] + ["", "</details>"]
    return "\n".join(out) + "\n"
