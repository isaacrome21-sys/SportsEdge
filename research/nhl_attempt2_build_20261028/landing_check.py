#!/usr/bin/env python3
"""Landing check for NHL_ATTEMPT2_V1 on the pinned MoneyPuck samples.

Build-stage proof, NON-COUNTED in every field: the full pipeline runs
end-to-end on the admission's hash-pinned sample pulls
(~/workspace/moneypuck_data, verified against
research/nhl_moneypuck_admission_20261028/sample_manifest.json before
any row is read) and every enforcement point is exercised on real data:

1. PIN VERIFICATION — all six sample files recompute to their manifest
   hashes (6/6 PIN_MATCH or the check refuses).
2. STRICTLY-PRIOR PARITY — Anaheim's features for its 2026-10-20 game
   reproduce the admission record's own strictly-prior demonstration
   (8 games, max gameDate 20261019, xGoalsFor 25.708 / xGoalsAgainst
   27.884) from this construction's loader, collector semantics.
3. VINTAGE REFUSAL — a rate book asked to pool 2025 + 2026 rows with no
   treatment refuses XG_VINTAGE_POOLING_REFUSED on real rows; under the
   declared treatment the legacy rows are excluded and counted.
4. FROZEN-PATH REFUSAL — params_from_constants() refuses
   NHL_ATTEMPT2_NOT_FROZEN while the freeze-owed values are unpinned.
5. SLATE PRICING — the 2026-10-26 slate (the pinned pull's last date)
   priced strictly-prior under explicit BUILD-STAGE ILLUSTRATIVE
   parameters (disclosed in the result; NOT the frozen constants,
   which do not exist yet), features restricted to the declared
   regular-season window (gameDate >= 20261008), goaltenders
   unconfirmed -> blend, degraded=True.

Nothing here is a screen, a freeze, or validation evidence: admission
section 8 — fits and runs on this data are design evidence only, and
verification accrues forward only (Stage B, Dec 1 2026 - Jan 31 2027,
gated on the Nov 30 2026 Stage A verdict).

Stdlib only. Usage: landing_check.py --data-dir DIR --manifest PATH
"""
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sportsedge import nhl_attempt2 as A          # noqa: E402
from sportsedge import nhl_attempt2_constants as C  # noqa: E402

ILLUSTRATIVE = A.Params(
    half_life_games=20.0,          # BUILD-STAGE ILLUSTRATIVE — not frozen
    shrinkage_prior_games=10.0,    # BUILD-STAGE ILLUSTRATIVE — not frozen
    goalie_shrinkage_games=5.0,    # BUILD-STAGE ILLUSTRATIVE — not frozen
    phi=C.DISPERSION_PHI,          # the build-stage fit (fitted_constants)
    ot_home_win_share=C.OT_HOME_WIN_SHARE,      # neutral placeholder
    ot_decision_share=C.OT_DECISION_SHARE,      # neutral placeholder
    treatment=C.DECLARED_CROSS_VINTAGE_TREATMENT,
)
SLATE_DATE = 20261026


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main(argv):
    data_dir = None
    manifest_path = None
    i = 0
    while i < len(argv):
        if argv[i] == "--data-dir":
            data_dir = Path(argv[i + 1]); i += 2
        elif argv[i] == "--manifest":
            manifest_path = Path(argv[i + 1]); i += 2
        else:
            print(f"unknown arg: {argv[i]}", file=sys.stderr)
            return 2
    if data_dir is None or manifest_path is None:
        print("usage: landing_check.py --data-dir DIR --manifest PATH",
              file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = {"construction_id": C.CONSTRUCTION_ID,
              "check": "LANDING_CHECK — NON_COUNTED, BUILD_STAGE",
              "counted": False, "frozen": False,
              "validation_credit": False, "play_eligible": False}

    # 1. Pins.
    pins = []
    for entry in manifest["samples"]:
        path = data_dir / entry["stored_as"]
        actual = sha256_of(path) if path.exists() else None
        pins.append({"stored_as": entry["stored_as"],
                     "status": "PIN_MATCH" if actual == entry["sha256"]
                     else "PIN_MISMATCH"})
    result["pin_verification"] = pins
    if any(p["status"] != "PIN_MATCH" for p in pins):
        result["verdict"] = "REFUSED — MANIFEST_MISMATCH"
        print(json.dumps(result, indent=2, sort_keys=True))
        return 3

    # 2. ANA strictly-prior parity (collector semantics, all 2026 rows).
    rows26 = A.load_team_rows(data_dir / "all_teams.csv", seasons={2026})
    ana = [r for r in rows26
           if r.team == "ANA" and r.gamedate < 20261020]
    result["strictly_prior_parity_ANA_20261020"] = {
        "games_used": len(ana),
        "max_gameDate_used": max(r.gamedate for r in ana),
        "xGoalsFor_sum": round(sum(r.xgoals_for for r in ana), 3),
        "xGoalsAgainst_sum": round(sum(r.xgoals_against for r in ana), 3),
        "admission_demonstration": {"games_used": 8,
                                    "max_gameDate_used": 20261019,
                                    "xGoalsFor_sum": 25.708,
                                    "xGoalsAgainst_sum": 27.884},
    }
    p = result["strictly_prior_parity_ANA_20261020"]
    p["match"] = (p["games_used"] == 8 and p["max_gameDate_used"] == 20261019
                  and p["xGoalsFor_sum"] == 25.708
                  and p["xGoalsAgainst_sum"] == 27.884)

    # 3. Vintage enforcement on real rows.
    rows_mixed = A.load_team_rows(data_dir / "all_teams.csv",
                                  seasons={2025, 2026})
    demo = {}
    try:
        A.build_rate_book(rows_mixed, SLATE_DATE,
                          A.Params(half_life_games=20.0,
                                   shrinkage_prior_games=10.0,
                                   goalie_shrinkage_games=5.0,
                                   treatment=None))
        demo["no_treatment"] = "NO REFUSAL — ENFORCEMENT FAILURE"
    except A.Attempt2Refusal as refusal:
        demo["no_treatment"] = refusal.code
    book = A.build_rate_book(rows_mixed, SLATE_DATE, ILLUSTRATIVE)
    demo["declared_treatment"] = {
        "rows_used": book.rows_used,
        "vintage_excluded_rows": book.vintage_excluded_rows}
    result["vintage_enforcement"] = demo

    # 4. Frozen-path refusal.
    try:
        A.params_from_constants()
        result["frozen_path"] = "NO REFUSAL — ENFORCEMENT FAILURE"
    except A.Attempt2Refusal as refusal:
        result["frozen_path"] = refusal.code

    # 5. Price the slate, regular-season window, strictly prior.
    start = C.REGULAR_SEASON_START[2026]
    windowed = [r for r in rows26 if r.gamedate >= start]
    goalies = [g for g in A.load_goalie_rows(
        data_dir / "season_goalies_2026.zip", seasons={2026})
        if g.gamedate >= start]
    slate_rows = [r for r in rows26 if r.gamedate == SLATE_DATE
                  and not r.playoff_game]
    games = []
    seen = set()
    for r in slate_rows:
        key = tuple(sorted((r.team, r.opponent)))
        if key in seen:
            continue
        seen.add(key)
        home = r.team if r.home_or_away == "HOME" else r.opponent
        away = r.opponent if r.home_or_away == "HOME" else r.team
        games.append((home, away))
    priced = []
    for home, away in sorted(games):
        price = A.price_game(windowed, goalies, home, away, SLATE_DATE,
                             ILLUSTRATIVE)
        sim = price.sim
        o55, u55, _ = sim.totals(5.5)
        o65, u65, _ = sim.totals(6.5)
        priced.append({
            "matchup": f"{away} @ {home}",
            "mu_home": round(price.mu_home, 4),
            "mu_away": round(price.mu_away, 4),
            "p_home_ml": round(sim.p_home_ml, 4),
            "p_away_ml": round(sim.p_away_ml, 4),
            "p_home_reg_win": round(sim.p_home_reg_win, 4),
            "p_reg_tie": round(sim.p_reg_tie, 4),
            "p_away_reg_win": round(sim.p_away_reg_win, 4),
            "p_home_puck_line_minus15": round(
                sim.p_home_puck_line_minus15, 4),
            "p_away_puck_line_plus15": round(
                sim.p_away_puck_line_plus15, 4),
            "total_5_5": {"over": round(o55, 4), "under": round(u55, 4)},
            "total_6_5": {"over": round(o65, 4), "under": round(u65, 4)},
            "home_games_used": price.home_rate.games,
            "away_games_used": price.away_rate.games,
            "degraded_goalie_blend": price.degraded,
            "counted": False, "frozen": False})
    result["slate_20261026"] = {
        "parameters": "BUILD-STAGE ILLUSTRATIVE — half_life 20 games, "
                      "shrinkage K 10 games, goalie K 5 games, phi = "
                      "build fit, OT shares = neutral placeholders; "
                      "NOT FROZEN, NOT THE PRICING PATH",
        "feature_window": f"regular season, gameDate >= {start}, "
                          f"strictly before {SLATE_DATE}",
        "games": priced}
    result["verdict"] = "LANDING CHECK COMPLETE — machinery runs "
    result["verdict"] += "end-to-end on pinned data; nothing counted"
    out = Path(__file__).with_name("landing_check_result.json")
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
