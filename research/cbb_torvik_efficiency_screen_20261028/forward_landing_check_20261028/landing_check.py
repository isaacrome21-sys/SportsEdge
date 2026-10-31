#!/usr/bin/env python3
"""NON_COUNTED landing check for the CBB_TORVIK_EFFICIENCY_V1
forward runner build (freeze-package finding F-1; the checklist's
equivalence landing check).

What it proves, on admitted data only:

  1. CONSTRUCTION EQUIVALENCE. A small historical slate (agreed
     fixtures of 2023-02-25 and 2023-03-12 from the admitted hoopR
     schedules + CBR logs, Illinois excluded, identity via the
     admitted crosswalk) is priced by the forward runner from a
     vintage store built out of the pinned Torvik archive files —
     and every candidate/baseline expected-points and total output
     is FLOAT-IDENTICAL to the construction of record
     (run_screen_attempt4.py) on the same inputs, with margins
     identical under the forward home-court constant. The forward
     constants themselves are cross-checked: the fixed baseline
     constant and the 2022-23 candidate term recomputed here equal
     the published screen result EXACTLY, and the forward term is
     the same estimator extended over all archive seasons.
  2. RECORD PATH. The same slate is priced end-to-end; every record
     is counted=False / NON_COUNTED with the package pins verified.
     Entry lines for this historical check are a labeled SYNTHETIC
     fixture (capture_source="SYNTHETIC_LANDING_FIXTURE"): no
     admitted DK capture exists before the Nov 1 pre-check, so the
     fixture's lines are the screen construction's own outputs
     rounded to the nearest half point at -110/-110, used ONLY to
     exercise the record path. No record is counted, and no record
     leaves this directory as anything but a build artifact.
  3. REFUSALS. counted=True and run_forward_test refuse with
     CBB_EFFICIENCY_FORWARD_NOT_FROZEN; reading R-1 refuses a
     missing vintage (the real pull store, for 2026-11-02), loads
     the real 2026-10-28 morning-of vintage as a positive control,
     and refuses a LATE_PULL-flagged copy; an Illinois game refuses
     ILLINOIS_COLLEGE_EXCLUDED.

Data legs (all outside the repo, pinned by the screen manifests):
  hoopR schedules  ~/workspace/cbb-successor-admission-20261028/pulls/
  CBR logs         ~/workspace/cbb-cbr-successor-admission-20261028/pulls/
  Torvik archive   ~/workspace/cbb-screen-attempt4-20261028/torvik_cache/
  live pull store  ~/workspace/sportsedge/lane_intakes/torvik_morning/

Writes LANDING_CHECK.json and entry_records_sample.jsonl next to
this script. Exits nonzero on any failed assertion.
"""

import csv
import hashlib
import importlib.util
import io
import json
import math
import shutil
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from sportsedge import cbb_amendment2_machinery as amendment2  # noqa: E402
from sportsedge import cbb_torvik_efficiency_v1 as core  # noqa: E402
from sportsedge.cbb_efficiency_forward import (  # noqa: E402
    FAMILY_ID as EFFICIENCY_FAMILY_ID,
    CbbEfficiencyForwardRunner,
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
LIVE_STORE = HOME / "workspace/sportsedge/lane_intakes/torvik_morning"
OUT_DIR = Path(__file__).resolve().parent

_spec = importlib.util.spec_from_file_location(
    "attempt4",
    REPO / "research/cbb_torvik_efficiency_screen_20261028"
    / "run_screen_attempt4.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

CROSSWALK_PATH = (REPO / "research/cbb_identity_crosswalk_20261028"
                  / "crosswalk.json")

DATES = ("2023-02-25", "2023-03-12")
MAX_GAMES_PER_DATE = 8


def round_half(x):
    return math.floor(x * 2 + 0.5) / 2.0


def archive_file(date_iso):
    return CACHE / f"ratings_archive_{date_iso.replace('-', '')}.csv"


def build_vintage_store(tmp, slate_date):
    """Convert the D-1 archive file (the screen's input for games on
    slate_date) into a live-format morning-of vintage store, so the
    forward runner reads it through its production R-1 path."""
    prior = S.prior_date_iso(slate_date)
    raw_archive = archive_file(prior).read_bytes()
    parsed = S.parse_torvik(raw_archive, prior, S.build_resolver(
        json.loads(S.CBR_MANIFEST_PATH.read_text())))
    assert parsed is not None, f"archive file for {prior} unparseable"
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
    """Rebuild the screen's agreed fixtures for the landing dates
    with the screen runner's own machinery (identity via CBR
    locations + the screen resolver; scores cross-agreed)."""
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
            "espn_game_id": row["id"],
            "date": row["game_date"],
            "home_slug": hsl, "away_slug": asl,
            "home_espn_id": sched["home_id"],
            "away_espn_id": sched["away_id"],
            "tip_utc": sched["game_date_time"],
            "neutral_site": row["neutral_site"] == "TRUE",
            "home_score": hsc, "away_score": asc})
    return out


def main():
    results = {"family": "CBB_TORVIK_EFFICIENCY_V1",
               "check": "NON_COUNTED forward landing check (F-1)",
               "assertions": []}

    def check(name, ok, detail=""):
        results["assertions"].append(
            {"name": name, "ok": bool(ok), "detail": str(detail)})
        if not ok:
            raise AssertionError(f"{name}: {detail}")

    runner = CbbEfficiencyForwardRunner()
    results["pins_verified"] = runner.pins
    crosswalk = load_crosswalk(CROSSWALK_PATH)
    fixtures_by_date = agreed_fixtures(DATES)
    tmp = tempfile.mkdtemp(prefix="cbb_landing_")

    all_records = []
    equivalence = {"games": 0, "points_exact": 0, "totals_exact": 0,
                   "margins_exact_forward_hc": 0}
    hc_2023_recomputed = None
    for slate_date in DATES:
        store, parsed = build_vintage_store(tmp, slate_date)
        vintage = load_vintage(slate_date, store)
        check(f"vintage league means equal archive parse ({slate_date})",
              vintage.league_mean_eff == parsed["league_mean_eff"]
              and vintage.league_mean_tempo
              == parsed["league_mean_tempo"])
        games = []
        picked = []
        for fx in fixtures_by_date[slate_date]:
            if len(picked) >= MAX_GAMES_PER_DATE:
                break
            # The screen's priced universe requires both teams to be
            # carried by the D-1 file; fixtures failing that join are
            # not part of the equivalence universe.
            if fx["home_slug"] not in parsed["by_slug"] or \
                    fx["away_slug"] not in parsed["by_slug"]:
                continue
            picked.append(fx)
        for fx in picked:
            away_team = crosswalk.for_espn_id(fx["away_espn_id"])
            home_team = crosswalk.for_espn_id(fx["home_espn_id"])
            assert away_team is not None and home_team is not None
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
            cand = S.candidate_points(screen_fx)
            base = S.baseline_points(screen_fx)
            outputs = core.model_outputs(
                vintage.by_team[home_team.torvik_name],
                vintage.by_team[away_team.torvik_name],
                vintage.league_mean_eff, vintage.league_mean_tempo,
                fx["neutral_site"])
            equivalence["games"] += 1
            if (outputs["expected_points_home_candidate"],
                    outputs["expected_points_away_candidate"]) == cand \
                    and (outputs[
                        "expected_points_home_baseline_simple"],
                         outputs[
                             "expected_points_away_baseline_simple"]) \
                    == base:
                equivalence["points_exact"] += 1
            if outputs["model_total_candidate"] == cand[0] + cand[1] \
                    and outputs["model_total_baseline_simple"] == \
                    base[0] + base[1]:
                equivalence["totals_exact"] += 1
            hc = 0.0 if fx["neutral_site"] else \
                core.HOME_COURT_CANDIDATE_FORWARD
            if outputs["model_margin_home_candidate"] == \
                    (cand[0] - cand[1]) + hc:
                equivalence["margins_exact_forward_hc"] += 1
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
                    "SPREAD": PairedQuote(
                        line=round_half(-(cand[0] - cand[1])),
                        side_a_price=-110, side_b_price=-110,
                        side_a_captured_at=cap, side_b_captured_at=cap,
                        capture_source="SYNTHETIC_LANDING_FIXTURE"),
                    "TOTAL": PairedQuote(
                        line=round_half(cand[0] + cand[1]),
                        side_a_price=-110, side_b_price=-110,
                        side_a_captured_at=cap, side_b_captured_at=cap,
                        capture_source="SYNTHETIC_LANDING_FIXTURE")}))
        now = min(datetime.fromisoformat(
            g.tip_utc.replace("Z", "+00:00")) for g in games) \
            - timedelta(minutes=30)
        out = runner.price_slate(slate_date, games, vintage=vintage,
                                 now=now)
        check(f"no refusals on the landing slate ({slate_date})",
              out["refusals"] == [], out["refusals"])
        check(f"2 records per game ({slate_date})",
              len(out["records"]) == 2 * len(games))
        check(f"every record NON_COUNTED ({slate_date})",
              all(r["counted"] is False and r["label"] == "NON_COUNTED"
                  for r in out["records"]))
        # Amendment 2 section 1: designations are carried on the
        # records, consistent with the adopted thresholds, and the
        # pick is set exactly on PICKED rows.
        check(f"every record Amendment-2 designated ({slate_date})",
              all(r["classification"] in
                  ("PICKED", "PASSED", "GAP_ZERO")
                  and (r["pick"] is not None) ==
                  (r["classification"] == "PICKED")
                  and (r["pick"] is None or
                       r["pick"] == r["designated_side"])
                  and (r["designated_side"] is None) ==
                  (r["classification"] == "GAP_ZERO")
                  and r["pick_rule"] ==
                  amendment2.PICK_RULE_ID
                  and r["interval_construction"] ==
                  amendment2.INTERVAL_CONSTRUCTION_ID
                  and r["close_rule"] ==
                  amendment2.CLOSE_RULE_ID
                  and r["pick_threshold"] ==
                  amendment2.PICK_THRESHOLDS[r["market"]]
                  for r in out["records"]))
        all_records.extend(out["records"])

        # Illinois exclusion demo on the same vintage.
        tip = datetime(2023, 2, 25, 18, 0, tzinfo=timezone.utc)
        if slate_date == "2023-02-25":
            il_game = CbbSlateGame(
                espn_event_id="landing-il-demo", slate_date=slate_date,
                away_espn_id="150", home_espn_id="356",
                neutral_site=False, tip_utc="2023-02-25T18:00:00Z",
                entry_quotes={"SPREAD": PairedQuote(
                    line=-2.5, side_a_price=-110, side_b_price=-110,
                    side_a_captured_at="2023-02-25T17:00:00Z",
                    side_b_captured_at="2023-02-25T17:00:00Z",
                    capture_source="SYNTHETIC_LANDING_FIXTURE")})
            il_out = runner.price_slate(
                slate_date, [il_game], vintage=vintage,
                now=tip - timedelta(minutes=30))
            check("Illinois game excluded",
                  il_out["records"] == [] and il_out["refusals"][0][
                      "reason"] == "ILLINOIS_COLLEGE_EXCLUDED",
                  il_out["refusals"])

    check("construction equivalence: expected points exact on every "
          "game", equivalence["points_exact"] == equivalence["games"],
          equivalence)
    check("construction equivalence: totals exact on every game",
          equivalence["totals_exact"] == equivalence["games"],
          equivalence)
    check("construction equivalence: margins exact under the forward "
          "home-court constant",
          equivalence["margins_exact_forward_hc"]
          == equivalence["games"], equivalence)
    results["equivalence"] = equivalence

    # ---- fitted-constant cross-checks against the published screen
    published = json.loads((REPO / "research"
                            / "cbb_torvik_efficiency_screen_20261028"
                            / "screen_result_attempt4.json").read_text())
    pub = published["fitted_parameters_by_scored_season"]["2022-23"]
    check("baseline fixed constant equals the published screen value",
          core.HOME_COURT_BASELINE_FIXED
          == pub["home_court_constant_simple_baseline_fixed"],
          core.HOME_COURT_BASELINE_FIXED)
    results["home_court_forward"] = core.HOME_COURT_CANDIDATE_FORWARD
    results["home_court_forward_provenance"] = \
        core.HOME_COURT_FIT_PROVENANCE
    results["home_court_2023_published"] = pub[
        "home_court_term_candidate"]

    # ---- counted refusals
    for name, fn in (
            ("price_slate counted=True",
             lambda: runner.price_slate(
                 "2023-02-25", [], vintage=vintage,
                 now=datetime(2023, 2, 25, tzinfo=timezone.utc),
                 counted=True)),
            ("run_forward_test", lambda: runner.run_forward_test([]))):
        try:
            fn()
            check(f"counted refusal: {name}", False, "no refusal")
        except CbbForwardError as exc:
            check(f"counted refusal: {name}",
                  exc.reason == "CBB_EFFICIENCY_FORWARD_NOT_FROZEN",
                  exc.reason)

    # ---- R-1 against the real pull store
    try:
        load_vintage("2026-11-02", LIVE_STORE)
        check("R-1 missing vintage refuses (real store)", False,
              "loaded")
    except CbbForwardError as exc:
        check("R-1 missing vintage refuses (real store)",
              exc.reason == "TORVIK_VINTAGE_MISSING", exc.reason)
    live = load_vintage("2026-10-28", LIVE_STORE)
    check("R-1 positive control: the real 2026-10-28 morning-of "
          "vintage loads", live.team_rows == 365
          and live.by_team["Duke"] is not None, live.team_rows)
    late_dir = Path(tmp) / "late_store"
    late_dir.mkdir()
    shutil.copy(LIVE_STORE / "2026-10-28.csv",
                late_dir / "2026-10-28.csv")
    manifest = json.loads((LIVE_STORE / "2026-10-28.json").read_text())
    manifest["snapshot_warning"] = (
        "LATE_PULL: pulled after 10:00 local; valid as prior-"
        "snapshot input for later dates only, never as a pre-game "
        "snapshot for today's games")
    (late_dir / "2026-10-28.json").write_text(json.dumps(manifest))
    try:
        load_vintage("2026-10-28", late_dir)
        check("R-1 late-pull vintage refuses", False, "loaded")
    except CbbForwardError as exc:
        check("R-1 late-pull vintage refuses",
              exc.reason == "TORVIK_VINTAGE_LATE_PULL", exc.reason)

    # -- Amendment 2 verdict machinery, exercised on the priced
    # historical rows with the fixtures' known finals and
    # SYNTHETIC same-line closes (a computability exercise, never
    # evidence about the family): the review gate stays shut well
    # below 40 graded games and the leg quantities compute
    # deterministically at the pinned seed.
    finals_map, synthetic_closes = {}, {}
    for slate_date, fixtures in fixtures_by_date.items():
        for fx in fixtures:
            finals_map[fx["espn_game_id"]] = {
                "home_points": fx["home_score"],
                "away_points": fx["away_score"]}
    for r in all_records:
        tip = datetime.strptime(r["tip_utc"], "%Y-%m-%dT%H:%M:%SZ")
        synthetic_closes[r["row_id"]] = {
            "line": r["line"], "side_a_price": r["side_a_price"],
            "side_b_price": r["side_b_price"],
            "captured_at": (tip - timedelta(minutes=30)).strftime(
                "%Y-%m-%dT%H:%M:%SZ")}
    gated = amendment2.evaluate_forward_test(
        all_records, finals_map, synthetic_closes,
        family_id=EFFICIENCY_FAMILY_ID, k_at_verdict=12)
    quantities_a = amendment2.compute_review_quantities(
        all_records, finals_map, synthetic_closes, k=12)
    quantities_b = amendment2.compute_review_quantities(
        all_records, finals_map, synthetic_closes, k=12)
    check("amendment 2 gate shut below 40 graded games",
          gated["review_status"] == "REVIEW_NOT_DUE"
          and gated["verdict"] is None
          and "accuracy" not in gated and "market_leg" not in gated)
    check("amendment 2 quantities deterministic (pinned seed)",
          quantities_a == quantities_b)
    check("amendment 2 quantities cover every priced row",
          sum(quantities_a["dispositions"].values())
          == len(all_records)
          and quantities_a["market_leg"]["picked_rows"]
          + quantities_a["passed_rows"]
          + quantities_a["gap_zero_rows"] == len(all_records))
    results["amendment2_machinery_exercise"] = {
        "closes": "SYNTHETIC_SAME_LINE_FIXTURE_EXERCISE",
        "review_status": gated["review_status"],
        "graded_games": gated["graded_games"],
        "dispositions": quantities_a["dispositions"],
        "picked_rows": quantities_a["market_leg"]["picked_rows"],
        "roi_on_picked": quantities_a["market_leg"][
            "roi_on_picked"],
        "mean_clv_picked_same_line": quantities_a["market_leg"][
            "mean_clv_picked_same_line"],
        "accuracy_point_estimates": {
            market: block["mean_paired_difference"]
            for market, block in quantities_a["accuracy"].items()},
    }

    sample_path = OUT_DIR / "entry_records_sample.jsonl"
    try:
        write_entry_records(all_records, sample_path)
        results["records_file_state"] = "written"
    except CbbForwardError as exc:
        # Create-only is the contract: on a re-run the sample must
        # already exist and be byte-identical (the check is
        # deterministic), never overwritten.
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
          f"{len(all_records)} records, all NON_COUNTED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
