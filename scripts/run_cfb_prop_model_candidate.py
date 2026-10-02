#!/usr/bin/env python3
"""Run frozen CFB shared-path prop simulation as a research-only candidate lane.

This entrypoint deliberately bypasses bettor-facing engine authority. It can emit
research MODEL_CANDIDATE probabilities only after the frozen artifact, frozen
predictive code surface, fresh PIT live features, and a pregame odds snapshot all
validate. These are research candidate probabilities, not production Model_P authority. It has no evidence/certification/floor promotion path and forcibly
blocks every betting decision.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from math import isfinite
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.football_prop_odds_source import build_odds_snapshot, fetch_event_prop_odds
from sportsedge.football_prop_run_machine import FootballPropRunError
from sportsedge.football_prop_extended_run_machine import (
    OFFENSIVE_OU_MARKETS,
    SCORER_MARKETS,
    run_football_extended_props,
)
from sportsedge.sports.cfb.prop_bundle import CFBPropBundleError, load_cfb_prop_artifact_bundle
from sportsedge.sports.nfl.prop_code_surface import (
    CFBPropCodeSurfaceError,
    verify_cfb_prop_code_surface,
)

DEFAULT_FREEZE = ROOT / "config/cfb_prop_model_freeze.json"
DEFAULT_BUNDLE = ROOT / "artifacts/football/cfb_prop_artifact_bundle_v1.json"
DEFAULT_FEATURES = ROOT / "artifacts/football/cfb_prop_live_features.json"
DEFAULT_ODDS = ROOT / "artifacts/football/cfb_prop_odds_snapshot.json"
DEFAULT_OUTPUT = ROOT / "artifacts/run_it/cfb_prop_model_candidate.json"
CFB_PROXY_PROVIDER_MARKETS = tuple(sorted(set(OFFENSIVE_OU_MARKETS) | set(SCORER_MARKETS)))


class CFBPropCandidateError(ValueError):
    pass


def _json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise CFBPropCandidateError(code) from exc
    if not isinstance(value, dict):
        raise CFBPropCandidateError(code)
    return value


def _utc(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    text = value.strip().replace("Z", "+00:00")
    try:
        out = datetime.fromisoformat(text)
    except ValueError as exc:
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ASOF_INVALID") from exc
    if out.tzinfo is None or out.utcoffset() is None:
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ASOF_TIMEZONE_REQUIRED")
    return out.astimezone(timezone.utc)


def _load_frozen_model(freeze_path: Path, bundle_path: Path) -> tuple[dict, str, dict]:
    registry = _json(freeze_path, "CFB_PROP_CANDIDATE_FREEZE_REGISTRY_INVALID")
    if registry.get("sport") != "CFB" or registry.get("status") != "FROZEN":
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_FROZEN_MODEL_REQUIRED")
    if registry.get("promotion_authority") is not False:
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_PROMOTION_AUTHORITY_INVALID")
    expected_sha = str(registry.get("artifact_sha256") or "").strip().lower()
    if len(expected_sha) != 64 or any(ch not in "0123456789abcdef" for ch in expected_sha):
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ARTIFACT_SHA_INVALID")
    declared = (ROOT / str(registry.get("artifact_path") or "")).resolve()
    if freeze_path.resolve() == DEFAULT_FREEZE.resolve() and declared != bundle_path.resolve():
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ARTIFACT_BINDING_INVALID")
    artifact = load_cfb_prop_artifact_bundle(root=ROOT, bundle_path=bundle_path)
    fit_sha = str(artifact.get("code_git_sha") or "").strip().lower()
    if fit_sha != str(registry.get("code_git_sha") or "").strip().lower():
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_CODE_SHA_MISMATCH")
    attestation = verify_cfb_prop_code_surface(
        root=ROOT, registry=registry, artifact=artifact
    )
    return artifact, expected_sha, attestation



def _odds_keys() -> list[str]:
    keys = [
        str(os.environ.get(name) or "").strip()
        for name in (
            "SPORTSEDGE_ODDS_API_KEY",
            "SPORTSEDGE_ODDS_API_KEY_2",
            "SPORTSEDGE_ODDS_API_KEY_3",
            "SPORTSEDGE_ODDS_API_KEY_4",
            "ODDS_API_KEY",
        )
    ]
    keys = [key for key in keys if key]
    if not keys:
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ODDS_API_KEY_REQUIRED")
    return keys


def _network_odds(
    *, live: dict, current: datetime, markets: tuple[str, ...] | None = None
) -> dict:
    games = live.get("games")
    if not isinstance(games, list) or not games:
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_LIVE_GAMES_REQUIRED")
    keys = _odds_keys()
    events: list[dict] = []
    seen: set[str] = set()
    for game in games:
        if not isinstance(game, dict):
            raise CFBPropCandidateError("CFB_PROP_CANDIDATE_LIVE_GAME_INVALID")
        event_id = str(game.get("provider_event_id") or "").strip()
        if not event_id:
            raise CFBPropCandidateError("CFB_PROP_CANDIDATE_PROVIDER_EVENT_ID_REQUIRED")
        if event_id in seen:
            continue
        seen.add(event_id)
        fetched = fetch_event_prop_odds(
            keys, sport="CFB", event_id=event_id, markets=markets
        )
        if not isinstance(fetched.value, dict):
            raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ODDS_PROVIDER_PAYLOAD_INVALID")
        events.append(dict(fetched.value))
    return build_odds_snapshot(events, observed_at=current)

def _norm_player_name(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _proxy_event_player_names(live: dict) -> dict[str, set[str]]:
    games = live.get("games")
    if not isinstance(games, list):
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_LIVE_GAMES_REQUIRED")
    out: dict[str, set[str]] = {}
    for game in games:
        if not isinstance(game, dict):
            raise CFBPropCandidateError("CFB_PROP_CANDIDATE_LIVE_GAME_INVALID")
        event_id = str(game.get("provider_event_id") or "").strip()
        if not event_id:
            raise CFBPropCandidateError("CFB_PROP_CANDIDATE_PROVIDER_EVENT_ID_REQUIRED")
        names: set[str] = set()
        for usage_field in ("home_usage", "away_usage"):
            usage = game.get(usage_field)
            if not isinstance(usage, dict):
                continue
            players = usage.get("players")
            if not isinstance(players, list):
                continue
            for player in players:
                if not isinstance(player, dict):
                    continue
                key = _norm_player_name(player.get("player_name"))
                if key:
                    names.add(key)
        if not names:
            raise CFBPropCandidateError(
                f"CFB_PROP_CANDIDATE_PROXY_PLAYER_NAMES_EMPTY:{event_id}"
            )
        prior = out.get(event_id)
        if prior is not None and prior != names:
            raise CFBPropCandidateError(
                f"CFB_PROP_CANDIDATE_PROXY_EVENT_DUPLICATE_CONFLICT:{event_id}"
            )
        out[event_id] = names
    return out


def _filter_proxy_odds_by_live_identity(
    odds: dict, *, live: dict
) -> tuple[dict, list[dict]]:
    """Fail closed per unmatched sportsbook player before the frozen engine."""
    filtered = deepcopy(odds)
    allowed_by_event = _proxy_event_player_names(live)
    blocks: list[dict] = []
    events = filtered.get("events")
    if not isinstance(events, list):
        raise CFBPropCandidateError("CFB_PROP_CANDIDATE_ODDS_EVENTS_REQUIRED")
    supported = set(CFB_PROXY_PROVIDER_MARKETS)
    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = str(event.get("id") or "").strip()
        allowed = allowed_by_event.get(event_id)
        if allowed is None:
            continue
        books = event.get("bookmakers")
        if not isinstance(books, list):
            continue
        for book in books:
            if not isinstance(book, dict):
                continue
            markets = book.get("markets")
            if not isinstance(markets, list):
                continue
            for market in markets:
                if not isinstance(market, dict):
                    continue
                provider_market = str(market.get("key") or "").strip()
                if provider_market not in supported:
                    continue
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list):
                    continue
                kept = []
                for outcome in outcomes:
                    if not isinstance(outcome, dict):
                        kept.append(outcome)
                        continue
                    player_name = str(outcome.get("description") or "").strip()
                    if _norm_player_name(player_name) in allowed:
                        kept.append(outcome)
                        continue
                    blocks.append({
                        "sport": "CFB",
                        "provider_event_id": event_id,
                        "bookmaker": str(book.get("key") or "").strip() or None,
                        "provider_market": provider_market,
                        "player_name": player_name or None,
                        "side": str(outcome.get("name") or "").strip() or None,
                        "line": outcome.get("point"),
                        "american_odds": outcome.get("price"),
                        "model_p": None,
                        "bet_status": "BLOCKED",
                        "official_eligible": False,
                        "reason": (
                            "FOOTBALL_PROP_PLAYER_NAME_UNRESOLVED:"
                            + (player_name or "MISSING")
                        ),
                    })
                market["outcomes"] = kept
    return filtered, blocks


def _candidateize(report: dict, *, proxy_usage: bool = False) -> dict:
    candidate_rows = 0
    stale_rows = 0
    for row in report.get("results", []):
        if not isinstance(row, dict):
            continue
        model_p = row.get("model_p")
        genuine = (
            isinstance(model_p, (int, float)) and not isinstance(model_p, bool)
            and isfinite(float(model_p)) and 0.0 <= float(model_p) <= 1.0
        )
        row["official_eligible"] = False
        row["bet_status"] = "BLOCKED"
        row["promotion_authority"] = False
        one_sided = row.get("market_no_vig_p_status") == "UNAVAILABLE_ONE_SIDED"
        market_comparable = row.get("fair_market_p") is not None or one_sided
        if genuine and market_comparable and row.get("ev_per_dollar") is not None:
            row["decision_tier"] = "MODEL_CANDIDATE"
            row["presentation_label"] = "LEAN"
            row["model_candidate_status"] = "READY"
            row["usage_input_class"] = "RESEARCH_PROXY" if proxy_usage else "OBSERVED_USAGE_INPUT"
            row["reason"] = (
                "CFB_PROP_RESEARCH_PROXY_USAGE_INDEPENDENT_VALIDATION_REQUIRED"
                if proxy_usage
                else "CFB_PROP_RESEARCH_ONLY_INDEPENDENT_VALIDATION_REQUIRED"
            )
            candidate_rows += 1
        else:
            row["decision_tier"] = "NO_ACTIONABLE_CANDIDATE"
            row["presentation_label"] = "NO_PLAY"
            row["usage_input_class"] = "RESEARCH_PROXY" if proxy_usage else "OBSERVED_USAGE_INPUT"
            row["model_candidate_status"] = "BLOCKED"
            if "STALE" in str(row.get("reason") or ""):
                stale_rows += 1
    report["run_status"] = (
        "MODEL_CANDIDATES_AVAILABLE_OFFICIAL_BLOCKED"
        if candidate_rows else "BLOCKED_NO_FRESH_MODEL_CANDIDATES"
    )
    report.setdefault("summary", {})["model_candidate_rows"] = candidate_rows
    report["summary"]["official_bets"] = 0
    report["summary"]["stale_rows"] = stale_rows
    report["governance"] = {
        **dict(report.get("governance") or {}),
        "research_only": True,
        "promotion_authority": False,
        "official_bets_allowed": False,
        "independent_validation_required": True,
        "engine_surface_changed": False,
        "truth_gate_changed": False,
        "evidence_registry_consumed": False,
        "certification_registry_consumed": False,
        "frozen_edge_floor_can_promote": False,
        "research_proxy_usage": bool(proxy_usage),
        "production_eligible": False,
    }
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-registry", type=Path, default=DEFAULT_FREEZE)
    ap.add_argument("--model-artifact", type=Path, default=DEFAULT_BUNDLE)
    ap.add_argument("--live-features", type=Path, default=DEFAULT_FEATURES)
    ap.add_argument("--odds-snapshot", type=Path, default=DEFAULT_ODDS)
    ap.add_argument("--bookmaker", default="draftkings")
    ap.add_argument("--n-paths", type=int, default=20000)
    ap.add_argument("--root-seed", type=int, default=20260909)
    ap.add_argument("--asof")
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    current = _utc(args.asof)
    try:
        artifact, artifact_sha, attestation = _load_frozen_model(
            args.freeze_registry, args.model_artifact
        )
        live = _json(args.live_features, "CFB_PROP_CANDIDATE_LIVE_FEATURES_REQUIRED")
        live_governance = live.get("governance") if isinstance(live.get("governance"), dict) else {}
        proxy_usage = live_governance.get("research_proxy_usage") is True
        if proxy_usage and live.get("schema_version") != "CFB_PROP_RESEARCH_PROXY_LIVE_FEATURES_V1":
            raise CFBPropCandidateError("CFB_PROP_PROXY_USAGE_SCHEMA_INVALID")
        odds = (
            _json(args.odds_snapshot, "CFB_PROP_CANDIDATE_ODDS_SNAPSHOT_REQUIRED")
            if args.odds_snapshot.is_file()
            else _network_odds(
                live=live,
                current=current,
                markets=CFB_PROXY_PROVIDER_MARKETS if proxy_usage else None,
            )
        )
        identity_blocks: list[dict] = []
        if proxy_usage:
            odds, identity_blocks = _filter_proxy_odds_by_live_identity(
                odds, live=live
            )
        report = run_football_extended_props(
            sport="CFB",
            now=current,
            artifact_payload=artifact,
            expected_artifact_sha256=artifact_sha,
            runtime_code_git_sha=str(artifact["code_git_sha"]),
            live_features=live,
            odds_snapshot=odds,
            root_seed=int(args.root_seed),
            n_paths=int(args.n_paths),
            book_key=str(args.bookmaker),
        )
        report = _candidateize(report, proxy_usage=proxy_usage)
        report["identity_blocks"] = identity_blocks
        report.setdefault("summary", {})["identity_blocks"] = len(identity_blocks)
        payload = {
            "schema_version": "CFB_PROP_MODEL_CANDIDATE_RUN_V1",
            "status": "SUCCESS" if report["summary"]["model_candidate_rows"] else "BLOCKED",
            "sport": "CFB",
            "report": report,
            "model_code_attestation": attestation,
            "governance": {
                "research_only": True,
                "promotion_authority": False,
                "official_bets_allowed": False,
                "bettor_facing_engine_surface_unchanged": True,
                "market_prices_can_create_model_p": False,
                "usage_can_be_synthesized": False,
                "network_odds_allowed_only_after_live_features": True,
                "research_proxy_usage": bool(proxy_usage),
                "research_proxy_provider_markets": (
                    list(CFB_PROXY_PROVIDER_MARKETS) if proxy_usage else None
                ),
                "unresolved_provider_player_rows_fail_closed_before_frozen_engine": bool(proxy_usage),
                "production_eligible": False,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({
            "status": payload["status"],
            "model_candidate_rows": report["summary"]["model_candidate_rows"],
            "official_bets": 0,
            "output": str(args.output),
        }, sort_keys=True))
        return 0 if payload["status"] == "SUCCESS" else 2
    except (
        CFBPropCandidateError, CFBPropBundleError, CFBPropCodeSurfaceError,
        FootballPropRunError, ValueError,
    ) as exc:
        payload = {
            "schema_version": "CFB_PROP_MODEL_CANDIDATE_RUN_V1",
            "status": "BLOCKED",
            "sport": "CFB",
            "blocker": str(exc),
            "generated_at_utc": current.isoformat(),
            "report": {
                "run_status": "BLOCKED",
                "results": [{
                    "sport": "CFB", "market": "CFB_PLAYER_PROPS",
                    "model_p": None, "bet_status": "BLOCKED",
                    "official_eligible": False, "reason": str(exc),
                }],
                "summary": {"model_candidate_rows": 0, "official_bets": 0},
            },
            "governance": {
                "research_only": True,
                "promotion_authority": False,
                "official_bets_allowed": False,
                "bettor_facing_engine_surface_unchanged": True,
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(json.dumps({"status": "BLOCKED", "blocker": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
