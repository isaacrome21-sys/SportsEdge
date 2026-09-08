#!/usr/bin/env python3
"""Capture real production-path MLB quote-binding evidence.

This acceptance probe intentionally uses the same acquisition and normalization
adapters as production. It fetches the official MLB StatsAPI schedule independently,
fetches DraftKings full-game markets through The Odds API, normalizes the emitted
quotes, and executes the hardened orchestration quote-binding boundary.

No model is run and no betting decision is produced. This artifact is source-wiring
evidence only. A provider event id is preserved as provenance while official MLB
``game_pk``/team ids/game number originate from the independent schedule source.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sportsedge.game_odds_source import GAME_MARKETS, fetch_mlb_game_quotes
from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.mlb_source import GameSnapshot, fetch_schedule
from sportsedge.orchestrator import validate_normalized_mlb_quote_binding
from sportsedge.quote_bridge import normalize_offer

UTC = timezone.utc
CHICAGO = ZoneInfo("America/Chicago")
KEY_ENV = (
    "SPORTSEDGE_ODDS_API_KEY",
    "SPORTSEDGE_ODDS_API_KEY_2",
    "SPORTSEDGE_ODDS_API_KEY_3",
    "SPORTSEDGE_ODDS_API_KEY_4",
)
REQUIRED_MARKETS = ("MONEYLINE", "RUN_LINE", "TOTALS")
SCHEMA_VERSION = "MLB_SOURCE_BINDING_ACCEPTANCE_V1"


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value)).hexdigest()


def _live_identity(snapshot: GameSnapshot) -> LiveGame:
    """Build only the official identity shell needed by quote binding.

    Lineups are deliberately empty/unconfirmed because this acceptance probe proves
    source identity wiring, not lineup eligibility or Model_P readiness.
    """
    return LiveGame(
        game_pk=int(snapshot.game_pk),
        away_team_id=int(snapshot.away_id),
        home_team_id=int(snapshot.home_id),
        away_probable_pitcher_id=snapshot.away_probable_pitcher_id,
        home_probable_pitcher_id=snapshot.home_probable_pitcher_id,
        away_lineup=TeamLineup(int(snapshot.away_id), "away", (), (), False),
        home_lineup=TeamLineup(int(snapshot.home_id), "home", (), (), False),
        game_number=snapshot.game_number,
        double_header=snapshot.double_header,
        venue_id=snapshot.venue_id,
        official_date=snapshot.official_date,
        status=snapshot.status,
    )


def _key_slots() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    seen: set[str] = set()
    for slot, name in enumerate(KEY_ENV, 1):
        value = os.environ.get(name, "").strip()
        if value and value not in seen:
            out.append((slot, value))
            seen.add(value)
    return out


def _source_schedule_rows(schedule: Iterable[GameSnapshot]) -> list[dict[str, Any]]:
    return [
        {
            "game_pk": g.game_pk,
            "game_number": g.game_number,
            "official_date": g.official_date,
            "game_date": g.game_date,
            "away_id": g.away_id,
            "away_name": g.away_name,
            "home_id": g.home_id,
            "home_name": g.home_name,
            "source": g.source,
            "retrieved_at": g.retrieved_at,
        }
        for g in schedule
    ]


def run_acceptance(*, out_root: Path, now: datetime | None = None) -> tuple[dict[str, Any], Path]:
    now = now or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)
    target_date = now.astimezone(CHICAGO).date().isoformat()
    out_dir = out_root / target_date
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%S.%fZ")
    evidence_path = out_dir / f"binding_{stamp}.json"

    row: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_at_utc": now.isoformat(),
        "target_official_date": target_date,
        "acceptance_scope": "REAL_EXTERNAL_SOURCE_WIRING_ONLY_NOT_MODEL_PROMOTION",
        "official_source": "MLB_STATSAPI_SCHEDULE",
        "odds_source": "THE_ODDS_API",
        "bookmakers": ["draftkings"],
        "provider_markets": list(GAME_MARKETS),
        "required_sportsedge_markets": list(REQUIRED_MARKETS),
        "key_slots_present": len(_key_slots()),
        "attempts": [],
        "status": "BLOCKED_UNRUN",
    }

    try:
        schedule = fetch_schedule(target_date, now=now)
    except Exception as exc:
        row.update(status="BLOCKED_OFFICIAL_SCHEDULE", reason=f"{type(exc).__name__}:{exc}")
        evidence_path.write_text(json.dumps(_jsonable(row), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return row, evidence_path

    schedule_rows = _source_schedule_rows(schedule)
    row["official_schedule_games"] = len(schedule_rows)
    row["official_schedule_sha256"] = _digest(schedule_rows)
    row["official_schedule_identity"] = schedule_rows

    keys = _key_slots()
    if not keys:
        row.update(status="BLOCKED_NO_ODDS_KEY", reason="no configured provider key slot")
        evidence_path.write_text(json.dumps(_jsonable(row), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return row, evidence_path

    snapshot = None
    key_slot = None
    for slot, key in keys:
        try:
            candidate = fetch_mlb_game_quotes(
                api_key=key,
                schedule=schedule,
                bookmakers=("draftkings",),
            )
            attempt = {
                "key_slot": slot,
                "quotes": len(candidate.quotes),
                "failures": len(candidate.failures),
                "failure_reasons": dict(Counter(str(x.get("reason") or "UNKNOWN") for x in candidate.failures)),
            }
            row["attempts"].append(attempt)
            if candidate.quotes:
                snapshot = candidate
                key_slot = slot
                break
        except Exception as exc:
            row["attempts"].append({"key_slot": slot, "reason": f"{type(exc).__name__}:{exc}"})

    if snapshot is None:
        row.update(status="BLOCKED_NO_ODDS", reason="all configured provider key slots produced zero accepted quotes")
        evidence_path.write_text(json.dumps(_jsonable(row), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return row, evidence_path

    by_game = {int(g.game_pk): _live_identity(g) for g in schedule}
    normalized: list[dict[str, Any]] = []
    attested: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = list(snapshot.failures)
    for raw in snapshot.quotes:
        try:
            quote = normalize_offer(raw)
            live_game = by_game.get(int(quote["game_id"]))
            if live_game is None:
                raise RuntimeError("OFFICIAL_GAME_LOOKUP_MISSING_AFTER_ACQUISITION")
            attestation = validate_normalized_mlb_quote_binding(game=live_game, quote=quote)
            normalized.append(quote)
            attested.append(asdict(attestation))
        except Exception as exc:
            failures.append({
                "reason": f"{type(exc).__name__}:{exc}",
                "game_id": str(raw.get("game_id") or ""),
                "market": str(raw.get("market") or ""),
                "book_key": str(raw.get("book_key") or ""),
            })

    acquired_counts = Counter(str(q.get("market") or "") for q in snapshot.quotes)
    normalized_counts = Counter(str(q.get("market") or "") for q in normalized)
    attested_counts = Counter(str(a.get("market") or "") for a in attested)
    provider_ids = {str(q.get("provider_event_id") or "") for q in normalized if q.get("provider_event_id")}
    official_ids = {str(q.get("event_id") or "") for q in normalized if q.get("event_id")}

    row.update(
        key_slot=key_slot,
        acquired_quote_count=len(snapshot.quotes),
        normalized_quote_count=len(normalized),
        attested_quote_count=len(attested),
        acquired_by_market=dict(acquired_counts),
        normalized_by_market=dict(normalized_counts),
        attested_by_market=dict(attested_counts),
        unique_provider_event_ids=len(provider_ids),
        unique_official_event_ids=len(official_ids),
        quote_export_sha256=_digest(normalized),
        attestation_sha256=_digest(attested),
        canonical_quotes=_jsonable(normalized),
        binding_attestations=_jsonable(attested),
        failures=_jsonable(failures),
    )

    passed = [m for m in REQUIRED_MARKETS if attested_counts.get(m, 0) >= 2]
    row["source_wiring_pass_markets"] = passed
    missing = [m for m in REQUIRED_MARKETS if m not in passed]
    if missing:
        row.update(
            status="PARTIAL_SOURCE_WIRING",
            reason=f"missing real paired attested quotes for: {','.join(missing)}",
        )
    elif len(attested) != len(normalized):
        row.update(status="BLOCKED_BINDING_LOSS", reason="not every normalized quote produced a binding attestation")
    else:
        row.update(status="SOURCE_WIRING_PASS", reason="real provider quotes crossed production acquisition, normalization, and binding boundary")

    evidence_path.write_text(json.dumps(_jsonable(row), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return row, evidence_path


def main() -> int:
    out_root = Path(os.environ.get("SPORTSEDGE_BINDING_ACCEPTANCE_DIR", "artifacts/mlb-binding-acceptance"))
    row, path = run_acceptance(out_root=out_root)
    print(json.dumps({
        "status": row.get("status"),
        "target_official_date": row.get("target_official_date"),
        "source_wiring_pass_markets": row.get("source_wiring_pass_markets", []),
        "attested_by_market": row.get("attested_by_market", {}),
        "evidence_path": str(path),
    }, sort_keys=True))
    return 0 if row.get("status") == "SOURCE_WIRING_PASS" else 3


if __name__ == "__main__":
    raise SystemExit(main())
