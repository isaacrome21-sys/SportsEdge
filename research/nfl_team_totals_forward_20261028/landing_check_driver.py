"""NON-COUNTED landing check for the NFL team-totals driver
(``sportsedge/nfl_team_total_driver.py``) around the FROZEN runner.

Runs the driver end-to-end on the already-played 2026-10-25 slate's
real captured data (San Francisco 49ers @ Atlanta Falcons — the one
game on that slate whose operative capture carries team-total rows),
prices it with the pinned runner, and settles it against the final
score in the pinned nflverse schedules record. Proves:

- entry records are written, create-only, carrying the freeze pins
  (engine / runner / config / preregistration sha256, all equal to
  the FREEZE_RECORD pins);
- every priced row's settlement carries exactly one section 7 close
  disposition from the pinned runner's declared set;
- NOTHING is counted: this slate predates any counting use of the
  driver, the records keep the runner's PROSPECTIVE label, and no
  section 6 metric is computed anywhere (the family evaluator is
  PENDING per the freeze record; no interim looks).

Inputs (all hash-pinned or verbatim-copied, provenance in
DRIVER_LANDING_CHECK.md):

- capture: ``landing_check_driver_capture_20261025.json`` next to
  this script — the event-34118095 entry copied verbatim from
  ``operative_run_20261025_runit_nfl/captures_all.json`` (source file
  sha256 05d47af0cab58d9a69a8908ed745e9ec7ab89e33d4c0c7e3869325d4682323c9).
- schedules/history/finals: the in-repo pinned nflverse games file
  ``research/nfl_cfb_design_baselines_20261027/nflverse_games.csv.gz``
  (sha256 82b05d7096b3f59acd127da8762b1e2260f4af70b49e5548ce4cd3ade92a49a5).

Lane A runs in its offline manual mode (the runner tests' mode), so
the check is deterministic and needs no network. The close source is
the same capture file: its only paired team-total capture is the
10:53:25 entry pair, 66m35s before the 12:00 kickoff — outside the
section 7 60:00 window — so both rows must settle CLOSE_STALE with
GRADED finals. No close quote is fabricated to force a READABLE.

Usage: python3 landing_check_driver.py
Outputs (create-only; delete landing_check_driver_out/ to re-run):
landing_check_driver_out/{entry_2026-10-25.jsonl,
entry_2026-10-25.report.json, settlement_2026-10-25.jsonl} and
landing_check_driver_result.json next to this script.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sportsedge import nfl_team_total_driver as driver  # noqa: E402
from sportsedge import nfl_team_total_runner as runner  # noqa: E402

CAPTURE = HERE / "landing_check_driver_capture_20261025.json"
GAMES = (REPO_ROOT / "research" / "nfl_cfb_design_baselines_20261027"
         / "nflverse_games.csv.gz")
OUT_DIR = HERE / "landing_check_driver_out"
RESULT = HERE / "landing_check_driver_result.json"
NOW = "2026-10-25T10:54:25-05:00"  # 60 s after the entry capture

# The FREEZE_RECORD pins (research/nfl_team_totals_forward_20261028/
# FREEZE_RECORD.md), re-asserted against the live files at run time.
PIN_ENGINE = "50c5d9ff068b3bf629a725d5713a956d3149565c2f29c59ac8af3fc6461dcc27"
PIN_RUNNER = "076da740f5ac0517bbe2f52b28decf77d9923226c51a8228ff5e57b4b14f323e"
PIN_CONFIG = "4c5d7afbfe97d0c5f48644b7fe36c2f7666fba6caf10421f16e3a516485aa3d7"
PIN_PREREG = "83f25f0e92c3ea39c8b18e194ce5743ceff6b595dc7dcb342175a57e46743581"
PIN_GAMES = "82b05d7096b3f59acd127da8762b1e2260f4af70b49e5548ce4cd3ade92a49a5"

EXPECTED_FINALS = {"SF": 20, "ATL": 29}  # schedules record 2026_07_SF_ATL
SECTION6_KEYS = {"clv", "delta_mae", "mae", "hit_rate", "verdict",
                 "beats_market", "section6", "metrics"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _no_section6(obj, path="$"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key.lower() not in SECTION6_KEYS, (path, key)
            _no_section6(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_section6(value, f"{path}[{i}]")


def main() -> int:
    if OUT_DIR.exists() or RESULT.exists():
        print("landing check outputs already exist; delete "
              "landing_check_driver_out/ and landing_check_driver_result"
              ".json to re-run (create-only discipline)")
        return 2
    assert _sha(GAMES) == PIN_GAMES, "pinned games file hash mismatch"
    assert _sha(REPO_ROOT / "sportsedge" / "nfl_team_total_dist.py") \
        == PIN_ENGINE
    assert _sha(REPO_ROOT / "sportsedge" / "nfl_team_total_runner.py") \
        == PIN_RUNNER

    rc = driver.main(["price", "--captures", str(CAPTURE),
                      "--games", str(GAMES), "--slate-date", "2026-10-25",
                      "--out-dir", str(OUT_DIR), "--now", NOW,
                      "--lane-a-mode", "manual"])
    assert rc == 0, f"price rc={rc}"
    records = [json.loads(x) for x in
               (OUT_DIR / "entry_2026-10-25.jsonl").read_text()
               .splitlines() if x]
    report = json.loads((OUT_DIR / "entry_2026-10-25.report.json")
                        .read_text())
    assert report["records_written"] == 2 and report["runner_refusals"] \
        == [] and report["driver_refusals"] == []
    assert report["metrics_computed"] is False
    by_team = {r["team"]: r for r in records}
    assert set(by_team) == {"SF", "ATL"}
    for team, rec in by_team.items():
        assert rec["game_id"] == "2026_07_SF_ATL" and rec["week"] == 7
        assert rec["engine_sha256"] == PIN_ENGINE
        assert rec["runner_sha256"] == PIN_RUNNER
        assert rec["config_sha256"] == PIN_CONFIG
        assert rec["prereg_sha256"] == PIN_PREREG
        assert rec["label"] == "PROSPECTIVE"
        # The pmf grid is truncated at MAX_SCORE=120; the tail mass
        # beyond the support is < 5e-6 at these means. The model_p
        # partition the test actually scores sums to 1 exactly.
        assert abs(sum(rec["distribution"]["pmf"]) - 1.0) < 1e-4
        mp = rec["model_p"]
        assert abs(mp["OVER"] + mp["UNDER"] + mp["PUSH"] - 1.0) < 1e-9
        assert rec["lane_a"]["team_mean"] is not None
        # Section 5 pick rule, recomputed independently from the
        # record's own mu and entry line.
        gap = rec["mu"] - rec["entry"]["line"]
        expected_pick = ("PICKED_OVER" if gap >= 2.0 else
                         "PICKED_UNDER" if gap <= -2.0 else "PASSED")
        assert rec["pick"] == expected_pick
        assert abs(rec["gap"] - gap) < 1e-9
        _no_section6(rec)

    settlement_path = OUT_DIR / "settlement_2026-10-25.jsonl"
    rc = driver.main(["settle", "--records",
                      str(OUT_DIR / "entry_2026-10-25.jsonl"),
                      "--captures", str(CAPTURE), "--games", str(GAMES),
                      "--out", str(settlement_path)])
    assert rc == 0, f"settle rc={rc}"
    settled = [json.loads(x) for x in
               settlement_path.read_text().splitlines() if x]
    assert len(settled) == 2
    for row in settled:
        assert row["close_status"] in runner.CLOSE_DISPOSITIONS
        # The only paired capture is 66m35s pre-kickoff: outside the
        # section 7 window, so CLOSE_STALE is the honest disposition.
        assert row["close_status"] == "CLOSE_STALE"
        assert row["settlement"] == "GRADED"
        assert row["final_team_points"] == EXPECTED_FINALS[row["team"]]
        _no_section6(row)

    result = {
        "check": "NFL_TEAM_TOTAL_DRIVER_LANDING_CHECK_V1",
        "label": "NON_COUNTED",
        "counted": False,
        "slate_date": "2026-10-25",
        "game_id": "2026_07_SF_ATL",
        "rows_priced": len(records),
        "picks": {t: by_team[t]["pick"] for t in sorted(by_team)},
        "mu": {t: by_team[t]["mu"] for t in sorted(by_team)},
        "lane_a_team_mean": {t: by_team[t]["lane_a"]["team_mean"]
                             for t in sorted(by_team)},
        "dispositions": {row["team"]: row["close_status"]
                         for row in settled},
        "final_team_points": EXPECTED_FINALS,
        "history_games": report["history_games"],
        "history_snapshot_sha256": report["history_snapshot_sha256"],
        "pins_verified": {"engine": PIN_ENGINE, "runner": PIN_RUNNER,
                          "config": PIN_CONFIG, "prereg": PIN_PREREG,
                          "games_file": PIN_GAMES},
        "metrics_computed": False,
    }
    with RESULT.open("x", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    print(json.dumps(result, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
