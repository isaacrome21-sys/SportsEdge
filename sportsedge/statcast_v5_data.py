"""Chronology-safe raw Statcast feature construction for MLB V5.

Only raw/observational Baseball Savant fields are trusted as historical inputs.
Retrospectively recomputable Savant expected-stat columns are intentionally ignored.
Expected contact value is produced by a separately frozen transformer trained only
on the predeclared training period.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
import csv
import hashlib
import io
import math
from typing import Any, Iterable, Mapping, Sequence

HIT_EVENTS = {"single", "double", "triple", "home_run"}
CONTACT_EVENTS = HIT_EVENTS | {
    "field_out", "force_out", "grounded_into_double_play", "field_error",
    "fielders_choice", "fielders_choice_out", "double_play", "triple_play",
    "sac_fly", "sac_bunt",
}
# Fixed before fitting. These are model targets on a wOBA-like contact-value scale,
# not MLB's retrospectively generated Savant xwOBA field.
CONTACT_VALUE = {
    "single": 0.90,
    "double": 1.25,
    "triple": 1.60,
    "home_run": 2.00,
}

RAW_REQUIRED_COLUMNS = (
    "game_date", "game_pk", "batter", "pitcher", "events", "home_team",
    "away_team", "inning", "inning_topbot", "at_bat_number", "launch_speed",
    "launch_angle",
)

class StatcastDataError(ValueError):
    pass


def _float(v: Any) -> float | None:
    if v is None or str(v).strip() in {"", "null", "None", "nan"}:
        return None
    try:
        x = float(v)
    except Exception:
        return None
    return x if math.isfinite(x) else None


def _int(v: Any) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    try:
        return int(float(v))
    except Exception:
        return None

@dataclass(frozen=True)
class PlateAppearance:
    game_date: str
    game_pk: int
    batter: int
    pitcher: int
    event: str
    home_team: str
    away_team: str
    inning: int
    topbot: str
    at_bat_number: int
    launch_speed: float | None
    launch_angle: float | None

    @property
    def batting_team(self) -> str:
        return self.away_team if self.topbot.lower().startswith("top") else self.home_team

    @property
    def fielding_team(self) -> str:
        return self.home_team if self.topbot.lower().startswith("top") else self.away_team

    @property
    def is_contact(self) -> bool:
        return self.event in CONTACT_EVENTS and self.launch_speed is not None and self.launch_angle is not None

    @property
    def hard_hit(self) -> float:
        if self.launch_speed is None:
            raise StatcastDataError("HARD_HIT_WITHOUT_EXIT_VELOCITY")
        return float(self.launch_speed >= 95.0)

    @property
    def actual_hit(self) -> float:
        return float(self.event in HIT_EVENTS)

    @property
    def actual_contact_value(self) -> float:
        return float(CONTACT_VALUE.get(self.event, 0.0))


def parse_savant_csv(text: str) -> list[PlateAppearance]:
    reader = csv.DictReader(io.StringIO(text))
    fields = tuple(reader.fieldnames or ())
    missing = [x for x in RAW_REQUIRED_COLUMNS if x not in fields]
    if missing:
        raise StatcastDataError(f"STATCAST_COLUMNS_MISSING:{','.join(missing)}")
    out: list[PlateAppearance] = []
    seen_pa: set[tuple[int, int]] = set()
    for raw in reader:
        # Statcast search CSV can contain every pitch. Keep only terminal PA rows.
        event = str(raw.get("events") or "").strip()
        if not event:
            continue
        gp = _int(raw.get("game_pk")); batter = _int(raw.get("batter")); pitcher = _int(raw.get("pitcher"))
        inn = _int(raw.get("inning")); ab = _int(raw.get("at_bat_number"))
        gd = str(raw.get("game_date") or "").strip()
        if None in (gp, batter, pitcher, inn, ab) or not gd:
            raise StatcastDataError("STATCAST_IDENTITY_FIELD_INVALID")
        try:
            date.fromisoformat(gd)
        except Exception as exc:
            raise StatcastDataError("STATCAST_GAME_DATE_INVALID") from exc
        key = (int(gp), int(ab))
        if key in seen_pa:
            # Multiple terminal-looking rows for one PA are ambiguous and unsafe.
            raise StatcastDataError(f"STATCAST_DUPLICATE_PA:{gp}:{ab}")
        seen_pa.add(key)
        out.append(PlateAppearance(
            game_date=gd, game_pk=int(gp), batter=int(batter), pitcher=int(pitcher), event=event,
            home_team=str(raw.get("home_team") or "").strip(), away_team=str(raw.get("away_team") or "").strip(),
            inning=int(inn), topbot=str(raw.get("inning_topbot") or "").strip(), at_bat_number=int(ab),
            launch_speed=_float(raw.get("launch_speed")), launch_angle=_float(raw.get("launch_angle")),
        ))
    out.sort(key=lambda x: (x.game_date, x.game_pk, x.at_bat_number))
    return out


def source_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

@dataclass
class RollingContact:
    n: int = 0
    sum_xhit: float = 0.0
    sum_xvalue: float = 0.0
    hard_hits: int = 0
    sum_ev: float = 0.0
    ev_n: int = 0

    def add(self, *, xhit: float, xvalue: float, ev: float) -> None:
        self.n += 1
        self.sum_xhit += float(xhit)
        self.sum_xvalue += float(xvalue)
        self.hard_hits += int(ev >= 95.0)
        self.sum_ev += float(ev)
        self.ev_n += 1

    def values(self, *, min_bbe: int) -> dict[str, float]:
        if self.n < min_bbe or self.ev_n < min_bbe:
            raise StatcastDataError(f"STATCAST_SAMPLE_TOO_SMALL:n={self.n}:min={min_bbe}")
        return {
            "xhit": self.sum_xhit / self.n,
            "xcontact_woba": self.sum_xvalue / self.n,
            "hard_hit_rate": self.hard_hits / self.n,
            "avg_exit_velocity": self.sum_ev / self.ev_n,
        }

@dataclass
class V5State:
    team: dict[str, RollingContact] = field(default_factory=lambda: defaultdict(RollingContact))
    pitcher: dict[int, RollingContact] = field(default_factory=lambda: defaultdict(RollingContact))
    batter: dict[int, RollingContact] = field(default_factory=lambda: defaultdict(RollingContact))


def infer_starters(rows: Sequence[PlateAppearance]) -> tuple[int, int]:
    """Return (away starter, home starter) from earliest PA pitcher identity.

    The home starter is the first pitcher to face the away offense; the away
    starter is the first pitcher to face the home offense. This uses identity/order
    only, never target-game contact outcome values.
    """
    if not rows:
        raise StatcastDataError("STATCAST_GAME_ROWS_EMPTY")
    ordered = sorted(rows, key=lambda x: x.at_bat_number)
    home = rows[0].home_team; away = rows[0].away_team
    home_sp = next((r.pitcher for r in ordered if r.batting_team == away), None)
    away_sp = next((r.pitcher for r in ordered if r.batting_team == home), None)
    if home_sp is None or away_sp is None:
        raise StatcastDataError("STATCAST_STARTER_ID_UNRESOLVED")
    return int(away_sp), int(home_sp)


def infer_top_order(rows: Sequence[PlateAppearance], team: str, n: int = 3) -> tuple[int, ...]:
    seen: list[int] = []
    for r in sorted(rows, key=lambda x: x.at_bat_number):
        if r.batting_team != team or r.batter in seen:
            continue
        seen.append(r.batter)
        if len(seen) == n:
            return tuple(seen)
    raise StatcastDataError(f"STATCAST_TOP_ORDER_UNRESOLVED:{team}")


def _avg_player_metric(state: V5State, players: Sequence[int], key: str, *, min_bbe: int) -> float:
    vals = [state.batter[int(p)].values(min_bbe=min_bbe)[key] for p in players]
    return float(sum(vals) / len(vals))


def feature_game_before_update(
    state: V5State,
    rows: Sequence[PlateAppearance],
    *,
    min_team_bbe: int = 75,
    min_pitcher_bbe: int = 30,
    min_batter_bbe: int = 20,
) -> dict[str, Any]:
    if not rows:
        raise StatcastDataError("STATCAST_GAME_ROWS_EMPTY")
    away = rows[0].away_team; home = rows[0].home_team
    away_sp, home_sp = infer_starters(rows)
    away_top = infer_top_order(rows, away); home_top = infer_top_order(rows, home)
    a = state.team[away].values(min_bbe=min_team_bbe); h = state.team[home].values(min_bbe=min_team_bbe)
    asp = state.pitcher[away_sp].values(min_bbe=min_pitcher_bbe); hsp = state.pitcher[home_sp].values(min_bbe=min_pitcher_bbe)
    return {
        "game_pk": rows[0].game_pk, "game_date": rows[0].game_date,
        "away_team": away, "home_team": home, "away_sp": away_sp, "home_sp": home_sp,
        "away": {
            "off_xwoba": a["xcontact_woba"], "off_xba": a["xhit"], "off_hard_hit_rate": a["hard_hit_rate"], "off_avg_exit_velocity": a["avg_exit_velocity"],
            "opp_sp_xwoba_allowed": hsp["xcontact_woba"], "opp_sp_xba_allowed": hsp["xhit"], "opp_sp_hard_hit_rate_allowed": hsp["hard_hit_rate"], "opp_sp_avg_exit_velocity_allowed": hsp["avg_exit_velocity"],
        },
        "home": {
            "off_xwoba": h["xcontact_woba"], "off_xba": h["xhit"], "off_hard_hit_rate": h["hard_hit_rate"], "off_avg_exit_velocity": h["avg_exit_velocity"],
            "opp_sp_xwoba_allowed": asp["xcontact_woba"], "opp_sp_xba_allowed": asp["xhit"], "opp_sp_hard_hit_rate_allowed": asp["hard_hit_rate"], "opp_sp_avg_exit_velocity_allowed": asp["avg_exit_velocity"],
        },
        "first_inning": {
            "away_top_order_xwoba": _avg_player_metric(state, away_top, "xcontact_woba", min_bbe=min_batter_bbe),
            "home_top_order_xwoba": _avg_player_metric(state, home_top, "xcontact_woba", min_bbe=min_batter_bbe),
            "away_sp_xwoba_allowed": asp["xcontact_woba"], "home_sp_xwoba_allowed": hsp["xcontact_woba"],
            "away_sp_hard_hit_rate_allowed": asp["hard_hit_rate"], "home_sp_hard_hit_rate_allowed": hsp["hard_hit_rate"],
        },
    }


def update_state(state: V5State, rows: Sequence[PlateAppearance], transformer: Any) -> None:
    contacts = [r for r in rows if r.is_contact]
    if not contacts:
        return
    X = [[float(r.launch_speed), float(r.launch_angle)] for r in contacts]
    xhit = transformer.predict_hit_probability(X)
    xvalue = transformer.predict_contact_value(X)
    for r, ph, pv in zip(contacts, xhit, xvalue):
        ev = float(r.launch_speed)
        state.team[r.batting_team].add(xhit=float(ph), xvalue=float(pv), ev=ev)
        state.pitcher[r.pitcher].add(xhit=float(ph), xvalue=float(pv), ev=ev)
        state.batter[r.batter].add(xhit=float(ph), xvalue=float(pv), ev=ev)


def build_prior_only_game_features(rows: Sequence[PlateAppearance], transformer: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Feature each date from state frozen at the end of the previous date.

    No game on a date can update another game on the same date, preventing
    doubleheader/same-day leakage.
    """
    by_date: dict[str, dict[int, list[PlateAppearance]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_date[r.game_date][r.game_pk].append(r)
    state = V5State(); out: list[dict[str, Any]] = []
    for gd in sorted(by_date):
        pending: list[list[PlateAppearance]] = []
        for gp in sorted(by_date[gd]):
            game_rows = by_date[gd][gp]
            pending.append(game_rows)
            try:
                out.append(feature_game_before_update(state, game_rows, **kwargs))
            except StatcastDataError as exc:
                out.append({"game_pk": gp, "game_date": gd, "blocked": str(exc)})
        for game_rows in pending:
            update_state(state, game_rows, transformer)
    return out
