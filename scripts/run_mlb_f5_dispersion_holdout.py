"""Pre-registered F5 dispersion fit (2024) and 2025 holdout. See docs/MLB_F5_DISPERSION_PREREG_20261013.md."""
import glob
import json
import os
import sys

from sportsedge.mlb_f5_walkforward import LINES, fit_f5_dispersion, parse_schedule, run_walkforward

cache = sys.argv[1]
games = parse_schedule(json.load(open(f)) for f in sorted(glob.glob(os.path.join(cache, "*.json"))))
g24 = [g for g in games if g["date"].startswith("2024")]
g25 = [g for g in games if g["date"].startswith("2025")]
rows = []
run_walkforward(g24, rows_out=rows)
fit = fit_f5_dispersion(rows)
base = run_walkforward(g25)
cand = run_walkforward(g25, f5_params=(fit["r_f5"], fit["pi"]))
passed = all(cand["lines"][str(x)]["brier_model"] < cand["lines"][str(x)]["brier_naive"]
             and cand["lines"][str(x)]["ll_model"] < cand["lines"][str(x)]["ll_naive"] for x in LINES)
print(json.dumps({"fit_2024": fit, "holdout_2025": {
    str(x): {"n": cand["lines"][str(x)]["n"],
             "brier_candidate": cand["lines"][str(x)]["brier_model"], "brier_naive": cand["lines"][str(x)]["brier_naive"],
             "brier_baseline_nb": base["lines"][str(x)]["brier_model"],
             "ll_candidate": cand["lines"][str(x)]["ll_model"], "ll_naive": cand["lines"][str(x)]["ll_naive"],
             "ll_baseline_nb": base["lines"][str(x)]["ll_model"],
             "mean_p": cand["lines"][str(x)]["mean_p"], "hit_rate": cand["lines"][str(x)]["hit_rate"]} for x in LINES},
    "decision": "PASS_RESEARCH" if passed else "FAIL", "market_baseline": "MISSING"}, indent=1))
