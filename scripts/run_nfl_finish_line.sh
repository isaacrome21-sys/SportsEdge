#!/usr/bin/env bash
set -euo pipefail

# One-shot manual/local NFL evidence runner.
# Mirrors the pre-CI GitHub Actions evidence workflow while deliberately stopping
# before CI attestation so manual execution can never impersonate successful CI.

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
HEAD_SHA="$(git rev-parse HEAD | tr '[:upper:]' '[:lower:]')"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
DIRTY="$(git status --porcelain)"

if [[ -n "$DIRTY" ]]; then
  echo "ERROR: WORKTREE_DIRTY"
  exit 2
fi
if [[ "${ALLOW_NON_MAIN:-0}" != "1" && "$BRANCH" != "main" ]]; then
  echo "ERROR: MAIN_BRANCH_REQUIRED (current=$BRANCH)"
  exit 2
fi
EXPECTED_SHA="${EXPECTED_SHA:-$HEAD_SHA}"
EXPECTED_SHA="$(printf '%s' "$EXPECTED_SHA" | tr '[:upper:]' '[:lower:]')"
if [[ "$EXPECTED_SHA" != "$HEAD_SHA" ]]; then
  echo "ERROR: EXACT_HEAD_SHA_MISMATCH expected=$EXPECTED_SHA actual=$HEAD_SHA"
  exit 2
fi
export EVIDENCE_GIT_SHA="$HEAD_SHA"
PYTHON_BIN="${PYTHON_BIN:-python3}"
CURL_BIN="${CURL_BIN:-curl}"
command -v "$PYTHON_BIN" >/dev/null || { echo "ERROR: python not found: $PYTHON_BIN"; exit 2; }
command -v "$CURL_BIN" >/dev/null || { echo "ERROR: curl not found: $CURL_BIN"; exit 2; }
mkdir -p artifacts/football/sources/{pbp,participation,depth}

printf '\n=== NFL FINISH LINE ===\nbranch=%s\nsha=%s\n' "$BRANCH" "$HEAD_SHA"

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

fetch() {
  local url="$1" out="$2"
  if [[ -s "$out" && "${REFETCH:-0}" != "1" ]]; then
    echo "reuse $out"
  else
    echo "fetch $out"
    "$CURL_BIN" --fail --location --retry 3 --retry-delay 2 "$url" -o "$out"
  fi
}

fetch 'https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv' artifacts/football/sources/games.csv
fetch 'https://raw.githubusercontent.com/greerreNFL/Stadiums/efa9543af50b01424754219fa0e4f3c7044ff198/data/team_stadiums.csv' artifacts/football/sources/team_stadiums.csv
for season in $(seq 2016 2025); do
  fetch "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_${season}.csv.gz" "artifacts/football/sources/pbp/play_by_play_${season}.csv.gz"
  fetch "https://github.com/nflverse/nflverse-data/releases/download/pbp_participation/pbp_participation_${season}.csv" "artifacts/football/sources/participation/pbp_participation_${season}.csv"
  fetch "https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_${season}.csv" "artifacts/football/sources/depth/depth_charts_${season}.csv"
done

"$PYTHON_BIN" scripts/run_nfl_production_validation.py \
  --schedule-file artifacts/football/sources/games.csv \
  --pbp-dir artifacts/football/sources/pbp \
  --participation-dir artifacts/football/sources/participation \
  --depth-dir artifacts/football/sources/depth \
  --stadium-file artifacts/football/sources/team_stadiums.csv \
  --git-sha "$EVIDENCE_GIT_SHA" \
  --start-season 2016 --end-season 2025 \
  --neutral-site-policy exclude_from_evaluation \
  --out artifacts/football/nfl_production_validation.json \
  --manifest-out artifacts/football/nfl_source_manifest.json

"$PYTHON_BIN" scripts/audit_nfl_real_history.py \
  --source-file artifacts/football/sources/games.csv \
  --min-season 1999 --max-season 2025 \
  --output artifacts/football/nfl_real_history_audit.json
"$PYTHON_BIN" scripts/validate_nfl_simulator_profile.py artifacts/football/nfl_real_history_audit.json --out artifacts/football/nfl_simulator_profile_schedule.json
"$PYTHON_BIN" scripts/bind_nfl_math_to_source_manifest.py \
  --math-evidence artifacts/football/nfl_simulator_profile_schedule.json \
  --source-manifest artifacts/football/nfl_source_manifest.json \
  --git-sha "$EVIDENCE_GIT_SHA" \
  --out artifacts/football/nfl_simulator_profile.json

"$PYTHON_BIN" - <<'PY'
import json, os
from pathlib import Path
from sportsedge.sports.nfl.m2 import NFL_M2_FEATURE_CONTRACT, PRODUCTION_NFL_M2_MODEL_ID
history=json.loads(Path('artifacts/football/nfl_production_validation.json').read_text())
math=json.loads(Path('artifacts/football/nfl_simulator_profile.json').read_text())['math_artifact']
manifest=json.loads(Path('artifacts/football/nfl_source_manifest.json').read_text())
source=manifest['manifest_sha256']; git=os.environ['EVIDENCE_GIT_SHA'].lower()
if history['model_id'] != PRODUCTION_NFL_M2_MODEL_ID: raise SystemExit('NFL_EVIDENCE_MODEL_ID_MISMATCH')
if history['feature_contract'] != NFL_M2_FEATURE_CONTRACT: raise SystemExit('NFL_EVIDENCE_FEATURE_CONTRACT_MISMATCH')
if {history['source_sha256'], math['source_sha256'], source} != {source}: raise SystemExit('NFL_EVIDENCE_MANIFEST_BINDING_MISMATCH')
if {history['code_git_sha'], math['code_git_sha'], git} != {git}: raise SystemExit('NFL_EVIDENCE_CODE_SHA_MISMATCH')
print('identity=PASS')
PY

"$PYTHON_BIN" scripts/build_nfl_promotion_registry.py \
  --math-evidence artifacts/football/nfl_simulator_profile.json \
  --historical-evidence artifacts/football/nfl_production_validation.json \
  --market-surface config/football_market_surface.json \
  --out artifacts/football/nfl_promotion_registry.json

"$PYTHON_BIN" - <<'PY'
import hashlib, json, os
from pathlib import Path
source=json.loads(Path('artifacts/football/nfl_source_manifest.json').read_text())
paths=sorted(Path('artifacts/football').glob('*.json'))
payload={
 'schema_version':2,
 'git_sha':os.environ['EVIDENCE_GIT_SHA'].lower(),
 'source_manifest_sha256':source['manifest_sha256'],
 'ci_attestation_state':'MANUAL_PRE_CI_CANNOT_ATTEST',
 'promotion_state':'NOT_DEPLOYABLE_FROM_MANUAL_RUN',
 'artifacts':[{'path':p.name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
}
Path('artifacts/football/nfl_manual_evidence_manifest.json').write_text(json.dumps(payload,indent=2,sort_keys=True)+'\n')
PY

printf '\nMANUAL EVIDENCE COMPLETE\nsha=%s\nCI attestation: NOT GRANTED\nDEPLOYED promotion: NOT GRANTED\n' "$EVIDENCE_GIT_SHA"
