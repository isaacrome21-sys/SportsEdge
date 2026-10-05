#!/usr/bin/env python3
"""Create a PIT-safe NFL_SCORE_COUNTS_G1 forward prediction artifact.

Historical 2018-2025 PBP/depth bytes come from the immutable development source
contract. Current schedule, 2026 PBP and 2026 depth bytes are snapshotted at run
time, SHA-bound, projected to market-blind fields, and persisted in a forward
source manifest. No sportsbook quotes are accepted by this runner.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import gzip
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sportsedge.sports.nfl.score_counts_artifact import build_forward_prediction
from sportsedge.sports.nfl.score_counts_features import build_score_count_forward_rows
from sportsedge.sports.nfl.score_counts_forward_source import (
    build_forward_source_manifest,
    project_depth_rows,
    project_schedule_rows,
    select_forward_targets,
)
from sportsedge.sports.nfl.score_counts_source_manifest import load_source_contract
from sportsedge.sports.nfl.score_counts_source_projection import project_pbp_row

CURRENT_SCHEDULE_URL = (
    "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
)
CURRENT_PBP_2026_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "pbp/play_by_play_2026.csv.gz"
)
CURRENT_DEPTH_2026_URL = (
    "https://github.com/nflverse/nflverse-data/releases/download/"
    "depth_charts/depth_charts_2026.csv"
)
COMPAT_PATH = Path(
    "config/research/nfl_score_counts_forward_serving_compat_v1.json"
)
SERVING_IDENTITY_PATHS = (
    "config/research/nfl_score_counts_forward_serving_compat_v1.json",
    "config/research/nfl_score_counts_direct_td_paths_v1.json",
    "sportsedge/sports/nfl/score_counts_source_projection.py",
    "sportsedge/sports/nfl/score_counts_features.py",
    "sportsedge/sports/nfl/m2_history_features.py",
    "sportsedge/sports/nfl/score_counts_g1.py",
    "sportsedge/sports/nfl/score_counts_artifact.py",
    "sportsedge/sports/nfl/score_counts_forward_source.py",
    "scripts/run_nfl_score_counts_forward.py",
)


def _sha_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    h = sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _serving_code_identity(root: Path = Path(".")) -> str:
    entries = {}
    for rel in SERVING_IDENTITY_PATHS:
        path = root / rel
        if not path.is_file():
            raise RuntimeError(f"SERVING_IDENTITY_PATH_MISSING:{rel}")
        entries[rel] = _sha_file(path)
    payload = json.dumps(
        entries, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(payload).hexdigest()


def _download(
    uri: str,
    target: Path,
    *,
    expected_sha256: str | None = None,
    retries: int = 4,
) -> tuple[str, str]:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".partial")
    tmp.unlink(missing_ok=True)
    last = None
    retrieved_at = None
    for attempt in range(retries):
        try:
            req = Request(
                uri,
                headers={
                    "User-Agent": "SportsEdge-score-count-forward/1",
                    "Accept": "*/*",
                },
            )
            with urlopen(req, timeout=120) as response, tmp.open("wb") as out:
                shutil.copyfileobj(response, out, length=1024 * 1024)
            retrieved_at = datetime.now(timezone.utc).isoformat()
            got = _sha_file(tmp)
            if expected_sha256 is not None and got != expected_sha256:
                raise RuntimeError(
                    f"SHA256_MISMATCH:{target.name}:"
                    f"expected={expected_sha256}:got={got}"
                )
            tmp.replace(target)
            return got, retrieved_at
        except (HTTPError, URLError, TimeoutError, OSError, RuntimeError) as exc:
            last = exc
            tmp.unlink(missing_ok=True)
            if attempt + 1 < retries:
                time.sleep(2)
    raise RuntimeError(f"DOWNLOAD_FAILED:{uri}:{last}")


def _read_csv(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8-sig", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _iter_projected_pbp(paths: list[Path]):
    for path in paths:
        with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as f:
            for raw in csv.DictReader(f):
                yield project_pbp_row(raw)


def _receipt(
    *,
    name: str,
    uri: str,
    retrieved_at: str,
    byte_sha256: str,
    season_scope: list[int],
    expected_sha256: str | None = None,
) -> dict:
    return {
        "name": name,
        "source_uri": uri,
        "retrieved_at_utc": retrieved_at,
        "byte_sha256": byte_sha256,
        "immutable_expected_sha256": expected_sha256,
        "season_scope": season_scope,
    }


def run(
    *,
    fit_path: Path,
    output_dir: Path,
    horizon_days: int,
    explicit_game_ids: list[str],
) -> dict:
    fit_artifact = json.loads(fit_path.read_text(encoding="utf-8"))
    if (
        fit_artifact.get("status") != "DEVELOPMENT_ATTEMPT_PASS"
        or not bool((fit_artifact.get("development_gate") or {}).get("pass"))
    ):
        raise RuntimeError("FORWARD_REQUIRES_PASSED_DEVELOPMENT_ARTIFACT")

    output_dir.mkdir(parents=True, exist_ok=True)
    serving_code = _serving_code_identity()
    compat_sha = _sha_file(COMPAT_PATH)
    contract = load_source_contract()

    receipts: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="nfl-score-count-forward-") as tmp_raw:
        raw_root = Path(tmp_raw)

        schedule_path = raw_root / "games.csv"
        schedule_sha, schedule_at = _download(
            CURRENT_SCHEDULE_URL, schedule_path
        )
        receipts.append(_receipt(
            name="schedule_current",
            uri=CURRENT_SCHEDULE_URL,
            retrieved_at=schedule_at,
            byte_sha256=schedule_sha,
            season_scope=list(range(2018, 2027)),
        ))
        schedule_rows = project_schedule_rows(_read_csv(schedule_path))

        pbp_paths: list[Path] = []
        depth_rows: list[dict] = []
        for season in range(2018, 2026):
            pbp_spec = contract["pbp"][str(season)]
            pbp_path = raw_root / "pbp" / f"play_by_play_{season}.csv.gz"
            pbp_sha, pbp_at = _download(
                pbp_spec["fetch_uri"],
                pbp_path,
                expected_sha256=pbp_spec["expected_sha256"],
            )
            pbp_paths.append(pbp_path)
            receipts.append(_receipt(
                name=f"pbp_{season}_frozen",
                uri=pbp_spec["fetch_uri"],
                retrieved_at=pbp_at,
                byte_sha256=pbp_sha,
                expected_sha256=pbp_spec["expected_sha256"],
                season_scope=[season],
            ))

            depth_spec = contract["depth"][str(season)]
            depth_path = raw_root / "depth" / f"depth_{season}.csv"
            depth_sha, depth_at = _download(
                depth_spec["fetch_uri"],
                depth_path,
                expected_sha256=depth_spec["expected_sha256"],
            )
            depth_rows.extend(project_depth_rows(_read_csv(depth_path)))
            receipts.append(_receipt(
                name=f"depth_{season}_frozen",
                uri=depth_spec["fetch_uri"],
                retrieved_at=depth_at,
                byte_sha256=depth_sha,
                expected_sha256=depth_spec["expected_sha256"],
                season_scope=[season],
            ))

        current_pbp_path = raw_root / "pbp" / "play_by_play_2026.csv.gz"
        current_pbp_sha, current_pbp_at = _download(
            CURRENT_PBP_2026_URL, current_pbp_path
        )
        pbp_paths.append(current_pbp_path)
        receipts.append(_receipt(
            name="pbp_2026_snapshot",
            uri=CURRENT_PBP_2026_URL,
            retrieved_at=current_pbp_at,
            byte_sha256=current_pbp_sha,
            season_scope=[2026],
        ))

        current_depth_path = raw_root / "depth" / "depth_2026.csv"
        current_depth_sha, current_depth_at = _download(
            CURRENT_DEPTH_2026_URL, current_depth_path
        )
        depth_rows.extend(project_depth_rows(_read_csv(current_depth_path)))
        receipts.append(_receipt(
            name="depth_2026_snapshot",
            uri=CURRENT_DEPTH_2026_URL,
            retrieved_at=current_depth_at,
            byte_sha256=current_depth_sha,
            season_scope=[2026],
        ))

        prediction_at = datetime.now(timezone.utc)
        target_ids = select_forward_targets(
            schedule_rows,
            as_of=prediction_at,
            horizon_days=int(horizon_days),
            season=2026,
            minimum_week=5,
            explicit_game_ids=explicit_game_ids,
        )
        if not target_ids:
            raise RuntimeError("NO_ELIGIBLE_FORWARD_TARGETS")

        forward_rows = build_score_count_forward_rows(
            schedule_rows=schedule_rows,
            pbp_rows=_iter_projected_pbp(pbp_paths),
            depth_rows=depth_rows,
            target_game_ids=target_ids,
            as_of=prediction_at,
            seasons=tuple(range(2018, 2027)),
        )

        fit_training_source_sha = str(
            fit_artifact.get("source_manifest_sha256") or
            (fit_artifact.get("fit") or {}).get("source_manifest_sha256") or ""
        )
        manifest = build_forward_source_manifest(
            receipts,
            prediction_at=prediction_at,
            target_game_ids=target_ids,
            fit_artifact_sha256=str(fit_artifact.get("artifact_sha256") or ""),
            fit_training_source_manifest_sha256=fit_training_source_sha,
            serving_code_identity=serving_code,
        )
        manifest_path = output_dir / "source_manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        prediction = build_forward_prediction(
            fit_artifact,
            forward_rows,
            prediction_at=prediction_at,
            source_manifest_sha256=manifest["manifest_sha256"],
            code_identity=serving_code,
            serving_compatibility_sha256=compat_sha,
            paths=50000,
        )
        prediction["forward_source_manifest_path"] = manifest_path.name
        prediction.pop("prediction_sha256", None)
        canonical = json.dumps(
            prediction,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        prediction["prediction_sha256"] = sha256(canonical).hexdigest()

        prediction_path = output_dir / "prediction.json"
        prediction_path.write_text(
            json.dumps(prediction, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    summary = {
        "schema": "SPORTSEDGE_NFL_SCORE_COUNTS_G1_FORWARD_RUN_SUMMARY_V1",
        "status": "FROZEN_PREGAME_RESEARCH_PREDICTION",
        "prediction_at": prediction["prediction_at"],
        "target_game_ids": [game["game_id"] for game in prediction["games"]],
        "game_count": len(prediction["games"]),
        "paths_per_game": 50000,
        "fit_artifact_sha256": prediction["fit_artifact_sha256"],
        "training_source_manifest_sha256": prediction[
            "training_source_manifest_sha256"
        ],
        "forward_source_manifest_sha256": prediction[
            "forward_source_manifest_sha256"
        ],
        "serving_code_identity": prediction["serving_code_identity"],
        "serving_compatibility_sha256": prediction[
            "serving_compatibility_sha256"
        ],
        "prediction_sha256": prediction["prediction_sha256"],
        "market_data_used": False,
        "backfill": False,
        "authority": prediction["authority"],
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--horizon-days", type=int, default=7)
    ap.add_argument("--game-id", action="append", default=[])
    args = ap.parse_args()
    summary = run(
        fit_path=args.fit,
        output_dir=args.output_dir,
        horizon_days=int(args.horizon_days),
        explicit_game_ids=list(args.game_id),
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
