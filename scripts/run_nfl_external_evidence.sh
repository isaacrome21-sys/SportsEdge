#!/usr/bin/env bash
set -euo pipefail

# External execution lane for NFL historical/model evidence when GitHub-hosted
# Actions cannot allocate a runner. This lane intentionally CANNOT create CI
# attestation or DEPLOYED status. It exists only to produce the exact same
# historical/math/source-bound evidence on an exact repository SHA.

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

HEAD_SHA="$(git rev-parse HEAD | tr '[:upper:]' '[:lower:]')"
EXPECTED_SHA="${EVIDENCE_GIT_SHA:-$HEAD_SHA}"
EXPECTED_SHA="$(printf '%s' "$EXPECTED_SHA" | tr '[:upper:]' '[:lower:]')"

if [[ "$HEAD_SHA" != "$EXPECTED_SHA" ]]; then
  echo "NFL_EXTERNAL_EVIDENCE_SHA_MISMATCH: head=$HEAD_SHA expected=$EXPECTED_SHA" >&2
  exit 2
fi

if ! git diff --quiet --ignore-submodules -- || ! git diff --cached --quiet --ignore-submodules --; then
  echo "NFL_EXTERNAL_EVIDENCE_DIRTY_TREE" >&2
  exit 2
fi

if [[ "${ALLOW_NON_MAIN_EXTERNAL_EVIDENCE:-0}" != "1" ]]; then
  BRANCH="$(git branch --show-current || true)"
  if [[ -n "$BRANCH" && "$BRANCH" != "main" ]]; then
    echo "NFL_EXTERNAL_EVIDENCE_MAIN_REQUIRED: current=$BRANCH" >&2
    exit 2
  fi
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "NFL_EXTERNAL_EVIDENCE_PYTHON_MISSING:$PYTHON_BIN" >&2
  exit 2
fi
if ! command -v curl >/dev/null 2>&1; then
  echo "NFL_EXTERNAL_EVIDENCE_CURL_MISSING" >&2
  exit 2
fi

export EVIDENCE_GIT_SHA="$HEAD_SHA"
ARTIFACT_ROOT="${NFL_EVIDENCE_ARTIFACT_ROOT:-artifacts/football}"
SOURCE_ROOT="$ARTIFACT_ROOT/sources"
mkdir -p "$SOURCE_ROOT"/{pbp,participation,depth}

# Same contract-test surface as .github/workflows/football-nfl-promotion-evidence.yml.
"$PYTHON_BIN" -m py_compile \
  sportsedge/core/clv/football.py \
  sportsedge/core/promotion/football_registry.py \
  sportsedge/core/validation/nfl_ci_attestation.py \
  sportsedge/sports/nfl/m2.py \
  sportsedge/sports/nfl/m2_history_features.py \
  sportsedge/sports/nfl/m2_history_policy.py \
  sportsedge/sports/nfl/historical_validation.py \
  sportsedge/sports/nfl/production_validation.py \
  sportsedge/sports/nfl/source_manifest.py \
  sportsedge/sports/nfl/simulator_profile.py \
  scripts/run_nfl_production_validation.py \
  scripts/bind_nfl_math_to_source_manifest.py \
  scripts/validate_nfl_simulator_profile.py \
  scripts/build_nfl_promotion_registry.py \
  scripts/build_nfl_clv_evidence.py \
  scripts/attest_nfl_ci_and_build_registry.py

"$PYTHON_BIN" -m unittest discover -s tests -p 'test_football*.py' -v
"$PYTHON_BIN" -m unittest discover -s tests -p 'test_nfl*.py' -v

curl --fail --location --retry 3 \
  'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv' \
  -o "$SOURCE_ROOT/games.csv"
curl --fail --location --retry 3 \
  'https://raw.githubusercontent.com/greerreNFL/Stadiums/efa9543af50b01424754219fa0e4f3c7044ff198/data/team_stadiums.csv' \
  -o "$SOURCE_ROOT/team_stadiums.csv"

for season in $(seq 2016 2025); do
  curl --fail --location --retry 3 \
    "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_${season}.csv.gz" \
    -o "$SOURCE_ROOT/pbp/play_by_play_${season}.csv.gz"
  curl --fail --location --retry 3 \
    "https://github.com/nflverse/nflverse-data/releases/download/pbp_participation/pbp_participation_${season}.csv" \
    -o "$SOURCE_ROOT/participation/pbp_participation_${season}.csv"
  curl --fail --location --retry 3 \
    "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_${season}.csv" \
    -o "$SOURCE_ROOT/depth/depth_charts_${season}.csv"
done

"$PYTHON_BIN" scripts/run_nfl_production_validation.py \
  --schedule-file "$SOURCE_ROOT/games.csv" \
  --pbp-dir "$SOURCE_ROOT/pbp" \
  --participation-dir "$SOURCE_ROOT/participation" \
  --depth-dir "$SOURCE_ROOT/depth" \
  --stadium-file "$SOURCE_ROOT/team_stadiums.csv" \
  --git-sha "$EVIDENCE_GIT_SHA" \
  --start-season 2016 --end-season 2025 \
  --neutral-site-policy exclude_from_evaluation \
  --out "$ARTIFACT_ROOT/nfl_production_validation.json" \
  --manifest-out "$ARTIFACT_ROOT/nfl_source_manifest.json"

"$PYTHON_BIN" scripts/audit_nfl_real_history.py \
  --source-file "$SOURCE_ROOT/games.csv" \
  --min-season 1999 --max-season 2025 \
  --output "$ARTIFACT_ROOT/nfl_real_history_audit.json"

"$PYTHON_BIN" scripts/validate_nfl_simulator_profile.py \
  "$ARTIFACT_ROOT/nfl_real_history_audit.json" \
  --out "$ARTIFACT_ROOT/nfl_simulator_profile_schedule.json"

"$PYTHON_BIN" scripts/bind_nfl_math_to_source_manifest.py \
  --math-evidence "$ARTIFACT_ROOT/nfl_simulator_profile_schedule.json" \
  --source-manifest "$ARTIFACT_ROOT/nfl_source_manifest.json" \
  --git-sha "$EVIDENCE_GIT_SHA" \
  --out "$ARTIFACT_ROOT/nfl_simulator_profile.json"

"$PYTHON_BIN" - <<'PY'
import json, os
from pathlib import Path
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID

root = Path(os.environ.get("NFL_EVIDENCE_ARTIFACT_ROOT", "artifacts/football"))
history = json.loads((root / "nfl_production_validation.json").read_text())
math = json.loads((root / "nfl_simulator_profile.json").read_text())["math_artifact"]
manifest = json.loads((root / "nfl_source_manifest.json").read_text())
expected_source = manifest["manifest_sha256"]
expected_git = os.environ["EVIDENCE_GIT_SHA"].lower()
if history["model_id"] != PRODUCTION_NFL_M2_MODEL_ID:
    raise SystemExit("NFL_EVIDENCE_MODEL_ID_MISMATCH")
if history["feature_contract"] != NFL_M2_FEATURE_CONTRACT:
    raise SystemExit("NFL_EVIDENCE_FEATURE_CONTRACT_MISMATCH")
if {history["source_sha256"], math["source_sha256"], expected_source} != {expected_source}:
    raise SystemExit("NFL_EVIDENCE_MANIFEST_BINDING_MISMATCH")
if {history["code_git_sha"], math["code_git_sha"], expected_git} != {expected_git}:
    raise SystemExit("NFL_EVIDENCE_CODE_SHA_MISMATCH")
PY

"$PYTHON_BIN" scripts/build_nfl_promotion_registry.py \
  --math-evidence "$ARTIFACT_ROOT/nfl_simulator_profile.json" \
  --historical-evidence "$ARTIFACT_ROOT/nfl_production_validation.json" \
  --market-surface config/football_market_surface.json \
  --out "$ARTIFACT_ROOT/nfl_promotion_registry.json"

# External execution may establish historical/math evidence, but it must never
# impersonate GitHub CI. Record that limitation in a hash manifest and verify
# the pre-CI registry has not produced DEPLOYED markets.
NFL_EVIDENCE_ARTIFACT_ROOT="$ARTIFACT_ROOT" "$PYTHON_BIN" - <<'PY'
import hashlib, json, os
from pathlib import Path

root = Path(os.environ["NFL_EVIDENCE_ARTIFACT_ROOT"])
registry = json.loads((root / "nfl_promotion_registry.json").read_text())
text = json.dumps(registry).upper()
if '"DEPLOYED"' in text:
    raise SystemExit("EXTERNAL_RUNNER_CANNOT_CREATE_DEPLOYED_STATE")
source = json.loads((root / "nfl_source_manifest.json").read_text())
paths = sorted(root.glob("*.json"))
payload = {
    "schema_version": 1,
    "git_sha": os.environ["EVIDENCE_GIT_SHA"].lower(),
    "source_manifest_sha256": source["manifest_sha256"],
    "execution_lane": "EXTERNAL_EXACT_HEAD",
    "ci_attestation_state": "EXTERNAL_RUNNER_UNATTESTED",
    "promotion_allowed": False,
    "artifacts": [
        {"path": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in paths
        if p.name != "nfl_external_evidence_manifest.json"
    ],
}
(root / "nfl_external_evidence_manifest.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n"
)
print(json.dumps({
    "status": "EXTERNAL_HISTORICAL_EVIDENCE_COMPLETE_CI_UNATTESTED",
    "git_sha": payload["git_sha"],
    "source_manifest_sha256": payload["source_manifest_sha256"],
    "manifest": str(root / "nfl_external_evidence_manifest.json"),
}, sort_keys=True))
PY
