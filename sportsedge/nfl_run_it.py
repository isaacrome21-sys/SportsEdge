"""NFL sides/totals RUN IT card.

Quotes + model probabilities in. Short ranked +EV card out.
An empty card is a valid result. Official labels live in the ledger, not here.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any, Iterable, Mapping, Sequence

from sportsedge.core.simulate.markets import derive_game_markets
from sportsedge.market_ids import canonical_market_id
from sportsedge.truth_gate import american_to_decimal


CARD_SCHEMA = "SPORTSEDGE_NFL_RUN_IT_CARD_V1"
SUPPORTED_MARKETS = frozenset({"moneyline", "spread", "total"})
DEFAULT_EDGE_FLOOR = 0.02  # probability points; card floor, not Official gate


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
    model_p: float
    novig_p: float
    edge_probability_points: float
    ev_per_dollar: float
    score: int
    reason: str
    paired: bool


@dataclass(frozen=True)
class RunItCard:
    schema: str
    sport: str
    picks: tuple[CardPick, ...]
    omitted: int
    empty_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "sport": self.sport,
            "picks": [asdict(p) for p in self.picks],
            "omitted": self.omitted,
            "empty_reason": self.empty_reason,
        }

    def render(self) -> str:
        if not self.picks:
            return "NFL — RUN IT\nNothing looks strong enough."
        lines = ["NFL — RUN IT"]
        for p in self.picks:
            if p.market == "total":
                sel = f"{p.away}/{p.home} {p.selection} {p.line:g}"
            elif p.market == "spread":
                sel = f"{p.selection} {p.line:+g}"
            else:
                sel = p.selection
            price = f"{p.price_american:+d}"
            edge = f"edge {p.edge_probability_points * 100:+.1f}pp"
            lines.append(
                f"{p.rank}. {sel}  {price}   {edge}   {p.score}   {p.reason}"
            )
        if self.omitted:
            lines.append(f"— {self.omitted} other quote(s) below the floor.")
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
        if upper in {"HOME"}:
            return home
        if upper in {"AWAY"}:
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
    return {
        "game_id": game_id,
        "home": home,
        "away": away,
        "market": market,
        "selection": selection,
        "line": _optional_line(raw, market),
        "price_american": _american(raw.get("price_american", raw.get("american_odds"))),
        "book": str(raw.get("book") or raw.get("book_key") or "unknown").strip(),
        "reason_hint": str(raw["reason_hint"]).strip() if raw.get("reason_hint") else None,
    }


def normalize_model_row(raw: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise NflRunItError("model row must be an object")
    game_id = _req_text(raw, "game_id")
    market = canonical_market_id("nfl", _req_text(raw, "market"))
    if market not in SUPPORTED_MARKETS:
        raise NflRunItError(f"NFL_RUN_IT_MARKET_OUT_OF_SCOPE:{market}")
    home = str(raw.get("home") or "").strip()
    away = str(raw.get("away") or "").strip()
    selection_raw = _req_text(raw, "selection")
    selection = (
        _normalize_selection(market, selection_raw, home, away)
        if home and away
        else selection_raw
    )
    p = raw.get("model_p")
    try:
        model_p = float(p)
    except (TypeError, ValueError) as exc:
        raise NflRunItError("model_p invalid") from exc
    if not isfinite(model_p) or not 0.0 < model_p < 1.0:
        raise NflRunItError("model_p must be in (0,1)")
    line = raw.get("line")
    norm_line = None if line is None else float(line)
    return {
        "game_id": game_id,
        "market": market,
        "selection": selection,
        "line": norm_line,
        "model_p": model_p,
        "why": str(raw["why"]).strip() if raw.get("why") else None,
    }


def _model_key(game_id: str, market: str, selection: str, line: float | None) -> tuple:
    return (game_id, market, selection, None if line is None else round(float(line), 4))


def _implied(price: int) -> float:
    return 1.0 / american_to_decimal(price)


def _pair_key(q: Mapping[str, Any]) -> tuple:
    line = q["line"]
    if q["market"] == "spread" and line is not None:
        line = abs(float(line))
    return (q["game_id"], q["market"], q["book"], None if line is None else round(float(line), 4))


def _is_complement(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    if _pair_key(a) != _pair_key(b):
        return False
    if a["selection"] == b["selection"]:
        return False
    if a["market"] == "total":
        return {a["selection"], b["selection"]} == {"OVER", "UNDER"}
    return True


def find_pair(candidate: Mapping[str, Any], quotes: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    matches = [q for q in quotes if q is not candidate and _is_complement(candidate, q)]
    if len(matches) == 1:
        return matches[0]
    return None


def novig_probability(candidate: Mapping[str, Any], opposite: Mapping[str, Any] | None) -> tuple[float, bool]:
    raw = _implied(int(candidate["price_american"]))
    if opposite is None:
        return raw, False
    other = _implied(int(opposite["price_american"]))
    total = raw + other
    if total <= 0:
        raise NflRunItError("invalid paired implied sum")
    return raw / total, True


def ev_per_dollar(model_p: float, price: int) -> float:
    dec = american_to_decimal(price)
    return model_p * (dec - 1.0) - (1.0 - model_p)


def score_pick(*, edge: float, paired: bool, has_reason: bool, price: int) -> int:
    """Support rank. Does not invent edge."""
    pts = min(70.0, max(0.0, edge) * 1200.0)
    if paired:
        pts += 15.0
    if has_reason:
        pts += 10.0
    if abs(price) <= 250:
        pts += 5.0
    return int(max(0, min(100, round(pts))))


def model_p_from_simulation(
    rows: Iterable[Mapping[str, Any]],
    *,
    market: str,
    selection: str,
    line: float | None,
    home: str,
    away: str,
) -> tuple[float, float]:
    """Return (model_p, push_p) from joint score rows at the posted line."""
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
        if selection == home:
            return float(block["home_cover"]), push
        return float(block["away_cover"]), push
    block = markets["total"]
    push = float(block["push"])
    if selection == "OVER":
        return float(block["over"]), push
    return float(block["under"]), push


def run_it(
    quotes: Sequence[Mapping[str, Any]],
    models: Sequence[Mapping[str, Any]],
    *,
    edge_floor: float = DEFAULT_EDGE_FLOOR,
    simulations: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> RunItCard:
    if not isinstance(edge_floor, (int, float)) or isinstance(edge_floor, bool) or not isfinite(float(edge_floor)) or float(edge_floor) < 0:
        raise NflRunItError("edge_floor must be finite and >= 0")
    floor = float(edge_floor)

    norm_quotes = [normalize_quote(q) for q in quotes]
    model_map: dict[tuple, dict[str, Any]] = {}
    for raw in models:
        row = normalize_model_row(raw)
        key = _model_key(row["game_id"], row["market"], row["selection"], row["line"])
        if key in model_map and model_map[key]["model_p"] != row["model_p"]:
            raise NflRunItError(f"conflicting model_p for {key}")
        model_map[key] = row

    scored: list[dict[str, Any]] = []
    omitted = 0
    for quote in norm_quotes:
        key = _model_key(quote["game_id"], quote["market"], quote["selection"], quote["line"])
        model = model_map.get(key)
        push_p = 0.0
        why = quote.get("reason_hint")
        if model is None:
            sim_rows = (simulations or {}).get(quote["game_id"])
            if not sim_rows:
                omitted += 1
                continue
            model_p, push_p = model_p_from_simulation(
                sim_rows,
                market=quote["market"],
                selection=quote["selection"],
                line=quote["line"],
                home=quote["home"],
                away=quote["away"],
            )
        else:
            model_p = float(model["model_p"])
            why = model.get("why") or why

        opposite = find_pair(quote, norm_quotes)
        novig_p, paired = novig_probability(quote, opposite)
        non_push = max(1e-12, 1.0 - push_p)
        conditional = model_p / non_push
        edge = conditional - novig_p
        ev = ev_per_dollar(model_p, quote["price_american"])
        if edge <= floor or ev <= 0:
            omitted += 1
            continue
        reason = why or (
            f"Model {model_p:.3f} vs no-vig {novig_p:.3f} at {quote['price_american']:+d}"
            if paired
            else f"Model {model_p:.3f} vs raw implied {novig_p:.3f} at {quote['price_american']:+d} (unpaired)"
        )
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
                "model_p": model_p,
                "novig_p": novig_p,
                "edge_probability_points": edge,
                "ev_per_dollar": ev,
                "score": score_pick(
                    edge=edge,
                    paired=paired,
                    has_reason=bool(why),
                    price=quote["price_american"],
                ),
                "reason": reason,
                "paired": paired,
            }
        )

    scored.sort(key=lambda r: (-r["ev_per_dollar"], -r["edge_probability_points"], -r["score"]))
    picks = tuple(CardPick(rank=i, **row) for i, row in enumerate(scored, start=1))
    empty = None if picks else "Nothing looks strong enough."
    return RunItCard(
        schema=CARD_SCHEMA,
        sport="nfl",
        picks=picks,
        omitted=omitted,
        empty_reason=empty,
    )


def main(argv: Sequence[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="NFL sides/totals RUN IT card")
    parser.add_argument("--quotes", required=True)
    parser.add_argument("--models", default=None)
    parser.add_argument("--simulations", default=None)
    parser.add_argument("--edge-floor", type=float, default=DEFAULT_EDGE_FLOOR)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    quotes = json.loads(Path(args.quotes).read_text(encoding="utf-8"))
    models = json.loads(Path(args.models).read_text(encoding="utf-8")) if args.models else []
    simulations = (
        json.loads(Path(args.simulations).read_text(encoding="utf-8")) if args.simulations else None
    )
    card = run_it(quotes, models, edge_floor=args.edge_floor, simulations=simulations)
    print(card.render())
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(card.to_dict(), indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
