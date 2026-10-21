"""NBA player-props forward-test evaluator — the §12 implementation of
the FROZEN preregistration
``research/nba_props_forward_20261020/PREREG_NBA_PROPS_FORWARD_V1.md``
(sha256 54363908b1e2332a57af9b9263ac2f398438c81b2d366442b80667086657bc79;
frozen 2026-10-20 by owner ruling). This module is that document's
evaluator: it is hash-pinned to the frozen text by the family configs
(``prereg`` / ``prereg_sha256``) and by the constants below, and no §9
verdict can issue under the preregistration except through it.

Scope (prereg §2): exactly the four canonical registry families
``player_points``, ``player_rebounds``, ``player_assists``,
``player_pra``, priced by ``NBA_PROP_EMPIRICAL_V1``
(``sportsedge/nba_prop_empirical.py``; cards price them through
``sportsedge/nba_phone_prop_pricing.py``). The scoring mechanics —
admission refusals, the §7 close rule, the five CLV_MISSING reasons,
no-vig CLV, game-clustered bootstrap CIs, the §4 gates and the §8
>20% rule — are the framework's (``core.py``), reused unchanged; the
§9 picked-vs-passed verdict condition is the core picked/passed mode
the four configs declare. What lives here is the prereg's input
discipline, applied before the framework sees a row:

- §2 scope: a row whose sport is not NBA, or whose market is not the
  family's market, is refused ``MARKET_OUT_OF_SCOPE`` and excluded
  from inference — reported in the record, never silently absorbed
  into a denominator.
- §5 row construction: a prospective in-scope row must carry the
  engine stamp — ``engine_id`` = ``NBA_PROP_EMPIRICAL_V1``,
  ``sufficiency_met`` true, ``n_prior`` >= 10, pool source, store
  provenance, and the engine's declared participation limitation
  (accepted from an ``engine_stamp`` mapping, the pricing lane's
  ``nba_prop_engine`` mapping, or top-level fields of the same
  names). A row without engine provenance is not an engine row: it is
  excluded and reported, with the missing elements named. HISTORICAL
  rows skip the stamp screen — they are excluded from verdict math
  by the framework regardless — but they are still scope-screened.
- §5 picked/passed: each row must carry the runner's disposition
  (``disposition`` or the lane's ``status``); unclassifiable rows are
  reported by the core aggregation and enter no denominator.

Boundary (§4): prospective counting begins with the first slate
captured after the freeze — Wednesday Oct 21, 2026. That boundary is
enforced by record discipline (only post-freeze slates are submitted
as PROSPECTIVE records; anything written after an event starts must
be labeled HISTORICAL and is excluded), exactly as the frozen Part 2
test enforces its own boundary. This evaluator invents no date gate
of its own.

Nothing here prices a market, changes any family's registration,
eligibility, or validation state, or creates a PLAY: the four
families stay REGISTERED_RESEARCH_ONLY / NOT_VALIDATED, and a
BEATS_MARKET verdict is evidence for an owner ruling (prereg §9).
"""
from __future__ import annotations

from pathlib import Path

from . import core
from .core import FamilyConfig, ForwardValidationRefusal, load_config

PREREG_PATH = ("research/nba_props_forward_20261020/"
               "PREREG_NBA_PROPS_FORWARD_V1.md")
PREREG_SHA256 = ("54363908b1e2332a57af9b9263ac2f398438c81b2d366"
                 "442b80667086657bc79")
ENGINE_ID = "NBA_PROP_EMPIRICAL_V1"
MIN_PRIOR_GAMES = 10  # prereg §5: n_prior >= 10 on every engine row

CONFIG_FILES = {
    "player_points": "nba_player_points.json",
    "player_rebounds": "nba_player_rebounds.json",
    "player_assists": "nba_player_assists.json",
    "player_pra": "nba_player_pra.json",
}

_CONFIG_DIR = Path(__file__).resolve().parent / "configs"


def load_nba_config(family: str) -> FamilyConfig:
    """Load one family's frozen config and verify the §12 pin: the
    config must name the frozen preregistration, carry its sha256,
    pin the engine version the frozen header names, and declare the
    §9 picked/passed mode. Any drift refuses CONFIG_INVALID — a
    config that no longer matches the frozen document is a different
    test and must not score under this one's name."""
    if family not in CONFIG_FILES:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID", {"field": "family", "value": family,
                               "known": sorted(CONFIG_FILES)})
    cfg = load_config(_CONFIG_DIR / CONFIG_FILES[family])
    problems = {}
    if cfg.sport != "NBA" or cfg.markets != [family]:
        problems["identity"] = {"sport": cfg.sport, "markets": cfg.markets}
    if cfg.engine_id != ENGINE_ID or cfg.model_version != ENGINE_ID:
        problems["engine_pin"] = {"engine_id": cfg.engine_id,
                                  "model_version": cfg.model_version}
    if cfg.prereg != PREREG_PATH or cfg.prereg_sha256 != PREREG_SHA256:
        problems["prereg_pin"] = {"prereg": cfg.prereg,
                                  "prereg_sha256": cfg.prereg_sha256}
    if not cfg.picked_beats_passed_required:
        problems["picked_beats_passed_required"] = False
    if problems:
        raise ForwardValidationRefusal("CONFIG_INVALID", problems)
    return cfg


def _stamp_of(row: dict) -> dict:
    """The engine stamp (§5), wherever the producing lane put it: an
    explicit ``engine_stamp`` mapping, the phone lane's
    ``nba_prop_engine`` mapping, or top-level fields of the same names."""
    for key in ("engine_stamp", "nba_prop_engine"):
        stamp = row.get(key)
        if isinstance(stamp, dict):
            return stamp
    return row


def _provenance_problems(cfg: FamilyConfig, row: dict) -> list:
    stamp = _stamp_of(row)
    problems = []
    if stamp.get("engine_id") != cfg.engine_id:
        problems.append("ENGINE_ID_MISSING_OR_MISMATCH")
    if stamp.get("sufficiency_met") is not True:
        problems.append("SUFFICIENCY_NOT_MET")
    n_prior = stamp.get("n_prior")
    try:
        sufficient = n_prior is not None and float(n_prior) >= MIN_PRIOR_GAMES
    except (TypeError, ValueError):
        sufficient = False
    if not sufficient:
        problems.append("N_PRIOR_MISSING_OR_BELOW_10")
    if not stamp.get("pool_source"):
        problems.append("POOL_SOURCE_MISSING")
    if not (stamp.get("store_provenance") or stamp.get("history_basis")):
        problems.append("STORE_PROVENANCE_MISSING")
    if not (stamp.get("limitation") or stamp.get("participation_limitation")
            or stamp.get("participation_feed")):
        problems.append("PARTICIPATION_LIMITATION_MISSING")
    return problems


def screen_nba_rows(cfg: FamilyConfig, rows: list) -> tuple[list, dict]:
    """Apply the prereg's §2 scope refusal and §5 provenance screen.
    Returns (admissible_rows, exclusions); the framework's admission
    refusals (version, timestamps, duplicates, post-start) apply to
    the survivors unchanged."""
    kept, out_of_scope, no_provenance = [], [], []
    for row in rows:
        row_id = row.get("row_id") or "<no row_id>"
        if row.get("sport") not in (None, "NBA") \
                or row.get("market") not in cfg.markets:
            out_of_scope.append({
                "row_id": row_id, "reason": "MARKET_OUT_OF_SCOPE",
                "sport": row.get("sport"), "market": row.get("market")})
            continue
        if (row.get("label") or "PROSPECTIVE") == "HISTORICAL":
            kept.append(row)  # excluded from verdict math by the framework
            continue
        problems = _provenance_problems(cfg, row)
        if problems:
            no_provenance.append({"row_id": row_id, "problems": problems})
            continue
        kept.append(row)
    return kept, {"out_of_scope_rows": out_of_scope,
                  "no_engine_provenance_rows": no_provenance}


def evaluate_nba_props(cfg: FamilyConfig, entry_rows: list, close_rows: list,
                       outcomes: list, *,
                       slates_completed: int | None = None) -> dict:
    """Score one NBA prop family under the frozen preregistration.
    ``cfg`` must come from :func:`load_nba_config` (the §12 pin is
    verified there). Inputs follow the framework's record contracts
    (README.md) plus the §5 engine stamp and runner disposition.
    Returns the framework verdict record, with the prereg named on its
    face and the §2/§5 exclusions merged into ``record["excluded"]``.
    Raises ForwardValidationRefusal on any fail-closed condition."""
    kept, exclusions = screen_nba_rows(cfg, entry_rows)
    record = core.evaluate_family(cfg, kept, close_rows, outcomes,
                                  slates_completed=slates_completed)
    record["label"] = (
        "FORWARD VALIDATION — verdict record under PREREG_NBA_PROPS_"
        "FORWARD_V1 (FROZEN 2026-10-20; CLV primary per §6, verdicts "
        "per §9; no verdict creates a PLAY)")
    record["excluded"] = {**exclusions, **record["excluded"]}
    return record
