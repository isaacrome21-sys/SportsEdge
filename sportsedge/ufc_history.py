"""Leakage-safe rolling UFC history built from fight-level UFCStats data.

This module intentionally consumes factual raw data only. It does not copy or use
third-party model code. Historical features are snapshotted *before* each fight is
applied to fighter state, so future fight outcomes/statistics cannot leak backward.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import csv
import io
import re
import unicodedata
from statistics import mean
from typing import Callable, Iterable, Mapping
from urllib.request import Request, urlopen

from .ufc_training import TrainingRow, update_elo

GRECO_BASE = "https://raw.githubusercontent.com/Greco1899/scrape_ufc_stats/main"
DEFAULT_EVENT_URL = f"{GRECO_BASE}/ufc_event_details.csv"
DEFAULT_RESULTS_URL = f"{GRECO_BASE}/ufc_fight_results.csv"
DEFAULT_STATS_URL = f"{GRECO_BASE}/ufc_fight_stats.csv"
DEFAULT_FIGHTERS_URL = f"{GRECO_BASE}/ufc_fighter_tott.csv"


class UFCHistoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class FighterPhysical:
    name: str
    height_in: float | None = None
    reach_in: float | None = None
    stance: str = "Unknown"
    dob: date | None = None


@dataclass
class FighterState:
    elo: float = 1500.0
    fights: int = 0
    wins: int = 0
    losses: int = 0
    draws: int = 0
    total_seconds: float = 0.0
    sig_landed: float = 0.0
    sig_attempted: float = 0.0
    sig_absorbed: float = 0.0
    sig_faced_attempted: float = 0.0
    td_landed: float = 0.0
    td_attempted: float = 0.0
    td_allowed: float = 0.0
    td_faced_attempted: float = 0.0
    sub_attempts: float = 0.0
    control_seconds: float = 0.0
    knockdowns: float = 0.0
    finish_wins: int = 0
    finish_losses: int = 0
    last_fight_date: date | None = None
    recent_results: list[float] = field(default_factory=list)
    opponent_pre_fight_elos: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class FightAggregate:
    sig_landed: float = 0.0
    sig_attempted: float = 0.0
    td_landed: float = 0.0
    td_attempted: float = 0.0
    sub_attempts: float = 0.0
    control_seconds: float = 0.0
    knockdowns: float = 0.0


@dataclass
class UFCHistoryBundle:
    training_rows: list[TrainingRow]
    metadata: list[dict[str, object]]
    states: dict[str, FighterState]
    profiles: dict[str, FighterPhysical]
    last_fight_date: str
    source_urls: dict[str, str]

    def snapshot_dict(
        self,
        name: str,
        event_date: str | date,
        weight_class: str = "",
        *,
        late_replacement: bool = False,
        profile_override: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        event_day = parse_date(event_date) if isinstance(event_date, str) else event_date
        return snapshot_from_state(
            name,
            self.states.get(normalize_name(name), FighterState()),
            self.profiles.get(normalize_name(name)),
            event_day,
            weight_class,
            late_replacement=late_replacement,
            profile_override=profile_override,
        )


def normalize_name(value: str) -> str:
    text = "".join(
        c for c in unicodedata.normalize("NFKD", str(value or ""))
        if not unicodedata.combining(c)
    ).lower()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def normalize_event(value: str) -> str:
    return " ".join(str(value or "").split())


def parse_date(value: str) -> date:
    text = str(value or "").strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    raise UFCHistoryError(f"UFC_HISTORY_DATE_INVALID {text!r}")


def _fetch_text(url: str, *, opener: Callable = urlopen, timeout: int = 60) -> str:
    req = Request(url, headers={"User-Agent": "SportsEdge/1.0"})
    try:
        with opener(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:  # pragma: no cover - network wrapper
        raise UFCHistoryError(f"UFC_HISTORY_FETCH_FAILED {url}: {type(exc).__name__}: {exc}") from exc


def _csv_rows(text: str) -> list[dict[str, str]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def _number(value: object, default: float = 0.0) -> float:
    try:
        text = str(value or "").strip()
        if text in {"", "--", "---"}:
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _of(value: object) -> tuple[float, float]:
    m = re.search(r"(-?\d+(?:\.\d+)?)\s+of\s+(-?\d+(?:\.\d+)?)", str(value or ""), flags=re.I)
    if not m:
        return 0.0, 0.0
    return float(m.group(1)), float(m.group(2))


def _clock_seconds(value: object) -> float:
    text = str(value or "").strip()
    m = re.fullmatch(r"(\d+):(\d{1,2})", text)
    if not m:
        return 0.0
    return float(int(m.group(1)) * 60 + int(m.group(2)))


def _height_inches(value: object) -> float | None:
    text = str(value or "").strip()
    if text in {"", "--"}:
        return None
    m = re.search(r"(\d+)\s*'\s*(\d+)\s*\"?", text)
    if not m:
        return None
    return float(int(m.group(1)) * 12 + int(m.group(2)))


def _reach_inches(value: object) -> float | None:
    text = str(value or "").strip()
    if text in {"", "--"}:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _dob(value: object) -> date | None:
    text = str(value or "").strip()
    if text in {"", "--"}:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


def _fighters_from_bout(value: str) -> tuple[str, str] | None:
    parts = re.split(r"\s+vs\.?\s+", str(value or "").strip(), maxsplit=1, flags=re.I)
    if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
        return None
    return parts[0].strip(), parts[1].strip()


def _scheduled_rounds(time_format: str) -> int | None:
    m = re.search(r"\b(\d+)\s*Rnd\b", str(time_format or ""), flags=re.I)
    return int(m.group(1)) if m else None


def _elapsed_seconds(round_value: object, time_value: object, time_format: str) -> float | None:
    try:
        round_num = int(float(str(round_value or "").strip()))
    except (TypeError, ValueError):
        return None
    if round_num < 1:
        return None
    final_seconds = _clock_seconds(time_value)
    m = re.search(r"\((\d+(?:-\d+)*)\)", str(time_format or ""))
    if not m:
        return None
    durations = [int(x) * 60 for x in m.group(1).split("-")]
    if round_num > len(durations):
        return None
    return float(sum(durations[: round_num - 1]) + final_seconds)


def _weight_class(value: str) -> str:
    text = " ".join(str(value or "").split())
    text = re.sub(r"^UFC\s+", "", text, flags=re.I)
    text = re.sub(r"\s+Title\s+Bout$", "", text, flags=re.I)
    text = re.sub(r"\s+Bout$", "", text, flags=re.I)
    return text.strip()


def _fight_key(event: str, bout: str) -> tuple[str, str]:
    return normalize_event(event), " ".join(str(bout or "").split())


def parse_profiles(rows: Iterable[Mapping[str, str]]) -> dict[str, FighterPhysical]:
    out: dict[str, FighterPhysical] = {}
    for row in rows:
        name = str(row.get("FIGHTER") or "").strip()
        if not name:
            continue
        out[normalize_name(name)] = FighterPhysical(
            name=name,
            height_in=_height_inches(row.get("HEIGHT")),
            reach_in=_reach_inches(row.get("REACH")),
            stance=str(row.get("STANCE") or "Unknown").strip() or "Unknown",
            dob=_dob(row.get("DOB")),
        )
    return out


def aggregate_stats(rows: Iterable[Mapping[str, str]]) -> dict[tuple[str, str, str], FightAggregate]:
    work: dict[tuple[str, str, str], dict[str, float]] = {}
    for row in rows:
        event = normalize_event(str(row.get("EVENT") or ""))
        bout = " ".join(str(row.get("BOUT") or "").split())
        fighter = str(row.get("FIGHTER") or "").strip()
        if not event or not bout or not fighter:
            continue
        key = (event, bout, normalize_name(fighter))
        agg = work.setdefault(key, {
            "sig_landed": 0.0, "sig_attempted": 0.0,
            "td_landed": 0.0, "td_attempted": 0.0,
            "sub_attempts": 0.0, "control_seconds": 0.0,
            "knockdowns": 0.0,
        })
        sig_l, sig_a = _of(row.get("SIG.STR."))
        td_l, td_a = _of(row.get("TD"))
        agg["sig_landed"] += sig_l
        agg["sig_attempted"] += sig_a
        agg["td_landed"] += td_l
        agg["td_attempted"] += td_a
        agg["sub_attempts"] += _number(row.get("SUB.ATT"))
        agg["control_seconds"] += _clock_seconds(row.get("CTRL"))
        agg["knockdowns"] += _number(row.get("KD"))
    return {key: FightAggregate(**value) for key, value in work.items()}


def _age(profile: FighterPhysical | None, event_day: date) -> float:
    if profile is None or profile.dob is None:
        return 30.0
    return max(18.0, (event_day - profile.dob).days / 365.2425)


def _sos(state: FighterState) -> float:
    if not state.opponent_pre_fight_elos:
        return 0.5
    avg = mean(state.opponent_pre_fight_elos)
    return 1.0 / (1.0 + 10.0 ** ((1500.0 - avg) / 400.0))


def _rate(value: float, seconds: float, scale_seconds: float) -> float:
    return 0.0 if seconds <= 0 else value / seconds * scale_seconds


def snapshot_from_state(
    name: str,
    state: FighterState,
    profile: FighterPhysical | None,
    event_day: date,
    weight_class: str,
    *,
    late_replacement: bool = False,
    profile_override: Mapping[str, object] | None = None,
) -> dict[str, object]:
    override = profile_override or {}
    height = override.get("height_in") if override.get("height_in") not in (None, 0, 0.0) else (profile.height_in if profile else None)
    reach = override.get("reach_in") if override.get("reach_in") not in (None, 0, 0.0) else (profile.reach_in if profile else None)
    stance = str(override.get("stance") or (profile.stance if profile else "Unknown") or "Unknown")
    override_age = override.get("age")
    age = float(override_age) if isinstance(override_age, (int, float)) and override_age > 0 else _age(profile, event_day)
    observed_history = state.total_seconds > 0
    recent = mean(state.recent_results[-5:]) if state.recent_results else 0.5
    days_since = float((event_day - state.last_fight_date).days) if state.last_fight_date else 180.0
    missing_flags = [height is None, reach is None] + ([False] * 7 if observed_history else [True] * 7)
    missingness = sum(1 for x in missing_flags if x) / len(missing_flags)
    return {
        "name": name,
        "age": age,
        "height_in": float(height or 0.0),
        "reach_in": float(reach or 0.0),
        "stance": stance,
        "wins": state.wins,
        "losses": state.losses,
        "draws": state.draws,
        "sig_strikes_landed_pm": _rate(state.sig_landed, state.total_seconds, 60.0),
        "sig_strikes_absorbed_pm": _rate(state.sig_absorbed, state.total_seconds, 60.0),
        "sig_strike_accuracy": 0.0 if state.sig_attempted <= 0 else state.sig_landed / state.sig_attempted,
        "sig_strike_defense": 0.0 if state.sig_faced_attempted <= 0 else 1.0 - state.sig_absorbed / state.sig_faced_attempted,
        "takedowns_per_15": _rate(state.td_landed, state.total_seconds, 900.0),
        "takedown_accuracy": 0.0 if state.td_attempted <= 0 else state.td_landed / state.td_attempted,
        "takedown_defense": 0.0 if state.td_faced_attempted <= 0 else 1.0 - state.td_allowed / state.td_faced_attempted,
        "submissions_per_15": _rate(state.sub_attempts, state.total_seconds, 900.0),
        "control_seconds_per_15": _rate(state.control_seconds, state.total_seconds, 900.0),
        "knockdowns_per_15": _rate(state.knockdowns, state.total_seconds, 900.0),
        "finish_win_rate": 0.0 if state.wins <= 0 else state.finish_wins / state.wins,
        "finish_loss_rate": 0.0 if state.losses <= 0 else state.finish_losses / state.losses,
        "recent_win_rate": recent,
        "strength_of_schedule": _sos(state),
        "elo": state.elo,
        "days_since_last_fight": max(0.0, days_since),
        "weight_class": weight_class,
        "late_replacement": bool(late_replacement),
        "missingness": min(1.0, max(0.0, missingness)),
    }


def _feature_diff(a: Mapping[str, object], b: Mapping[str, object]) -> dict[str, float]:
    return {
        "elo_diff": float(a["elo"]) - float(b["elo"]),
        "age_diff": float(a["age"]) - float(b["age"]),
        "reach_diff": float(a["reach_in"]) - float(b["reach_in"]),
        "height_diff": float(a["height_in"]) - float(b["height_in"]),
        "slpm_diff": float(a["sig_strikes_landed_pm"]) - float(b["sig_strikes_landed_pm"]),
        "sapm_diff": float(a["sig_strikes_absorbed_pm"]) - float(b["sig_strikes_absorbed_pm"]),
        "str_acc_diff": float(a["sig_strike_accuracy"]) - float(b["sig_strike_accuracy"]),
        "str_def_diff": float(a["sig_strike_defense"]) - float(b["sig_strike_defense"]),
        "td_avg_diff": float(a["takedowns_per_15"]) - float(b["takedowns_per_15"]),
        "td_acc_diff": float(a["takedown_accuracy"]) - float(b["takedown_accuracy"]),
        "td_def_diff": float(a["takedown_defense"]) - float(b["takedown_defense"]),
        "sub_avg_diff": float(a["submissions_per_15"]) - float(b["submissions_per_15"]),
        "recent_win_rate_diff": float(a["recent_win_rate"]) - float(b["recent_win_rate"]),
        "sos_diff": float(a["strength_of_schedule"]) - float(b["strength_of_schedule"]),
        "rest_days_diff": float(a["days_since_last_fight"]) - float(b["days_since_last_fight"]),
        "late_replacement_diff": float(bool(a["late_replacement"])) - float(bool(b["late_replacement"])),
        "experience_diff": float(int(a["wins"]) + int(a["losses"]) + int(a["draws"])) - float(int(b["wins"]) + int(b["losses"]) + int(b["draws"])),
    }


def build_history_from_text(
    *,
    events_text: str,
    results_text: str,
    stats_text: str,
    fighters_text: str,
    min_date: str = "2010-01-01",
    source_urls: Mapping[str, str] | None = None,
) -> UFCHistoryBundle:
    event_rows = _csv_rows(events_text)
    result_rows = _csv_rows(results_text)
    stat_rows = _csv_rows(stats_text)
    profile_rows = _csv_rows(fighters_text)
    profiles = parse_profiles(profile_rows)
    stats = aggregate_stats(stat_rows)
    min_day = parse_date(min_date)
    event_dates: dict[str, date] = {}
    for row in event_rows:
        event = normalize_event(str(row.get("EVENT") or ""))
        if event and row.get("DATE"):
            event_dates[event] = parse_date(str(row["DATE"]))

    ordered: list[tuple[date, str, str, dict[str, str]]] = []
    for row in result_rows:
        event = normalize_event(str(row.get("EVENT") or ""))
        bout = " ".join(str(row.get("BOUT") or "").split())
        event_day = event_dates.get(event)
        if event_day is None or event_day < min_day or not bout:
            continue
        ordered.append((event_day, event, bout, row))
    ordered.sort(key=lambda x: (x[0], x[1], x[2]))
    if not ordered:
        raise UFCHistoryError("UFC_HISTORY_NO_FIGHTS")

    states: dict[str, FighterState] = {}
    examples: list[tuple[TrainingRow, dict[str, object]]] = []
    last_day = ordered[-1][0]
    for event_day, event, bout, row in ordered:
        pair = _fighters_from_bout(bout)
        if pair is None:
            continue
        fighter_a, fighter_b = pair
        ka, kb = normalize_name(fighter_a), normalize_name(fighter_b)
        a_state = states.setdefault(ka, FighterState())
        b_state = states.setdefault(kb, FighterState())
        weight_class = _weight_class(str(row.get("WEIGHTCLASS") or ""))
        rounds = _scheduled_rounds(str(row.get("TIME FORMAT") or ""))
        elapsed = _elapsed_seconds(row.get("ROUND"), row.get("TIME"), str(row.get("TIME FORMAT") or ""))
        outcome = str(row.get("OUTCOME") or "").strip().upper().replace(" ", "")
        y: int | None = 1 if outcome == "W/L" else (0 if outcome == "L/W" else None)

        a_snapshot = snapshot_from_state(fighter_a, a_state, profiles.get(ka), event_day, weight_class)
        b_snapshot = snapshot_from_state(fighter_b, b_state, profiles.get(kb), event_day, weight_class)
        if y is not None and rounds in {3, 5} and elapsed is not None and elapsed > 0:
            tr = TrainingRow(
                fight_date=event_day.isoformat(),
                event=event,
                fighter_a=fighter_a,
                fighter_b=fighter_b,
                y_a_win=y,
                features=_feature_diff(a_snapshot, b_snapshot),
            )
            meta = {
                "fight_date": event_day.isoformat(),
                "event": event,
                "fighter_a": fighter_a,
                "fighter_b": fighter_b,
                "fighter_a_experience": a_state.fights,
                "fighter_b_experience": b_state.fights,
                "weight_class": weight_class,
                "gender": "FEMALE" if "women" in weight_class.lower() else "MALE",
                "scheduled_rounds": rounds,
                "market_probability_a": None,
            }
            examples.append((tr, meta))

        pre_a_elo, pre_b_elo = a_state.elo, b_state.elo
        a_agg = stats.get((event, bout, ka), FightAggregate())
        b_agg = stats.get((event, bout, kb), FightAggregate())
        if elapsed is not None and elapsed > 0:
            for state, own, opp in ((a_state, a_agg, b_agg), (b_state, b_agg, a_agg)):
                state.total_seconds += elapsed
                state.sig_landed += own.sig_landed
                state.sig_attempted += own.sig_attempted
                state.sig_absorbed += opp.sig_landed
                state.sig_faced_attempted += opp.sig_attempted
                state.td_landed += own.td_landed
                state.td_attempted += own.td_attempted
                state.td_allowed += opp.td_landed
                state.td_faced_attempted += opp.td_attempted
                state.sub_attempts += own.sub_attempts
                state.control_seconds += own.control_seconds
                state.knockdowns += own.knockdowns
        a_state.fights += 1
        b_state.fights += 1
        a_state.last_fight_date = event_day
        b_state.last_fight_date = event_day
        a_state.opponent_pre_fight_elos.append(pre_b_elo)
        b_state.opponent_pre_fight_elos.append(pre_a_elo)
        method = str(row.get("METHOD") or "").strip().lower()
        finish = bool(method) and not method.startswith("decision")
        if outcome == "W/L":
            a_state.wins += 1; b_state.losses += 1
            a_state.recent_results.append(1.0); b_state.recent_results.append(0.0)
            if finish: a_state.finish_wins += 1; b_state.finish_losses += 1
            a_state.elo, b_state.elo = update_elo(pre_a_elo, pre_b_elo, 1.0)
        elif outcome == "L/W":
            a_state.losses += 1; b_state.wins += 1
            a_state.recent_results.append(0.0); b_state.recent_results.append(1.0)
            if finish: a_state.finish_losses += 1; b_state.finish_wins += 1
            a_state.elo, b_state.elo = update_elo(pre_a_elo, pre_b_elo, 0.0)
        elif outcome in {"D/D", "DRAW/DRAW"}:
            a_state.draws += 1; b_state.draws += 1
            a_state.recent_results.append(0.5); b_state.recent_results.append(0.5)
            a_state.elo, b_state.elo = update_elo(pre_a_elo, pre_b_elo, 0.5)

    examples.sort(key=lambda p: (p[0].fight_date, p[0].event, p[0].fighter_a, p[0].fighter_b))
    return UFCHistoryBundle(
        training_rows=[p[0] for p in examples],
        metadata=[p[1] for p in examples],
        states=states,
        profiles=profiles,
        last_fight_date=last_day.isoformat(),
        source_urls=dict(source_urls or {}),
    )


def load_history_from_urls(
    *,
    event_url: str = DEFAULT_EVENT_URL,
    results_url: str = DEFAULT_RESULTS_URL,
    stats_url: str = DEFAULT_STATS_URL,
    fighters_url: str = DEFAULT_FIGHTERS_URL,
    min_date: str = "2010-01-01",
    opener: Callable = urlopen,
) -> UFCHistoryBundle:
    urls = {
        "events": event_url,
        "results": results_url,
        "stats": stats_url,
        "fighters": fighters_url,
    }
    return build_history_from_text(
        events_text=_fetch_text(event_url, opener=opener),
        results_text=_fetch_text(results_url, opener=opener),
        stats_text=_fetch_text(stats_url, opener=opener),
        fighters_text=_fetch_text(fighters_url, opener=opener),
        min_date=min_date,
        source_urls=urls,
    )
