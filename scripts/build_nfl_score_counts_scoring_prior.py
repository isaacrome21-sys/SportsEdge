#!/usr/bin/env python3
"""Build a hash-bound market-blind NFL scoring-composition prior from frozen sources."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from scripts.run_nfl_score_counts_attempt import (
    code_identity,
    download_exact,
    iter_projected_pbp,
    read_csv,
    sha256_file,
)
from sportsedge.nfl_scoring_composition_artifact import dump_prior
from sportsedge.nfl_scoring_composition_fit import fit_scoring_composition_prior
from sportsedge.sports.nfl.score_counts_scoring_prior import (
    build_scoring_composition_rows,
)
from sportsedge.sports.nfl.score_counts_source_manifest import load_source_contract

CONFIG = Path("config/research/nfl_score_counts_scoring_composition_prior_v1.json")


def _canonical_sha(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(raw).hexdigest()


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SystemExit(f"JSON_OBJECT_REQUIRED:{path}")
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", type=Path, required=True)
    ap.add_argument("--prior-out", type=Path, required=True)
    ap.add_argument("--attestation-out", type=Path, required=True)
    args = ap.parse_args()

    cfg = _load(CONFIG)
    if cfg.get("schema") != "SPORTSEDGE_NFL_SCORE_COUNTS_SCORING_COMPOSITION_PRIOR_BUILD_V1":
        raise SystemExit("NFL_SCORING_PRIOR_BUILD_CONFIG_SCHEMA_INVALID")
    if cfg.get("status") != "FROZEN_BEFORE_PRIOR_BUILD":
        raise SystemExit("NFL_SCORING_PRIOR_BUILD_CONFIG_NOT_FROZEN")
    if any(bool(v) for v in (cfg.get("authority") or {}).values()):
        raise SystemExit("NFL_SCORING_PRIOR_BUILD_AUTHORITY_ESCALATION")
    rules = cfg.get("rules") or {}
    required_true = (
        "frozen_source_bytes_only",
        "expected_sha256_must_match",
        "score_must_reconstruct_from_pbp_components",
        "reconstructed_score_must_match_frozen_schedule",
        "market_inputs_prohibited",
        "source_substitution_forbidden",
        "post_build_retuning_prohibited",
    )
    if not all(rules.get(key) is True for key in required_true):
        raise SystemExit("NFL_SCORING_PRIOR_BUILD_RULE_DRIFT")
    if rules.get("prior_build_consumes_score_count_attempt") is not False:
        raise SystemExit("NFL_SCORING_PRIOR_BUILD_ATTEMPT_AUTHORITY_INVALID")

    source_contract_path = Path(cfg["source_contract_path"])
    observed_blob = subprocess.check_output(
        ["git", "rev-parse", f"HEAD:{source_contract_path.as_posix()}"],
        text=True,
    ).strip()
    if observed_blob != str(cfg["source_contract_git_blob"]):
        raise SystemExit(
            f"NFL_SCORING_PRIOR_SOURCE_CONTRACT_BLOB_DRIFT:{observed_blob}:"
            f"{cfg['source_contract_git_blob']}"
        )

    contract = load_source_contract()
    seasons = tuple(int(v) for v in cfg["seasons"])
    root = args.source_root
    root.mkdir(parents=True, exist_ok=True)

    schedule_spec = contract["schedule"]
    schedule_path = root / "games.csv"
    download_exact(
        schedule_spec["fetch_uri"],
        schedule_path,
        schedule_spec["expected_sha256"],
    )
    source_bytes = [{
        "name": "schedule",
        "expected_sha256": schedule_spec["expected_sha256"],
        "actual_sha256": sha256_file(schedule_path),
    }]

    pbp_paths: list[Path] = []
    for season in seasons:
        spec = contract["pbp"][str(season)]
        path = root / f"play_by_play_{season}.csv.gz"
        download_exact(spec["fetch_uri"], path, spec["expected_sha256"])
        pbp_paths.append(path)
        source_bytes.append({
            "name": f"pbp_{season}",
            "expected_sha256": spec["expected_sha256"],
            "actual_sha256": sha256_file(path),
        })

    excluded = [
        str(row["game_id"])
        for row in cfg.get("excluded_games") or []
        if isinstance(row, dict) and str(row.get("game_id") or "").strip()
    ]
    rows = build_scoring_composition_rows(
        schedule_rows=read_csv(schedule_path),
        pbp_rows=iter_projected_pbp(pbp_paths),
        seasons=seasons,
        conservative_completion_lag_hours=int(cfg["conservative_completion_lag_hours"]),
        excluded_game_ids=excluded,
    )
    prior = fit_scoring_composition_prior(rows, as_of=cfg["as_of"])
    payload = dump_prior(prior)

    args.prior_out.parent.mkdir(parents=True, exist_ok=True)
    args.prior_out.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    attestation = {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_SCORING_COMPOSITION_PRIOR_ATTESTATION_V1",
        "status": "BUILT_FROM_FROZEN_MARKET_BLIND_SOURCE",
        "as_of": prior.as_of,
        "training_rows": int(prior.training_rows),
        "training_rows_sha256": _canonical_sha(rows),
        "prior_artifact_sha256": payload["artifact_sha256"],
        "source_contract_path": cfg["source_contract_path"],
        "source_contract_sha256": sha256_file(Path(cfg["source_contract_path"])),
        "source_contract_git_blob": cfg["source_contract_git_blob"],
        "score_count_code_identity": code_identity(),
        "source_bytes": source_bytes,
        "excluded_games": list(cfg.get("excluded_games") or []),
        "market_inputs_used": False,
        "score_count_attempt_consumed": False,
        "authority": {
            "model_p": False,
            "truth_gate": False,
            "promotion": False,
            "staking": False,
            "official": False,
            "validation_attempt": False,
            "score_count_attempt": False,
            "backfill": False,
        },
    }
    args.attestation_out.parent.mkdir(parents=True, exist_ok=True)
    args.attestation_out.write_text(
        json.dumps(attestation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": attestation["status"],
        "training_rows": prior.training_rows,
        "prior_artifact_sha256": payload["artifact_sha256"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
