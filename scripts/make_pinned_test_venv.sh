#!/usr/bin/env bash
# t263: build a fresh test venv whose numpy equals the frozen v2k runtime pin,
# so tests/test_nfl_v2k_attempt1_runner.py preflight does not hit
# V2K_RUNTIME_NUMPY_MISMATCH on hosts with a newer system numpy.
# The venv must live OUTSIDE the repo: the screen-only guard treats frames under
# the repo root as repo code, so an in-repo venv makes it refuse tests.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd -P)"
if [ "${SPORTSEDGE_PINNED_VENV_CREATE_ONLY:-}" = "1" ] && [ -z "${PYTEST_CURRENT_TEST:-}" ]; then
  echo "CREATE_ONLY_REQUIRES_PYTEST: SPORTSEDGE_PINNED_VENV_CREATE_ONLY is a test-only hook" >&2
  exit 2
fi
if [ -n "${1:-}" ]; then
  VENV="$1"
else
  # Per-run default: a fresh directory every run, outside the repo.
  VENV="$(mktemp -d "${TMPDIR:-/tmp}/sportsedge-venv-pinned-XXXXXX")"
fi
case "$VENV" in /*) ;; *) VENV="$REPO/$VENV" ;; esac
VENV_ABS="$(realpath -m "$VENV")"
if [ "$VENV_ABS" = "$REPO" ] || [ "${VENV_ABS#"$REPO"/}" != "$VENV_ABS" ]; then
  echo "VENV_INSIDE_REPO_REFUSED:$VENV_ABS" >&2
  exit 2
fi
echo "pinned venv path: $VENV_ABS"
# --clear: never reuse an existing venv (stale extra packages would survive).
python3 -m venv --clear "$VENV_ABS"
if [ "${SPORTSEDGE_PINNED_VENV_CREATE_ONLY:-}" = "1" ]; then
  # Test hook: stop after (re)creating the venv; skips the network install.
  echo "venv (create-only): $VENV_ABS"
  exit 0
fi
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
