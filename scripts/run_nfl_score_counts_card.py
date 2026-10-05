#!/usr/bin/env python3
"""Price a pasted NFL board against a frozen NFL_SCORE_COUNTS_G1 prediction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from sportsedge.nfl_lines_intake import parse_nfl_lines, tickets_to_dict
from sportsedge.nfl_scoring_composition_artifact import load_prior
from sportsedge.sports.nfl.score_counts_phone_card import (
    build_score_count_phone_card,
)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prediction", type=Path, required=True)
    ap.add_argument("--lines-file", type=Path, required=True)
    ap.add_argument("--observed-at", required=True)
    ap.add_argument("--team-models", type=Path)
    ap.add_argument("--scoring-prior", type=Path)
    ap.add_argument("--injury-source-ready", action="store_true")
    ap.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/run_it/nfl_score_counts_card.json"),
    )
    args = ap.parse_args()

    prediction = _json(args.prediction)
    body = args.lines_file.read_text(encoding="utf-8")
    ticket = tickets_to_dict(
        parse_nfl_lines(body),
        observed_at=args.observed_at,
    )
    team_models = _json(args.team_models) if args.team_models else {}
    scoring_prior = (
        load_prior(_json(args.scoring_prior))
        if args.scoring_prior
        else None
    )
    card = build_score_count_phone_card(
        prediction,
        ticket,
        team_models=team_models,
        injury_source_ready=bool(args.injury_source_ready),
        scoring_prior=scoring_prior,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(card, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": "OK",
        "rows": len(card["rows"]),
        "selected": len(card["selected_rows"]),
        "output": str(args.output),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
