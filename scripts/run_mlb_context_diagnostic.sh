#!/usr/bin/env bash
set +e
mkdir -p artifacts/mlb-context/_runner
PYTHONPATH=. python scripts/refresh_mlb_game_context.py \
  > >(tee artifacts/mlb-context/_runner/stdout.log) \
  2> >(tee artifacts/mlb-context/_runner/stderr.log >&2)
code=$?
printf '%s\n' "$code" > artifacts/mlb-context/_runner/exit_code.txt
python - "$code" <<'PY'
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
code = int(sys.argv[1])
out = Path('artifacts/mlb-context/_runner')
(out / 'runner_manifest.json').write_text(json.dumps({
    'run_at_utc': datetime.now(timezone.utc).isoformat(),
    'exit_code': code,
    'status': 'PASS' if code == 0 else 'ERROR',
}, indent=2, sort_keys=True) + '\n')
PY
exit "$code"
