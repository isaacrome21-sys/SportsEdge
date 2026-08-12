"""Cutoff-correct Statcast primitives for SportsEdge V5.

Historical expected-stat columns are deliberately ignored.  Expected contact is
reconstructed from raw launch speed/angle with a transformer fitted only on the
2021-2023 training window declared in the V5 protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from io import StringIO
import hashlib
import json
from pathlib import Path
from typing import Iterable, Mapping, Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor

SAVANT_CSV = "https://baseballsavant.mlb.com/statcast_search/csv"
CONTACT_TRANSFORMER_VERSION = "SPORTSEDGE_CONTACT_X_V1"
RAW_REQUIRED = (
    "game_date", "game_pk", "batter", "pitcher", "events", "launch_speed",
    "launch_angle", "launch_speed_angle", "inning", "inning_topbot",
    "at_bat_number", "home_team", "away_team",
)
CONTACT_WOBA = {
    "single": 0.88,
    "double": 1.24,
    "triple": 1.56,
    "home_run": 2.00,
}
HIT_EVENTS = frozenset(CONTACT_WOBA)

class StatcastV5Error(ValueError):
    pass


def _daterange_chunks(start: date, end: date, days: int = 14):
    cur = start
    while cur <= end:
        stop = min(end, cur + timedelta(days=days - 1))
        yield cur, stop
        cur = stop + timedelta(days=1)


def _csv_url(start: date, end: date) -> str:
    params = {
        "all": "true",
        "type": "details",
        "player_type": "batter",
        "game_date_gt": start.isoformat(),
        "game_date_lt": end.isoformat(),
        "hfGT": "R|",
    }
    return f"{SAVANT_CSV}?{urlencode(params)}"


def fetch_savant_events(start: date, end: date, cache_dir: Path) -> pd.DataFrame:
    """Fetch official Savant event CSV in bounded chunks and cache raw bytes.

    The raw cache identity includes the exact requested dates.  Duplicate pitches
    caused by inclusive endpoint behavior are removed with a stable pitch key.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    parts: list[pd.DataFrame] = []
    for lo, hi in _daterange_chunks(start, end):
        p = cache_dir / f"savant_{lo.isoformat()}_{hi.isoformat()}.csv"
        if p.exists():
            raw = p.read_text(errors="replace")
        else:
            req = Request(_csv_url(lo, hi), headers={"Accept": "text/csv", "User-Agent": "SportsEdge/1.0"})
            with urlopen(req, timeout=120) as r:
                raw = r.read().decode("utf-8", errors="replace")
            if not raw.lstrip().startswith(("pitch_type,", "game_date,")) and ",game_pk," not in raw[:5000]:
                raise StatcastV5Error(f"SAVANT_NON_CSV_RESPONSE:{lo}:{hi}")
            p.write_text(raw)
        if not raw.strip():
            continue
        frame = pd.read_csv(StringIO(raw), low_memory=False)
        missing = [c for c in RAW_REQUIRED if c not in frame.columns]
        if missing:
            raise StatcastV5Error(f"SAVANT_COLUMNS_MISSING:{','.join(missing)}")
        parts.append(frame)
    if not parts:
        raise StatcastV5Error("SAVANT_NO_ROWS")
    df = pd.concat(parts, ignore_index=True)
    for c in ("game_pk", "batter", "pitcher", "inning", "at_bat_number"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce").dt.date
    df = df[df["game_date"].notna() & df["game_pk"].notna()].copy()
    # at_bat_number + pitcher/batter is stable enough when pitch_number is absent.
    key = [c for c in ("game_pk", "at_bat_number", "pitch_number", "pitcher", "batter") if c in df.columns]
    df = df.sort_values(["game_date", "game_pk", "at_bat_number"] + (["pitch_number"] if "pitch_number" in df.columns else []))
    df = df.drop_duplicates(key, keep="last")
    return df.reset_index(drop=True)


def batted_balls(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["launch_speed"] = pd.to_numeric(out["launch_speed"], errors="coerce")
    out["launch_angle"] = pd.to_numeric(out["launch_angle"], errors="coerce")
    out["launch_speed_angle"] = pd.to_numeric(out["launch_speed_angle"], errors="coerce")
    out = out[out["events"].notna() & out["launch_speed"].notna() & out["launch_angle"].notna()].copy()
    out["is_hit"] = out["events"].isin(HIT_EVENTS).astype(int)
    out["contact_woba"] = out["events"].map(CONTACT_WOBA).fillna(0.0).astype(float)
    out["barrel"] = (out["launch_speed_angle"] == 6).astype(float)
    out["hard_hit"] = (out["launch_speed"] >= 95.0).astype(float)
    return out


def fit_contact_transformer(train_events: pd.DataFrame) -> dict[str, Any]:
    bb = batted_balls(train_events)
    if len(bb) < 100000:
        raise StatcastV5Error(f"CONTACT_TRAIN_SAMPLE_TOO_SMALL:{len(bb)}")
    X = bb[["launch_speed", "launch_angle"]].to_numpy(float)
    hit_model = HistGradientBoostingClassifier(
        learning_rate=0.05, max_iter=180, max_leaf_nodes=31,
        min_samples_leaf=150, l2_regularization=2.0, random_state=71,
    )
    woba_model = HistGradientBoostingRegressor(
        loss="squared_error", learning_rate=0.05, max_iter=180, max_leaf_nodes=31,
        min_samples_leaf=150, l2_regularization=2.0, random_state=73,
    )
    hit_model.fit(X, bb["is_hit"].to_numpy(int))
    woba_model.fit(X, bb["contact_woba"].to_numpy(float))
    global_prior = {
        "xwoba": float(bb["contact_woba"].mean()),
        "xba": float(bb["is_hit"].mean()),
        "barrel": float(bb["barrel"].mean()),
        "hard_hit": float(bb["hard_hit"].mean()),
        "ev": float(bb["launch_speed"].mean()),
    }
    return {
        "version": CONTACT_TRANSFORMER_VERSION,
        "train_start": str(min(bb["game_date"])),
        "train_end": str(max(bb["game_date"])),
        "inputs": ("launch_speed", "launch_angle"),
        "hit_model": hit_model,
        "woba_model": woba_model,
        "global_prior": global_prior,
        "n_train_batted_balls": int(len(bb)),
        "target_woba_values": dict(CONTACT_WOBA),
    }


def save_joblib_hashed(obj: Any, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(obj, path, compress=3)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contact_transformer(path: Path, expected_sha256: str | None = None) -> dict[str, Any]:
    raw = path.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    if expected_sha256 and sha != expected_sha256:
        raise StatcastV5Error(f"CONTACT_TRANSFORMER_SHA_MISMATCH:{sha}")
    obj = joblib.load(path)
    if obj.get("version") != CONTACT_TRANSFORMER_VERSION:
        raise StatcastV5Error("CONTACT_TRANSFORMER_VERSION_MISMATCH")
    return obj


def apply_contact_transformer(events: pd.DataFrame, transformer: Mapping[str, Any]) -> pd.DataFrame:
    bb = batted_balls(events)
    if bb.empty:
        return bb
    X = bb[["launch_speed", "launch_angle"]].to_numpy(float)
    bb["frozen_xba"] = np.clip(transformer["hit_model"].predict_proba(X)[:, 1], 0.0, 1.0)
    bb["frozen_xwoba"] = np.clip(transformer["woba_model"].predict(X), 0.0, 2.0)
    return bb


@dataclass
class ContactState:
    n: int = 0
    xwoba: float = 0.0
    xba: float = 0.0
    barrel: float = 0.0
    hard_hit: float = 0.0
    ev: float = 0.0

    def add(self, row: Mapping[str, Any]) -> None:
        self.n += 1
        self.xwoba += float(row["frozen_xwoba"])
        self.xba += float(row["frozen_xba"])
        self.barrel += float(row["barrel"])
        self.hard_hit += float(row["hard_hit"])
        self.ev += float(row["launch_speed"])


def smoothed(state: ContactState | None, prior: Mapping[str, float], pseudo_n: float) -> dict[str, float]:
    s = state or ContactState()
    den = float(s.n) + float(pseudo_n)
    return {
        "xwoba": (s.xwoba + pseudo_n * float(prior["xwoba"])) / den,
        "xba": (s.xba + pseudo_n * float(prior["xba"])) / den,
        "barrel": (s.barrel + pseudo_n * float(prior["barrel"])) / den,
        "hard_hit": (s.hard_hit + pseudo_n * float(prior["hard_hit"])) / den,
        "ev": (s.ev + pseudo_n * float(prior["ev"])) / den,
        "n": float(s.n),
    }


def game_identity(events: pd.DataFrame) -> dict[str, Any]:
    """Extract only identities needed pregame: teams, starters, first-three hitters."""
    if events.empty:
        raise StatcastV5Error("GAME_STATCAST_EMPTY")
    e = events.sort_values(["inning", "at_bat_number"] + (["pitch_number"] if "pitch_number" in events.columns else []))
    home = str(e["home_team"].dropna().iloc[0]); away = str(e["away_team"].dropna().iloc[0])
    top = e[e["inning_topbot"].astype(str).str.lower().eq("top")]
    bot = e[e["inning_topbot"].astype(str).str.lower().eq("bot")]
    if top.empty or bot.empty:
        raise StatcastV5Error("GAME_HALFINNING_IDENTITY_MISSING")
    home_sp = int(pd.to_numeric(top["pitcher"], errors="coerce").dropna().iloc[0])
    away_sp = int(pd.to_numeric(bot["pitcher"], errors="coerce").dropna().iloc[0])
    top1 = top[pd.to_numeric(top["inning"], errors="coerce").eq(1)].sort_values("at_bat_number")
    bot1 = bot[pd.to_numeric(bot["inning"], errors="coerce").eq(1)].sort_values("at_bat_number")
    away_order = list(dict.fromkeys(int(x) for x in pd.to_numeric(top1["batter"], errors="coerce").dropna().tolist()))[:3]
    home_order = list(dict.fromkeys(int(x) for x in pd.to_numeric(bot1["batter"], errors="coerce").dropna().tolist()))[:3]
    if len(away_order) != 3 or len(home_order) != 3:
        raise StatcastV5Error("TOP_ORDER_IDENTITY_INCOMPLETE")
    return {
        "away_team": away, "home_team": home,
        "away_sp": away_sp, "home_sp": home_sp,
        "away_top3": tuple(away_order), "home_top3": tuple(home_order),
    }


def canonical_manifest(paths: Iterable[Path]) -> dict[str, Any]:
    files = []
    for p in paths:
        b = p.read_bytes()
        files.append({"path": str(p), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()})
    return {"schema_version": 1, "files": files}
