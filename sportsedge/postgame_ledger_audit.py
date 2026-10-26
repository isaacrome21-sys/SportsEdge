"""Research-only postgame ledger auditor; does not produce or promote picks."""
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

REQUIRED = ("selection_id", "event_id", "sport", "market", "model_version",
            "captured_at", "event_start", "status", "american_odds", "stake")
SETTLED = {"WIN", "LOSS", "PUSH", "VOID"}


def _timestamp(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must have timezone")
    return parsed


def american_profit(odds, stake):
    o, s = Decimal(str(odds)), Decimal(str(stake))
    if not o.is_finite() or not s.is_finite() or s <= 0 or o != o.to_integral_value() or abs(o) < 100:
        raise ValueError("invalid American odds or stake")
    return s * (o / 100 if o > 0 else 100 / -o)


def audit(rows):
    """Audit supplied rows only; never infer outcomes, prices or timestamps."""
    findings, seen, counts = [], set(), Counter()
    profit = Decimal(0)
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            findings.append((index, "INVALID_ROW", None))
            continue
        missing = tuple(key for key in REQUIRED if key not in row or row[key] in (None, ""))
        if missing:
            findings.append((index, "MISSING_FIELDS", missing))
            continue
        identity = (row["selection_id"], row["event_id"], row["model_version"])
        if identity in seen:
            findings.append((index, "DUPLICATE_SELECTION", identity))
            continue
        seen.add(identity)
        status = str(row["status"]).upper()
        if status not in SETTLED:
            findings.append((index, "UNSETTLED_OR_UNKNOWN", status))
            continue
        try:
            captured, start = _timestamp(row["captured_at"]), _timestamp(row["event_start"])
            if captured >= start:
                findings.append((index, "INVALID_PREGAME_TIMESTAMP", identity))
                continue
            stake = Decimal(str(row["stake"]))
            odds = Decimal(str(row["american_odds"]))
            american_profit(odds, stake)
            pnl = american_profit(odds, stake) if status == "WIN" else -stake if status == "LOSS" else Decimal(0)
        except (ValueError, TypeError, InvalidOperation, OverflowError):
            findings.append((index, "INVALID_PRICE_OR_TIME", identity))
            continue
        counts[status] += 1
        profit += pnl
    return {"counts": dict(counts), "profit_units": str(profit),
            "findings": findings, "accepted": sum(counts.values())}
