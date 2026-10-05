#!/usr/bin/env python3
"""One-look MLB pitcher-prop promotion study preregistered in #1538.

This file is safe to import and unit-test before the postseason ends. The evidence
path is gated by a completed-World-Series check and is never exercised by CI.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from math import floor, log
from pathlib import Path
import random
import re
import subprocess
import sys
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sportsedge.mlb_all_market_features import MLBAllMarketHistorySource
from sportsedge.mlb_generic_features import MLBGenericFeatureError
from sportsedge.mlb_history_cache import MLBHistoryCachedOpener
from sportsedge.mlb_source import fetch_boxscore, fetch_schedule, parse_game_start
from sportsedge.pitcher_joint_engine import price_pitcher_market

PREREG = Path("docs/MLB_PITCHER_PROP_PROMOTION_PREREG.md")
PIT_CONTEXT_AMENDMENT = Path("docs/MLB_PITCHER_PROP_PROMOTION_PIT_CONTEXT_AMENDMENT.md")
MARKETS = ("PITCHER_K", "PITCHER_BB", "PITCHER_ER", "PITCHER_HITS_ALLOWED")
STAT_KEY = {
    "PITCHER_K": "strikeOuts",
    "PITCHER_BB": "baseOnBalls",
    "PITCHER_ER": "earnedRuns",
    "PITCHER_HITS_ALLOWED": "hits",
}
BOOT_REPS = 2000
BOOT_SEED = 20261005
CI_LEVEL = 0.9875
MIN_UNITS = 150
MIN_BETS = 40
EV_FLOOR = 0.02
TAIL_LOW = 0.10
TAIL_HIGH = 0.90
EASTERN = ZoneInfo("America/New_York")
WS_START = "2026-10-20"
WS_END_SCAN = "2026-11-15"
API = "https://statsapi.mlb.com/api/v1"
PIT_CONTEXT_MAX_AGE_SECONDS = 20 * 60
CONTEXT_PATH_RE = re.compile(r"^runtime/mlb-context/runs/[^/]+/[^/]+/game_(\d+)\.json$")


def _get_json(url: str) -> dict:
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "SportsEdge/1.0"})
    with urlopen(req, timeout=30) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise RuntimeError("MLB_PROMOTION_SOURCE_NOT_OBJECT")
    return value


def _parse_iso(value) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("timezone-aware timestamp required")
    return dt.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _person(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    folded = "".join(c for c in decomposed if not unicodedata.combining(c))
    parts = []
    for raw in folded.replace(".", " ").replace("-", " ").split():
        token = "".join(c.lower() for c in raw if c.isalnum())
        if token:
            parts.append(token)
    while parts and parts[-1] in {"jr", "sr", "ii", "iii", "iv", "v"}:
        parts.pop()
    return "".join(parts)


def _words(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", str(value or "")).lower())


def _team_variants(value: str) -> tuple[str, ...]:
    parts = _words(value)
    vals = {" ".join(parts)}
    if len(parts) >= 2:
        vals.add(" ".join(parts[-2:]))
    if parts:
        vals.add(parts[-1])
    return tuple(sorted(v for v in vals if v))


def _event_has_team(event_name: str, team_name: str) -> bool:
    event = " ".join(_words(event_name))
    return any(v in event for v in _team_variants(team_name))


def american_to_decimal(odds: int) -> float:
    o = int(odds)
    if o == 0 or -100 < o < 100:
        raise ValueError("invalid American odds")
    return 1.0 + (o / 100.0 if o > 0 else 100.0 / abs(o))


def fair_over_probability(over_odds: int, under_odds: int) -> float:
    do = american_to_decimal(over_odds)
    du = american_to_decimal(under_odds)
    io, iu = 1.0 / do, 1.0 / du
    return io / (io + iu)


def is_half_line(value: float) -> bool:
    x = float(value)
    return abs((x - floor(x)) - 0.5) <= 1e-9


def _unique_price(rows: list[dict], side: str) -> int | None:
    prices = {int(r["american_odds"]) for r in rows if str(r.get("side", "")).upper() == side}
    return next(iter(prices)) if len(prices) == 1 else None


def select_units(payloads, *, cutoff: datetime | None = None) -> tuple[list[dict], dict[str, int]]:
    """Keep the last admissible two-sided half-line snapshot per provider event/pitcher/market."""
    selected: dict[tuple[str, str, str], dict | None] = {}
    drops = Counter()
    for payload in payloads:
        if payload.get("archive_type") != "MLB_PROP_PIT_QUOTES":
            continue
        if payload.get("provider") != "DRAFTKINGS_WEB_RESEARCH":
            continue
        grouped: dict[tuple[str, str, str], dict[float, list[dict]]] = defaultdict(lambda: defaultdict(list))
        for raw in payload.get("quotes") or []:
            if not isinstance(raw, dict):
                continue
            market = str(raw.get("market") or "").upper()
            if market not in MARKETS or not raw.get("pit_eligible") or raw.get("is_alternate"):
                continue
            if str(raw.get("book_key") or "") != "draftkings_direct":
                continue
            try:
                line = float(raw.get("line"))
                first_pitch = _parse_iso(raw.get("first_pitch_at"))
                retrieved = _parse_iso(raw.get("quote_retrieved_at") or raw.get("retrieved_at"))
            except Exception:
                drops["invalid_timestamp_or_line"] += 1
                continue
            if not is_half_line(line):
                drops["integer_or_non_half_line"] += 1
                continue
            if retrieved >= first_pitch or (cutoff is not None and first_pitch > cutoff):
                drops["not_eligible_time"] += 1
                continue
            event_id = str(raw.get("provider_event_id") or "").strip()
            entity = str(raw.get("entity_name_normalized") or _person(raw.get("entity_name") or "")).strip()
            if not event_id or not entity:
                drops["missing_identity"] += 1
                continue
            grouped[(event_id, entity, market)][line].append(raw)

        for key, by_line in grouped.items():
            valid = []
            for line, rows in by_line.items():
                over = _unique_price(rows, "OVER")
                under = _unique_price(rows, "UNDER")
                if over is None or under is None:
                    continue
                exemplar = rows[0]
                observed = max(_parse_iso(r.get("quote_retrieved_at") or r.get("retrieved_at")) for r in rows)
                valid.append({
                    "provider_event_id": key[0],
                    "entity_name_normalized": key[1],
                    "entity_name": str(exemplar.get("entity_name") or ""),
                    "market": key[2],
                    "line": float(line),
                    "over_odds": over,
                    "under_odds": under,
                    "observed_at": observed.isoformat(),
                    "first_pitch_at": _parse_iso(exemplar.get("first_pitch_at")).isoformat(),
                    "event_name": str(exemplar.get("event_name") or ""),
                    "archive_captured_at": str(exemplar.get("archive_captured_at") or payload.get("captured_at") or ""),
                })
            if len(valid) == 1:
                selected[key] = valid[0]
            elif len(valid) > 1:
                selected[key] = None
                drops["ambiguous_multiple_main_lines"] += 1
    out = [row for row in selected.values() if isinstance(row, dict)]
    drops["selected_units"] = len(out)
    return sorted(out, key=lambda r: (r["first_pitch_at"], r["provider_event_id"], r["entity_name_normalized"], r["market"])), dict(drops)


def _world_series_cutoff() -> datetime | None:
    q = urlencode({"sportId": 1, "gameTypes": "W", "startDate": WS_START, "endDate": WS_END_SCAN})
    payload = _get_json(f"{API}/schedule?{q}")
    finals: list[datetime] = []
    incomplete = 0
    for block in payload.get("dates") or []:
        for game in block.get("games") or []:
            status = game.get("status") or {}
            abstract = str(status.get("abstractGameState") or "")
            detailed = str(status.get("detailedState") or "")
            if abstract == "Final":
                finals.append(_parse_iso(game.get("gameDate")))
            elif detailed.lower() not in {"cancelled", "canceled"}:
                incomplete += 1
    if len(finals) < 4 or incomplete:
        return None
    return max(finals)


def _data_branch_paths() -> list[str]:
    subprocess.run(["git", "fetch", "--quiet", "origin", "data"], check=True)
    raw = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "origin/data", "runtime/mlb-prop-pit"],
        text=True,
    )
    return sorted(p for p in raw.splitlines() if "/props_" in p and p.endswith(".json"))


def _payloads_from_data():
    for path in _data_branch_paths():
        raw = subprocess.check_output(["git", "show", f"origin/data:{path}"])
        yield json.loads(raw)


class PITContextError(RuntimeError):
    pass


def choose_pit_context(candidates, *, observed_at: datetime):
    """Latest context snapshot at/before the quote, bounded by a frozen 20-minute age."""
    observed = observed_at.astimezone(timezone.utc)
    eligible = []
    for path, payload in candidates:
        if not isinstance(payload, dict):
            continue
        try:
            captured = _parse_iso(payload.get("retrieved_at"))
        except Exception:
            continue
        age = (observed - captured).total_seconds()
        if 0 <= age <= PIT_CONTEXT_MAX_AGE_SECONDS:
            eligible.append((captured, str(path), payload))
    if not eligible:
        return None
    captured, path, payload = max(eligible, key=lambda row: (row[0], row[1]))
    return {"path": path, "retrieved_at": captured.isoformat(), "payload": payload}


class PITContextArchive:
    """Read immutable pregame MLB context snapshots from the data branch."""

    def __init__(self, paths_by_game):
        self.paths_by_game = {int(k): tuple(v) for k, v in paths_by_game.items()}
        self._payload_cache = {}

    @classmethod
    def from_data(cls):
        raw = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", "origin/data", "runtime/mlb-context/runs"],
            text=True,
        )
        by_game = defaultdict(list)
        for path in raw.splitlines():
            match = CONTEXT_PATH_RE.match(path)
            if match:
                by_game[int(match.group(1))].append(path)
        return cls(by_game)

    def _load(self, path: str):
        if path not in self._payload_cache:
            raw = subprocess.check_output(["git", "show", f"origin/data:{path}"])
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise PITContextError("PIT_CONTEXT_NOT_OBJECT")
            self._payload_cache[path] = value
        return self._payload_cache[path]

    def latest(self, *, game_pk: int, observed_at: datetime):
        candidates = [(path, self._load(path)) for path in self.paths_by_game.get(int(game_pk), ())]
        return choose_pit_context(candidates, observed_at=observed_at)


def _context_lineup_orders(proof) -> dict[int, tuple[int, ...]]:
    payload = proof["payload"]
    state = str((payload.get("source_states") or {}).get("confirmed_lineup") or "").upper()
    if state == "ABSENT":
        return {}
    if state != "PRESENT":
        raise PITContextError("PIT_LINEUP_STATE_UNPROVEN")
    grouped = defaultdict(list)
    for row in payload.get("lineups") or []:
        if not isinstance(row, dict) or str(row.get("starter_status") or "") != "CONFIRMED_STARTER":
            continue
        try:
            grouped[int(row["team_id"])].append((int(row["batting_order"]), int(row["player_id"])))
        except (KeyError, TypeError, ValueError):
            raise PITContextError("PIT_LINEUP_ROW_INVALID")
    orders = {}
    for team_id, rows in grouped.items():
        rows = sorted(rows)
        if [slot for slot, _ in rows] == list(range(1, 10)) and len({pid for _, pid in rows}) == 9:
            orders[team_id] = tuple(pid for _, pid in rows)
    if len(orders) != 2:
        raise PITContextError("PIT_LINEUP_PRESENT_BUT_INCOMPLETE")
    return orders


def _context_umpire(proof):
    payload = proof["payload"]
    state = str((payload.get("source_states") or {}).get("plate_umpire") or "").upper()
    if state == "ABSENT":
        return None
    if state != "PRESENT":
        raise PITContextError("PIT_UMPIRE_STATE_UNPROVEN")
    row = payload.get("umpire") or {}
    try:
        umpire_id = int(row["home_plate_umpire_id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PITContextError("PIT_UMPIRE_PRESENT_BUT_INVALID") from exc
    return {
        "umpire_id": umpire_id,
        "umpire_name": str(row.get("home_plate_umpire_name") or "").strip() or None,
        "official_type": "Home Plate",
    }


def bind_pit_context(source, *, game_pk: int, market: str, proof):
    """Force current-game optional context to the archived decision-time state."""
    if proof is None:
        raise PITContextError("PIT_CONTEXT_FRESH_SNAPSHOT_MISSING")
    summary = {
        "path": proof["path"],
        "retrieved_at": proof["retrieved_at"],
        "max_age_seconds": PIT_CONTEXT_MAX_AGE_SECONDS,
        "confirmed_lineup": (proof["payload"].get("source_states") or {}).get("confirmed_lineup"),
        "plate_umpire": (proof["payload"].get("source_states") or {}).get("plate_umpire"),
    }
    if market == "PITCHER_K":
        orders = _context_lineup_orders(proof)
        original = source._lineup_boxscore
        def pit_lineup_boxscore(pk):
            if int(pk) == int(game_pk):
                return {"orders": orders}
            return original(pk)
        source._lineup_boxscore = pit_lineup_boxscore
    elif market == "PITCHER_BB":
        umpire = _context_umpire(proof)
        original_umpire = source.plate_umpire
        def pit_plate_umpire(*, game_pk: int, target_date: date):
            if int(game_pk) == int(summary_game_pk):
                return umpire
            return original_umpire(game_pk=game_pk, target_date=target_date)
        summary_game_pk = int(game_pk)
        source.plate_umpire = pit_plate_umpire
    return summary


def _match_game(unit: dict, schedule) -> object | None:
    fp = _parse_iso(unit["first_pitch_at"])
    candidates = []
    for game in schedule:
        if not (_event_has_team(unit["event_name"], game.away_name) and _event_has_team(unit["event_name"], game.home_name)):
            continue
        delta = abs((parse_game_start(game.game_date) - fp).total_seconds())
        if delta <= 3 * 3600:
            candidates.append((delta, game))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1].game_pk))
    if len(candidates) > 1 and abs(candidates[1][0] - candidates[0][0]) <= 60:
        return None
    return candidates[0][1]


def _starter_identity(boxscore: dict, game, entity_normalized: str):
    matches = []
    teams = boxscore.get("teams") or {}
    for side, team_id in (("away", game.away_id), ("home", game.home_id)):
        row = teams.get(side) or {}
        pitchers = row.get("pitchers") or []
        if not pitchers:
            continue
        try:
            pid = int(pitchers[0])
        except (TypeError, ValueError):
            continue
        person = (row.get("players") or {}).get(f"ID{pid}") or {}
        name = str((person.get("person") or {}).get("fullName") or "")
        if _person(name) == entity_normalized:
            matches.append((pid, int(team_id), side, person))
    return matches[0] if len(matches) == 1 else None


def _outcome_stat(person: dict, market: str) -> int:
    pitching = ((person.get("stats") or {}).get("pitching") or {})
    value = pitching.get(STAT_KEY[market])
    if value is None:
        raise ValueError("pitcher outcome stat missing")
    return int(value)


def _model_probability(unit: dict, game, pitcher_id: int, team_id: int, *, cache_dir: Path, pit_context=None) -> tuple[float, dict, dict | None]:
    target_date = datetime.fromisoformat(str(game.official_date)).date() if game.official_date else parse_game_start(game.game_date).date()
    opener = MLBHistoryCachedOpener(target_date=target_date, cache_dir=cache_dir)
    source = MLBAllMarketHistorySource(opener=opener, retrieved_at=_parse_iso(unit["observed_at"]))
    context_proof = None
    if unit["market"] in {"PITCHER_K", "PITCHER_BB"}:
        context_proof = bind_pit_context(
            source, game_pk=int(game.game_pk), market=unit["market"], proof=pit_context
        )
    own = source.pitcher_joint_rows(player_id=pitcher_id, target_date=target_date)
    if len(own) < 5:
        raise MLBGenericFeatureError("PROMOTION_STUDY_REQUIRES_K_GE_5")
    feature = source.feature_row(
        game_pk=int(game.game_pk), market=unit["market"], entity_id=str(pitcher_id),
        target_date=target_date, away_team_id=int(game.away_id), home_team_id=int(game.home_id),
        player_id=int(pitcher_id), team_id=int(team_id),
    )
    result = price_pitcher_market({
        "game_id": str(game.game_pk), "market": unit["market"], "entity_id": str(pitcher_id),
        "line": float(unit["line"]), "side": "OVER", "feature_source_hash": feature.get("source_subset_hash"),
        "features": feature["features"],
    })
    return float(result["model_p"]), feature, context_proof


def _ll(p: float, y: int) -> float:
    p = min(1 - 1e-12, max(1e-12, float(p)))
    return -(y * log(p) + (1 - y) * log(1 - p))


def _flag(model_p_over: float, over_odds: int, under_odds: int, outcome_over: int) -> dict | None:
    candidates = []
    for side, p, odds, won in (
        ("OVER", model_p_over, over_odds, bool(outcome_over)),
        ("UNDER", 1.0 - model_p_over, under_odds, not bool(outcome_over)),
    ):
        if p <= TAIL_LOW or p >= TAIL_HIGH:
            continue
        dec = american_to_decimal(odds)
        ev = p * dec - 1.0
        if ev >= EV_FLOOR:
            candidates.append((ev, side, p, dec, won))
    if not candidates:
        return None
    ev, side, p, dec, won = max(candidates, key=lambda x: x[0])
    return {"side": side, "model_p": p, "decimal_odds": dec, "ev": ev, "won": won, "pnl": dec - 1.0 if won else -1.0}


def grade_unit(unit: dict, game, pitcher_id: int, person: dict, model_p_over: float) -> dict:
    stat = _outcome_stat(person, unit["market"])
    outcome_over = int(stat > float(unit["line"]))
    q_over = fair_over_probability(unit["over_odds"], unit["under_odds"])
    flagged = _flag(model_p_over, unit["over_odds"], unit["under_odds"], outcome_over)
    return {
        **unit,
        "game_pk": int(game.game_pk),
        "pitcher_id": int(pitcher_id),
        "observed_stat": stat,
        "outcome_over": outcome_over,
        "model_p_over": float(model_p_over),
        "market_q_over": q_over,
        "ll_diff": _ll(model_p_over, outcome_over) - _ll(q_over, outcome_over),
        "brier_diff": (model_p_over - outcome_over) ** 2 - (q_over - outcome_over) ** 2,
        "flagged": flagged,
    }


def _quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("empty quantile")
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo = int(floor(pos))
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


def _cluster_ci(rows: list[dict], value_fn, include_fn=lambda r: True, *, seed: int = BOOT_SEED) -> dict | None:
    clusters: dict[int, list[float]] = defaultdict(list)
    for row in rows:
        if include_fn(row):
            clusters[int(row["pitcher_id"])].append(float(value_fn(row)))
    if not clusters:
        return None
    keys = sorted(clusters)
    point_vals = [v for key in keys for v in clusters[key]]
    rng = random.Random(seed)
    boots = []
    for _ in range(BOOT_REPS):
        sampled = [keys[rng.randrange(len(keys))] for _ in keys]
        vals = [v for key in sampled for v in clusters[key]]
        boots.append(sum(vals) / len(vals))
    alpha = (1.0 - CI_LEVEL) / 2.0
    return {
        "value": sum(point_vals) / len(point_vals),
        "lo": _quantile(boots, alpha),
        "hi": _quantile(boots, 1.0 - alpha),
        "clusters": len(keys),
        "n": len(point_vals),
    }


def _reliability(rows: list[dict]) -> list[dict]:
    bins = [[] for _ in range(10)]
    for row in rows:
        p = min(1 - 1e-12, max(1e-12, float(row["model_p_over"])))
        bins[min(9, int(p * 10))].append(row)
    out = []
    for i, bucket in enumerate(bins):
        if bucket:
            out.append({"bin": i, "n": len(bucket), "mean_p": sum(r["model_p_over"] for r in bucket) / len(bucket),
                        "win_rate": sum(r["outcome_over"] for r in bucket) / len(bucket)})
    return out


def market_metrics(rows: list[dict]) -> dict:
    ll = _cluster_ci(rows, lambda r: r["ll_diff"])
    roi = _cluster_ci(rows, lambda r: r["flagged"]["pnl"], include_fn=lambda r: r.get("flagged") is not None, seed=BOOT_SEED)
    flags = [r for r in rows if r.get("flagged") is not None]
    passes = bool(
        len(rows) >= MIN_UNITS and len(flags) >= MIN_BETS and ll and ll["hi"] < 0 and roi and roi["lo"] > 0
    )
    buckets = {"2-5%": [], "5-10%": [], "10%+": []}
    for row in flags:
        ev = row["flagged"]["ev"]
        key = "2-5%" if ev < 0.05 else ("5-10%" if ev < 0.10 else "10%+")
        buckets[key].append(row["flagged"]["pnl"])
    return {
        "units": len(rows),
        "flagged_bets": len(flags),
        "delta_log_loss": ll,
        "flagged_roi": roi,
        "flagged_win_rate": None if not flags else sum(1 for r in flags if r["flagged"]["won"]) / len(flags),
        "mean_model_minus_market": None if not rows else sum(r["model_p_over"] - r["market_q_over"] for r in rows) / len(rows),
        "mean_brier_diff": None if not rows else sum(r["brier_diff"] for r in rows) / len(rows),
        "reliability": _reliability(rows),
        "roi_by_ev_bucket": {k: (None if not v else {"n": len(v), "roi": sum(v) / len(v)}) for k, v in buckets.items()},
        "passes_promotion_rule": passes,
    }


def render_report(result: dict) -> str:
    lines = ["## MLB pitcher-prop promotion final look", ""]
    lines.append(f"Pre-registration SHA-256: `{result['prereg_sha256']}`.")
    lines.append(f"PIT-context amendment SHA-256: `{result['pit_context_amendment_sha256']}`.")
    lines.append("One-look study; no model fitting or threshold tuning is performed here.")
    lines.append("")
    lines.append("| market | units | flagged | ΔLL 98.75% CI | ROI 98.75% CI | decision |")
    lines.append("|---|---:|---:|---|---|---|")
    for market in MARKETS:
        m = result["markets"][market]
        ll = m["delta_log_loss"]
        roi = m["flagged_roi"]
        ll_txt = "n/a" if not ll else f"{ll['value']:.4f} [{ll['lo']:.4f}, {ll['hi']:.4f}]"
        roi_txt = "n/a" if not roi else f"{roi['value']:.3f} [{roi['lo']:.3f}, {roi['hi']:.3f}]"
        decision = "PASS" if m["passes_promotion_rule"] else "STAYS LEAN"
        lines.append(f"| {market} | {m['units']} | {m['flagged_bets']} | {ll_txt} | {roi_txt} | {decision} |")
    lines.append("")
    lines.append("Drop counts: " + ", ".join(f"{k}={v}" for k, v in sorted(result["drops"].items())) + ".")
    lines.append("")
    lines.append("A PASS only makes a market eligible for a separate promotion PR; this run creates no deployment, staking, or OFFICIAL authority.")
    return "\n".join(lines) + "\n"


def run_final(*, out_dir: Path, cache_dir: Path) -> dict:
    cutoff = _world_series_cutoff()
    if cutoff is None:
        raise RuntimeError("POSTSEASON_NOT_COMPLETE_NO_LOOK")
    units, drops = select_units(_payloads_from_data(), cutoff=cutoff)
    context_archive = PITContextArchive.from_data()
    schedule_cache = {}
    box_cache = {}
    graded = []
    for unit in units:
        day = _parse_iso(unit["first_pitch_at"]).astimezone(EASTERN).date().isoformat()
        schedule = schedule_cache.setdefault(day, fetch_schedule(day, now=_parse_iso(unit["observed_at"])))
        game = _match_game(unit, schedule)
        if game is None:
            drops["game_identity_unresolved"] = drops.get("game_identity_unresolved", 0) + 1
            continue
        if str(game.status).lower() != "final":
            drops["game_not_final"] = drops.get("game_not_final", 0) + 1
            continue
        box = box_cache.setdefault(int(game.game_pk), fetch_boxscore(int(game.game_pk)))
        starter = _starter_identity(box, game, unit["entity_name_normalized"])
        if starter is None:
            drops["starter_identity_unresolved"] = drops.get("starter_identity_unresolved", 0) + 1
            continue
        pitcher_id, team_id, _side, person = starter
        try:
            pit_context = None
            if unit["market"] in {"PITCHER_K", "PITCHER_BB"}:
                pit_context = context_archive.latest(
                    game_pk=int(game.game_pk), observed_at=_parse_iso(unit["observed_at"])
                )
            p, _feature, context_proof = _model_probability(
                unit, game, pitcher_id, team_id, cache_dir=cache_dir, pit_context=pit_context
            )
            row = grade_unit(unit, game, pitcher_id, person, p)
            if context_proof is not None:
                row["pit_context_proof"] = context_proof
            graded.append(row)
        except PITContextError as exc:
            key = "pit_context_unproven:" + str(exc)
            drops[key] = drops.get(key, 0) + 1
            continue
        except MLBGenericFeatureError:
            drops["production_path_blocked"] = drops.get("production_path_blocked", 0) + 1
            continue
    by_market = {market: [r for r in graded if r["market"] == market] for market in MARKETS}
    result = {
        "schema": "MLB_PITCHER_PROP_PROMOTION_FINAL_LOOK_V1",
        "prereg_sha256": _sha256(PREREG),
        "pit_context_amendment_sha256": _sha256(PIT_CONTEXT_AMENDMENT),
        "postseason_cutoff_utc": cutoff.isoformat(),
        "bootstrap": {"reps": BOOT_REPS, "seed": BOOT_SEED, "ci_level": CI_LEVEL, "cluster": "pitcher_id"},
        "drops": drops,
        "markets": {market: market_metrics(rows) for market, rows in by_market.items()},
        "graded_rows": graded,
        "authority": {"model_p_change": False, "deployment": False, "staking": False, "official": False},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out_dir / "report.md").write_text(render_report(result), encoding="utf-8")
    return result


def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out-dir", type=Path, default=Path("artifacts/mlb_research_pitcher_prop_promotion"))
    p.add_argument("--cache", type=Path, default=Path(".cache/mlb-pitcher-prop-promotion"))
    args = p.parse_args(argv)
    try:
        result = run_final(out_dir=args.out_dir, cache_dir=args.cache)
    except RuntimeError as exc:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        msg = f"## MLB pitcher-prop promotion final look\n\n**BLOCKED:** {exc}. No archived outcomes were graded.\n"
        (args.out_dir / "report.md").write_text(msg, encoding="utf-8")
        print(msg)
        return 2
    print(render_report(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
