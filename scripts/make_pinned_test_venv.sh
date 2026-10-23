#!/usr/bin/env bash
# t263: build a fresh test venv whose numpy equals the frozen v2k runtime pin,
# so tests/test_nfl_v2k_attempt1_runner.py preflight does not hit
# V2K_RUNTIME_NUMPY_MISMATCH on hosts with a newer system numpy.
# The venv must live OUTSIDE the repo: the screen-only guard treats frames under
# the repo root as repo code, so an in-repo venv makes it refuse tests.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd -P)"
VENV="${1:-${TMPDIR:-/tmp}/sportsedge-venv-pinned}"
case "$VENV" in /*) ;; *) VENV="$REPO/$VENV" ;; esac
VENV_ABS="$(realpath -m "$VENV")"
if [ "$VENV_ABS" = "$REPO" ] || [ "${VENV_ABS#"$REPO"/}" != "$VENV_ABS" ]; then
  echo "VENV_INSIDE_REPO_REFUSED:$VENV_ABS" >&2
  exit 2
fi
python3 -m venv "$VENV_ABS"
"$VENV_ABS/bin/python" -m pip install --disable-pip-version-check -q \
  -c constraints/v2k-runtime.txt -r requirements-test.txt
"$VENV_ABS/bin/python" - <<'PY'
import json, numpy
c = json.load(open("sportsedge/sports/nfl/NFL_V2K_DEVELOPMENT_VALIDATION_PREATTEMPT_V1.json"))
want = c["unresolved_required_freezes"]["final_hardened_implementation_identity"]["runtime"]["numpy"]
assert numpy.__version__ == want, f"V2K_RUNTIME_NUMPY_MISMATCH:{numpy.__version__}!={want}"
print("numpy", numpy.__version__, "== frozen pin")
PY
echo "venv: $VENV_ABS"
