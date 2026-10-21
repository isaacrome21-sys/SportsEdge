"""MLB full-game terminal-score exotics from the existing M7 score joint.

Pure research readouts only. The source distribution is the incumbent,
deployment-gated GameTotalDistribution; this module does not fit a model,
create a new history pool, fabricate DraftKings quotes, or alter a gate.

Supported events are functions solely of the FINAL (away, home) score:
both-teams-to-score 1+..9+, final correct score, final winning margin,
and a selected team's final run parity.

IMPORTANT CONSTRUCTION / SETTLEMENT LIMITATION: The source full-game
joint is the independent PRODUCT of the away and home final-score
marginals. In the reviewed reference joint this assigns 0.1933
(19.33%) to tied final-score cells, although an official MLB final
game cannot end tied (true final-tie event probability 0). The
WINNING_MARGIN TIE readout returns 0.1775 (17.75%) from that artifact
after settlement-mass stabilization. The WINNING_MARGIN TIE bucket
and all exact tied FINAL-score cells inherit this nonphysical mass.
The frozen research screen will score the unchanged eleven-class
WINNING_MARGIN partition against actual untied finals: observed TIE=0;
retain the model's TIE probability as-is and penalize it through the
full multiclass Brier/log loss, without deleting or renormalizing the
bucket. Tied CORRECT_SCORE cells likewise receive zero observed wins.
These figures are reviewed reference values, not a historical test.

EXTRA_INNINGS is intentionally unsupported: a final score, including
extra-innings runs, does not disclose whether the clubs were tied after
nine innings. Likewise, no scoring-order, inning or play-event market can
be reconstructed from a final-score joint.

All input score states are validated, posterior settlement mass uses the
same Jeffreys discipline as F5 derived readouts, and the readout SHA
includes the original joint-distribution SHA. There is NO historical
market-leg evaluation, validation, eligibility or deployment authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Mapping, Sequence

from .f5_derived_readouts import (
    ANY_OTHER, correct_score_selection, margin_band_selection,
    margin_bands_partition, parse_correct_score_selection, parse_margin_band,
)
from .game_total_distribution import GameTotalDistribution
from .mlb_empirical_bayes import JEFFREYS_ALPHA, posterior_settlement_mass
from .source_lineage import canonical_json_sha256

VERSION = "mlb_m50_terminal_score_readout_v1_jeffreys"
BTTS_MIN_RUNG = 1
BTTS_MAX_RUNG = 9
TERMINAL_SCORE_MARKETS = frozenset({
    "BOTH_TEAMS_TO_SCORE_RUNS", "CORRECT_SCORE",
    "WINNING_MARGIN", "TEAM_TOTAL_ODD_EVEN",
})
NO_SCORE_PATH_MARKETS = frozenset({
    "EXTRA_INNINGS", "GRAND_SLAM", "RACE_TO_RUNS",
    "INNING_OF_FIRST_RUN", "INNING_OF_LAST_RUN",
    "TEAM_WITH_HIGHEST_SCORING_INNING", "TEAM_TO_WIN_MOST_INNINGS",
    "BAT_IN_BOTTOM_9TH", "FIRST_SCORING_PLAY_RUNS",
})


class GameExoticReadoutError(ValueError):
    """Named refusal: unsupported settlement or malformed score state."""


@dataclass(frozen=True)
class GameExoticReadout:
    market: str
    selection: str
    line: int | None
    probability: float
    push_probability: float
    distribution_sha256: str
    readout_sha256: str
    readout_version: str = VERSION
    status: str = "RESEARCH_ESTIMATE_UNVALIDATED"
    eligible: bool = False
    market_test: str = "NO_MARKET_TEST"


def _states(distribution: GameTotalDistribution) -> tuple[tuple[int, int, float], ...]:
    if not isinstance(distribution, GameTotalDistribution):
        raise GameExoticReadoutError("FULL_GAME_DISTRIBUTION_REQUIRED")
    result = []
    total = 0.0
    for key, raw in distribution.joint_score_pmf.items():
        try:
            text_away, text_home = key.split(",")
            away, home, p = int(text_away), int(text_home), float(raw)
        except (AttributeError, TypeError, ValueError) as exc:
            raise GameExoticReadoutError("INVALID_FULL_GAME_SCORE_STATE") from exc
        if (key != f"{away},{home}" or min(away, home) < 0
                or not isfinite(p) or p < 0):
            raise GameExoticReadoutError("INVALID_FULL_GAME_SCORE_STATE")
        result.append((away, home, p))
        total += p
    if not result or abs(total - 1.0) > 1e-12:
        raise GameExoticReadoutError("FULL_GAME_SCORE_MASS_NOT_CONSERVED")
    if (min(distribution.away_history_games,
            distribution.home_history_games) <= 0):
        raise GameExoticReadoutError("NO_HISTORY_EFFECTIVE_SAMPLE")
    if not isinstance(distribution.distribution_sha256, str) or (
            len(distribution.distribution_sha256) != 64 or
            any(x not in "0123456789abcdef" for x in
                distribution.distribution_sha256.lower())):
        raise GameExoticReadoutError("DISTRIBUTION_HASH_REQUIRED")
    return tuple(result)


def _rung(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise GameExoticReadoutError("BTTS_INTEGER_RUNG_REQUIRED")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise GameExoticReadoutError("BTTS_INTEGER_RUNG_REQUIRED") from exc
    if (not isfinite(number) or number != int(number) or
            not BTTS_MIN_RUNG <= number <= BTTS_MAX_RUNG):
        raise GameExoticReadoutError("BTTS_RUNG_OUT_OF_CATALOG")
    return int(number)


def _binary_posterior(mass: float, n: float, *, positive: bool) -> float:
    posterior = posterior_settlement_mass(
        over_mass=mass, under_mass=1.0 - mass, push_mass=0.0,
        effective_n=n, has_push=False)
    return float(posterior["p_over" if positive else "p_under"])


def _posterior_partition(raw: Mapping[str, float], n: float) -> dict[str, float]:
    if not raw or abs(sum(raw.values()) - 1.0) > 1e-9:
        raise GameExoticReadoutError("SELECTION_PARTITION_NOT_CONSERVED")
    if any((not isfinite(x)) or x < -1e-12 for x in raw.values()):
        raise GameExoticReadoutError("SELECTION_PARTITION_INVALID_MASS")
    weights = {name: JEFFREYS_ALPHA + n * max(0.0, p)
               for name, p in raw.items()}
    denominator = sum(weights.values())
    return {name: value / denominator for name, value in weights.items()}


def _canonical_partition(partition: Sequence[str], parser, label: str) -> dict:
    if (not isinstance(partition, Sequence) or isinstance(partition, (str, bytes))
            or not partition):
        raise GameExoticReadoutError(f"{label}_COMPLETE_PARTITION_REQUIRED")
    parsed = {}
    for raw in partition:
        try:
            item = parser(raw)
            name = (correct_score_selection(item) if label == "CORRECT_SCORE"
                    else margin_band_selection(item))
        except ValueError as exc:
            raise GameExoticReadoutError(f"{label}_SELECTION_MALFORMED") from exc
        if name in parsed:
            raise GameExoticReadoutError(f"{label}_DUPLICATE_SELECTION")
        parsed[name] = item
    return parsed


def _readout(distribution: GameTotalDistribution, *, market: str,
             selection: str, line: int | None, probability: float,
             evidence: Mapping[str, Any]) -> GameExoticReadout:
    material = {
        "readout_version": VERSION,
        "distribution_sha256": distribution.distribution_sha256,
        "market": market,
        "selection": selection,
        "line": line,
        "probability": float(probability),
        "push_probability": 0.0,
        "evidence": dict(evidence),
    }
    return GameExoticReadout(
        market, selection, line, float(probability), 0.0,
        distribution.distribution_sha256, canonical_json_sha256(material))


def read_game_exotic_probability(
    distribution: GameTotalDistribution,
    *, market: str, selection: str, line: Any = None,
    team_side: str | None = None, partition: Sequence[str] | None = None,
) -> GameExoticReadout:
    """Read one terminal-score settlement cell; never create a market price.

    Winning-margin and correct-score forms REQUIRE a complete partition.
    The caller, not this module, must independently verify that a bookmaker
    actually offered every member of that partition at the same fixture.
    No quote binding or deployment path is provided here.
    """
    market = str(market or "").strip().upper()
    if market not in TERMINAL_SCORE_MARKETS:
        code = ("REQUIRES_NINTH_INNING_STATE" if market == "EXTRA_INNINGS"
                else "NON_TERMINAL_SCORE_EVENT_OR_UNSUPPORTED_MARKET")
        raise GameExoticReadoutError(code)
    states = _states(distribution)
    n = float(min(distribution.away_history_games,
                  distribution.home_history_games))
    selected = str(selection or "").strip().upper()
    extra = {}
    if market == "BOTH_TEAMS_TO_SCORE_RUNS":
        rung = _rung(line)
        if selected not in {"YES", "NO"}:
            raise GameExoticReadoutError("BTTS_YES_NO_SELECTION_REQUIRED")
        yes_mass = sum(p for away, home, p in states
                       if min(away, home) >= rung)
        probability = _binary_posterior(yes_mass, n, positive=selected == "YES")
        line_out = rung
        extra = {"raw_yes_mass": yes_mass, "effective_history_games": n}
    elif market == "TEAM_TOTAL_ODD_EVEN":
        team = str(team_side or "").strip().upper()
        if team not in {"AWAY", "HOME"}:
            raise GameExoticReadoutError("ODD_EVEN_TEAM_SIDE_REQUIRED")
        if selected not in {"ODD", "EVEN"}:
            raise GameExoticReadoutError("ODD_EVEN_SELECTION_REQUIRED")
        if line is not None:
            raise GameExoticReadoutError("ODD_EVEN_MUST_NOT_HAVE_LINE")
        odd_mass = sum(p for away, home, p in states
                       if (away if team == "AWAY" else home) % 2 == 1)
        probability = _binary_posterior(odd_mass, n, positive=selected == "ODD")
        line_out = None
        extra = {"team_side": team, "raw_odd_mass": odd_mass,
                 "effective_history_games": n}
    elif market == "CORRECT_SCORE":
        if line is not None:
            raise GameExoticReadoutError("CORRECT_SCORE_MUST_NOT_HAVE_LINE")
        cells = _canonical_partition(partition, parse_correct_score_selection,
                                     "CORRECT_SCORE")
        if ANY_OTHER not in cells:
            raise GameExoticReadoutError("CORRECT_SCORE_ANY_OTHER_REQUIRED")
        try:
            selected = correct_score_selection(parse_correct_score_selection(selected))
        except ValueError as exc:
            raise GameExoticReadoutError("CORRECT_SCORE_SELECTION_MALFORMED") from exc
        if selected not in cells:
            raise GameExoticReadoutError("CORRECT_SCORE_SELECTION_NOT_IN_PARTITION")
        raw = {}
        for name, parsed in cells.items():
            if name == ANY_OTHER:
                continue
            raw[name] = sum(p for away, home, p in states
                            if away == parsed[1] and home == parsed[2])
        raw[ANY_OTHER] = max(0.0, 1.0 - sum(raw.values()))
        probability = _posterior_partition(raw, n)[selected]
        line_out = None
        extra = {"partition": sorted(cells), "raw_cell_mass": raw[selected],
                 "effective_history_games": n}
    else:
        if line is not None:
            raise GameExoticReadoutError("WINNING_MARGIN_MUST_NOT_HAVE_LINE")
        cells = _canonical_partition(partition, parse_margin_band,
                                     "WINNING_MARGIN")
        if not margin_bands_partition(list(cells.values())):
            raise GameExoticReadoutError("WINNING_MARGIN_INCOMPLETE_PARTITION")
        try:
            selected = margin_band_selection(parse_margin_band(selected))
        except ValueError as exc:
            raise GameExoticReadoutError("WINNING_MARGIN_SELECTION_MALFORMED") from exc
        if selected not in cells:
            raise GameExoticReadoutError("WINNING_MARGIN_SELECTION_NOT_IN_PARTITION")
        raw = {name: sum(p for away, home, p in states
                         if band.contains(home - away))
               for name, band in cells.items()}
        probability = _posterior_partition(raw, n)[selected]
        line_out = None
        extra = {"partition": sorted(cells), "raw_cell_mass": raw[selected],
                 "effective_history_games": n}
    return _readout(distribution, market=market, selection=selected,
                    line=line_out, probability=probability, evidence=extra)
