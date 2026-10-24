"""Rebuild game_table.csv from the hashed nflverse files (see SOURCES.json)."""
import sys, pandas as pd
d = sys.argv[1]
g = pd.read_csv(f"{d}/games.csv")
cols = ['game_id','season','season_type','week','home_team','away_team','touchdown','td_team','total_home_score','total_away_score','play_id','game_date']
out = []
for s in range(2018, 2026):
    p = pd.read_csv(f"{d}/pbp_{s}.csv.gz", usecols=cols, low_memory=False)
    for gid, x in p.groupby('game_id'):
        x = x.sort_values('play_id'); h, a = x.home_team.iloc[0], x.away_team.iloc[0]
        td = x[x.touchdown == 1]
        hs = x.total_home_score.ffill().fillna(0).values; as_ = x.total_away_score.ffill().fillna(0).values
        race = {}
        for N in (10, 15, 20, 25, 30):
            w = None
            for u, v in zip(hs, as_):
                if u >= N and v < N: w = 'H'; break
                if v >= N and u < N: w = 'A'; break
                if u >= N and v >= N: w = 'TIE'; break
            race[N] = w or 'NEITHER'
        out.append(dict(game_id=gid, season=s, stype=x.season_type.iloc[0], week=int(x.week.iloc[0]), date=x.game_date.iloc[0], home=h, away=a,
                        home_td=int((td.td_team == h).sum()), away_td=int((td.td_team == a).sum()), home_pts=int(hs.max()), away_pts=int(as_.max()),
                        **{f'race{N}': v for N, v in race.items()}))
m = pd.DataFrame(out).merge(g[['game_id','home_score','away_score','gameday','gametime']], on='game_id', how='left')
bad = ((m.home_pts != m.home_score) | (m.away_pts != m.away_score)).sum()
if bad:
    raise SystemExit(f"SCORE_CROSS_CHECK_FAILED:{bad}")
m.to_csv(sys.argv[2], index=False)
