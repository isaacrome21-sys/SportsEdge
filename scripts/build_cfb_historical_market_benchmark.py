#!/usr/bin/env python3
"""Build the deterministic research-only CFB historical market benchmark."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

# Support direct execution as ``python scripts/<name>.py`` in hosted CI without
# requiring an editable install.  This changes import plumbing only.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sportsedge.sports.cfb.history_cache import cache_market_archive, iter_market_archive
from sportsedge.sports.cfb.market_benchmark import build_historical_market_benchmark


def build(*, contract_path: Path, cache_root: Path, output_path: Path) -> dict:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    upstream = contract.get("upstream") or {}
    profile = contract.get("verified_profile") or {}
    cached = cache_market_archive(
        contract_path=contract_path,
        cache_root=cache_root,
        allow_benchmark=True,
    )
    report = build_historical_market_benchmark(
        iter_market_archive(contract_path=contract_path, cache_file=cached["cache_file"]),
        source_sha256=str(upstream.get("expected_sha256") or ""),
        expected_row_count=int(profile.get("row_count") or 0),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "source_sha256": report["source_sha256"],
                "report_sha256": report["report_sha256"],
                "row_count": report["row_count"],
                "season_start": report["season_start"],
                "season_end": report["season_end"],
                "book_count": report["book_count"],
                "rows_by_market": report["rows_by_market"],
                "keyed_rows_by_market": report["keyed_rows_by_market"],
                "side_matched_rows_by_market": report["side_matched_rows_by_market"],
                "reference_game_counts": report["reference_game_counts"],
                "ambiguous_book_game_groups": report["ambiguous_book_game_groups"],
                "output": str(output_path),
            },
            sort_keys=True,
        )
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contract",
        default="config/research/cfb_historical_market_source_v1.json",
    )
    parser.add_argument("--cache-root", default="artifacts/cfb/history/cache")
    parser.add_argument(
        "--output",
        default="artifacts/cfb/history/cfb_historical_market_benchmark_v1.json",
    )
    args = parser.parse_args()
    build(
        contract_path=Path(args.contract),
        cache_root=Path(args.cache_root),
        output_path=Path(args.output),
    )


if __name__ == "__main__":
    main()
