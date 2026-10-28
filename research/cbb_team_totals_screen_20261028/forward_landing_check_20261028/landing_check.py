#!/usr/bin/env python3
"""NON_COUNTED landing check for the CBB team-totals forward runner
build (freeze-package finding F-1).

The family is a READOUT of CBB_TORVIK_EFFICIENCY_V1: the expected
team points of the parent construction ARE the team-total forecasts.
This check proves, on admitted data only:

  1. READOUT EQUIVALENCE. The same landing slate as the parent
     family's check (agreed fixtures of 2023-02-25 and 2023-03-12
     from the admitted hoopR schedules + CBR logs, Illinois
     excluded, identity via the admitted crosswalk) is priced by
     the team-totals runner from vintage stores built out of the
     pinned Torvik archive files — and every record's model team
     points, candidate AND simple baseline, are FLOAT-IDENTICAL to
     the construction of record (cbb_team_totals.py:
     candidate_team_points / simple_baseline_team_points) on the
     same inputs. No naive value is recorded (package answer A-1:
     the forward accuracy leg names the simple baseline only).
  2. RECORD PATH. Every record is counted=False / NON_COUNTED with
     the package pins verified. Entry lines are the labeled
     SYNTHETIC fixture described in the parent family's check (no
     admitted DK capture exists before the Nov 1 pre-check).
  3. REFUSALS. counted=True and run_forward_test refuse with
     CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN; an Illinois game refuses
     ILLINOIS_COLLEGE_EXCLUDED; the R-1 vintage refusals are the
     shared core's and are proven in the parent family's check.

Writes LANDING_CHECK.json and entry_records_sample.jsonl next to
this script. Exits nonzero on any failed assertion.
"""

import csv
import hashlib
import importlib.util
import io
import json
import math
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from sportsedge import cbb_torvik_efficiency_v1 as core  # noqa: E402
from sportsedge.cbb_team_total_forward import (  # noqa: E402
    CbbTeamTotalForwardRunner,
)
from sportsedge.cbb_torvik_efficiency_v1 import (  # noqa: E402
    CbbForwardError,
    CbbSlateGame,
    PairedQuote,
    load_crosswalk,
    load_vintage,
    write_entry_records,
)

HOME = Path.home()
HOOPR = HOME / "workspace/cbb-successor-admission-20261028/pulls"
CACHE = HOME / "workspace/cbb-screen-attempt4-20261028/torvik_cache"
OUT_DIR = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location(
    "attempt4",
    REPO / "research/cbb_torvik_efficiency_screen_20261028"
    / "run_screen_attempt4.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)
_spec2 = importlib.util.spec_from_file_location(
    "cbb_team_totals",
    REPO / "research/cbb_team_totals_screen_20261028/cbb_team_totals.py")
TT = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(TT)

CROSSWALK_PATH = (REPO / "research/cbb_identity_crosswalk_20261028"
                  / "crosswalk.json")
DATES = ("2023-02-25", "2023-03-12")
MAX_GAMES_PER_DATE = 8


def round_half(x):
    return math.floor(x * 2 + 0.5) / 2.0


def build_vintage_store(tmp, slate_date):
    prior = S.prior_date_iso(slate_date)
    raw_archive = (CACHE / f"ratings_archive_"
                   f"{prior.replace('-', '')}.csv").read_bytes()
    parsed = S.parse_torvik(raw_archive, prior, S.build_resolver(
        json.loads(S.CBR_MANIFEST_PATH.read_text())))
    assert parsed is not None
    rows_in = list(csv.DictReader(io.StringIO(
        raw_archive.decode("utf-8"))))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "team", "conf", "record", "adjoe", "oe Rank",
                "adjde", "de Rank", "barthag", "adjt"])
    for i, r in enumerate(rows_in, 1):
        w.writerow([i, r["team"], r["conf"], r["record"], r["adj_o"],
                    r["adj_o_rk"], r["adj_d"], r["adj_d_rk"],
                    r["barthag"], r["adj_tempo"]])
    raw = buf.getvalue().encode("utf-8")
    store = Path(tmp) / f"store_{slate_date}"
    store.mkdir(parents=True)
    (store / f"{slate_date}.csv").write_bytes(raw)
    (store / f"{slate_date}.json").write_text(json.dumps({
        "season_year": 2023, "as_of_local_date": slate_date,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw), "team_rows": len(rows_in),
        "evidence_state": "verified-by-pull",
        "landing_check_note": "converted from the pinned D-1 archive "
                              "file for construction-equivalence "
                              "purposes only"}))
    return store, parsed


def agreed_fixtures(slate_dates):
    hoopr_manifest = json.loads(S.HOOPR_MANIFEST_PATH.read_text())
    cbr_manifest = json.loads(S.CBR_MANIFEST_PATH.read_text())
    S.verify_all_pins(hoopr_manifest, cbr_manifest, CACHE)
    resolve = S.build_resolver(cbr_manifest)
    schedules = {}
    with open(HOOPR / "mbb_schedule_2023.csv", newline="",
              encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            schedules[row["id"]] = row
    cbr_fixtures, cbr_conflicts, _ = S.derive_cbr_fixtures(
        2023, cbr_manifest, resolve)
    out = {}
    for row in S.load_hoopr_rows(2023, hoopr_manifest):
        if row["game_date"] not in slate_dates:
            continue
        hsl, asl = resolve(row["home_location"]), resolve(
            row["away_location"])
        if hsl is None or asl is None:
            continue
        if hsl in S.ILLINOIS_SLUGS or asl in S.ILLINOIS_SLUGS:
            continue
        try:
            hsc, asc = int(row["home_score"]), int(row["away_score"])
        except (TypeError, ValueError):
            continue
        key = (row["game_date"], tuple(sorted((hsl, asl))))
        if key in cbr_conflicts or key not in cbr_fixtures:
            continue
        if cbr_fixtures[key] != {hsl: hsc, asl: asc}:
            continue
        sched = schedules[row["id"]]
        out.setdefault(row["game_date"], []).append({
            "espn_game_id": row["id"], "date": row["game_date"],
            "home_slug": hsl, "away_slug": asl,
            "home_espn_id": sched["home_id"],
            "away_espn_id": sched["away_id"],
            "tip_utc": sched["game_date_time"],
            "neutral_site": row["neutral_site"] == "TRUE",
            "home_score": hsc, "away_score": asc})
    return out


def main():
    results = {"family": "CBB_TORVIK_EFFICIENCY_V1_TEAM_TOTALS",
               "check": "NON_COUNTED forward landing check (F-1)",
               "assertions": []}

    def check(name, ok, detail=""):
        results["assertions"].append(
            {"name": name, "ok": bool(ok), "detail": str(detail)})
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    runner = CbbTeamTotalForwardRunner()
    results["pins_verified"] = runner.pins
    crosswalk = load_crosswalk(CROSSWALK_PATH)
    fixtures_by_date = agreed_fixtures(DATES)
    tmp = tempfile.mkdtemp(prefix="cbb_tt_landing_")

    all_records = []
    equivalence = {"games": 0, "candidate_points_exact": 0,
                   "baseline_points_exact": 0}
    for slate_date in DATES:
        store, parsed = build_vintage_store(tmp, slate_date)
        vintage = load_vintage(slate_date, store)
        games = []
        expected_by_event = {}
        picked = []
        for fx in fixtures_by_date[slate_date]:
            if len(picked) >= MAX_GAMES_PER_DATE:
                break
            if fx["home_slug"] not in parsed["by_slug"] or \
                    fx["away_slug"] not in parsed["by_slug"]:
                continue
            picked.append(fx)
        for fx in picked:
            away_team = crosswalk.for_espn_id(fx["away_espn_id"])
            home_team = crosswalk.for_espn_id(fx["home_espn_id"])
            assert away_team.canonical_id == fx["away_slug"]
            assert home_team.canonical_id == fx["home_slug"]
            hr = parsed["by_slug"][fx["home_slug"]]
            ar = parsed["by_slug"][fx["away_slug"]]
            screen_fx = {
                "adj_o_home": hr[0], "adj_d_home": hr[1],
                "tempo_home": hr[2], "adj_o_away": ar[0],
                "adj_d_away": ar[1], "tempo_away": ar[2],
                "league_mean_eff": parsed["league_mean_eff"],
                "league_mean_tempo": parsed["league_mean_tempo"]}
            cand = TT.candidate_team_points(screen_fx)
            base = TT.simple_baseline_team_points(screen_fx)
            expected_by_event[fx["espn_game_id"]] = (cand, base)
            equivalence["games"] += 1
            tip = datetime.fromisoformat(
                fx["tip_utc"].replace("Z", "+00:00"))
            cap = (tip - timedelta(hours=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
            games.append(CbbSlateGame(
                espn_event_id=fx["espn_game_id"], slate_date=slate_date,
                away_espn_id=fx["away_espn_id"],
                home_espn_id=fx["home_espn_id"],
                neutral_site=fx["neutral_site"], tip_utc=fx["tip_utc"],
                entry_quotes={
                    "TEAM_TOTAL_AWAY": PairedQuote(
                        line=round_half(cand[1]), side_a_price=-110,
                        side_b_price=-110, side_a_captured_at=cap,
                        side_b_captured_at=cap,
                        capture_source="SYNTHETIC_LANDING_FIXTURE"),
                    "TEAM_TOTAL_HOME": PairedQuote(
                        line=round_half(cand[0]), side_a_price=-110,
                        side_b_price=-110, side_a_captured_at=cap,
                        side_b_captured_at=cap,
                        capture_source="SYNTHETIC_LANDING_FIXTURE")}))
        now = min(datetime.fromisoformat(
            g.tip_utc.replace("Z", "+00:00")) for g in games) \
            - timedelta(minutes=30)
        out = runner.price_slate(slate_date, games, vintage=vintage,
                                 now=now)
        check(f"no refusals on the landing slate ({slate_date})",
              out["refusals"] == [], out["refusals"])
        check(f"2 team records per game ({slate_date})",
              len(out["records"]) == 2 * len(games))
        for rec in out["records"]:
            cand, base = expected_by_event[rec["espn_event_id"]]
            idx = 0 if rec["venue"] == "HOME" else 1
            if rec["model_team_points_candidate"] == cand[idx]:
                equivalence["candidate_points_exact"] += 1
            if rec["model_team_points_baseline_simple"] == base[idx]:
                equivalence["baseline_points_exact"] += 1
            assert rec["counted"] is False
            assert rec["label"] == "NON_COUNTED"
            assert rec["forward_baselines"] == ["SIMPLE_RATINGS"]
            assert not any("naive" in k for k in rec)
        all_records.extend(out["records"])

        if slate_date == "2023-02-25":
            il_game = CbbSlateGame(
                espn_event_id="landing-il-demo", slate_date=slate_date,
                away_espn_id="150", home_espn_id="356",
                neutral_site=False, tip_utc="2023-02-25T18:00:00Z",
                entry_quotes={"TEAM_TOTAL_HOME": PairedQuote(
                    line=70.5, side_a_price=-110, side_b_price=-110,
                    side_a_captured_at="2023-02-25T17:00:00Z",
                    side_b_captured_at="2023-02-25T17:00:00Z",
                    capture_source="SYNTHETIC_LANDING_FIXTURE")})
            il_out = runner.price_slate(
                slate_date, [il_game], vintage=vintage,
                now=datetime.fromisoformat("2023-02-25T17:30:00+00:00"))
            check("Illinois game excluded",
                  il_out["records"] == [] and il_out["refusals"][0][
                      "reason"] == "ILLINOIS_COLLEGE_EXCLUDED",
                  il_out["refusals"])

    check("readout equivalence: candidate team points exact on every "
          "record", equivalence["candidate_points_exact"]
          == 2 * equivalence["games"], equivalence)
    check("readout equivalence: baseline team points exact on every "
          "record", equivalence["baseline_points_exact"]
          == 2 * equivalence["games"], equivalence)
    results["equivalence"] = equivalence

    for name, fn in (
            ("price_slate counted=True",
             lambda: runner.price_slate(
                 "2023-02-25", [], vintage=vintage,
                 now=datetime.fromisoformat("2023-02-25T00:00:00+00:00"),
                 counted=True)),
            ("run_forward_test", lambda: runner.run_forward_test([]))):
        try:
            fn()
            check(f"counted refusal: {name}", False, "no refusal")
        except CbbForwardError as exc:
            check(f"counted refusal: {name}",
                  exc.reason == "CBB_TEAM_TOTAL_FORWARD_NOT_FROZEN",
                  exc.reason)

    sample_path = OUT_DIR / "entry_records_sample.jsonl"
    try:
        write_entry_records(all_records, sample_path)
        results["records_file_state"] = "written"
    except CbbForwardError as exc:
        assert exc.reason == "RECORD_FILE_EXISTS", exc.reason
        existing = sample_path.read_text(encoding="utf-8")
        regenerated = "".join(
            json.dumps(r, sort_keys=True) + "\n" for r in all_records)
        check("re-run reproduces the committed sample byte-identically",
              existing == regenerated)
        results["records_file_state"] = "preexisting_identical"
    results["records_written"] = len(all_records)
    results["records_file"] = "entry_records_sample.jsonl"
    results["verdict"] = "LANDING CHECK PASS (NON_COUNTED)"
    (OUT_DIR / "LANDING_CHECK.json").write_text(
        json.dumps(results, indent=1))
    print(f"LANDING CHECK PASS: {equivalence['games']} games, "
          f"{len(all_records)} team records, all NON_COUNTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
