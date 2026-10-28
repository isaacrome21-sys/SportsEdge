"""Landing check for the NBA period-lines forward build — NON_COUNTED.

Prices and grades one historical slate end to end from admitted-feed
data only (ESPN summary API, admission PR #2880), through the built
wiring (``sportsedge/nba_period_forward.py``) and the §4.2 capture
grammar (``sportsedge/nba_period_lines_intake.py``). Nothing counts:
the preregistration is DRAFT_NOT_IN_FORCE, every record stamps
counted=False, and this script is evidence about the wiring, not a
screen or a verdict.

Data: entries pulled from the admitted route into local staging by
``pull_landing_data.py`` (scoreboard = discovery/identity only, per
the admission record; summaries extracted and validated by the
admission packet's own puller). Raw payloads are never committed; the
entries file's sha256 is recorded in the output.

Slate: 2015-04-15 (ET), the final day of the 2014-15 regular season —
14 games, one of them the admission packet's pinned sample
(400579520, CHA @ TOR), which is cross-checked against the merged
manifest before anything is priced. Priors: admitted-feed games dated
2015-03-20..2015-04-14 ET (strictly before the slate).

Usage: python3 run_landing_check.py --entries <landing_entries.json>
           [--out LANDING_CHECK.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sportsedge import nba_period_forward as fwd          # noqa: E402
from sportsedge import nba_period_lines_intake as intake  # noqa: E402

SLATE_DATE = "2015-04-15"
SEASON = 2014
PINNED_EVENT = "400579520"


def _capture_body(entry, actuals) -> str:
    """A synthetic DK-style capture for the §4.2 exercise. Lines are
    constructed from the finals (actual - 2.5 game / actual - 1.5
    team) purely to exercise parse + settlement; they are NOT market
    data and are labeled synthetic in the output record. The Q3
    sections are declared NOT_OFFERED to exercise the census path."""
    home, away = actuals.home, actuals.away
    lines = [f"{away} @ {home}", "Captured: 2015-04-15T17:45:00-04:00",
             "ML -110 -110", "Spread -1.5 -110 -110", "Total 183.5 -110 -110"]
    windows = ("Q1", "Q2", "Q3", "Q4", "1H", "2H")
    for i, w in enumerate(windows):
        game_actual = (actuals.game_quarters[i] if i < 4
                       else actuals.game_halves[i - 4])
        if w == "Q3":
            lines.append(f"{w} Total NOT_OFFERED")
        else:
            lines.append(f"{w} Total {game_actual - 2.5} -110 -110")
        for team in (away, home):
            team_actual = (actuals.team_quarters[team][i] if i < 4
                           else actuals.team_halves[team][i - 4])
            if w == "Q3":
                lines.append(f"{team} {w} TT NOT_OFFERED")
            else:
                lines.append(f"{team} {w} TT {team_actual - 1.5} -110 -110")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--entries", required=True)
    ap.add_argument("--out", default=str(Path(__file__).with_name("LANDING_CHECK.json")))
    args = ap.parse_args()

    raw = Path(args.entries).read_bytes()
    doc = json.loads(raw)
    entries = doc["entries"]
    entry_refusals = doc.get("refusals", [])

    # Every staged entry must pass the §4.1 form gate as built.
    form_refusals = []
    valid_entries = []
    for e in entries:
        try:
            fwd.observation_from_manifest_entry(e)
            valid_entries.append(e)
        except fwd.NBAPeriodForwardError as exc:
            form_refusals.append({"event": e.get("espn_event_id"),
                                  "reason": exc.reason, "detail": exc.detail})

    # Cross-check the pinned admission sample before pricing anything.
    manifest = json.loads((Path(__file__).resolve().parents[1]
                           / "nba_quarter_score_feed_admission_20261028"
                           / "sample_manifest.json").read_text(encoding="utf-8"))
    pinned = next(s for s in manifest["samples"]
                  if s["espn_event_id"] == PINNED_EVENT)
    staged = next(e for e in valid_entries
                  if e["espn_event_id"] == PINNED_EVENT)
    cross_check = {
        "event": PINNED_EVENT,
        "home_quarters_match": (staged["home_quarters_regulation"]
                                == pinned["home_quarters_regulation"]),
        "away_quarters_match": (staged["away_quarters_regulation"]
                                == pinned["away_quarters_regulation"]),
        "finals_match": (staged["home_final"] == pinned["home_final"]
                         and staged["away_final"] == pinned["away_final"]),
    }
    cross_check["passed"] = all(v for k, v in cross_check.items() if k != "event")

    history = fwd.history_from_entries(valid_entries, before_date=SLATE_DATE)
    slate = [e for e in valid_entries
             if fwd.game_row_from_entry(e)["date"] == SLATE_DATE]

    prior_counts = Counter()
    for r in history:
        prior_counts[r["home"]] += 1
        prior_counts[r["away"]] += 1

    games_out = []
    mae_accum = {name: [] for name in fwd.SUBFAMILIES}
    refusal_counts = Counter()
    settlements_all = []
    capture_exercise = None
    for e in sorted(slate, key=lambda x: x["espn_event_id"]):
        row = fwd.game_row_from_entry(e)
        priced = fwd.price_period_game(history, row["home"], row["away"],
                                       season=SEASON, target_date=SLATE_DATE)
        rec = {"game_id": row["game_id"], "away": row["away"],
               "home": row["home"],
               "priors": priced.get("priors"),
               "price_status": priced.get("status"),
               "periods_status": (priced.get("periods") or {}).get("status"),
               "counted": False}
        if priced.get("status") != "PRICED" or \
                (priced.get("periods") or {}).get("status") != "PRICED":
            refusal_counts[priced.get("reason")
                           or (priced.get("periods") or {}).get("reason")] += 1
            rec["refusal"] = priced.get("reason") or (priced.get("periods") or {}).get("reason")
            games_out.append(rec)
            continue
        graded = fwd.grade_period_game(priced, e)
        rec["grade_status"] = graded["status"]
        rec["mae"] = graded["mae"]
        for name, v in graded["mae"].items():
            if v is not None:
                n = graded["n_errors"][name]
                mae_accum[name].extend([v] * n)
        if row["game_id"] == PINNED_EVENT:
            actuals = fwd.actuals_from_entry(e)
            body = _capture_body(e, actuals)
            caps = intake.parse_period_capture(body)
            quotes = [q.to_dict() for q in caps[0].quotes]
            graded2 = fwd.grade_period_game(priced, e, closing_quotes=quotes)
            settlements_all = graded2["settlements"]
            capture_exercise = {
                "game_id": row["game_id"],
                "census": caps[0].census(),
                "quotes_recorded": len(quotes),
                "not_offered_recorded": sum(1 for q in quotes
                                            if q["status"] == "NOT_OFFERED"),
                "lines_are_synthetic": True,
                "settlements": settlements_all,
            }
        games_out.append(rec)

    aggregate_mae = {name: (sum(v) / len(v) if v else None)
                     for name, v in mae_accum.items()}
    priced_n = sum(1 for g in games_out if g.get("grade_status") == "GRADED")
    out = {
        "record": "NBA_PERIOD_FORWARD_LANDING_CHECK",
        "state": "NON_COUNTED",
        "freeze_state": fwd.FREEZE_STATE,
        "counted": False,
        "validation_credit": False,
        "forward_clock_credit": False,
        "play_eligible": False,
        "slate_date": SLATE_DATE,
        "season_engine": SEASON,
        "entries_file_sha256": hashlib.sha256(raw).hexdigest(),
        "entries_pulled": len(entries),
        "pull_refusals": entry_refusals,
        "form_gate_refusals": form_refusals,
        "pinned_sample_cross_check": cross_check,
        "history_games": len(history),
        "history_team_game_priors_min": min(prior_counts.values()) if prior_counts else None,
        "slate_games": len(slate),
        "games_priced_and_graded": priced_n,
        "price_refusals": dict(refusal_counts),
        "aggregate_mae": aggregate_mae,
        "mae_n": {name: len(v) for name, v in mae_accum.items()},
        "capture_grammar_exercise": capture_exercise,
        "games": games_out,
        "note": ("NON_COUNTED wiring evidence only. The synthetic capture "
                 "lines are constructed from finals to exercise the §4.2 "
                 "grammar and settlement path; they are not market data. "
                 "No screen, verdict, clock or counted row is produced."),
    }
    Path(args.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in
                      ("entries_pulled", "history_games", "slate_games",
                       "games_priced_and_graded", "price_refusals",
                       "aggregate_mae", "pinned_sample_cross_check")},
                     indent=1))
    return 0 if priced_n > 0 and cross_check["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
