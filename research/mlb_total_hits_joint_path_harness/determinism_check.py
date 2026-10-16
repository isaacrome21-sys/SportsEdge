"""Determinism check for PREREG V1 scoring (section 3: reruns must
reproduce bit-identical per-game distributions).

Re-simulates a fixed sample of scored games from the stored bundles and
compares candidate PMFs, path_set_id and readout hashes EXACTLY against
pmf_rows.jsonl. Usage: determinism_check.py <work_dir> [stride]
"""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import score_fold as sf  # noqa: E402


def main() -> None:
    work_dir = Path(sys.argv[1])
    stride = int(sys.argv[2]) if len(sys.argv) > 2 else 75
    bundles = pickle.loads((work_dir / "bundles.pkl").read_bytes())["bundles"]
    stored = {}
    for line in (work_dir / "pmf_rows.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            stored[r["game_id"]] = r
    sample = [b for i, b in enumerate(
        sorted(bundles, key=lambda x: (x["date"], x["game_id"]))) if i % stride == 0]
    ok = True
    for b in sample:
        row = sf.simulate_game(b)
        ref = stored[b["game_id"]]
        same = (row["candidate"] == {k: {int(kk): vv for kk, vv in v.items()}
                                     for k, v in ref["candidate"].items()}
                and row["path_set_id"] == ref["path_set_id"]
                and row["readout_sha256"] == ref["readout_sha256"])
        print(b["game_id"], "IDENTICAL" if same else "MISMATCH")
        ok = ok and same
    print(f"determinism: {len(sample)} games, {'ALL IDENTICAL' if ok else 'FAILED'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
