"""Signed bias by season and band, same 4,374 test games as bt_nba_lines.py (runs its lines 1-165 unchanged)."""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
src = (HERE / "bt_nba_lines.py").read_text().splitlines()
ns = {"__file__": str(HERE / "bt_nba_lines.py"), "__name__": "bt"}
exec(compile("\n".join(src[:165]), "bt_nba_lines.py", "exec"), ns)
test, boot = ns["test"], ns["boot"]
assert len(test) == 4374, len(test)
def band_sp(g):
    a = abs(g["spread"]); return "0-3" if a < 3 else "3-7" if a < 7 else "7-11" if a < 11 else "11+"
def band_tot(g):
    o = g["ou"]; return "<215" if o < 215 else "215-225" if o < 225 else "225-235" if o < 235 else "235+"
out = {"note": "bias = mean(prediction - actual), points; positive = prediction too high (home margin for spread, game total for total). CI: date-cluster bootstrap, seed 20261017, 2000 resamples.", "n": len(test)}
def block(key, pred, actual, grp):
    res = {}
    groups = sorted({grp(g) for g, *_ in test})
    for G in ["ALL"] + groups:
        rows = [(g, mm, tt) for g, mm, tt in test if G == "ALL" or grp(g) == G]
        dates = [g["date"] for g, *_ in rows]
        res[G] = {"model": boot([pred(g, mm, tt) - actual(g) for g, mm, tt in rows], dates),
                  "line": boot([(g["spread"] if key == "spread" else g["ou"]) - actual(g) for g, mm, tt in rows], dates),
                  "model_minus_line": boot([pred(g, mm, tt) - (g["spread"] if key == "spread" else g["ou"]) for g, mm, tt in rows], dates)}
    return res
sp = lambda g, mm, tt: mm
to = lambda g, mm, tt: tt
out["spread_by_season"] = block("spread", sp, lambda g: g["margin"], lambda g: g["season"])
out["spread_by_band"] = block("spread", sp, lambda g: g["margin"], band_sp)
out["total_by_season"] = block("total", to, lambda g: g["total"], lambda g: g["season"])
out["total_by_band"] = block("total", to, lambda g: g["total"], band_tot)
(HERE / "nba_bias_results.json").write_text(json.dumps(out, indent=1))
for k in ("spread_by_season", "spread_by_band", "total_by_season", "total_by_band"):
    print(k)
    for G, r in out[k].items():
        f = lambda c: f"{c['mean']:+.2f} [{c['lo']:+.2f},{c['hi']:+.2f}]"
        print(f"  {G:8s} n={r['model']['n']:5d} model {f(r['model'])}  line {f(r['line'])}  model-line {f(r['model_minus_line'])}")
# Favorite-oriented spread view: (prediction - x) * sign(line), so negative = less extreme than the favorite's line.
fav = {}
for B in ["ALL", "0-3", "3-7", "7-11", "11+"]:
    rows = [(g, mm, tt) for g, mm, tt in test if g["spread"] != 0 and (B == "ALL" or band_sp(g) == B)]
    s = lambda g: 1.0 if g["spread"] > 0 else -1.0
    d = [g["date"] for g, *_ in rows]
    fav[B] = {"model_minus_line_fav": boot([(mm - g["spread"]) * s(g) for g, mm, tt in rows], d),
              "model_minus_actual_fav": boot([(mm - g["margin"]) * s(g) for g, mm, tt in rows], d),
              "line_minus_actual_fav": boot([(g["spread"] - g["margin"]) * s(g) for g, mm, tt in rows], d)}
out["spread_by_band_favorite_oriented"] = fav
(HERE / "nba_bias_results.json").write_text(json.dumps(out, indent=1))
print("spread_by_band_favorite_oriented")
for B, r in fav.items():
    f = lambda c: f"{c['mean']:+.2f} [{c['lo']:+.2f},{c['hi']:+.2f}]"
    print(f"  {B:5s} n={r['model_minus_line_fav']['n']:5d} model-line {f(r['model_minus_line_fav'])}  model-actual {f(r['model_minus_actual_fav'])}  line-actual {f(r['line_minus_actual_fav'])}")
