#!/usr/bin/env python3
"""Build a frozen CFB AUTO model artifact from a declared PIT training bundle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sportsedge.sports.cfb.training_artifact import (  # noqa: E402
    CFBTrainingArtifactError,
    build_cfb_artifact_from_pit_bundle,
)

_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_CFB_MODEL_ARTIFACT_PATH = Path("models/cfb_joint_v1.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--training-bundle", type=Path, required=True)
    ap.add_argument("--fit-max-season", type=int, required=True)
    ap.add_argument("--ridge-alpha", type=float, default=10.0)
    ap.add_argument("--git-sha", required=True)
    ap.add_argument("--output", type=Path, default=DEFAULT_CFB_MODEL_ARTIFACT_PATH)
    ap.add_argument("--provenance-output", type=Path, default=Path("artifacts/cfb/cfb_model_training_provenance.json"))
    args = ap.parse_args()

    git_sha = str(args.git_sha or "").strip().lower()
    if not _GIT_SHA_RE.fullmatch(git_sha):
        raise SystemExit("CFB_CODE_GIT_SHA_INVALID")

    try:
        raw = args.training_bundle.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("CFB_TRAINING_BUNDLE_UNREADABLE") from exc
    try:
        artifact, provenance = build_cfb_artifact_from_pit_bundle(
            payload,
            raw_bytes=raw,
            repo_root=ROOT,
            fit_max_season=args.fit_max_season,
            ridge_alpha=args.ridge_alpha,
        )
    except CFBTrainingArtifactError as exc:
        raise SystemExit(str(exc)) from exc

    # These labels bind the provenance artifact to the exact claim being made.
    # The deterministic boundary begins at the already-materialized PIT bundle;
    # it does not certify upstream feature acquisition/materialization.
    provenance = dict(provenance)
    provenance.update({
        "sport": "cfb",
        "code_git_sha": git_sha,
        "determinism_class": "SAME_ENV_SAME_SHA",
        "replay_scope": "TRAINING_BUNDLE_TO_ARTIFACT",
    })

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.provenance_output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.provenance_output.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "artifact_sha256": artifact["artifact_sha256"],
        "training_bundle_sha256": provenance["training_bundle_sha256"],
        "source_manifest_sha256": provenance["upstream_source_manifest_sha256"],
        "fit_max_season": provenance["fit_max_season"],
        "row_count": provenance["row_count"],
        "promotion_changed": False,
        "determinism_class": provenance["determinism_class"],
        "replay_scope": provenance["replay_scope"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
