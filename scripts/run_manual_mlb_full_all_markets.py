from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from sportsedge.canonical_manual_mlb import (
    PLAYER_MARKETS,
    _engine_market,
    _resolve_game,
    _resolve_subject,
    run_canonical_manual_mlb,
)
from sportsedge.generic_card_pipeline import run_generic_card
from sportsedge.live_slate import LiveGame, TeamLineup
from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_empirical_support import support_evidence
from sportsedge.mlb_history_cache import MLBHistoryCachedOpener
from sportsedge.mlb_myspari_own_model import myspari_rows
from sportsedge.runtime import parse_timestamp


def _stub(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        game_id=str(raw["game_id"]),
        first_pitch_at=parse_timestamp(raw["first_pitch_at"]),
        observed_at=parse_timestamp(raw["observed_at"]),
        subject_name=raw.get("subject_name"),
        subject_id=raw.get("subject_id"),
    )


def _quote(raw: dict, *, game_pk: int, market: str, entity_id: str) -> dict:
    return {
        "game_id": str(game_pk),
        "period": "FG",
        "market": market,
        "entity_id": str(entity_id),
        "line": float(raw["line"]),
        "side": str(raw["side"]).upper(),
        "american_odds": int(raw["price"]),
        "book_key": str(raw.get("book") or "draftkings").lower(),
        "is_alternate": True,
        "raw_market_name": str(raw["market_type"]),
        "retrieved_at": str(raw["observed_at"]),
        "ttl_seconds": 3600,
        "sportsbook": "DraftKings",
        "selection": f"{raw.get('subject_name') or ''} {raw['side']} {raw['line']}",
        "source_url": "MANUAL_SCREENSHOT",
        "source": "MANUAL",
    }


def run_one_sided(rows: list[dict], *, history_cache_dir: str | Path | None = None) -> tuple[list[dict], list[dict], dict[str, str]]:
    results: list[dict] = []
    games_meta: list[dict] = []
    names: dict[str, str] = {}

    by_game: dict[str, list[dict]] = {}
    for raw in rows:
        by_game.setdefault(str(raw["game_id"]), []).append(raw)

    for input_game_id, game_rows in by_game.items():
        stubs = [_stub(r) for r in game_rows]
        anchor = max(stubs, key=lambda r: r.observed_at)
        g = _resolve_game(anchor)
        captured = max(s.observed_at for s in stubs).astimezone(timezone.utc)
        target_date = datetime.fromisoformat(str(g.official_date)).date() if g.official_date else captured.date()

        subject_cache: dict[tuple[str | None, str | None], tuple[str | None, int | None]] = {}
        resolved: list[tuple[str | None, int | None, str | None]] = []
        for raw, stub in zip(game_rows, stubs):
            key = (stub.subject_name, stub.subject_id)
            try:
                if key not in subject_cache:
                    subject_cache[key] = _resolve_subject(stub)
                pid, tid = subject_cache[key]
                if pid and tid is not None and tid not in {g.away_id, g.home_id}:
                    raise ValueError(f"MANUAL_SUBJECT_TEAM_NOT_IN_GAME:{stub.subject_name or pid}")
                if pid and stub.subject_name:
                    names[str(pid)] = str(stub.subject_name)
                resolved.append((pid, tid, None))
            except Exception as exc:
                resolved.append((None, None, f"{type(exc).__name__}:{exc}"))

        away_players = tuple(sorted({
            int(pid) for (pid, tid, err), raw in zip(resolved, game_rows)
            if not err and pid and tid == g.away_id and not str(raw["market_type"]).upper().startswith("PITCHER_")
        }))
        home_players = tuple(sorted({
            int(pid) for (pid, tid, err), raw in zip(resolved, game_rows)
            if not err and pid and tid == g.home_id and not str(raw["market_type"]).upper().startswith("PITCHER_")
        }))
        live = LiveGame(
            g.game_pk, g.away_id, g.home_id, g.away_probable_pitcher_id, g.home_probable_pitcher_id,
            TeamLineup(g.away_id, "away", away_players, (), False),
            TeamLineup(g.home_id, "home", home_players, (), False),
            g.game_number, g.double_header, g.venue_id, g.official_date, g.status,
        )
        hist = MLBAllMarketHistorySource(
            opener=MLBHistoryCachedOpener(target_date=captured.date(), cache_dir=history_cache_dir),
            retrieved_at=captured,
        )

        features: list[dict] = []
        quotes: list[dict] = []
        blocked: list[dict] = []
        seen_features: set[tuple[str, str]] = set()
        feature_by_key: dict[tuple[str, str], dict] = {}

        for raw, (pid, tid, err) in zip(game_rows, resolved):
            market = _engine_market(SimpleNamespace(market_type=str(raw["market_type"]), line=float(raw["line"])))
            if err or not pid:
                blocked.append({
                    "game_id": str(g.game_pk), "market": market,
                    "entity_id": str(raw.get("subject_name") or "UNRESOLVED"),
                    "line": float(raw["line"]), "side": str(raw["side"]).upper(),
                    "american_odds": int(raw["price"]), "model_p": None,
                    "bet_status": "BLOCKED", "reason": err or "SUBJECT_UNRESOLVED",
                    "book_key": str(raw.get("book") or "draftkings").lower(),
                    "sportsbook": "DraftKings", "quote_retrieved_at": str(raw["observed_at"]),
                })
                continue
            entity_id = str(pid)
            key = (market, entity_id)
            if key not in seen_features:
                seen_features.add(key)
                feat = hist.feature_row(
                    game_pk=g.game_pk, market=market, entity_id=entity_id, target_date=target_date,
                    away_team_id=int(g.away_id), home_team_id=int(g.home_id),
                    player_id=int(pid), team_id=tid,
                    away_pitcher_id=g.away_probable_pitcher_id, home_pitcher_id=g.home_probable_pitcher_id,
                )
                features.append(feat)
                feature_by_key[key] = feat
            quotes.append(_quote(raw, game_pk=g.game_pk, market=market, entity_id=entity_id))

        priced = run_generic_card(
            games=[live], feature_rows=features, quotes=quotes,
            ingestion_now=captured, finalization_now=captured,
            require_confirmed_lineup=False,
        )
        for r in priced:
            row = asdict(r)
            feat = feature_by_key.get((str(row["market"]), str(row["entity_id"])), {})
            evidence = support_evidence(feat, row)
            if evidence is not None:
                row["empirical_evidence"] = evidence
            results.append(row)
        results.extend(blocked)
        games_meta.append({
            "input_game_id": input_game_id,
            "resolved_game": {
                "game_pk": int(g.game_pk), "away_team": g.away_name, "home_team": g.home_name,
                "scheduled_start_utc": g.game_date,
            },
            "observed_at_utc": captured.isoformat(),
        })

    return results, games_meta, names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--output", required=True)
    ap.add_argument("--history-cache-dir", default=".cache/mlb-history")
    args = ap.parse_args()

    payload = json.loads(Path(args.input).read_text())
    paired_rows = list(payload.get("paired_rows") or [])
    one_rows = list(payload.get("one_sided_rows") or [])

    combined_results: list[dict] = []
    games_meta: list[dict] = []
    names: dict[str, str] = {}

    by_game: dict[str, list[dict]] = {}
    for row in paired_rows:
        by_game.setdefault(str(row["game_id"]), []).append(row)
    for game_id, rows in by_game.items():
        out = run_canonical_manual_mlb(rows, history_cache_dir=args.history_cache_dir)
        combined_results.extend(out.get("results") or [])
        games_meta.append({
            "input_game_id": game_id,
            "resolved_game": out.get("resolved_game"),
            "observed_at_utc": out.get("observed_at_utc"),
        })
        for mr in out.get("market_resolution") or []:
            if mr.get("subject_id") and mr.get("subject_name"):
                names[str(mr["subject_id"])] = str(mr["subject_name"])

    one_results, one_games, one_names = run_one_sided(one_rows, history_cache_dir=args.history_cache_dir)
    combined_results.extend(one_results)
    names.update(one_names)

    # Deduplicate game metadata by resolved game id, preferring paired-run metadata.
    seen_games: set[str] = set()
    merged_games: list[dict] = []
    for g in games_meta + one_games:
        rg = g.get("resolved_game") or {}
        key = str(rg.get("game_pk") or g.get("input_game_id"))
        if key in seen_games:
            continue
        seen_games.add(key)
        merged_games.append(g)

    observed_times = [parse_timestamp(r["observed_at"]) for r in paired_rows + one_rows]
    max_age = max(0.0, (datetime.now(timezone.utc) - max(observed_times).astimezone(timezone.utc)).total_seconds()) if observed_times else 0.0
    engine_payload = {
        "schema_version": 3,
        "run_type": "MANUAL_FULL_ALL_MARKETS",
        "source": "MANUAL_SCREENSHOTS",
        "games": merged_games,
        "results": combined_results,
        "names": names,
        "input_counts": {"paired_rows": len(paired_rows), "one_sided_rows": len(one_rows)},
    }
    scored = myspari_rows(engine_payload, quote_age_seconds=max_age, names=names)
    engine_payload["scored_rows"] = scored
    engine_payload["quote_age_seconds_at_build"] = max_age
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(engine_payload, indent=2, sort_keys=True))
    print(json.dumps({
        "output": args.output,
        "results": len(combined_results),
        "scored_rows": len(scored),
        "actionable": sum(1 for r in scored if r.get("status") == "ACTIONABLE"),
        "blocked": sum(1 for r in scored if r.get("status") in {"BLOCKED", "NO_MODEL"}),
        "input_counts": engine_payload["input_counts"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
