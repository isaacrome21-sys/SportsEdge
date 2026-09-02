#!/usr/bin/env python3
"""Plan and materialize clean MLB V8 forward decision/close evidence.

This lane is cheap outside capture windows: it calls only MLB StatsAPI. When a game
is near the standardized V8 decision or close window, the workflow runs the canonical
MLB machine once and this script converts that exact card into immutable evidence.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from capture_mlb_v8_forward_evidence import persist

CT = ZoneInfo("America/Chicago")
MLB_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule"
EFFECTIVE_CT = "2026-09-03"
DECISION_TARGET_MIN = 30.0
DECISION_TOLERANCE_MIN = 6.0
CLOSE_TARGETS_MIN = (10.0, 0.0)
CLOSE_TOLERANCE_MIN = 6.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value: Any) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return _sha(raw)


def fetch_schedule(slate_date_ct: str, opener=urlopen) -> list[dict[str, Any]]:
    uri = MLB_SCHEDULE + "?" + urlencode({"sportId": 1, "date": slate_date_ct, "hydrate": "team"})
    req = Request(uri, headers={"Accept": "application/json", "User-Agent": "SportsEdge-V8-Evidence/1.0"})
    with opener(req, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    games: list[dict[str, Any]] = []
    for date_row in payload.get("dates", []):
        for game in date_row.get("games", []):
            game_pk = game.get("gamePk")
            start = game.get("gameDate")
            if game_pk in (None, "") or not start:
                continue
            status = str(((game.get("status") or {}).get("abstractGameState") or "")).strip()
            teams = game.get("teams") or {}
            games.append({
                "game_id": str(game_pk),
                "first_pitch_at": _parse_ts(start).isoformat(),
                "abstract_game_state": status,
                "home_team": str((((teams.get("home") or {}).get("team") or {}).get("name") or "")),
                "away_team": str((((teams.get("away") or {}).get("team") or {}).get("name") or "")),
            })
    return games


def build_plan(now: datetime, games: Iterable[dict[str, Any]]) -> dict[str, Any]:
    current = _parse_ts(now.isoformat())
    slate_ct = current.astimezone(CT).date().isoformat()
    selected: list[dict[str, Any]] = []
    if slate_ct < EFFECTIVE_CT:
        return {
            "schema": "MLB_V8_FORWARD_PLAN_V1",
            "planned_at_utc": current.isoformat(),
            "slate_date_ct": slate_ct,
            "effective": False,
            "needs_model": False,
            "games": [],
            "reason": "BEFORE_V8_FORWARD_EFFECTIVE_DATE",
        }

    for game in games:
        start = _parse_ts(game["first_pitch_at"])
        seconds_to = (start - current).total_seconds()
        if seconds_to <= 0:
            continue
        minutes_to = seconds_to / 60.0
        phases: list[str] = []
        labels: list[str] = []
        if abs(minutes_to - DECISION_TARGET_MIN) <= DECISION_TOLERANCE_MIN:
            phases.append("decision")
            labels.append("T-30")
        for target in CLOSE_TARGETS_MIN:
            if abs(minutes_to - target) <= CLOSE_TOLERANCE_MIN:
                phases.append("close")
                labels.append("T0" if target == 0 else f"T-{int(target)}")
                break
        if not phases:
            continue
        selected.append({
            **dict(game),
            "minutes_to_first_pitch": round(minutes_to, 3),
            "phases": phases,
            "capture_labels": labels,
        })

    return {
        "schema": "MLB_V8_FORWARD_PLAN_V1",
        "planned_at_utc": current.isoformat(),
        "slate_date_ct": slate_ct,
        "effective": True,
        "needs_model": bool(selected),
        "games": selected,
        "decision_target_minutes": DECISION_TARGET_MIN,
        "close_targets_minutes": list(CLOSE_TARGETS_MIN),
    }


def _quote_rows(results: list[dict[str, Any]], game_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in results:
        if str(row.get("game_id")) != str(game_id):
            continue
        price = row.get("american_odds")
        book = row.get("book_key")
        market = row.get("market")
        retrieved = row.get("quote_retrieved_at")
        if price in (None, "") or book in (None, "") or market in (None, "", "UNKNOWN") or retrieved in (None, ""):
            continue
        key = (
            str(book), str(market), str(row.get("entity_id")), str(row.get("side")),
            json.dumps(row.get("line"), sort_keys=True, default=str), str(price), str(retrieved), str(row.get("offer_id")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "book_key": str(book),
            "sportsbook": row.get("sportsbook"),
            "market": str(market),
            "entity_id": str(row.get("entity_id") or ""),
            "side": str(row.get("side") or ""),
            "line": row.get("line"),
            "price": price,
            "retrieved_at": str(retrieved),
            "offer_id": row.get("offer_id"),
            "source_index": row.get("source_index"),
        })
    out.sort(key=lambda r: (r["market"], r["entity_id"], r["book_key"], r["side"], str(r["line"]), str(r["price"])))
    return out


def _decision_rows(results: list[dict[str, Any]], game_id: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in results:
        if str(row.get("game_id")) != str(game_id):
            continue
        if row.get("model_p") is None or not row.get("distribution_sha256") or not row.get("model_input_hash"):
            continue
        out.append({
            "source_index": row.get("source_index"),
            "market": row.get("market"),
            "entity_id": row.get("entity_id"),
            "line": row.get("line"),
            "side": row.get("side"),
            "american_odds": row.get("american_odds"),
            "book_key": row.get("book_key"),
            "quote_retrieved_at": row.get("quote_retrieved_at"),
            "model_p": row.get("model_p"),
            "implied_probability": row.get("implied_probability"),
            "edge": row.get("edge"),
            "ev_per_dollar": row.get("ev_per_dollar"),
            "bet_status": row.get("bet_status"),
            "reason": row.get("block_reason", row.get("reason")),
            "model_input_hash": row.get("model_input_hash"),
            "distribution_sha256": row.get("distribution_sha256"),
            "readout_sha256": row.get("readout_sha256"),
            "readout_version": row.get("readout_version"),
            "engine_version": row.get("engine_version"),
            "seed_policy": row.get("seed_policy"),
            "mc_paths": row.get("mc_paths"),
        })
    out.sort(key=lambda r: (str(r.get("market")), str(r.get("entity_id")), int(r.get("source_index") or 0)))
    return out


def materialize(
    *, plan: dict[str, Any], card_raw: bytes, model_sha: str, run_id: str,
    captured_at: datetime | None = None, root: Path | None = None,
) -> list[Path]:
    card = json.loads(card_raw.decode("utf-8"))
    results = card.get("results")
    if not isinstance(results, list):
        raise RuntimeError("canonical MLB card results missing")
    if not plan.get("needs_model"):
        return []
    current = _parse_ts((captured_at or _now()).isoformat())
    card_sha = _sha(card_raw)
    written: list[Path] = []

    for game in plan.get("games") or []:
        game_id = str(game["game_id"])
        quotes = _quote_rows(results, game_id)
        if not quotes:
            raise RuntimeError(f"V8 target game has no canonical sportsbook quotes:{game_id}")
        first_pitch = _parse_ts(game["first_pitch_at"])
        if current >= first_pitch:
            raise RuntimeError(f"V8 target game passed first pitch before evidence write:{game_id}")
        provenance = {
            "provider": "SPORTSEDGE_CANONICAL_MLB_MACHINE",
            "card_sha256": card_sha,
            "card_generated_at_utc": card.get("generated_at_utc"),
            "machine_mode": card.get("mode"),
            "run_status": card.get("run_status"),
            "runner": "scripts/run_auto_mlb_resilient.py",
            "model_release_identity": "EXACT_GIT_COMMIT_SHA",
            "model_release_sha": model_sha,
            "books": sorted({str(q["book_key"]) for q in quotes}),
        }
        common = {
            "game_id": game_id,
            "first_pitch_at": first_pitch.isoformat(),
            "captured_at": current.isoformat(),
            "quotes": quotes,
            "source_provenance": provenance,
            "capture_labels": list(game.get("capture_labels") or []),
            "slate_date_ct": plan.get("slate_date_ct"),
        }

        for phase in game.get("phases") or []:
            payload = dict(common)
            if phase == "decision":
                decisions = _decision_rows(results, game_id)
                if not decisions:
                    raise RuntimeError(f"V8 decision target has no model/distribution evidence:{game_id}")
                dist_binding = [
                    {
                        "source_index": row.get("source_index"),
                        "market": row.get("market"),
                        "entity_id": row.get("entity_id"),
                        "distribution_sha256": row.get("distribution_sha256"),
                    }
                    for row in decisions
                ]
                payload.update({
                    "run_id": run_id,
                    "model_sha": model_sha,
                    "distribution_sha": _canonical_sha(dist_binding),
                    "decision_rows": decisions,
                })
            destination = persist(payload, phase, root=root or Path("artifacts/mlb_v8_forward"))
            written.append(destination)
    return written


def self_test() -> int:
    import tempfile
    now = datetime(2026, 9, 3, 22, 30, tzinfo=timezone.utc)
    games = [{"game_id": "123", "first_pitch_at": "2026-09-03T23:00:00+00:00", "abstract_game_state": "Preview", "home_team": "Home", "away_team": "Away"}]
    plan = build_plan(now, games)
    assert plan["needs_model"] is True
    assert plan["games"][0]["phases"] == ["decision"]
    card = {
        "mode": "AUTOMATIC", "generated_at_utc": now.isoformat(), "run_status": "PASS",
        "results": [{
            "source_index": 1, "game_id": "123", "market": "MONEYLINE", "entity_id": "home",
            "line": None, "side": "HOME", "american_odds": -120, "model_p": 0.56,
            "implied_probability": 0.545, "edge": 0.015, "ev_per_dollar": 0.02,
            "bet_status": "BLOCKED", "block_reason": "UNVALIDATED", "model_input_hash": "input",
            "distribution_sha256": "d" * 64, "readout_sha256": "r" * 64,
            "readout_version": "v", "engine_version": "v8", "seed_policy": "fixed", "mc_paths": 10000,
            "book_key": "draftkings", "sportsbook": "DraftKings",
            "quote_retrieved_at": "2026-09-03T22:29:40+00:00", "offer_id": "offer-1"
        }]
    }
    raw = (json.dumps(card, sort_keys=True) + "\n").encode()
    with tempfile.TemporaryDirectory() as td:
        paths = materialize(plan=plan, card_raw=raw, model_sha="a" * 40, run_id="run-1", captured_at=datetime(2026, 9, 3, 22, 31, tzinfo=timezone.utc), root=Path(td))
        assert len(paths) == 1 and paths[0].is_file()
    close_plan = build_plan(datetime(2026, 9, 3, 22, 50, tzinfo=timezone.utc), games)
    assert close_plan["games"][0]["phases"] == ["close"]
    print(json.dumps({"status": "SELF_TEST_OK", "decision_window": "PASS", "close_window": "PASS", "canonical_card_binding": "PASS"}))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-output", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--card", type=Path)
    parser.add_argument("--model-sha")
    parser.add_argument("--run-id")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    if args.plan_output:
        now = _now()
        slate = now.astimezone(CT).date().isoformat()
        plan = build_plan(now, fetch_schedule(slate))
        args.plan_output.parent.mkdir(parents=True, exist_ok=True)
        args.plan_output.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        print(json.dumps(plan, sort_keys=True))
        return 0

    if not all((args.plan, args.card, args.model_sha, args.run_id)):
        parser.error("materialization requires --plan --card --model-sha --run-id")
    plan = json.loads(args.plan.read_text())
    written = materialize(
        plan=plan,
        card_raw=args.card.read_bytes(),
        model_sha=str(args.model_sha),
        run_id=str(args.run_id),
    )
    print(json.dumps({"status": "V8_FORWARD_CAPTURE_COMPLETE", "records_written": len(written), "paths": [str(p) for p in written]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
