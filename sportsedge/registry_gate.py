"""Shared runtime registry gate (t115 extracted, t118 extended).

Single implementation used by artifacts/run_it_full.run_full AND every
legacy runner that writes a card (t118). No runner may carry its own copy.

Rules (fail closed):
  * Any name a row is known by that resolves to a BLOCKED entry in
    sportsedge.canonical_coverage -> blocked row naming the blocker.
  * A sport that HAS a registry (MLB, NFL) and a market none of whose
    names resolve -> blocked row, blocker UNREGISTERED (state UNKNOWN).
  * CFB, NBA and CBB are registered at family level (t126,
    canonical_coverage.FAMILY_RESOLUTIONS); their markets resolve like any
    other registered sport.
  * A sport with NO registry at all, a missing sport, or a market matching
    no entry -> blocked UNREGISTERED (state UNKNOWN). The t118
    SPORT_NOT_IN_REGISTRY core-game-market pass-through is removed.
A blocked row never carries a probability, price or EV.
"""
from __future__ import annotations

from typing import Any, Iterable

from sportsedge.canonical_coverage import (
    BLOCKED as COVERAGE_BLOCKED,
    FAMILY_SPORTS,
    MARKET_RESOLUTIONS,
    blocked_row_for as coverage_blocked_row,
    resolve_market as coverage_resolve_market,
)

UNREGISTERED = "UNREGISTERED"
REGISTERED_SPORTS = frozenset(
    {s for (s, _m) in MARKET_RESOLUTIONS} | set(FAMILY_SPORTS))
CORE_GAME_MARKETS = frozenset({
    "ML", "MONEYLINE", "H2H", "SPREAD", "SPREADS", "RUN_LINE", "POINT_SPREAD",
    "TOTAL", "TOTALS", "GAME_TOTAL",
})
# Keys whose presence means a dict carries a model price/probability.
PRICING_KEYS = frozenset({
    "model_p", "model_prob", "model_probability", "probability", "prob",
    "p_model", "estimate_p", "fair_p", "fair_prob", "fair_odds", "fair_price",
    "fair_american", "ev", "edge", "expected_value", "model_price",
    "p_over", "p_under", "p_side", "win_prob",
})


def _resolve(sport, name):
    res = coverage_resolve_market(sport, name)
    if res is None:
        res = coverage_resolve_market(sport, name.lower())
        if res is not None:
            name = name.lower()
    return res, name


def registry_blocked_row(sport, markets: Iterable[Any], line: dict, *,
                         include_unregistered: bool = True):
    """Blocker row for this line, or None when it may proceed to a pricer.

    include_unregistered=False is used only for the run_it_full PRE-routing
    check, so a lane's own more specific fail-closed reason (e.g.
    ILLINOIS_COLLEGE_EXCLUDED) is kept; the post-evaluation check runs with
    True and blocks any unregistered row that came back PRICED.
    """
    sport = str(sport or "").upper()
    names = [str(n).strip() for n in markets if n and str(n).strip()]
    any_resolved = False
    for name in names:
        res, key = _resolve(sport, name)
        if res is None:
            continue
        any_resolved = True
        if res.get("state") == COVERAGE_BLOCKED:
            row = coverage_blocked_row(sport, key, line)
            row["market"] = line.get("market")
            row["registry_enforced"] = True
            return row
    if any_resolved or not include_unregistered:
        return None
    return unregistered_row(sport, names[0] if names else "", line)


def unregistered_row(sport, market, line):
    scope = ("market absent from the %s registry" % sport
             if sport in REGISTERED_SPORTS else
             "sport %s has no canonical registry; every market is "
             "blocked" % (sport or "UNKNOWN"))
    return {
        "status": "NO_MODEL_OR_MARKET",
        "reason": "UNREGISTERED: " + scope + "; absence is not a verified "
                  "pricing engine, state UNKNOWN",
        "blocker": UNREGISTERED, "registry_state": "UNKNOWN",
        "blocker_detail": scope, "coverage_market": market,
        "sport": sport, "market": line.get("market"),
        "selection": line.get("side") or line.get("selection"),
        "player_name": line.get("player_name") or line.get("label"),
        "research_only": True, "official_authority": False,
        "model_p_authority": False, "staking_authority": False,
        "registry_enforced": True,
    }


def label_unregistered_sport(row: dict, sport) -> dict:
    if str(sport or "").upper() not in REGISTERED_SPORTS:
        row.setdefault("registry_status", "SPORT_NOT_IN_REGISTRY")
    return row


def is_priced(d: dict) -> bool:
    """True when the dict carries any non-null model price/probability."""
    return any(d.get(k) is not None for k in PRICING_KEYS)


def _row_names(d: dict):
    out = []
    for k in ("market", "market_key", "market_type", "coverage_market", "bet_type"):
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip().upper())
    return out


def gate_payload(obj, default_sport=None, *, _sport=None, stats=None):
    """Recursively gate a legacy-runner card before it is written.

    Every dict that names a market AND carries a pricing key is checked;
    blocked/unregistered rows are replaced by the blocker row (identity
    fields kept, every pricing key dropped). Returns (gated_obj, stats).
    """
    top = stats is None
    if top:
        stats = {"checked": 0, "blocked": 0, "unregistered": 0}
    sport = _sport or default_sport
    if isinstance(obj, dict):
        sp = obj.get("sport") or obj.get("league")
        if isinstance(sp, str) and sp.strip():
            sport = sp.strip().upper()
        names = _row_names(obj)
        if names and is_priced(obj):
            stats["checked"] += 1
            gate = registry_blocked_row(sport, names, obj)
            if gate is not None:
                stats["unregistered" if gate["blocker"] == UNREGISTERED else "blocked"] += 1
                keep = {k: v for k, v in obj.items()
                        if k not in PRICING_KEYS and not isinstance(v, (dict, list))}
                keep.update(gate)
                for k in ("game", "event_id", "game_id", "home", "away", "line", "side"):
                    if k in obj and k not in keep:
                        keep[k] = obj[k]
                res = keep
                return (res, stats) if top else res
            obj = label_unregistered_sport(dict(obj), sport)
        res = {k: gate_payload(v, None, _sport=sport, stats=stats) for k, v in obj.items()}
    elif isinstance(obj, list):
        res = [gate_payload(v, None, _sport=sport, stats=stats) for v in obj]
    else:
        res = obj
    return (res, stats) if top else res


# The Odds API market keys -> registry intake names (t126; NFL fair-odds card).
ODDS_API_MARKET_ALIASES = {"h2h": "ML", "spreads": "SPREAD", "totals": "TOTAL",
                           "team_totals": "TEAM_TOTAL",
                           "alternate_spreads": "ALTERNATE_SPREAD",
                           "alternate_totals": "ALTERNATE_TOTAL"}


def gate_odds_api_events(events, sport, runner: str):
    """Drop every bookmaker market whose key the registry blocks or does not
    know, BEFORE any text/price is rendered from the events (t126).

    Returns (gated_events, stats). Events/bookmakers are copied, never
    mutated; a market with no key is dropped (fail closed)."""
    stats = {"runner": runner, "module": "sportsedge.registry_gate",
             "checked": 0, "blocked": 0, "unregistered": 0}
    out = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        ev = dict(event)
        books = []
        for book in event.get("bookmakers") or []:
            if not isinstance(book, dict):
                continue
            bk = dict(book)
            kept = []
            for market in book.get("markets") or []:
                key = str((market or {}).get("key") or "").strip()
                stats["checked"] += 1
                names = [key, ODDS_API_MARKET_ALIASES.get(key.lower(), "")]
                gate = registry_blocked_row(sport, names, {"market": key})
                if gate is None:
                    kept.append(market)
                else:
                    stats["unregistered" if gate["blocker"] == UNREGISTERED
                          else "blocked"] += 1
            bk["markets"] = kept
            books.append(bk)
        ev["bookmakers"] = books
        out.append(ev)
    return out, stats


def gate_card_file(card_path, sport, runner: str):
    """Gate a card JSON on disk and write the gated copy next to it; returns
    the gated path, or None when the card cannot be read (caller must then
    refuse to render). Used before image/text rendering (t126)."""
    import json
    from pathlib import Path
    src = Path(card_path)
    try:
        payload = json.loads(src.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if isinstance(payload, dict):
        gated = gate_and_stamp(payload, sport, runner)
    else:
        gated, _ = gate_payload(payload, sport)
    dst = src.with_name(src.stem + ".registry_gated.json")
    dst.write_text(json.dumps(gated, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    return dst


def gate_and_stamp(payload: dict, default_sport, runner: str) -> dict:
    """gate_payload + a provenance stamp; for runners writing a dict card."""
    gated, stats = gate_payload(payload, default_sport)
    if isinstance(gated, dict):
        gated["registry_gate"] = {"runner": runner, "module": "sportsedge.registry_gate", **stats}
    return gated
