"""MLB home-plate umpire assignment and context from public StatsAPI.

This is a context/acquisition lane only. It never creates Model_P. Assignment is
resolved from the live-feed boxscore first and the schedule officials hydration
second. Historical tendencies are empirical-Bayes shrunk toward a versioned
league prior, with an exact zero delta below the configured minimum HP sample.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .source_lineage import canonical_json_sha256

MLB_STATSAPI = "https://statsapi.mlb.com/api/v1"
SOURCE = "MLB_STATSAPI_UMPIRE_CONTEXT"
SCHEMA_VERSION = "mlb_umpire_source_v1"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "mlb_umpire_prior_v1.json"


class MLBUmpireSourceError(RuntimeError):
    pass


def _open_json(url: str, *, opener: Callable = urlopen) -> dict[str, Any]:
    req = Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "SportsEdge-MLB-Umpire/1.0",
    })
    try:
        with opener(req, timeout=30) as response:
            raw = response.read()
    except Exception as exc:
        raise MLBUmpireSourceError(f"UMPIRE_FETCH_FAILED:{url}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise MLBUmpireSourceError("UMPIRE_RESPONSE_NOT_JSON") from exc
    if not isinstance(payload, dict):
        raise MLBUmpireSourceError("UMPIRE_RESPONSE_NOT_OBJECT")
    return payload


def load_prior_config(path: str | Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        raise MLBUmpireSourceError(f"UMPIRE_CONFIG_LOAD_FAILED:{path}") from exc
    if not isinstance(payload, dict):
        raise MLBUmpireSourceError("UMPIRE_CONFIG_NOT_OBJECT")
    required = {"schema_version", "league_prior", "prior_equivalent_games", "min_home_plate_games", "history_days"}
    if not required.issubset(payload):
        raise MLBUmpireSourceError("UMPIRE_CONFIG_MISSING_REQUIRED_FIELDS")
    prior = payload.get("league_prior") or {}
    for key in ("runs_per_game", "strikeouts_per_game", "walks_per_game"):
        try:
            float(prior[key])
        except (KeyError, TypeError, ValueError) as exc:
            raise MLBUmpireSourceError(f"UMPIRE_CONFIG_INVALID_PRIOR:{key}") from exc
    if int(payload["min_home_plate_games"]) < 1 or int(payload["prior_equivalent_games"]) < 1:
        raise MLBUmpireSourceError("UMPIRE_CONFIG_INVALID_SAMPLE_POLICY")
    return payload


def _official_from_rows(rows: Any) -> dict[str, Any] | None:
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        role = str(row.get("officialType") or row.get("type") or "").strip().lower()
        if role not in {"home plate", "homeplate", "hp"}:
            continue
        official = row.get("official") or row.get("person") or {}
        if not isinstance(official, Mapping):
            continue
        try:
            official_id = int(official.get("id"))
        except (TypeError, ValueError):
            continue
        return {
            "umpire_id": official_id,
            "umpire_name": str(official.get("fullName") or official.get("name") or "").strip() or None,
            "official_type": "Home Plate",
        }
    return None


def home_plate_from_live(live_payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    payload = live_payload or {}
    boxscore = ((payload.get("liveData") or {}).get("boxscore") or {})
    return _official_from_rows(boxscore.get("officials")) if isinstance(boxscore, Mapping) else None


def home_plate_from_schedule(schedule_payload: Mapping[str, Any], *, game_pk: int) -> dict[str, Any] | None:
    for date_block in schedule_payload.get("dates") or []:
        if not isinstance(date_block, Mapping):
            continue
        for game in date_block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            try:
                candidate_pk = int(game.get("gamePk"))
            except (TypeError, ValueError):
                continue
            if candidate_pk != int(game_pk):
                continue
            found = _official_from_rows(game.get("officials"))
            if found:
                return found
    return None


def _official_date(live_payload: Mapping[str, Any] | None, explicit: str | None) -> str | None:
    if explicit:
        try:
            return date.fromisoformat(str(explicit)[:10]).isoformat()
        except ValueError:
            return None
    payload = live_payload or {}
    game_data = payload.get("gameData") or {}
    if not isinstance(game_data, Mapping):
        return None
    datetime_block = game_data.get("datetime") or {}
    candidates = [
        datetime_block.get("officialDate") if isinstance(datetime_block, Mapping) else None,
        game_data.get("officialDate"),
    ]
    for value in candidates:
        if value:
            try:
                return date.fromisoformat(str(value)[:10]).isoformat()
            except ValueError:
                continue
    return None


def assignment_schedule_url(official_date: str) -> str:
    return f"{MLB_STATSAPI}/schedule?" + urlencode({
        "sportId": 1,
        "date": official_date,
        "hydrate": "officials",
    })


def history_schedule_url(*, start_date: str, end_date: str) -> str:
    return f"{MLB_STATSAPI}/schedule?" + urlencode({
        "sportId": 1,
        "startDate": start_date,
        "endDate": end_date,
        "hydrate": "officials",
    })


def boxscore_url(game_pk: int) -> str:
    return f"{MLB_STATSAPI}/game/{int(game_pk)}/boxscore"


def assigned_game_pks(schedule_payload: Mapping[str, Any], *, umpire_id: int) -> list[int]:
    out: list[int] = []
    for date_block in schedule_payload.get("dates") or []:
        if not isinstance(date_block, Mapping):
            continue
        for game in date_block.get("games") or []:
            if not isinstance(game, Mapping):
                continue
            found = _official_from_rows(game.get("officials"))
            if not found or int(found["umpire_id"]) != int(umpire_id):
                continue
            status = game.get("status") or {}
            abstract = str(status.get("abstractGameState") or "") if isinstance(status, Mapping) else ""
            if abstract and abstract != "Final":
                continue
            try:
                out.append(int(game.get("gamePk")))
            except (TypeError, ValueError):
                continue
    return sorted(set(out))


def boxscore_game_metrics(boxscore_payload: Mapping[str, Any], *, game_pk: int | None = None) -> dict[str, Any] | None:
    teams = boxscore_payload.get("teams") or {}
    if not isinstance(teams, Mapping):
        return None
    totals = {"runs": 0.0, "strikeouts": 0.0, "walks": 0.0}
    found_sides = 0
    for side in ("away", "home"):
        team = teams.get(side) or {}
        batting = ((team.get("teamStats") or {}).get("batting") or {}) if isinstance(team, Mapping) else {}
        if not isinstance(batting, Mapping):
            return None
        values = {
            "runs": batting.get("runs"),
            "strikeouts": batting.get("strikeOuts"),
            "walks": batting.get("baseOnBalls"),
        }
        try:
            for key, value in values.items():
                totals[key] += float(value)
        except (TypeError, ValueError):
            return None
        found_sides += 1
    if found_sides != 2:
        return None
    row: dict[str, Any] = {
        "runs": totals["runs"],
        "strikeouts": totals["strikeouts"],
        "walks": totals["walks"],
    }
    if game_pk is not None:
        row["game_pk"] = int(game_pk)
    return row


def _mean(rows: Iterable[Mapping[str, Any]], key: str) -> float:
    values = [float(row[key]) for row in rows]
    return sum(values) / len(values)


def shrink_tendencies(
    history_rows: Iterable[Mapping[str, Any]],
    *,
    prior_config: Mapping[str, Any],
) -> dict[str, Any]:
    rows = [dict(row) for row in history_rows]
    n = len(rows)
    minimum = int(prior_config["min_home_plate_games"])
    prior_games = int(prior_config["prior_equivalent_games"])
    prior = prior_config["league_prior"]
    metrics = {
        "runs": "runs_per_game",
        "strikeouts": "strikeouts_per_game",
        "walks": "walks_per_game",
    }
    if n < minimum:
        return {
            "home_plate_games": n,
            "min_home_plate_games": minimum,
            "sample_gate": "BELOW_MIN_GAMES_ZERO_DELTA",
            "deltas": {f"{name}_delta": 0.0 for name in metrics},
            "observed_means": None,
            "shrunk_means": None,
        }

    observed: dict[str, float] = {}
    shrunk: dict[str, float] = {}
    deltas: dict[str, float] = {}
    for row_key, prior_key in metrics.items():
        obs = _mean(rows, row_key)
        prior_value = float(prior[prior_key])
        shrunk_value = ((n * obs) + (prior_games * prior_value)) / (n + prior_games)
        observed[prior_key] = round(obs, 4)
        shrunk[prior_key] = round(shrunk_value, 4)
        deltas[f"{row_key}_delta"] = round(shrunk_value - prior_value, 4)
    return {
        "home_plate_games": n,
        "min_home_plate_games": minimum,
        "sample_gate": "PASS",
        "deltas": deltas,
        "observed_means": observed,
        "shrunk_means": shrunk,
    }


def _acquire_history_rows(
    *,
    umpire_id: int,
    official_date: str,
    opener: Callable,
    history_days: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    target_day = date.fromisoformat(official_date)
    start = target_day - timedelta(days=int(history_days))
    end = target_day - timedelta(days=1)
    if end < start:
        return [], []
    errors: list[str] = []
    try:
        board = _open_json(
            history_schedule_url(start_date=start.isoformat(), end_date=end.isoformat()),
            opener=opener,
        )
    except MLBUmpireSourceError as exc:
        return [], [str(exc)]
    rows: list[dict[str, Any]] = []
    for prior_game_pk in assigned_game_pks(board, umpire_id=umpire_id):
        try:
            boxscore = _open_json(boxscore_url(prior_game_pk), opener=opener)
        except MLBUmpireSourceError as exc:
            errors.append(f"game_{prior_game_pk}:{exc}")
            continue
        metrics = boxscore_game_metrics(boxscore, game_pk=prior_game_pk)
        if metrics is None:
            errors.append(f"game_{prior_game_pk}:BOXSCORE_METRICS_MISSING")
            continue
        rows.append(metrics)
    return rows, errors


def acquire_umpire_context(
    *,
    game_pk: int,
    as_of: datetime,
    live_payload: Mapping[str, Any] | None = None,
    official_date: str | None = None,
    opener: Callable = urlopen,
    history_rows: Iterable[Mapping[str, Any]] | None = None,
    prior_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    config = dict(prior_config) if prior_config is not None else load_prior_config()
    day = _official_date(live_payload, official_date)
    errors: list[str] = []
    assignment = home_plate_from_live(live_payload)
    assignment_source = "LIVE_BOXSCORE" if assignment else None

    if assignment is None and day:
        try:
            schedule_payload = _open_json(assignment_schedule_url(day), opener=opener)
            assignment = home_plate_from_schedule(schedule_payload, game_pk=int(game_pk))
            if assignment:
                assignment_source = "SCHEDULE_HYDRATE_OFFICIALS"
        except MLBUmpireSourceError as exc:
            errors.append(str(exc))

    if assignment is None:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "game_pk": int(game_pk),
            "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
            "official_date": day,
            "source": SOURCE,
            "assignment": None,
            "assignment_source": assignment_source,
            "prior_config_version": config.get("schema_version"),
            "tendencies": None,
            "history_rows": [],
            "errors": errors,
            "status": "MISSING_ASSIGNMENT",
            "model_p_eligible": False,
        }
        payload["payload_sha256"] = canonical_json_sha256(payload)
        return payload

    if history_rows is None:
        if day:
            rows, history_errors = _acquire_history_rows(
                umpire_id=int(assignment["umpire_id"]),
                official_date=day,
                opener=opener,
                history_days=int(config["history_days"]),
            )
            errors.extend(history_errors)
            history_source = "MLB_STATSAPI_SCHEDULE_BOXSCORES"
        else:
            rows = []
            history_source = "UNAVAILABLE_NO_OFFICIAL_DATE"
            errors.append("MISSING_OFFICIAL_DATE_FOR_HISTORY")
    else:
        rows = [dict(row) for row in history_rows]
        history_source = "INJECTED_FIXTURE_OR_PRECOMPUTED"

    tendencies = shrink_tendencies(rows, prior_config=config)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "game_pk": int(game_pk),
        "as_of_utc": as_of.astimezone(timezone.utc).isoformat(),
        "official_date": day,
        "source": SOURCE,
        "assignment": assignment,
        "assignment_source": assignment_source,
        "prior_config_version": config.get("schema_version"),
        "league_prior": config.get("league_prior"),
        "prior_equivalent_games": int(config["prior_equivalent_games"]),
        "history_source": history_source,
        "history_rows": rows,
        "tendencies": tendencies,
        "errors": errors,
        "status": "AVAILABLE",
        "model_p_eligible": False,
    }
    payload["payload_sha256"] = canonical_json_sha256(payload)
    return payload
