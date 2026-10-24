#!/usr/bin/env python3
"""Phone-readable NFL/CFB cards from actual SportsEdge AUTO artifacts.

Presentation only: NEVER calculate probabilities, fabricate a missing price,
turn peer-book market probabilities into model estimates, or certify leans.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from math import isfinite
from statistics import median
from pathlib import Path
from zoneinfo import ZoneInfo


def _utc(value):
    try:
        t=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        if t.tzinfo is None or t.utcoffset() is None:
            return None
        return t.astimezone(timezone.utc)
    except (TypeError,ValueError,OverflowError):
        return None


def _ct(value):
    t=_utc(value)
    return t.astimezone(ZoneInfo("America/Chicago")).strftime("%a %b %-d %-I:%M %p CT") if t else "MISSING"


def pct(value, signed=False):
    if value is None:
        return "MISSING"
    try:
        v=float(value)*100
        return f"{v:+.1f}%" if signed else f"{v:.1f}%"
    except (TypeError,ValueError,OverflowError):
        return "MISSING"


def price(value):
    if value is None:
        return "MISSING"
    try:
        v=int(float(value))
        return f"+{v}" if v>0 else str(v)
    except (TypeError,ValueError,OverflowError):
        return "MISSING"


def candidates(sport, payload):
    rows=[]
    if sport=="NFL":
        for game in payload.get("games") or []:
            for market in game.get("markets") or []:
                for field,label in (("pick","BEST"),("lean","LEAN")):
                    r=market.get(field)
                    if not isinstance(r,dict):
                        continue
                    rows.append({
                        "role":label,"matchup":f"{game.get('away','?')} @ {game.get('home','?')}",
                        "market":market.get("market"),"side":r.get("selection"),
                        "line":r.get("line"),"price":r.get("price_american"),
                        "estimate_p":r.get("estimate_p"),"edge":r.get("edge_probability_points"),
                        "ev":r.get("ev_per_dollar"),"score":r.get("score_0_100"),
                        "kickoff_utc":game.get("commence_time"),
                        "quote_observed_at":market.get("quote_retrieved_at"),
                        "quote_timestamp_source":market.get("quote_timestamp_source"),
                        "reason":r.get("lean_reason") or r.get("reason") or "MISSING"
                    })
    elif sport=="CFB":
        for r in payload.get("results") or []:
            status=str(r.get("bet_status") or "").upper()
            if status not in {"BET","LEAN"}:
                continue
            rows.append({
                "role":"BEST" if status=="BET" else "LEAN",
                "matchup":r.get("matchup"),"market":r.get("market"),
                "side":r.get("side"),"line":r.get("line"),
                "price":r.get("american_odds"),
                "estimate_p":r.get("estimate_p") if r.get("estimate_p") is not None else r.get("model_p"),
                "edge":r.get("edge"),"ev":r.get("expected_roi"),
                "score":r.get("score_0_100"),
                "reason":r.get("reason") or "MISSING",
            })
    for r in rows:
        if any(r.get(k) is None for k in ("estimate_p","edge","ev","price")):
            r["role"]="LEAN"
            r["reason"]="UNPRICED_OR_UNMODELED:"+str(r["reason"])
    def n(x):
        try:return float(x) if x is not None else float("-inf")
        except (ValueError,TypeError):return float("-inf")
    # Role is for presentation, never used to inflate an EV or confidence score.
    rows.sort(key=lambda x:(-n(x.get("ev")),-n(x.get("edge")),
                            str(x.get("matchup")),str(x.get("market")),str(x.get("side"))))
    return rows


def row_text(r):
    line=r.get("line")
    market=str(r.get("market") or "MARKET MISSING")
    if line is None:
        threshold=""
    elif "spread" in market.lower():
        threshold=f" {float(line):+g}"
    else:
        threshold=f" {float(line):g}"
    label=f"{r.get('matchup') or 'MATCHUP MISSING'} — {market} {r.get('side') or 'SIDE MISSING'}{threshold}"
    quote_label=("DK intake stamp" if r.get("quote_timestamp_source")=="INTAKE_STAMPED"
                 else "DK quote")
    pit=(f" · kickoff {_ct(r.get('kickoff_utc'))} · {quote_label} {_ct(r.get('quote_observed_at'))}"
         if r.get("kickoff_utc") else "")
    return (f"- **{label}** · DK {price(r['price'])} · "
            f"estimate {pct(r['estimate_p'])} · edge {pct(r['edge'],True)} · "
            f"EV {pct(r['ev'],True)}{pit} · {str(r['reason'])}")


def _decimal_odds(american):
    """Quote conversion only; never treat reference fair as an originated model."""
    try:
        val = float(american)
        if not (val >= 100 or val <= -100):
            return None
        if val != val or abs(val) == float("inf"):
            return None
        return 1.0 + (val / 100.0 if val > 0 else 100.0 / -val)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError):
        return None


def _verified_peer_market_fair(reference, method, books, key, line):
    """Recompute market-only fair from *exact peer prices*, not an unbound field.

    Older captured artifacts that lack priced receipts fail closed. This never
    creates an independent predictive model or performs network requests.
    """
    from scripts.collect_auto_dk_four_sports import _pair_fair

    receipts=reference.get("peer_price_pairs")
    if (not isinstance(receipts,list) or len(receipts)!=len(books)
            or any(not isinstance(row,dict) for row in receipts)):
        return None
    pairs={}
    sides=("over","under") if key=="totals" else ("away","home")
    for receipt in receipts:
        book=receipt.get("book")
        odds=receipt.get("prices")
        if not isinstance(book,str) or book in pairs or book not in books or not isinstance(odds,dict):
            return None
        if set(odds)!=set(sides):
            return None
        parsed={}
        for side in sides:
            try:
                raw=float(odds[side])
            except (ValueError,TypeError,OverflowError):
                return None
            if not isfinite(raw) or not raw.is_integer() or -100 < raw < 100:
                return None
            parsed[side]=int(raw)
        fair=_pair_fair({"line":line,**parsed})
        if fair is None or len(fair)!=2:
            return None
        pairs[book]=fair
    if set(pairs)!=set(books):
        return None
    if method=="PINNACLE_POWER_V1":
        if len(books)!=1 or books[0]!="pinnacle":
            return None
        return pairs["pinnacle"]
    if method=="MULTIBOOK_MEDIAN_POWER_V1" and len(books)>=3 and "pinnacle" not in books:
        return [median(pairs[b][side] for b in books) for side in (0,1)]
    return None


def nfl_market_price_radar(root: Path, now: datetime):
    """Compare already captured DK prices to same-line reference books; ZERO network requests.

    Pinnacle no-vig is accepted, else require three independently quoted peer
    books. This radar is NOT a validated predictive model or a certified bet.
    Reject stale quotes, in-play games, invalid prices and excessive gaps.
    """
    odds_file = root.parent / "auto_dk" / "nfl_odds.json"
    if not odds_file.is_file():
        return [], "AUTO_DK_NFL_QUOTES_MISSING"
    try:
        captured = json.loads(odds_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], "AUTO_DK_NFL_QUOTES_INVALID"
    if captured.get("status") != "READY":
        return [], "AUTO_DK_NFL_NOT_READY"
    found = []
    for game in captured.get("games") or []:
        kickoff = _utc(game.get("commence_time"))
        if kickoff is None or kickoff <= now:
            continue
        matchup = f"{game.get('away')} @ {game.get('home')}"
        for key, quote in (game.get("markets") or {}).items():
            if key not in {"h2h", "spreads", "totals"} or not isinstance(quote, dict):
                continue
            updated = _utc(quote.get("observed_at"))
            if updated is None or not 0 <= (now - updated).total_seconds() <= 600:
                continue
            reference = (game.get("reference") or {}).get(key) or {}
            method = reference.get("method")
            books = reference.get("books") or []
            peer_rows = reference.get("peer_evidence") or []
            # A malformed or duplicate book/peer list is not evidence.
            if (not isinstance(books, list) or not books
                    or any(not isinstance(b, str) or not b for b in books)
                    or len(books) != len(set(books))
                    or not isinstance(peer_rows, list)
                    or any(not isinstance(p, dict) for p in peer_rows)):
                continue
            expected_books = set(books)
            if (not game.get("provider_event_id")
                    or reference.get("provider_event_id") != game.get("provider_event_id")
                    or reference.get("market_key") != key
                    or reference.get("dk_observed_at") != quote.get("observed_at")
                    or not peer_rows or not expected_books
                    or len(peer_rows) != len(expected_books)
                    or {p.get("book") for p in peer_rows if isinstance(p, dict)} != expected_books):
                continue
            try:
                same_ref_line = (reference.get("dk_line") == quote.get("line")
                                 if key == "h2h" else
                                 abs(float(reference["dk_line"])-float(quote["line"])) < 1e-9)
                peer_lines_ok = all(
                    (p.get("line") is None if key == "h2h" else
                     abs(float(p["line"])-float(quote["line"])) < 1e-9)
                    for p in peer_rows
                )
            except (ValueError,TypeError,KeyError,OverflowError):
                continue
            if not same_ref_line or not peer_lines_ok:
                continue
            peer_times = [_utc(p.get("observed_at")) for p in peer_rows]
            # Freshness of each leg alone is insufficient; quote timestamps
            # must be paired within 120 seconds to the exact DK market.
            if any(t is None
                   or not 0 <= (now - t).total_seconds() <= 600
                   or abs((updated - t).total_seconds()) > 120
                   for t in peer_times if t is not None) or any(t is None for t in peer_times):
                continue
            if method == "PINNACLE_POWER_V1":
                if "pinnacle" not in books:
                    continue
            elif method == "MULTIBOOK_MEDIAN_POWER_V1":
                if len(set(books)) < 3:
                    continue
            else:
                continue
            fair = reference.get("fair")
            verified_fair = _verified_peer_market_fair(reference,method,books,key,quote.get("line"))
            if not isinstance(fair,list) or len(fair)!=2 or verified_fair is None:
                continue
            try:
                if any(not isfinite(float(fair[i])) or
                       abs(float(fair[i])-float(verified_fair[i])) > 1e-8
                       for i in (0,1)):
                    continue
            except (ValueError,TypeError,OverflowError):
                continue
            sides = (("over", "under") if key == "totals" else ("away", "home"))
            for idx, side in enumerate(sides):
                price_num = quote.get(side)
                dec = _decimal_odds(price_num)
                if dec is None:
                    continue
                try:
                    quote_price = int(price_num)
                    p = float(fair[idx])
                except (TypeError, ValueError, OverflowError):
                    continue
                if quote_price != float(price_num) or quote_price < -165 or not 0 < p < 1:
                    continue
                ev = p * dec - 1.0
                # Outliers frequently mean a stale or mismatched offer. Fail closed.
                if not 0.02 <= ev < 0.05:
                    continue
                if key == "totals":
                    selection = f"{side.title()} {float(quote['line']):g}"
                elif key == "spreads":
                    line = float(quote["line"]) * (1 if side == "away" else -1)
                    selection = f"{game.get(side)} {line:+g}"
                else:
                    selection = f"{game.get(side)} ML"
                found.append({
                    "matchup": matchup, "selection": selection,
                    "price": quote_price, "ev": ev, "fair_p": p,
                    "method": method, "books": len(set(books)),
                    "kickoff": kickoff.isoformat(), "observed": updated.isoformat(),
                })
    found.sort(key=lambda row: (-row["ev"], row["matchup"], row["selection"]))
    return found, None


def render(root: Path, run_url: str, *, as_of_date: str | None = None,
           asof: datetime | None = None):
    now=asof or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("PREGAME_SNAPSHOT_REQUIRES_TIMEZONE")
    now=now.astimezone(timezone.utc)
    as_of_date = as_of_date or now.astimezone(ZoneInfo("America/Chicago")).date().isoformat()
    summary=json.loads((root/"summary.json").read_text(encoding="utf-8"))
    lines=["## SportsEdge AUTO — ranked NFL / CFB","",
           f"Snapshot captured {_ct(now.isoformat())}. Not continuously live; game starts invalidate pregame prices.","",
           "Prices: captured DraftKings offers. Probabilities: existing SportsEdge engines.",
           "**EV and edge are model estimates, not a guarantee of profitability.**",""]
    lines.append("### NFL sharp-price radar · market comparison only")
    radar, radar_problem = nfl_market_price_radar(root, now)
    if radar_problem:
        lines.append(f"Not priced: {radar_problem}. No market price or probability was invented.")
    elif not radar:
        lines.append("No fully verified fresh DK/peer exact-market discrepancies.")
    else:
        lines.append("Market-only discrepancies, not SportsEdge model EV, validated bets, or guaranteed returns. Recheck prices.")
        for candidate in radar[:5]:
            lines.append(
                f"- **{candidate['matchup']} — {candidate['selection']}** · "
                f"DK {price(candidate['price'])} · peer fair {pct(candidate['fair_p'])} · "
                f"price-only EV {pct(candidate['ev'],True)} · "
                f"DK quote {_ct(candidate['observed'])} · kickoff {_ct(candidate['kickoff'])} · "
                f"{candidate['method']} ({candidate['books']} book(s)) · PRICE_ONLY_NOT_MODEL_VALIDATED"
            )
    lines.append("")
    for sport in ("NFL","CFB"):
        state=summary.get(sport) or {}
        lines.append(f"### {sport} · {state.get('status') or 'MISSING'}")
        cards=state.get("cards") or []
        if not cards:
            lines.extend(["No generated model card for this sport.",""])
            continue
        picked=[]
        statuses=[]
        for item in cards:
            if not item.get("json"):
                continue
            source=root/Path(item["json"]).name
            if not source.is_file():
                statuses.append("CARD_FILE_MISSING:"+source.name)
                continue
            payload=json.loads(source.read_text(encoding="utf-8"))
            statuses.append(str(item.get("model_status") or item.get("state") or "MISSING"))
            found=candidates(sport,payload)
            if sport=="NFL":
                for row in found:
                    row["slate_date"]=item.get("date")
                    kickoff=_utc(row.get("kickoff_utc"))
                    if kickoff is None or kickoff <= now:
                        continue
                    picked.append(row)
            else:
                picked.extend(found)
        if sport=="CFB":
            lines.append("CFB model still requires out-of-sample validation; candidates are tracking only until then.")
            lines.append(f"Matched SDV games: {sum(int(x.get('priced_rows',0)) for x in cards)} modeled market rows; "
                         f"unmatched games: {state.get('unmatched_games','MISSING')}.")
        lines.append("Model status: "+", ".join(sorted(set(statuses))) if statuses else "Model status: MISSING")
        lines.append("")
        if sport=="NFL":
            # A Sunday phone card must not mix Thursday's future NFL slate into
            # its ranked Sunday leans. Every displayed row keeps its game date.
            dates=sorted({r.get("slate_date") for r in picked if r.get("slate_date")})
            if not dates and picked:
                dates=["MISSING"]
            for date in dates:
                if date=="MISSING":
                    label="Date MISSING — check source artifact"
                else:
                    try:
                        dt=datetime.fromisoformat(date)
                        label=f"{dt.strftime('%a %b')} {dt.day}"
                    except ValueError:
                        label=str(date)
                    label+=(" · TODAY" if date==as_of_date else
                            " · UPCOMING" if date>as_of_date else " · PAST")
                lines.append(f"**NFL slate: {label}**")
                group=[r for r in picked if (r.get("slate_date") or "MISSING")==date]
                for role,title in (("BEST","Best Plays"),("LEAN","Top Leans")):
                    lines.append(f"**{title}**")
                    view=[r for r in group if r["role"]==role][:5]
                    if view:
                        lines.extend(row_text(r) for r in view)
                    else:
                        lines.append("None with supported pregame pricing." if role=="BEST" else "No upcoming modeled leans.")
                    lines.append("")
            if not dates:
                lines.append("No priced NFL candidates on any captured date.")
                lines.append("")
            lines.extend(["**NFL player props — research-only paired DK offers**",
                          "These are not backtest-qualified bets; availability depends on PIT player roles and verified game identity."])
            found_any=False
            for item in cards:
                prop=item.get("props") or {}
                state=str(prop.get("status") or "NOT_CAPTURED")
                if state!="RESEARCH_ONLY":
                    # Every non-priced state is shown: a silent skip hid why the
                    # board had no props (capture limits, no paired DK offers).
                    plain={"NOT_CAPTURED":"no prop capture ran for this date",
                           "NO_PAIRED_DK_PROPS":"no two-sided DK prop offers captured"}.get(state)
                    lines.append(f"- {item.get('date','DATE MISSING')}: {state} · {prop.get('reason') or plain or 'SOURCE_UNAVAILABLE'}")
                    continue
                candidate=root/Path(prop.get("json") or "").name
                if not candidate.is_file():
                    lines.append("- Missing research artifact (not priced)")
                    continue
                prop_card=json.loads(candidate.read_text(encoding="utf-8"))
                chosen=[r for r in prop_card.get("selected_rows") or [] if
                        r.get("status")=="PRICED" and
                        r.get("price_american") is not None and
                        r.get("estimate_p") is not None and
                        r.get("ev_per_dollar") is not None and
                        r.get("edge_probability_points") is not None]
                chosen.sort(key=lambda r:(-float(r["ev_per_dollar"]),-float(r["edge_probability_points"]),
                                          str(r.get("player")),str(r.get("market"))))
                for r in chosen[:4]:
                    found_any=True
                    lines.append(f"- {r.get('player') or 'PLAYER MISSING'} {r.get('market') or 'MARKET MISSING'} "
                        f"{r.get('selection') or 'SIDE MISSING'} {r.get('line') if r.get('line') is not None else 'MISSING'} · "
                        f"DK {price(r.get('price_american'))} · estimate {pct(r.get('estimate_p'))} · "
                        f"edge {pct(r.get('edge_probability_points'),True)} · EV {pct(r.get('ev_per_dollar'),True)} · RESEARCH ONLY")
            if not found_any:
                lines.append("No supported priced research prop candidates.")
            lines.append("")
        else:
            for role,title in (("BEST","Best Plays"),("LEAN","Top Leans")):
                lines.append(f"**{title}**")
                view=[r for r in picked if r["role"]==role][:5]
                if view:
                    lines.extend(row_text(r) for r in view)
                else:
                    lines.append("None with supported model pricing." if role=="BEST" else "No modeled leans.")
                lines.append("")
    lines.extend(["**Open the run for the full quotes, cards and PNG images (when available):**",run_url,"",
                  "Unavailable data stays MISSING. A directional lean is not a verified betting edge."])
    return "\n".join(lines)+"\n"


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,default=Path("artifacts/auto_dk_cards"))
    ap.add_argument("--output",type=Path,default=Path("artifacts/auto_dk_cards/phone_summary.md"))
    ap.add_argument("--run-url",required=True)
    args=ap.parse_args()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(render(args.root,args.run_url),encoding="utf-8")


if __name__=="__main__":
    main()
