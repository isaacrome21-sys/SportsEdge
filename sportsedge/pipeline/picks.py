"""The one pick record every sport writes."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime
from math import isfinite
from numbers import Real
from typing import Any

SCHEMA = "sportsedge.pick.v1"
SPORTS = ("MLB", "NFL", "CFB", "NBA", "NHL")
SELECTIONS = ("AWAY", "HOME", "OVER", "UNDER", "YES", "NO")


class PickRecordError(ValueError):
    pass


def _finite_real(value: Any) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and isfinite(value)


def american_to_decimal(price: int) -> float:
    if isinstance(price, bool):
        raise PickRecordError(f"PICK_PRICE_INVALID:{price}")
    price = int(price)
    if -100 < price < 100:
        raise PickRecordError(f"PICK_PRICE_INVALID:{price}")
    return 1 + (price / 100 if price > 0 else 100 / -price)


def expected_value(model_p: float, dk_price: int) -> float:
    """EV per 1u staked at the DraftKings price (no new math: p * dec - 1)."""
    return float(model_p) * american_to_decimal(dk_price) - 1.0


@dataclass(frozen=True)
class PickRecord:
    sport: str
    market: str
    selection: str            # AWAY | HOME | OVER | UNDER | YES | NO (+ subject in `subject`)
    line: float | None
    dk_price: int
    captured_at: str          # sportsbook capture instant (ISO with offset), never issue time
    model_p: float
    engine: str               # engine id/version that produced model_p
    ev: float
    ladder_status: str        # from config/market_ladder_status.json, never inherited
    game: str = ""            # "Away @ Home"
    subject: str | None = None
    opposite_price: int | None = None   # paired side at capture (for no-vig CLV)
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if self.sport not in SPORTS:
            raise PickRecordError(f"PICK_SPORT_INVALID:{self.sport}")
        if not self.market or not self.selection:
            raise PickRecordError("PICK_MARKET_OR_SELECTION_MISSING")
        if self.selection not in SELECTIONS:
            raise PickRecordError(f"PICK_SELECTION_INVALID:{self.selection}")
        if self.line is not None and not _finite_real(self.line):
            raise PickRecordError(f"PICK_LINE_INVALID:{self.line}")
        american_to_decimal(self.dk_price)
        if self.opposite_price is not None:
            american_to_decimal(self.opposite_price)
        if not (_finite_real(self.model_p) and 0.0 < self.model_p < 1.0):
            raise PickRecordError(f"PICK_MODEL_P_INVALID:{self.model_p}")
        try:
            ts = datetime.fromisoformat(str(self.captured_at).replace("Z", "+00:00"))
        except ValueError as exc:
            raise PickRecordError(f"PICK_CAPTURED_AT_INVALID:{self.captured_at}") from exc
        if ts.tzinfo is None:
            raise PickRecordError(f"PICK_CAPTURED_AT_TZ_REQUIRED:{self.captured_at}")
        if not _finite_real(self.ev):
            raise PickRecordError(f"PICK_EV_INVALID:{self.ev}")
        if not abs(self.ev - expected_value(self.model_p, self.dk_price)) <= 1e-6:
            raise PickRecordError("PICK_EV_MISMATCH")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, row: Mapping[str, Any]) -> PickRecord:
        fields = {k: row[k] for k in cls.__dataclass_fields__ if k in row}
        return cls(**fields)


def make_pick(*, sport: str, market: str, selection: str, line: float | None, dk_price: int,
              captured_at: str, model_p: float, engine: str, ladder_status: str | None = None,
              game: str = "", subject: str | None = None, opposite_price: int | None = None,
              ladder: Mapping[str, Any] | None = None) -> PickRecord:
    """Build a pick; ``ladder_status`` defaults to the market's own ladder entry."""
    if ladder_status is None:
        from .ladder import status_for
        ladder_status = status_for(sport, market, ladder=ladder)
    return PickRecord(sport.upper(), market, str(selection).upper(), line, int(dk_price),
                      captured_at, float(model_p), engine, expected_value(model_p, dk_price),
                      ladder_status, game=game, subject=subject, opposite_price=opposite_price)
