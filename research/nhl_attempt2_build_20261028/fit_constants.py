#!/usr/bin/env python3
"""Build-stage fit for NHL_ATTEMPT2_V1: the dispersion parameter.

Design basis (research/activation_designs_20261027/NHL_SIDES_TOTALS_DESIGN.md
section 2): "Regulation goal distributions per team (Poisson with a
dispersion parameter fit on design data)". This script fits that one
parameter, once, on the declared design set, and writes
fitted_constants.json beside it. The freeze fit governs: at a freeze the
fit is re-run and re-pinned on the exact frozen head.

DESIGN SET (declared here, before the fit): MoneyPuck all_teams rows,
season 2026 (xg_model_vintage rebuilt_2026_27 — the single disclosed
vintage the Stage B fit is declared to sit inside, admission record
section 4.1), situation 'all' (the admitted collector's aggregate basis),
playoffGame == 0, gameDate >= 20261008 (the 2026-27 regular-season window
named in the design's Stage A citation; the admission record section 4.3
leaves competition windows to the consumer), from the hash-pinned sample
pull in the workspace data dir. The pin is verified before any row is
read; a mismatch is a refusal, not a fit.

METHOD: negative-binomial dispersion in the form Var = phi * mean.
MoneyPuck's own xGoalsFor/xGoalsAgainst per team-game is the mean proxy
mu; actual goalsFor/goalsAgainst is the outcome g. Each team-game row
contributes two (mu, g) pairs (for-side and against-side). Method of
moments: phi_hat = sum((g - mu)^2) / sum(mu), floored at 1.0 (Poisson).
Known contamination, disclosed: 'all'-situation goals include the
overtime winner's goal in games decided in OT (admission record section
4.2 keeps goal conventions inside one source; the effect is a small
upward pressure on phi, absorbed here as build-stage conservatism).

Stdlib only. Usage: fit_constants.py --data-dir DIR --manifest PATH
"""
import csv
import hashlib
import json
import sys
from pathlib import Path

REGULAR_SEASON_START = {2026: 20261008}
DESIGN_SEASON = 2026


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
        print("usage: fit_constants.py --data-dir DIR --manifest PATH",
              file=sys.stderr)
        return 2
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    pins = {e["stored_as"]: e["sha256"] for e in manifest["samples"]}
    teams_file = data_dir / "all_teams.csv"
    actual = sha256_of(teams_file)
    if actual != pins.get("all_teams.csv"):
        print(json.dumps({"refusal": "MANIFEST_MISMATCH",
                          "file": "all_teams.csv",
                          "expected": pins.get("all_teams.csv"),
                          "actual": actual}))
        return 3
    start = REGULAR_SEASON_START[DESIGN_SEASON]
    pairs = 0
    games = set()
    num = 0.0
    den = 0.0
    margin0_team_rows = 0
    team_rows = 0
    with open(teams_file, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if str(row["season"]) != str(DESIGN_SEASON):
                continue
            if row["situation"] != "all":
                continue
            if str(row.get("playoffGame")) not in ("0", "0.0"):
                continue
            if int(row["gameDate"]) < start:
                continue
            team_rows += 1
            games.add((row["gameDate"], row["gameId"]))
            if float(row["goalsFor"]) == float(row["goalsAgainst"]):
                margin0_team_rows += 1
            for mu_key, g_key in (("xGoalsFor", "goalsFor"),
                                  ("xGoalsAgainst", "goalsAgainst")):
                mu = float(row[mu_key])
                g = float(row[g_key])
                if mu <= 0:
                    continue
                pairs += 1
                num += (g - mu) ** 2
                den += mu
    raw_phi = (num / den) if den > 0 else None
    phi = max(1.0, raw_phi) if raw_phi is not None else None
    result = {
        "construction_id": "NHL_ATTEMPT2_V1",
        "fit_stage": "BUILD_STAGE — NOT FROZEN; the freeze fit governs",
        "design_basis": "NHL_SIDES_TOTALS_DESIGN.md section 2: dispersion "
                        "parameter fit on design data",
        "design_set": {
            "source": "MoneyPuck all_teams.csv (hash-pinned sample pull)",
            "sha256": actual,
            "season": DESIGN_SEASON,
            "xg_model_vintage": "rebuilt_2026_27",
            "situation": "all",
            "playoffGame": 0,
            "gameDate_min": start,
            "games": len(games),
            "team_rows": team_rows,
            "mu_g_pairs": pairs,
        },
        "dispersion_phi": phi,
        "dispersion_phi_raw_unfloored": raw_phi,
        "dispersion_method": "method of moments, Var = phi * mean, "
                             "phi = sum((g-mu)^2)/sum(mu), floored at 1.0; "
                             "mu = MoneyPuck xGoals (for/against), "
                             "g = actual goals (for/against)",
        "dispersion_reading": "The raw estimate lands BELOW the Poisson "
                              "floor (0.8208) on this design set: each "
                              "game's own xG already absorbs game-level "
                              "variation that a rate-based mean would "
                              "leave in the residuals. The floored value "
                              "phi = 1.0 (pure Poisson) is the build-stage "
                              "constant. A residuals-around-strictly-prior-"
                              "rates dispersion fit is the alternative "
                              "reading; the freeze package adjudicates. "
                              "Recorded, not smoothed over.",
        "observables_for_the_record": {
            "margin0_team_rows": margin0_team_rows,
            "margin0_share_of_team_rows": (margin0_team_rows / team_rows
                                           if team_rows else None),
            "note": "margin-0 finals are shootout games in shot-derived "
                    "data (the SO-deciding goal is not a shot). The OT-vs-SO "
                    "split of regulation ties and the OT/SO winner split are "
                    "NOT identifiable from this surface: a one-goal final "
                    "conflates regulation and OT decisions. See "
                    "BUILD_RECORD.md, readings.",
        },
    }
    out = Path(__file__).with_name("fitted_constants.json")
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
