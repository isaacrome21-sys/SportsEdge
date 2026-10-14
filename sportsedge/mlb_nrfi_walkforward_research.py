"""Offline MLB first-inning run-rate research; no odds, feeds, or betting authority.

Consumes caller-supplied OPEN_RESEARCH game outcomes only. A game's outcome
may enter training strictly after its recorded result-known timestamp, never
because its scheduled start is earlier. Scores are chronological diagnostics,
not validated market probabilities or prospective grading.
"""

from datetime import datetime, timezone
from math import log


def _utc(value):
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be an ISO-8601 string")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ValueError("invalid timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _prepare(rows):
    if not isinstance(rows, (list, tuple)):
        raise ValueError("rows must be a sequence")
    games, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("game must be an object")
        event = row.get("event_id")
        home, away = row.get("home_team"), row.get("away_team")
        if (not isinstance(event, str) or not event.strip() or event in seen
                or not isinstance(home, str) or not home.strip()
                or not isinstance(away, str) or not away.strip() or home == away
                or type(row.get("yrfi")) is not bool):
            raise ValueError("invalid or duplicate game identity/outcome")
        scheduled = _utc(row.get("scheduled_at_utc"))
        cutoff = _utc(row.get("forecast_cutoff_utc"))
        known = _utc(row.get("result_known_at_utc"))
        if not (cutoff < scheduled < known):
            raise ValueError("cutoff must precede start and result-known must follow start")
        seen.add(event)
        games.append((cutoff, event, home, away, row["yrfi"], known))
    return sorted(games, key=lambda g: (g[0], g[1]))


def evaluate_nrfi_walkforward(rows, *, dataset_scope):
    """Evaluate smoothed league and team-rate YRFI forecasts on open data.

    Uses Beta(1,1) league smoothing and team shrinkage weight 12. Neither is
    a fitted/approved model or a production eligibility threshold.
    """
    if dataset_scope != "OPEN_RESEARCH":
        raise ValueError("sealed, prospective, or unspecified data scope refused")
    games = _prepare(rows)
    results = []
    for cutoff, event, home, away, yrfi, _known in games:
        eligible = [g for g in games if g[5] < cutoff]
        league_n = len(eligible)
        league_y = sum(int(g[4]) for g in eligible)
        league_p = (league_y + 1.0) / (league_n + 2.0)
        rates = []
        for team in (home, away):
            matching = [g for g in eligible if team in (g[2], g[3])]
            team_y = sum(int(g[4]) for g in matching)
            rates.append((team_y + 12.0 * league_p) / (len(matching) + 12.0))
        team_p = sum(rates) / 2.0
        actual = float(yrfi)
        results.append({
            "event_id": event, "forecast_cutoff_utc": cutoff.isoformat(),
            "training_games_known_before_cutoff": league_n,
            "league_yrfi_probability": league_p,
            "team_shrunk_yrfi_probability": team_p,
            "observed_yrfi": yrfi,
            "league_brier": (league_p - actual) ** 2,
            "team_brier": (team_p - actual) ** 2,
            "league_log_loss": -(actual * log(league_p) + (1 - actual) * log(1 - league_p)),
            "team_log_loss": -(actual * log(team_p) + (1 - actual) * log(1 - team_p)),
        })
    n = len(results)
    metrics = {name: sum(r[name] for r in results) / n if n else None
               for name in ("league_brier", "team_brier", "league_log_loss", "team_log_loss")}
    return {
        "schema": "SPORTSEDGE_MLB_NRFI_OPEN_RESEARCH_WALKFORWARD_V1",
        "dataset_scope": "OPEN_RESEARCH", "evaluated_games": n,
        "rows": results, "metrics": metrics,
        "source_authenticity_verified": False,
        "historical_outcome_authenticity_verified": False,
        "market_probability_verified": False,
        "prospective_grading_verified": False,
        "pricing_authority": False, "play_authority": False, "staking_authority": False,
    }
