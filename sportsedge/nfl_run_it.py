"""NFL sides/totals RUN IT card.

Fresh paired prices + non-certifying estimates (or joint-score simulations) in.
Short ranked +EV card out. Empty is a valid result.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from sports.common.ev_math import EVError, devig, parse_utc
from sportsedge.core.simulate.markets import derive_game_markets
from sportsedge.market_ids import canonical_market_id
from sportsedge.truth_gate import american_to_decimal


CARD_SCHEMA = "SPORTSEDGE_NFL_RUN_IT_CARD_V2"
SUPPORTED_MARKETS = frozenset({"moneyline", "spread", "total"})
DEFAULT_EDGE_FLOOR = 0.02
QUOTE_TTL_SECONDS = 180
MAX_QUOTE_SKEW_SECONDS = 30
DEVIG_METHOD = "POWER_V1"
AUTHORITY_FOOTER = "NOT Model_P / NOT Truth Gate / NOT OFFICIAL"


class NflRunItError(ValueError):
    pass


@dataclass(frozen=True)
class CardPick:
    rank: int
    game_id: str
    home: str
    away: str
    market: str
    selection: str
    line: float | None
    price_american: int
    book: str
    retrieved_at: str
    estimate_p: float
    push_p: float
    market_no_vig_p: float
    edge_probability_points: float
    ev_per_dollar: float
    devig_method: str


@dataclass(frozen=True)
class RunItCard:
    schema: str
    sport: str
    picks: tuple[CardPick, ...]
    omitted: int
    empty_reason: str | None
    authority_footer: str = AUTHORITY_FOOTER

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "sport": self.sport,
            "picks": [asdict(p) for p in self.picks],
            "omitted": self.omitted,
            "empty_reason": self.empty_reason,
            "authority_footer": self.authority_footer,
        }

    def render(self) -> str:
        lines = ["NFL — RUN IT"]
        if not self.picks:
            lines.append("Nothing looks strong enough.")
        else:
            for p in self.picks:
                if p.market == "total":
                    sel = f"{p.away}/{p.home} {p.selection} {p.line:g}"
                elif p.market == "spread":
                    sel = f"{p.selection} {p.line:+g}"
                else:
                    sel = p.selection
                lines.append(
                    f"{p.rank}. {sel}  {p.price_american:+d}   "
                    f"edge {p.edge_probability_points * 100:+.1f}pp   "
                    f"EV {p.ev_per_dollar * 100:+.1f}%"
                )
        if self.omitted:
            lines.append(f"— {self.omitted} quote(s) omitted by fail-closed filters or floor.")
        lines.append(self.authority_footer)
        return "\n".join(lines)


def _req_text(row: Mapping[str, Any], key: str) -> str:
    value = row.get(key)
    if value is None or not str(value).strip():
        raise NflRunItError(f"QUOTE_IDENTITY_INCOMPLETE:{key}")
    return str(value).strip()


def _american(value: Any) -> int:
    try:
        odds = float(value)
    except (TypeError, ValueError) as exc:
        raise NflRunItError("american price invalid") from exc
    if not isfinite(odds) or odds != int(odds) or -100 < odds < 100:
        raise NflRunItError("american price must be integer <= -100 or >= 100")
    return int(odds)


def _timestamp(value: Any, code: str) -> datetime:
    if value is None or not str(value).strip():
        raise NflRunItError(code)
    try:
        dt = parse_utc(value)
    except (EVError, TypeError, ValueError) as exc:
        raise NflRunItError(code) from exc
    return dt.astimezone(timezone.utc)


def _optional_line(row: Mapping[str, Any], market: str) -> float | None:
    raw = row.get("line")
    if raw is None:
        if market == "moneyline":
            return None
        raise NflRunItError(f"line required for {market}")
    try:
        line = float(raw)
    except (TypeError, ValueError) as exc:
        raise NflRunItError("line invalid") from exc
    if not isfinite(line):
        raise NflRunItError("line must be finite")
    return line


def _normalize_selection(market: str, selection: str, home: str, away: str) -> str:
    sel = selection.strip()
    upper = sel.upper()
    if market == "total":
        if upper not in {"OVER", "UNDER"}:
            raise NflRunItError(f"unsupported total selection: {selection}")
        return upper
    if market in {"moneyline", "spread"}:
        if upper == "HOME":
            return home
        if upper == "AWAY":
            return away
        if sel not in {home, away}:
            raise NflRunItError(f"selection must be home or away team: {selection}")
        return sel
    raise NflRunItError(f"unsupported market: {market}")


def normalize_quote(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise NflRunItError("quote must be an object")
    game_id = _req_text(raw, "game_id")
    home = _req_text(raw, "home")
    away = _req_text(raw, "away")
    market = canonical_market_id("nfl", _req_text(raw, "market"))
    if market not in SUPPORTED_MARKETS:
        raise NflRunItError(f"NFL_RUN_IT_MARKET_OUT_OF_SCOPE:{market}")
    selection = _normalize_selection(market, _req_text(raw, "selection"), home, away)
    book = str(raw.get("book") or raw.get("book_key") or "").strip()
    if not book:
        raise NflRunItError("QUOTE_IDENTITY_INCOMPLETE:book")
    retrieved_at = _timestamp(raw.get("retrieved_at"), "QUOTE_RETRIEVED_AT_REQUIRED")
    return {
        "game_id": game_id,
        "home": home,
        "away": away,
        "market": market,
        "selection": selection,
        "line": _optional_line(raw, market),
        "price_american": _american(raw.get("price_american", raw.get("american_odds"))),
        "book": book,
        "retrieved_at": retrieved_at,
    }


def normalize_estimate_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise NflRunItError("estimate row must be an object")
    if "model_p" in raw:
        raise NflRunItError("MODEL_P_FIELD_FORBIDDEN_USE_ESTIMATE_P")
    game_id = _req_text(raw, "game_id")
    market = canonical_market_id("nfl", _req_text(raw, "market"))
    if market not in SUPPORTED_MARKETS:
        raise NflRunItError(f"NFL_RUN_IT_MARKET_OUT_OF_SCOPE:{market}")
    home = str(raw.get("home") or "").strip()
    away = str(raw.get("away") or "").strip()
    selection_raw = _req_text(raw, "selection")
    selection = _normalize_selection(market, selection_raw, home, away) if home and away else selection_raw
    try:
        estimate_p = float(raw.get("estimate_p"))
    except (TypeError, ValueError) as exc:
        raise NflRunItError("estimate_p invalid") from exc
    if not isfinite(estimate_p) or not 0.0 < estimate_p < 1.0:
        raise NflRunItError("estimate_p must be in (0,1)")
    line = raw.get("line")
    norm_line = None if line is None else float(line)
    if norm_line is not None and not isfinite(norm_line):
        raise NflRunItError("estimate line must be finite")
    return {
        "game_id": game_id,
        "market": market,
        "selection": selection,
        "line": norm_line,
        "estimate_p": estimate_p,
    }


def _estimate_key(game_id: str, market: str, selection: str, line: float | None) -> tuple:
    return (game_id, market, selection, None if line is None else round(float(line), 4))


def _pair_key(q: Mapping[str, Any]) -> tuple:
    line = q["line"]
    if q["market"] == "spread" and line is not None:
        line = abs(float(line))
    return (q["game_id"], q["market"], q["book"], None if line is None else round(float(line), 4))


def _is_complement(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    if _pair_key(a) != _pair_key(b) or a["selection"] == b["selection"]:
        return False
    if a["market"] == "total":
        return {a["selection"], b["selection"]} == {"OVER", "UNDER"}
    return True


def find_pair(candidate: Mapping[str, Any], quotes: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    matches = [q for q in quotes if q is not candidate and _is_complement(candidate, q)]
    return matches[0] if len(matches) == 1 else None


def _validate_quote_time(quote: Mapping[str, Any], *, as_of: datetime) -> None:
    retrieved_at = quote["retrieved_at"]
    age_s = (as_of - retrieved_at).total_seconds()
    if age_s > QUOTE_TTL_SECONDS:
        raise NflRunItError("QUOTE_STALE")
    if age_s < -MAX_QUOTE_SKEW_SECONDS:
        raise NflRunItError("QUOTE_CLOCK_SKEW")


def market_no_vig_probability(candidate: Mapping[str, Any], opposite: Mapping[str, Any]) -> float:
    skew = abs((candidate["retrieved_at"] - opposite["retrieved_at"]).total_seconds())
    if skew > MAX_QUOTE_SKEW_SECONDS:
        raise NflRunItError("PAIRED_QUOTE_TIME_SKEW")
    decimals = [
        american_to_decimal(int(candidate["price_american"])),
        american_to_decimal(int(opposite["price_american"])),
    ]
    try:
        return float(devig(decimals, trigger_american=400, max_spread_pp=1.0)[0])
    except EVError as exc:
        raise NflRunItError(exc.code) from exc


def ev_per_dollar(estimate_p: float, price: int, *, push_p: float = 0.0) -> float:
    if push_p < 0 or estimate_p < 0 or estimate_p + push_p > 1.0 + 1e-12:
        raise NflRunItError("INVALID_WIN_PUSH_MASS")
    loss_p = max(0.0, 1.0 - estimate_p - push_p)
    dec = american_to_decimal(price)
    return estimate_p * (dec - 1.0) - loss_p


def estimate_p_from_simulation(
    rows: Iterable[Mapping[str, Any]],
    *,
    market: str,
    selection: str,
    line: float | None,
    home: str,
    away: str,
) -> tuple[float, float]:
    """Return (estimate_p, push_p) from joint score rows at the posted line."""
    spread_line = 0.0
    total_line = None
    if market == "spread":
        if line is None:
            raise NflRunItError("spread line required")
        if selection == home:
            spread_line = float(line)
        elif selection == away:
            spread_line = -float(line)
        else:
            raise NflRunItError("spread selection must be a team")
    elif market == "total":
        if line is None:
            raise NflRunItError("total line required")
        total_line = float(line)
    markets = derive_game_markets(rows, spread_line=spread_line, total_line=total_line)
    if market == "moneyline":
        block = markets["moneyline"]
        if selection == home:
            return float(block["home_win"]), float(block["tie"])
        if selection == away:
            return float(block["away_win"]), float(block["tie"])
        raise NflRunItError("moneyline selection must be a team")
    if market == "spread":
        block = markets["spread"]
        push = float(block["push"])
        return (float(block["home_cover"]), push) if selection == home else (float(block["away_cover"]), push)
    block = markets["total"]
    push = float(block["push"])
    return (float(block["over"]), push) if selection == "OVER" else (float(block["under"]), push)


def _integer_line_requires_simulation(quote: Mapping[str, Any]) -> bool:
    line = quote["line"]
    return (
        quote["market"] in {"spread", "total"}
        and line is not None
        and abs(float(line) - round(float(line))) < 1e-9
    )


def run_it(
    quotes: Sequence[Mapping[str, Any]],
    estimates: Sequence[Mapping[str, Any]],
    *,
    edge_floor: float = DEFAULT_EDGE_FLOOR,
    simulations: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    as_of: datetime | str | None = None,
) -> RunItCard:
    if not isinstance(edge_floor, (int, float)) or isinstance(edge_floor, bool) or not isfinite(float(edge_floor)) or float(edge_floor) < 0:
        raise NflRunItError("edge_floor must be finite and >= 0")
    floor = float(edge_floor)
    now = datetime.now(timezone.utc) if as_of is None else _timestamp(as_of, "AS_OF_INVALID")

    norm_quotes = [normalize_quote(q) for q in quotes]
    for quote in norm_quotes:
        _validate_quote_time(quote, as_of=now)
        if find_pair(quote, norm_quotes) is None:
            raise NflRunItError(f"PAIRED_PRICE_REQUIRED:{_pair_key(quote)}")

    estimate_map: dict[tuple, dict[str, Any]] = {}
    for raw in estimates:
        row = normalize_estimate_row(raw)
        key = _estimate_key(row["game_id"], row["market"], row["selection"], row["line"])
        if key in estimate_map and estimate_map[key]["estimate_p"] != row["estimate_p"]:
            raise NflRunItError(f"conflicting estimate_p for {key}")
        estimate_map[key] = row

    scored: list[dict[str, Any]] = []
    omitted = 0
    for quote in norm_quotes:
        key = _estimate_key(quote["game_id"], quote["market"], quote["selection"], quote["line"])
        estimate = estimate_map.get(key)
        sim_rows = (simulations or {}).get(quote["game_id"])
        requires_sim = _integer_line_requires_simulation(quote)

        if requires_sim and not sim_rows:
            if estimate is not None:
                raise NflRunItError(f"SIMULATIONS_REQUIRED_FOR_INTEGER_LINE:{key}")
            omitted += 1
            continue

        if requires_sim or (estimate is None and sim_rows):
            estimate_p, push_p = estimate_p_from_simulation(
                sim_rows or (),
                market=quote["market"],
                selection=quote["selection"],
                line=quote["line"],
                home=quote["home"],
                away=quote["away"],
            )
        elif estimate is not None:
            estimate_p = float(estimate["estimate_p"])
            push_p = 0.0
        else:
            omitted += 1
            continue

        opposite = find_pair(quote, norm_quotes)
        if opposite is None:
            raise NflRunItError(f"PAIRED_PRICE_REQUIRED:{_pair_key(quote)}")
        no_vig_p = market_no_vig_probability(quote, opposite)
        non_push = 1.0 - push_p
        if non_push <= 0:
            raise NflRunItError("NON_PUSH_MASS_ZERO")
        conditional_estimate = estimate_p / non_push
        edge = conditional_estimate - no_vig_p
        ev = ev_per_dollar(estimate_p, quote["price_american"], push_p=push_p)
        if edge <= floor or ev <= 0:
            omitted += 1
            continue
        scored.append(
            {
                "game_id": quote["game_id"],
                "home": quote["home"],
                "away": quote["away"],
                "market": quote["market"],
                "selection": quote["selection"],
                "line": quote["line"],
                "price_american": quote["price_american"],
                "book": quote["book"],
                "retrieved_at": quote["retrieved_at"].isoformat().replace("+00:00", "Z"),
                "estimate_p": estimate_p,
                "push_p": push_p,
                "market_no_vig_p": no_vig_p,
                "edge_probability_points": edge,
                "ev_per_dollar": ev,
                "devig_method": DEVIG_METHOD,
            }
        )

    scored.sort(
        key=lambda r: (
            -r["ev_per_dollar"],
            -r["edge_probability_points"],
            r["game_id"],
            r["market"],
            r["selection"],
        )
    )
    picks = tuple(CardPick(rank=i, **row) for i, row in enumerate(scored, start=1))
    return RunItCard(
        schema=CARD_SCHEMA,
        sport="nfl",
        picks=picks,
        omitted=omitted,
        empty_reason=None if picks else "Nothing looks strong enough.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="NFL sides/totals RUN IT card")
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--estimates", default=None)
    parser.add_argument("--simulations", default=None)
    parser.add_argument("--edge-floor", type=float, default=DEFAULT_EDGE_FLOOR)
    parser.add_argument("--as-of", default=None)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    quotes = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    estimates = json.loads(Path(args.estimates).read_text(encoding="utf-8")) if args.estimates else []
    simulations = json.loads(Path(args.simulations).read_text(encoding="utf-8")) if args.simulations else None
    card = run_it(
        quotes,
        estimates,
        edge_floor=args.edge_floor,
        simulations=simulations,
        as_of=args.as_of,
    )
    print(card.render())
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(card.to_dict(), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())