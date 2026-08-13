from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.request import urlopen

from .forward_shadow import canonical_json

BASE = "https://statsapi.mlb.com"


class NRFIV6OutcomeError(RuntimeError):
    pass


def _get_json(url: str, opener: Callable = urlopen) -> Mapping[str, Any]:
    try:
        with opener(url, timeout=15) as response:
            out = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise NRFIV6OutcomeError(f"MLB_OUTCOME_FETCH_FAILED:{type(exc).__name__}") from exc
    if not isinstance(out, Mapping):
        raise NRFIV6OutcomeError("MLB_OUTCOME_RESPONSE_MALFORMED")
    return out


def first_inning_yrfi_outcome(game_pk: int, *, opener: Callable = urlopen) -> dict[str, Any] | None:
    payload = _get_json(f"{BASE}/api/v1.1/game/{int(game_pk)}/feed/live", opener)
    game_data = payload.get("gameData") or {}
    status = game_data.get("status") or {}
    abstract = str(status.get("abstractGameState") or "")
    detailed = str(status.get("detailedState") or "")
    if abstract != "Final":
        return None
    # Suspended/postponed/resumed games are not silently treated as ordinary finals.
    low = detailed.lower()
    if any(token in low for token in ("suspended", "postponed", "resumed")):
        raise NRFIV6OutcomeError(f"NONSTANDARD_FINAL_STATE:{game_pk}:{detailed}")
    innings = ((payload.get("liveData") or {}).get("linescore") or {}).get("innings") or []
    first = None
    for inning in innings:
        if isinstance(inning, Mapping) and int(inning.get("num") or 0) == 1:
            first = inning
            break
    if first is None:
        raise NRFIV6OutcomeError(f"FIRST_INNING_MISSING:{game_pk}")
    try:
        away_runs = int(((first.get("away") or {}).get("runs")) or 0)
        home_runs = int(((first.get("home") or {}).get("runs")) or 0)
    except Exception as exc:
        raise NRFIV6OutcomeError(f"FIRST_INNING_RUNS_INVALID:{game_pk}") from exc
    yrfi = 1 if (away_runs + home_runs) >= 1 else 0
    return {
        "game_id": str(int(game_pk)),
        "yrfi_outcome": yrfi,
        "nrfi_outcome": 1 - yrfi,
        "first_inning_away_runs": away_runs,
        "first_inning_home_runs": home_runs,
        "mlb_abstract_state": abstract,
        "mlb_detailed_state": detailed,
        "source": "MLB_STATSAPI_LIVE_FEED",
    }


def attach_outcomes(game_ids: Iterable[str], *, opener: Callable = urlopen, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise NRFIV6OutcomeError("TIMEZONE_REQUIRED")
    rows = []
    pending = []
    failures = []
    seen = set()
    for raw in game_ids:
        gid = str(raw).strip()
        if not gid or gid in seen:
            continue
        seen.add(gid)
        try:
            result = first_inning_yrfi_outcome(int(gid), opener=opener)
            if result is None:
                pending.append(gid)
            else:
                rows.append(result)
        except Exception as exc:
            failures.append({"game_id": gid, "reason": f"{type(exc).__name__}:{exc}"})
    rows.sort(key=lambda r: int(r["game_id"]))
    payload = {
        "schema_version": "nrfi_v6_outcomes_v1",
        "generated_at_utc": now.astimezone(timezone.utc).isoformat(),
        "outcome_count": len(rows),
        "pending_game_ids": sorted(pending, key=int),
        "failures": failures,
        "outcomes": rows,
        "prediction_rows_mutated": False,
    }
    payload["outcomes_sha256"] = hashlib.sha256(canonical_json(rows)).hexdigest()
    return payload


def write_outcomes(game_ids: Iterable[str], output: str | Path, *, opener: Callable = urlopen, now: datetime | None = None) -> Path:
    payload = attach_outcomes(game_ids, opener=opener, now=now)
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(canonical_json(payload))
    return p
