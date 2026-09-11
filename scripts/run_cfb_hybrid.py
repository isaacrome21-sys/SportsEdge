#!/usr/bin/env python3
"""CFB HYBRID runner: frozen Model_P path + manual two-sided DraftKings quotes.

The quote file is consumed only after the frozen game model is loaded. This path
requires CFBD for schedule/features/weather but never reads or requires an Odds API
credential. Manual prices remain market inputs and cannot create Model_P.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_cfb_auto import CFBAutoError, _model, _utc, discover_cfb_week
from sportsedge.sports.cfb.manual_quotes import CFBManualQuoteError, load_manual_cfb_quote_bundle
from sportsedge.sports.cfb.paths import DEFAULT_CFB_MODEL_ARTIFACT_PATH
from sportsedge.sports.cfb.run_machine import CFBRunMachineError, run_it_cfb


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quotes-file", type=Path, required=True)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--asof")
    ap.add_argument("--model-artifact", type=Path, default=DEFAULT_CFB_MODEL_ARTIFACT_PATH)
    ap.add_argument("--n-paths", type=int, default=20000)
    ap.add_argument("--root-seed", type=int, default=20260826)
    ap.add_argument("--output", type=Path, default=Path("artifacts/run_it/cfb_hybrid_card.json"))
    args = ap.parse_args()

    current = _utc(args.asof)
    try:
        cfbd_key = str(os.environ.get("SPORTSEDGE_CFBD_API_KEY") or os.environ.get("CFBD_API_KEY") or "").strip()
        if not cfbd_key:
            raise CFBAutoError("CFB_HYBRID_CFBD_API_KEY_REQUIRED")
        # Load/freeze validation happens before quote ingestion. Price bytes are
        # therefore outside the model artifact/input path by construction.
        model, artifact, registry = _model(args.model_artifact, repo_root=ROOT)
        bundle = load_manual_cfb_quote_bundle(args.quotes_file)
        season = int(args.season if args.season is not None else current.year)
        week = int(args.week) if args.week is not None else discover_cfb_week(
            season=season, now=current, cfbd_api_key=cfbd_key,
        )
        report = run_it_cfb(
            mode="HYBRID",
            season=season,
            week=week,
            model=model,
            now=current,
            quotes=bundle["quotes"],
            cfbd_api_key=cfbd_key,
            root_seed=int(args.root_seed),
            n_paths=int(args.n_paths),
        )
        payload = {
            "schema_version": "CFB_HYBRID_RUN_V1",
            "status": "SUCCESS",
            "season": season,
            "week": week,
            "model_artifact_sha256": artifact["artifact_sha256"],
            "training_source_sha256": artifact["training_source_sha256"],
            "game_freeze_registry_sha256": registry["registry_sha256"],
            "manual_quote_file_sha256": bundle["quote_file_sha256"],
            "manual_quote_observed_at": bundle["observed_at"],
            "manual_quote_book": bundle["book_key"],
            "manual_quote_source_evidence_ref": bundle["source_evidence_ref"],
            "report": report.to_dict(),
            "governance": {
                "mode": "HYBRID",
                "odds_api_used": False,
                "odds_api_key_required": False,
                "manual_prices_create_model_p": False,
                "two_sided_manual_prices_required": True,
                "promotion_changed": False,
                "truth_gate_changed": False,
                "fail_closed": True
            }
        }
        _write(args.output, payload)
        print(json.dumps({"status":"SUCCESS","run_status":report.run_status,"output":str(args.output)}, sort_keys=True))
        return 0
    except (CFBAutoError, CFBManualQuoteError, CFBRunMachineError, ValueError) as exc:
        payload = {
            "schema_version": "CFB_HYBRID_RUN_V1",
            "status": "BLOCKED",
            "blocker": str(exc),
            "generated_at_utc": current.isoformat(),
            "governance": {"odds_api_used": False, "promotion_changed": False, "truth_gate_changed": False, "fail_closed": True}
        }
        _write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
