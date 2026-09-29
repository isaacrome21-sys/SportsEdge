from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()

    root = Path(args.input_dir)
    meta = json.loads((root / "meta.json").read_text())
    games = list(meta["games"])
    observed = dict(meta["observed"])
    paired_rows = list(meta.get("paired_rows") or [])
    one_sided_rows: list[dict] = []

    for path in sorted(root.glob("*.json")):
        if path.name == "meta.json":
            continue
        payload = json.loads(path.read_text())
        market_type = str(payload["market_type"])
        observed_at = str(observed[market_type])
        for row in payload.get("rows") or []:
            game_index, subject_name, side, line, price = row
            game_id, first_pitch_at = games[int(game_index)]
            one_sided_rows.append({
                "game_id": str(game_id),
                "market_type": market_type,
                "subject_name": str(subject_name),
                "side": str(side),
                "line": float(line),
                "price": int(price),
                "book": "draftkings",
                "observed_at": observed_at,
                "first_pitch_at": str(first_pitch_at),
                "source": "MANUAL",
            })

    out = {"paired_rows": paired_rows, "one_sided_rows": one_sided_rows}
    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps({"paired_rows": len(paired_rows), "one_sided_rows": len(one_sided_rows), "output": str(dest)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
