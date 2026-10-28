#!/usr/bin/env python3
"""G3 audit measurement: CFB starting-QB identity sources, SDV ESPN family, 2023-2025.
Universe: team-games in espn_cfb_player_box where the team recorded >=1 pass attempt.
Sources: sportsdataverse-data releases espn_cfb_player_box / espn_cfb_pbp / espn_cfb_game_rosters.
Outputs JSON + printed summary. Read-only against ~/workspace/g3audit/data/*.parquet
"""
import json, sys
import pandas as pd
import pyarrow.parquet as pq

# argv[1] = directory holding pbp_<season>.parquet / player_box_<season>.parquet /
# game_rosters_<season>.parquet from the sportsdataverse-data releases named in
# CFB_G3_QB_ADMISSIBILITY_AUDIT.md section 2. argv[2] = output JSON path.
DATA = sys.argv[1] if len(sys.argv) > 1 else "data"

def load_box(y):
    t = pq.read_table(f"{DATA}/player_box_{y}.parquet",
                      columns=["athlete_id","athlete_name","team_id","game_id","category","completions/passingAttempts"]).to_pandas()
    t = t[t.category == "passing"].copy()
    t["att"] = t["completions/passingAttempts"].astype(str).str.split("/").str[-1]
    t["att"] = pd.to_numeric(t["att"], errors="coerce").fillna(0).astype(int)
    return t

def load_first_passer(y):
    t = pq.read_table(f"{DATA}/pbp_{y}.parquet",
                      columns=["game_id","game_play_number","pos_team_id","passer_player_id","pass_attempt","week"]).to_pandas()
    t = t[(t.pass_attempt == True) & t.passer_player_id.notna()]  # noqa: E712
    t = t.sort_values(["game_id","pos_team_id","game_play_number"])
    fp = t.groupby(["game_id","pos_team_id"]).first().reset_index()
    wk = t.groupby("game_id")["week"].max().rename("week")
    return fp[["game_id","pos_team_id","passer_player_id"]], wk

def load_starters(y):
    t = pq.read_table(f"{DATA}/game_rosters_{y}.parquet",
                      columns=["athlete_id","team_id","game_id","starter"]).to_pandas()
    return t[t.starter == True]  # noqa: E712

out = {}
for y in (2023, 2024, 2025):
    box = load_box(y)
    fp, wk = load_first_passer(y)
    starters = load_starters(y)
    # team-game passing table
    tg = box.groupby(["game_id","team_id"]).agg(team_att=("att","sum")).reset_index()
    prim = box.sort_values("att").groupby(["game_id","team_id"]).tail(1)[["game_id","team_id","athlete_id","att"]]
    prim = prim.rename(columns={"athlete_id":"primary_id","att":"primary_att"})
    m = tg.merge(prim, on=["game_id","team_id"], how="left")
    # first passer
    fp = fp.rename(columns={"pos_team_id":"team_id","passer_player_id":"first_id"})
    fp["first_id"] = pd.to_numeric(fp["first_id"], errors="coerce")
    m = m.merge(fp, on=["game_id","team_id"], how="left")
    attmap = box.set_index(["game_id","team_id","athlete_id"])["att"]
    def att_of(row, col):
        try: return int(attmap.loc[(row.game_id, row.team_id, row[col])])
        except Exception: return 0
    m["first_att"] = m.apply(lambda r: att_of(r, "first_id"), axis=1)
    # flagged starters who are QBs = starter-flagged and appear as passers for that team-game
    st = starters.merge(box[["game_id","team_id","athlete_id"]].drop_duplicates(),
                        on=["game_id","team_id","athlete_id"], how="inner")
    stc = st.groupby(["game_id","team_id"]).agg(n_flag_qb=("athlete_id","nunique"),
                                                flag_qb=("athlete_id","first")).reset_index()
    m = m.merge(stc, on=["game_id","team_id"], how="left")
    m["flag_att"] = m.apply(lambda r: att_of(r, "flag_qb") if pd.notna(r.get("flag_qb")) else 0, axis=1)
    # week ordering for churn (primary passer continuity)
    m = m.merge(wk, on="game_id", how="left")
    m = m.sort_values(["team_id","week","game_id"])
    m["prev_primary"] = m.groupby(["team_id"])["primary_id"].shift(1)
    m["prev_flag"] = m.groupby(["team_id"])["flag_qb"].shift(1)

    n = len(m)
    has_fp = m.first_id.notna()
    has_flag = m.flag_qb.notna()
    res = {
        "team_games_with_pass_att": int(n),
        "first_passer_present_pct": round(100*has_fp.mean(), 2),
        "first_ne_primary_pct": round(100*(m[has_fp].first_id != m[has_fp].primary_id).mean(), 2),
        "first_att_lt5_pct": round(100*(m[has_fp].first_att < 5).mean(), 2),
        "first_att_lt10_pct": round(100*(m[has_fp].first_att < 10).mean(), 2),
        "primary_att_lt20_pct": round(100*(m.primary_att < 20).mean(), 2),
        "excl_union_proxy_pct": round(100*((m.first_id != m.primary_id) | (m.first_att < 10) | m.first_id.isna()).mean(), 2),
        "primary_changed_vs_prev_pct": round(100*(m[m.prev_primary.notna()].primary_id != m[m.prev_primary.notna()].prev_primary).mean(), 2),
        "flag_qb_coverage_pct": round(100*has_flag.mean(), 2),
        "flag_multi_qb_pct_of_flagged": (round(100*(m[has_flag].n_flag_qb > 1).mean(), 2) if has_flag.any() else None),
    }
    if has_flag.any():
        f = m[has_flag]
        res.update({
            "flag_ne_primary_pct": round(100*(f.flag_qb != f.primary_id).mean(), 2),
            "flag_ne_first_pct": round(100*(f[f.first_id.notna()].flag_qb != f[f.first_id.notna()].first_id).mean(), 2),
            "first_eq_flag_given_both_pct": round(100*(f[f.first_id.notna()].flag_qb == f[f.first_id.notna()].first_id).mean(), 2),
            "flag_att_lt5_pct": round(100*(f.flag_att < 5).mean(), 2),
            "flag_att_lt10_pct": round(100*(f.flag_att < 10).mean(), 2),
            "flag_changed_vs_prev_pct": round(100*(f[f.prev_flag.notna()].flag_qb != f[f.prev_flag.notna()].prev_flag).mean(), 2),
            "excl_union_flag_pct": round(100*((f.flag_qb != f.primary_id) | (f.flag_att < 10)).mean(), 2),
        })
    out[y] = res
    print(y, json.dumps(res, indent=1))

with open(sys.argv[2] if len(sys.argv) > 2 else "leak_measurements.json", "w") as fh:
    json.dump(out, fh, indent=1)
print("written leak_measurements.json")
