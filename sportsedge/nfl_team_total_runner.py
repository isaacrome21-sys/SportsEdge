"""Forward runner for NFL_TEAM_TOTAL_DIST_V1 (NFL team totals).

The pinned pricing/record path for the family's forward test
(``research/nfl_team_totals_forward_20261028/PREREG_NFL_TEAM_TOTALS_FORWARD_V1.md``).
It prices one NFL slate's paired DraftKings team-total ENTRY captures
with the pinned engine (``sportsedge/nfl_team_total_dist.py``), records
Lane A's emitted team mean for the same team-game alongside every
candidate row (preregistration section 6b), and writes create-only
run records. At settlement it attaches the valid close under the
preregistration's section 7 rules and the final team points.

Fail-closed discipline (preregistration section 8): a malformed row is
refused alone with exactly one named code; it never aborts the slate
and is never zero-filled. The runner's declared refusal code set and
its pairing/freshness constants are part of its freeze pin:

- ``ENTRY_PAIR_SPAN_S = 120`` — max seconds between the two side
  quotes of the ENTRY pair.
- ``CLOSE_PAIR_SPAN_S = 150`` — max seconds between the two side
  quotes of the CLOSE pair.
- ``QUOTE_FRESH_S = 180`` — max seconds between the earliest ENTRY
  side quote and the moment the row is priced (``QUOTE_STALE_180S``).
- ``CLOSE_WINDOW_S = 3600`` — the section 7 close rule: the close is
  the last capture before kickoff and no more than 60:00 before it
  (exactly 60:00 is valid).

The runner refuses to price anything when the framework config's
``model_version`` pin does not match the engine file on disk
(``MODEL_VERSION_MISMATCH``), or when the history snapshot contains a
game that is not a final regular-season game
(``HISTORY_SNAPSHOT_INVALID``): both are run-level refusals that write
no records at all.

PAPER / research only. Pricing rows starts no clock by itself; rows
count toward the forward test only under the freeze recorded in the
package's FREEZE_RECORD (the freeze takes effect at the merge of the
freeze-act PR, and only slates priced after that merge count).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from sportsedge import nfl_team_total_dist as eng
from sportsedge.forward_validation.core import load_config

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_PATH = REPO_ROOT / "sportsedge" / "nfl_team_total_dist.py"
CONFIG_PATH = (REPO_ROOT / "sportsedge" / "forward_validation"
               / "configs" / "nfl_team_total.json")
LANE_A_PATH = REPO_ROOT / "artifacts" / "free_models.py"
LANE_A_SHIM_PATH = REPO_ROOT / "free_models.py"

RUNNER_ID = "NFL_TEAM_TOTAL_RUNNER_V1"
RECORD_SCHEMA = "NFL_TEAM_TOTAL_FORWARD_ROW_V1"

ENTRY_PAIR_SPAN_S = 120
CLOSE_PAIR_SPAN_S = 150
QUOTE_FRESH_S = 180
CLOSE_WINDOW_S = 3600

PICK_GAP = 2.0  # preregistration section 5: |mu - line| >= 2.0 picks

# The runner's declared refusal code set (preregistration section 8:
# engine/runner refusals are the pinned runner's code set).
RUNNER_REFUSALS = (
    "MODEL_VERSION_MISMATCH",
    "HISTORY_SNAPSHOT_INVALID",
    "ENTRY_CAPTURE_MISSING",
    "ENTRY_SINGLE_SIDED",
    "ENTRY_NOT_PRE_EVENT",
    "ENTRY_PAIR_SPAN_EXCEEDED",
    "QUOTE_STALE_180S",
    "PRICE_INVALID",
    "LINE_INVALID",
    "LANE_A_EMISSION_MISSING",
    "DUPLICATE_ROW",
)

# Settlement close dispositions (preregistration sections 7-8).
CLOSE_DISPOSITIONS = (
    "READABLE",
    "LINE_MOVED",
    "NO_CLOSE_ROW",
    "CLOSE_SINGLE_SIDED",
    "CLOSE_NOT_PREKICKOFF",
    "CLOSE_STALE",
    "PAIR_SPAN_EXCEEDED",
)


class RunnerRefusal(Exception):
    """Run-level refusal: nothing is priced and no record is written."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ts(value) -> Optional[datetime]:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _price_ok(price) -> bool:
    return (isinstance(price, (int, float)) and not isinstance(price, bool)
            and math.isfinite(float(price)) and abs(float(price)) >= 100)


def _implied(price: float) -> float:
    price = float(price)
    return (-price) / (-price + 100) if price < 0 else 100 / (price + 100)


def _no_vig(over_price: float, under_price: float) -> dict:
    io, iu = _implied(over_price), _implied(under_price)
    total = io + iu
    return {"OVER": io / total, "UNDER": iu / total}


def _fair_american(p_win: float, p_loss: float) -> Optional[float]:
    denom = p_win + p_loss
    if denom <= 0:
        return None
    cond = p_win / denom
    if cond <= 0 or cond >= 1:
        return None
    if cond >= 0.5:
        return -100 * cond / (1 - cond)
    return 100 * (1 - cond) / cond


def _ev(p_win: float, p_loss: float, price: float) -> float:
    dec = 1 + (100 / abs(price) if price < 0 else price / 100)
    return p_win * (dec - 1) - p_loss


@dataclass(frozen=True)
class PairedQuote:
    """One paired two-sided quote from a single capture designation."""

    line: object
    over_price: object
    under_price: object
    over_captured_at: str
    under_captured_at: str


@dataclass(frozen=True)
class SlateGame:
    """One game on the slate board, with its ENTRY team-total quotes.

    ``entry_quotes`` maps an engine team code (home or away) to that
    team's paired ENTRY team-total quote. ``total_line`` /
    ``total_over_price`` are the game's DK game-total ENTRY quote,
    used only to elicit Lane A's emitted means for the same game
    (Lane A prices game rows; its emitted home/away means are the
    section 6b baseline). Lane A never feeds the candidate.
    """

    game_id: str
    season: int
    week: int
    gameday: str
    home_team: str
    away_team: str
    home_name: str
    away_name: str
    kickoff: str
    entry_quotes: dict
    total_line: object = None
    total_over_price: object = None


def history_snapshot_sha256(games: Sequence[eng.GameRecord]) -> str:
    """Canonical hash of the history snapshot the engine priced from."""
    ordered = sorted(games, key=eng._sort_key)
    canon = [{
        "season": g.season, "week": g.week, "gameday": g.gameday,
        "game_id": g.game_id, "home_team": g.home_team,
        "away_team": g.away_team, "home_score": g.home_score,
        "away_score": g.away_score, "game_type": g.game_type,
    } for g in ordered]
    blob = json.dumps(canon, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


class TeamTotalRunner:
    """Prices NFL team-total slates with the pinned engine.

    Construction verifies the freeze pins (run-level, fail-closed):
    the config's ``model_version`` must equal the sha256 pin of the
    engine file on disk, and the config must name this engine.
    """

    def __init__(self, history_games: Sequence[eng.GameRecord], *,
                 config_path: Path = CONFIG_PATH):
        cfg = load_config(config_path)
        engine_sha = _sha256_file(ENGINE_PATH)
        expected_pin = f"{eng.MODEL_VERSION}@sha256:{engine_sha}"
        if cfg.engine_id != eng.ENGINE_ID or cfg.model_version != expected_pin:
            raise RunnerRefusal(
                "MODEL_VERSION_MISMATCH",
                f"config pin {cfg.model_version!r} != engine pin "
                f"{expected_pin!r}")
        for g in history_games:
            if not g.is_final_regular:
                raise RunnerRefusal(
                    "HISTORY_SNAPSHOT_INVALID",
                    f"{g.game_id} type={g.game_type} "
                    f"home_score={g.home_score} away_score={g.away_score}")
        self.config = cfg
        self.engine_sha256 = engine_sha
        self.runner_sha256 = _sha256_file(Path(__file__))
        self.lane_a_sha256 = _sha256_file(LANE_A_PATH)
        self.history_sha256 = history_snapshot_sha256(history_games)
        self.engine = eng.TeamTotalDistEngine()
        # Canonical snapshot load: walk-forward over the snapshot in
        # the engine's own order; predictions on history games are
        # discarded, the recorded state is what prices the slate.
        self.engine.process_snapshot(list(history_games))

    # -- Lane A (section 6b baseline) -----------------------------------

    def _lane_a_team_means(self, game: SlateGame, now: datetime,
                           provider, auto_context: bool):
        """Lane A's emitted (home_mean, away_mean) for this game.

        Calls Lane A's own ``calculate`` on the game's TOTAL row with
        lane="A" (the independent lane) and reads the means from its
        emitted lane-A view. Production passes Lane A's public-context
        provider (auto_context=True); auto_context=False is Lane A's
        own no-fetch manual mode. Any refusal, block, or missing
        emission returns None: the caller refuses the row
        ``LANE_A_EMISSION_MISSING`` rather than inventing a baseline.
        """
        if game.total_line is None or not _price_ok(game.total_over_price):
            return None
        from artifacts import free_models as lane_a
        row = {
            "sport": "NFL", "market": "TOTAL", "side": "OVER",
            "line": game.total_line, "odds": game.total_over_price,
            "away": game.away_name, "home": game.home_name,
            "commence_time": game.kickoff,
        }
        try:
            result = lane_a.calculate(row, provider, now,
                                      auto_context=auto_context, lane="A")
        except Exception:
            return None
        view = ((result.get("pricing_lanes") or {})
                .get("lane_a_independent") or {})
        home_mean, away_mean = view.get("home_mean"), view.get("away_mean")
        if not (isinstance(home_mean, (int, float))
                and isinstance(away_mean, (int, float))
                and math.isfinite(home_mean) and math.isfinite(away_mean)):
            return None
        return float(home_mean), float(away_mean)

    # -- pricing ---------------------------------------------------------

    def price_slate(self, slate_date: str, games: Sequence[SlateGame], *,
                    now: datetime, lane_a_provider="LIVE",
                    lane_a_auto_context: bool = True) -> dict:
        """Price one slate. Returns {"records": [...], "refusals": [...]}.

        Each priced game produces one record per team. Each refused
        team-row produces one refusal entry with exactly one code from
        RUNNER_REFUSALS. ``now`` is the pricing moment (the records'
        priced_at); it must precede each game's kickoff for that
        game's rows to price. ``lane_a_provider`` defaults to Lane A's
        live public-context provider, built per game at ``now``.
        """
        records, refusals = [], []
        seen_row_ids = set()
        lane_a_cache: dict = {}
        for game in games:
            kickoff = _ts(game.kickoff)
            home_pred, away_pred = self.engine.predict_game(eng.GameRecord(
                season=game.season, week=game.week, gameday=game.gameday,
                game_id=game.game_id, home_team=game.home_team,
                away_team=game.away_team))
            preds = {game.home_team: home_pred, game.away_team: away_pred}
            sides = {game.home_team: "HOME", game.away_team: "AWAY"}
            for team in (game.home_team, game.away_team):
                row_id = f"{game.game_id}:{team}"
                refusal = self._row_refusal(game, team, kickoff, now,
                                            row_id, seen_row_ids)
                seen_row_ids.add(row_id)
                if refusal is None and game.game_id not in lane_a_cache:
                    provider = lane_a_provider
                    if provider == "LIVE":
                        from artifacts import free_models as lane_a
                        provider = lane_a.PublicContext(now)
                    lane_a_cache[game.game_id] = self._lane_a_team_means(
                        game, now, provider, lane_a_auto_context)
                if refusal is None and lane_a_cache.get(game.game_id) is None:
                    refusal = "LANE_A_EMISSION_MISSING"
                if refusal is not None:
                    refusals.append({"row_id": row_id, "game_id": game.game_id,
                                     "team": team, "reason": refusal})
                    continue
                home_mean, away_mean = lane_a_cache[game.game_id]
                lane_a_mean = (home_mean if sides[team] == "HOME"
                               else away_mean)
                records.append(self._build_record(
                    slate_date, game, team, sides[team], preds[team],
                    lane_a_mean, now))
        return {"records": records, "refusals": refusals}

    def _row_refusal(self, game: SlateGame, team: str,
                     kickoff: Optional[datetime], now: datetime,
                     row_id: str, seen_row_ids: set) -> Optional[str]:
        if row_id in seen_row_ids:
            return "DUPLICATE_ROW"
        quote = (game.entry_quotes or {}).get(team)
        if quote is None:
            return "ENTRY_CAPTURE_MISSING"
        if kickoff is None or now >= kickoff:
            return "ENTRY_NOT_PRE_EVENT"
        if quote.line is None or quote.over_price is None \
                or quote.under_price is None:
            return "ENTRY_SINGLE_SIDED"
        if not (_price_ok(quote.over_price) and _price_ok(quote.under_price)):
            return "PRICE_INVALID"
        if not (isinstance(quote.line, (int, float))
                and math.isfinite(float(quote.line)) and float(quote.line) > 0):
            return "LINE_INVALID"
        t_over, t_under = _ts(quote.over_captured_at), _ts(quote.under_captured_at)
        if t_over is None or t_under is None:
            return "ENTRY_CAPTURE_MISSING"
        if t_over >= kickoff or t_under >= kickoff:
            return "ENTRY_NOT_PRE_EVENT"
        if abs((t_over - t_under).total_seconds()) > ENTRY_PAIR_SPAN_S:
            return "ENTRY_PAIR_SPAN_EXCEEDED"
        if (now - min(t_over, t_under)).total_seconds() > QUOTE_FRESH_S:
            return "QUOTE_STALE_180S"
        return None

    def _build_record(self, slate_date: str, game: SlateGame, team: str,
                      side_of_game: str, pred, lane_a_mean: float,
                      now: datetime) -> dict:
        quote = game.entry_quotes[team]
        line = float(quote.line)
        mu = float(pred.mu)
        pmf = eng.nb_pmf_grid(mu)
        p_over = float(eng.prob_over(mu, line))
        p_under = float(eng.prob_under(mu, line))
        p_push = float(eng.prob_push(mu, line))
        gap = mu - line
        pick = ("PICKED_OVER" if gap >= PICK_GAP else
                "PICKED_UNDER" if gap <= -PICK_GAP else "PASSED")
        return {
            "schema": RECORD_SCHEMA,
            "row_id": f"{game.game_id}:{team}",
            "sport": "NFL", "family": "TEAM_TOTAL", "market": "TEAM_TOTAL",
            "slate_date": slate_date,
            "game_id": game.game_id, "team": team,
            "opponent": pred.opponent, "side_of_game": side_of_game,
            "season": game.season, "week": game.week,
            "kickoff": game.kickoff, "priced_at": now.isoformat(),
            "label": "PROSPECTIVE",
            "engine_id": eng.ENGINE_ID,
            "model_version": self.config.model_version,
            "engine_sha256": self.engine_sha256,
            "runner_id": RUNNER_ID, "runner_sha256": self.runner_sha256,
            "config_sha256": self.config.sha256,
            "prereg_sha256": self.config.prereg_sha256,
            "history_snapshot_sha256": self.history_sha256,
            "lane_a": {
                "artifacts_free_models_sha256": self.lane_a_sha256,
                "team_mean": lane_a_mean,
            },
            "mu": mu,
            "distribution": {
                "law": "NEGATIVE_BINOMIAL", "mu": mu,
                "c": eng.POOLED_CV_C, "support_max": eng.MAX_SCORE,
                "pmf": [float(x) for x in pmf],
            },
            "b1_team_mean": float(pred.b1_team_mean),
            "b2_league_mean": float(pred.b2_league_mean),
            "off_rate": float(pred.off_rate), "def_rate": float(pred.def_rate),
            "entry": {
                "line": line,
                "over_price": quote.over_price,
                "under_price": quote.under_price,
                "over_captured_at": quote.over_captured_at,
                "under_captured_at": quote.under_captured_at,
                "no_vig": _no_vig(quote.over_price, quote.under_price),
            },
            "model_p": {"OVER": p_over, "UNDER": p_under, "PUSH": p_push},
            "fair_odds": {"OVER": _fair_american(p_over, p_under),
                          "UNDER": _fair_american(p_under, p_over)},
            "ev": {"OVER": _ev(p_over, p_under, quote.over_price),
                   "UNDER": _ev(p_under, p_over, quote.under_price)},
            "gap": gap, "pick": pick,
        }


def write_entry_records(records: Sequence[dict], out_path) -> Path:
    """Create-only record writer: refuses to touch an existing file,
    so a slate's committed records can never be rewritten in place."""
    path = Path(out_path)
    if path.exists():
        raise RunnerRefusal("RECORD_FILE_EXISTS", str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    return path


def evaluate_close(record: dict, close_quotes: Sequence[PairedQuote], *,
                   void: bool = False,
                   final_team_points: Optional[int] = None) -> dict:
    """Attach the section 7 close disposition and the settlement.

    ``close_quotes`` are every paired capture for the record's
    team-game after ENTRY. The valid close is the last paired capture
    before kickoff whose earliest side quote is no more than 60:00
    before kickoff; all other shapes resolve to exactly one named
    disposition from CLOSE_DISPOSITIONS. The outcome leg records the
    final team points, or VOID / RESULT_UNAVAILABLE / PUSH per
    preregistration section 3.
    """
    out = {"row_id": record["row_id"], "game_id": record["game_id"],
           "team": record["team"]}
    kickoff = _ts(record["kickoff"])
    entry_line = record["entry"]["line"]
    priced = [q for q in close_quotes
              if _price_ok(q.over_price) and _price_ok(q.under_price)
              and isinstance(q.line, (int, float))]
    if not close_quotes:
        out["close_status"] = "NO_CLOSE_ROW"
    elif not priced:
        out["close_status"] = "CLOSE_SINGLE_SIDED"
    else:
        pre = []
        for q in priced:
            t_o, t_u = _ts(q.over_captured_at), _ts(q.under_captured_at)
            if t_o is not None and t_u is not None \
                    and t_o < kickoff and t_u < kickoff:
                pre.append((max(t_o, t_u), min(t_o, t_u), q))
        if not pre:
            out["close_status"] = "CLOSE_NOT_PREKICKOFF"
        else:
            _, earliest, last = max(pre, key=lambda x: x[0])
            if (kickoff - earliest).total_seconds() > CLOSE_WINDOW_S:
                out["close_status"] = "CLOSE_STALE"
            else:
                t_o, t_u = (_ts(last.over_captured_at),
                            _ts(last.under_captured_at))
                if abs((t_o - t_u).total_seconds()) > CLOSE_PAIR_SPAN_S:
                    out["close_status"] = "PAIR_SPAN_EXCEEDED"
                else:
                    novig = _no_vig(last.over_price, last.under_price)
                    out["close"] = {
                        "line": float(last.line),
                        "over_price": last.over_price,
                        "under_price": last.under_price,
                        "over_captured_at": last.over_captured_at,
                        "under_captured_at": last.under_captured_at,
                        "no_vig": novig,
                    }
                    if float(last.line) == entry_line:
                        out["close_status"] = "READABLE"
                    else:
                        out["close_status"] = "LINE_MOVED"
                        # Move direction per NFL props v1.1: for the
                        # row's sign(gap) side, a close line that makes
                        # that side harder to win is adverse (OVER:
                        # line up; UNDER: line down), easier is
                        # favorable.
                        side = ("OVER" if record["gap"] >= 0 else "UNDER")
                        harder = (float(last.line) > entry_line
                                  if side == "OVER"
                                  else float(last.line) < entry_line)
                        out["moved_side"] = side
                        out["moved_direction"] = ("ADVERSE" if harder
                                                   else "FAVORABLE")
    if void:
        out["settlement"] = "VOID"
    elif final_team_points is None:
        out["settlement"] = "RESULT_UNAVAILABLE"
    else:
        out["settlement"] = "GRADED"
        out["final_team_points"] = int(final_team_points)
        if float(final_team_points) == entry_line:
            out["push"] = True
    return out
