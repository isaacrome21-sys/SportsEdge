"""Fresh NBA moneyline harness: one score per game, per-game rows persisted.

Inputs: the 43 committed scoreboard caches (verified against MANIFEST.sha256
before this runs). Each game is scored exactly once, by a model fit only on
games that tipped off at least EMBARGO before it (expanding window), after
MIN_TRAIN training games exist. Market leg: MISSING (no captured prices).
"""
import csv, gzip, hashlib, json, math, random, sys
from datetime import datetime, timedelta
from pathlib import Path

REPO = Path(sys.argv[1]); CACHE = Path(sys.argv[2]); OUT = Path(sys.argv[3])
sys.path.insert(0, str(REPO))
from sportsedge.sports.nba.espn_verified_source import NBASource
from sportsedge.sports.nba.nba_game_market_pricing import fit_verified_games, price_game_markets

MIN_TRAIN, EMBARGO, SEED, B = 120, timedelta(days=1), 20261017, 2000

def ts(s): return datetime.fromisoformat(s.replace("Z", "+00:00"))

src = NBASource(getter=lambda u: None)
games = []
for f in sorted(CACHE.glob("scoreboard_*.json")):
    games += src.parse_completed_games(json.loads(f.read_text()), skip_unregistered_teams=True)
uniq = {g["event_id"]: g for g in games}
games = sorted(uniq.values(), key=lambda g: (g["tipoff"], g["event_id"]))

rows = []
for g in games:
    t = ts(g["tipoff"])
    train = [h for h in games if ts(h["tipoff"]) <= t - EMBARGO]
    if len(train) < MIN_TRAIN:
        continue
    ratings, sm, st = fit_verified_games(train)
    p = price_game_markets(home_team_id=g["home_team_id"], away_team_id=g["away_team_id"],
                           ratings=ratings, sigma_margin=sm, sigma_total=st)
    base = min(0.99, max(0.01, sum(h["home_score"] > h["away_score"] for h in train) / len(train)))
    y = 1 if g["home_score"] > g["away_score"] else 0
    rows.append(dict(event_id=g["event_id"], tipoff=g["tipoff"], date=g["tipoff"][:10],
                     home=g["home_team_id"], away=g["away_team_id"], home_score=g["home_score"],
                     away_score=g["away_score"], home_win=y, n_train=len(train),
                     p_candidate=round(p.ml_home_probability, 6), p_baseline=round(base, 6),
                     brier_candidate=round((p.ml_home_probability - y) ** 2, 6),
                     brier_baseline=round((base - y) ** 2, 6),
                     pred_margin=round(p.predicted_margin, 3), pred_total=round(p.predicted_total, 3),
                     margin_err=round(abs(g["home_score"] - g["away_score"] - p.predicted_margin), 3),
                     total_err=round(abs(g["home_score"] + g["away_score"] - p.predicted_total), 3),
                     p_market="MISSING"))

assert len({r["event_id"] for r in rows}) == len(rows), "duplicate scoring"
OUT.mkdir(parents=True, exist_ok=True)
with open(OUT / "per_game_rows.csv", "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n"); w.writeheader(); w.writerows(rows)

def boot(clusters):
    rng = random.Random(SEED); keys = list(clusters); stats = []
    for _ in range(B):
        d = n = 0
        for k in (rng.choice(keys) for _ in keys):
            for r in clusters[k]:
                d += r["brier_candidate"] - r["brier_baseline"]; n += 1
        stats.append(d / n)
    stats.sort(); return stats[int(0.025 * B)], stats[int(0.975 * B) - 1]

n = len(rows)
bc = sum(r["brier_candidate"] for r in rows) / n
bb = sum(r["brier_baseline"] for r in rows) / n
by_game = {r["event_id"]: [r] for r in rows}
by_date = {}
for r in rows: by_date.setdefault(r["date"], []).append(r)
summary = dict(
    games_parsed=len(games), games_scored=n, scoring_dates=len(by_date),
    first_scored=rows[0]["date"], last_scored=rows[-1]["date"],
    min_train=MIN_TRAIN, embargo_days=1, seed=SEED, resamples=B,
    brier_candidate=round(bc, 5), brier_baseline=round(bb, 5), delta=round(bc - bb, 5),
    ci95_game_clustered=[round(x, 5) for x in boot(by_game)],
    ci95_date_clustered=[round(x, 5) for x in boot(by_date)],
    mae_margin=round(sum(r["margin_err"] for r in rows) / n, 3),
    mae_total=round(sum(r["total_err"] for r in rows) / n, 3),
    market_leg="MISSING", rows_sha256=hashlib.sha256((OUT / "per_game_rows.csv").read_bytes()).hexdigest())
(OUT / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))
