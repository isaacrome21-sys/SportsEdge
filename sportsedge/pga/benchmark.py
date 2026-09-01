from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Mapping, Sequence

from .market_pricing import full_field_no_vig, two_way_no_vig

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = ROOT / "config" / "pga_benchmark_methodology.json"


@dataclass(frozen=True)
class PGABenchmarkProbability:
    market: str
    selection: str
    probability: float
    methodology: str
    quote_set_sha256: str
    market_shape: str


def _contract(path: str | Path = DEFAULT_CONTRACT) -> dict:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != "PGA_BENCHMARK_V1":
        raise ValueError("PGA_BENCHMARK_CONTRACT_INVALID")
    return payload


def _quote_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def benchmark_probability(
    *,
    market: str,
    selection: str,
    prices: Mapping[str, float] | Sequence[tuple[str, float]],
    market_complete: bool | None = None,
    contract_path: str | Path = DEFAULT_CONTRACT,
) -> PGABenchmarkProbability:
    """Build a reproducible no-vig PGA benchmark under the frozen market-shape contract.

    OUTRIGHT/FRL require an exhaustive field. TOP_K and MAKE_CUT require the
    selected player's paired YES/NO outcomes. H2H requires both matchup sides.
    Cross-player normalization is never allowed for non-exhaustive markets.
    """
    market_key = str(market).strip().upper()
    selection_key = str(selection).strip()
    if not selection_key:
        raise ValueError("PGA_BENCHMARK_SELECTION_REQUIRED")
    contract = _contract(contract_path)
    row = (contract.get("markets") or {}).get(market_key)
    if not isinstance(row, dict):
        raise ValueError(f"PGA_BENCHMARK_MARKET_UNSUPPORTED:{market_key}")

    if isinstance(prices, Mapping):
        price_map = {str(k): float(v) for k, v in prices.items()}
    else:
        price_map = {str(k): float(v) for k, v in prices}
    if len(price_map) < 2:
        raise ValueError("PGA_BENCHMARK_PAIRED_QUOTES_REQUIRED")

    method = str(row.get("devig_method") or "")
    shape = str(row.get("shape") or "")
    if method == "MULTIPLICATIVE_NWAY_V1":
        if market_complete is not True:
            raise ValueError("PGA_COMPLETE_FIELD_REQUIRED_FOR_NWAY_DEVIG")
        fair = full_field_no_vig(price_map, market_complete=True)
        if selection_key not in fair:
            raise ValueError("PGA_BENCHMARK_SELECTION_NOT_IN_FIELD")
        probability = fair[selection_key]
    elif method == "MULTIPLICATIVE_2WAY_V1":
        if len(price_map) != 2:
            raise ValueError("PGA_BENCHMARK_EXACTLY_TWO_QUOTES_REQUIRED")
        if selection_key not in price_map:
            raise ValueError("PGA_BENCHMARK_SELECTION_NOT_IN_PAIR")
        names = list(price_map)
        p0, p1 = two_way_no_vig(price_map[names[0]], price_map[names[1]])
        probability = p0 if selection_key == names[0] else p1
    else:
        raise ValueError(f"PGA_BENCHMARK_METHOD_UNSUPPORTED:{method}")

    quote_payload = {
        "market": market_key,
        "selection": selection_key,
        "prices": sorted(price_map.items()),
        "market_complete": market_complete,
        "methodology": method,
    }
    return PGABenchmarkProbability(
        market=market_key,
        selection=selection_key,
        probability=float(probability),
        methodology=method,
        quote_set_sha256=_quote_hash(quote_payload),
        market_shape=shape,
    )
