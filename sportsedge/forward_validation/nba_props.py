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

V2 PREPARATION (added 2026-10-26; owner ruling: source amendment
approved for preparation, FREEZE HELD). The V2 preregistration
(``PREREG_NBA_PROPS_FORWARD_V2``) is V1's new version under V1 §10:
it changes only the admitted store source; every other term is
V1's, unchanged. The V1 path above is untouched — V1 configs, the
V1 pin, and V1 scoring behave exactly as frozen. What is added is
purely additive: a V2 pin registry entry (the final-candidate
text's sha256, pinned alongside V1's, never instead of it), V2
family configs (identical gates; status FINAL-CANDIDATE — NOT
FROZEN), a document-pin verifier that fails closed on a tampered
text, and a V2 entry point that partitions rows by declared prereg
identity (``prereg_id``) and counting class (``counting_class``)
BEFORE any scoring: a V2 verdict is computed only over rows declared
V2 + COUNTED; V1 rows, V2 research rows, and undeclared rows are
reported in the record's separation block and never blended into a
V2 denominator. Until the owner freezes V2, these functions prepare
and prove the integration — they authorize no counted row. And
since the Oct 26, 2026 repair (owner ruling on the independent
review's Concern 1), the V2 entry point enforces that hold itself:
while the V2 config state declares NOT FROZEN, a counted evaluation
attempt raises ``V2_FREEZE_NOT_AUTHORIZED`` before any scoring —
the authorization boundary no longer rests on upstream record
discipline alone.
"""
from __future__ import annotations

import hashlib
import re
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

# --- V2 (source amendment) pin registry — added alongside V1's pin ---
PREREG_ID_V1 = "PREREG_NBA_PROPS_FORWARD_V1"
PREREG_ID_V2 = "PREREG_NBA_PROPS_FORWARD_V2"
PREREG_PATH_V2 = ("research/nba_props_forward_20261020/"
                  "PREREG_NBA_PROPS_FORWARD_V2.md")
# sha256 of the FINAL-CANDIDATE V2 text (prepared 2026-10-26; the
# same bytes live in the goal workspace as
# NBA_PROPS_PREREG_V2_SOURCE_AMENDMENT_DRAFT_20261026.md). At the
# owner's freeze, the frozen text must hash to this value or the pin
# is re-struck on the frozen bytes — never silently.
PREREG_SHA256_V2 = ("9a20c19193095ebb9f93b12fae3877465b81f91682427ba2"
                    "770e60ebe5b3b944")

CONFIG_FILES_V2 = {
    "player_points": "nba_player_points_v2.json",
    "player_rebounds": "nba_player_rebounds_v2.json",
    "player_assists": "nba_player_assists_v2.json",
    "player_pra": "nba_player_pra_v2.json",
}

# Explicit recognized V2 states. The owner's future freeze changes the
# pinned document header and the registered status to the exact FROZEN token,
# with a new document SHA; it never depends on a caller-supplied substring.
V2_HELD_CONFIG_STATUS = (
    "FINAL-CANDIDATE -- NOT FROZEN -- PREREG_NBA_PROPS_FORWARD_V2 "
    "source amendment (prepared 2026-10-26; freeze HELD by owner)"
)
V2_FROZEN_CONFIG_STATUS = "FROZEN"

_CONFIG_DIR = Path(__file__).resolve().parent / "configs"
_REPO_ROOT = Path(__file__).resolve().parents[2]


def verify_prereg_document(version: str = "V1", *,
                           document_path=None) -> dict:
    """Hash the preregistration document on disk and check it against
    the pinned sha256 for ``version``. Fails closed: a missing or
    tampered document raises PREREG_PIN_MISMATCH — a text that does
    not hash to its pin is not the document the pin names and must
    not score under its name."""
    if version == "V1":
        rel, want = PREREG_PATH, PREREG_SHA256
    elif version == "V2":
        rel, want = PREREG_PATH_V2, PREREG_SHA256_V2
    else:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID", {"field": "version", "value": version,
                               "known": ["V1", "V2"]})
    path = Path(document_path) if document_path is not None \
        else _REPO_ROOT / rel
    try:
        raw = path.read_bytes()
    except OSError:
        raise ForwardValidationRefusal(
            "PREREG_PIN_MISMATCH",
            {"version": version, "path": str(path),
             "problem": "DOCUMENT_MISSING"})
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        raise ForwardValidationRefusal(
            "PREREG_PIN_MISMATCH",
            {"version": version, "path": str(path),
             "expected": want, "found": got})
    return {"version": version, "path": rel, "sha256": got}


def load_nba_config(family: str, version: str = "V1") -> FamilyConfig:
    """Load one family's config and verify its prereg pin: the config
    must name the preregistration of ``version`` (V1 default — the
    frozen document), carry its sha256, pin the engine version the
    frozen header names, and declare the §9 picked/passed mode. Any
    drift refuses CONFIG_INVALID — a config that no longer matches
    its document is a different test and must not score under this
    one's name. For V2 the config's NOT FROZEN or FROZEN state must match the
    actual status header of the pinned on-disk V2 document; the owner
    freeze is the documented change of both pins/statuses, not a caller flag
    (PREREG_PIN_MISMATCH, fail closed)."""
    if version == "V1":
        files, path_c, sha_c = CONFIG_FILES, PREREG_PATH, PREREG_SHA256
    elif version == "V2":
        files, path_c, sha_c = (CONFIG_FILES_V2, PREREG_PATH_V2,
                                PREREG_SHA256_V2)
    else:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID", {"field": "version", "value": version,
                               "known": ["V1", "V2"]})
    if family not in files:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID", {"field": "family", "value": family,
                               "known": sorted(files)})
    cfg = load_config(_CONFIG_DIR / files[family])
    problems = {}
    if cfg.sport != "NBA" or cfg.markets != [family]:
        problems["identity"] = {"sport": cfg.sport, "markets": cfg.markets}
    if cfg.engine_id != ENGINE_ID or cfg.model_version != ENGINE_ID:
        problems["engine_pin"] = {"engine_id": cfg.engine_id,
                                  "model_version": cfg.model_version}
    if cfg.prereg != path_c or cfg.prereg_sha256 != sha_c:
        problems["prereg_pin"] = {"prereg": cfg.prereg,
                                  "prereg_sha256": cfg.prereg_sha256}
    if version == "V2":
        # The pinned document is authoritative; the config cannot manufacture
        # an independent freeze.
        doc_state = _v2_document_freeze_state()
        cfg_state = _v2_config_freeze_state(cfg.status)
        if cfg_state != doc_state:
            problems["status"] = {"status": cfg.status,
                                  "document_state": doc_state}
    if not cfg.picked_beats_passed_required:
        problems["picked_beats_passed_required"] = False
    if problems:
        raise ForwardValidationRefusal("CONFIG_INVALID", problems)
    if version == "V2":
        verify_prereg_document("V2")
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


# ----------------------------------------------------------------------
# V2 separation — rows declare their test and their counting class;
# a V2 verdict is computed ONLY over V2 counted rows (V2 prereg §10).
# ----------------------------------------------------------------------

def partition_nba_rows(rows: list) -> dict:
    """Partition entry rows by declared prereg identity and counting
    class. A row declares its test in ``prereg_id``
    (``PREREG_NBA_PROPS_FORWARD_V1`` / ``..._V2``) and, under V2, its
    class in ``counting_class`` (``COUNTED`` / ``RESEARCH``).

    Fail-closed defaults: a V2 row whose counting class is missing
    or anything other than COUNTED is a RESEARCH row; a row with no
    (or an unknown) prereg identity is UNDECLARED. Neither research
    nor undeclared rows can ever enter a V2 verdict sample — the
    absence of a declaration is never read as permission to count."""
    parts = {"v1_rows": [], "v2_counted_rows": [], "v2_research_rows": [],
             "undeclared_rows": []}
    for row in rows:
        pid = row.get("prereg_id")
        if pid == PREREG_ID_V1:
            parts["v1_rows"].append(row)
        elif pid == PREREG_ID_V2:
            if str(row.get("counting_class") or "").upper() == "COUNTED":
                parts["v2_counted_rows"].append(row)
            else:
                parts["v2_research_rows"].append(row)
        else:
            parts["undeclared_rows"].append(row)
    return parts


def _separation_block(parts: dict) -> dict:
    return {name: {"count": len(rs),
                   "row_ids": [r.get("row_id") or "<no row_id>"
                               for r in rs]}
            for name, rs in parts.items()}


def _v2_document_freeze_state() -> str:
    """Read held/frozen state from the exact pinned preregistration bytes.

    Only the unique status header counts; later mentions of the phrase
    NOT FROZEN elsewhere in the document are explanatory, not state.
    """
    verify_prereg_document("V2")
    lines = (_REPO_ROOT / PREREG_PATH_V2).read_text(encoding="utf-8").splitlines()
    headers = [line for line in lines[:12] if line.startswith("**Status: ")]
    if len(headers) != 1:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID", {"field": "v2_document_status_header"})
    # Parse only the emphasized status field, never substrings in prose.
    match = re.match(r"^\*\*Status: ([^*]+)\*\*(?:\s|$)", headers[0])
    if not match:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID", {"field": "v2_document_status_header"})
    status = match.group(1).strip()
    if status == "FINAL-CANDIDATE — NOT FROZEN.":
        return "NOT_FROZEN"
    if status == "FROZEN.":
        return "FROZEN"
    raise ForwardValidationRefusal(
        "CONFIG_INVALID", {"field": "v2_document_status", "value": headers[0]})


def _v2_config_freeze_state(status: str | None) -> str:
    if status == V2_HELD_CONFIG_STATUS:
        return "NOT_FROZEN"
    if status == V2_FROZEN_CONFIG_STATUS:
        return "FROZEN"
    return "INVALID"


def _v2_freeze_authorized(authentic_cfg: FamilyConfig) -> bool:
    """Authorize only the pinned document + on-disk config freeze state."""
    return (_v2_document_freeze_state() == "FROZEN"
            and _v2_config_freeze_state(authentic_cfg.status) == "FROZEN")


def evaluate_nba_props_v2(cfg: FamilyConfig, entry_rows: list,
                          close_rows: list, outcomes: list, *,
                          slates_completed: int | None = None) -> dict:
    """Score one NBA prop family under the V2 source amendment —
    the ONLY public entry to a counted V2 verdict, and itself the
    freeze gate (owner ruling, Oct 26, 2026, on the independent
    review's Concern 1: the evaluator must refuse unauthorized
    counting itself, not rely on upstream record discipline).

    ``cfg`` must come from ``load_nba_config(family, version="V2")``
    — a V1 (or any non-V2-pinned) config is refused CONFIG_INVALID,
    so a V2 verdict can never issue under V1's pin.

    FREEZE GATE: while the pinned document/config state remains NOT
    FROZEN (see :func:`_v2_freeze_authorized`), any input row that
    declares V2 + COUNTED and is prospective is a counted evaluation
    attempt, and the attempt is refused
    ``V2_FREEZE_NOT_AUTHORIZED`` — raised after partitioning,
    BEFORE screening or any scoring (``core.evaluate_family`` is
    never reached; no record, verdict, or counted row id is
    emitted). Inputs carrying no prospective counted row — research
    diagnostics, class-less rows, and HISTORICAL counted rows (the
    framework's unchanged historical exclusion) — still return
    their diagnostic record. There is no caller-controlled bypass:
    no parameter, flag, or alternate public entry reaches the
    scorer around this gate.
    """
    # Re-load the genuine committed config and verify its pinned document
    # for every counted evaluation; caller cfg objects cannot grant a freeze.
    if len(cfg.markets) != 1 or cfg.markets[0] not in CONFIG_FILES_V2:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID", {"field": "v2_family", "markets": cfg.markets})
    authentic_cfg = load_nba_config(cfg.markets[0], version="V2")
    parts = partition_nba_rows(entry_rows)
    attempted = [r for r in parts["v2_counted_rows"]
                 if (r.get("label") or "PROSPECTIVE") != "HISTORICAL"]
    if attempted and not _v2_freeze_authorized(authentic_cfg):
        raise ForwardValidationRefusal(
            "V2_FREEZE_NOT_AUTHORIZED",
            {"prereg_id": PREREG_ID_V2,
             "config_status": authentic_cfg.status,
             "attempted_counted_rows": len(attempted),
             "attempted_counted_row_ids": sorted(
                 r.get("row_id") or "<no row_id>" for r in attempted),
             "rule": "counted V2 evaluation requires the owner's pinned "
                     "document/config freeze; V2 is NOT FROZEN"})
    if cfg != authentic_cfg:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID",
            {"field": "v2_caller_config_mismatch",
             "required_sha256": authentic_cfg.sha256,
             "caller_sha256": cfg.sha256})
    return _score_nba_props_v2(cfg, entry_rows, close_rows, outcomes,
                               slates_completed=slates_completed)


def _score_nba_props_v2(cfg: FamilyConfig, entry_rows: list,
                        close_rows: list, outcomes: list, *,
                        slates_completed: int | None = None) -> dict:
    """The V2 scoring implementation behind the gated entry point:
    partition, §2/§5 screens, framework scoring, provenance record.
    Internal on purpose — NOT exported and NOT an entry point. The
    test suite calls it directly as a research diagnostic to prove
    the verdict math and the §10 separation; a record produced here
    is an authorized counted verdict ONLY when it issued through
    :func:`evaluate_nba_props_v2` under a frozen V2 state. The mixed
    input is partitioned by :func:`partition_nba_rows` BEFORE
    screening and scoring: only V2 counted rows reach the framework,
    under the same screens and the same core mechanics V1 uses (the
    amendment changes the store source, nothing else). The record
    carries the counted rows' provenance on its face —
    ``counted_row_ids`` plus a ``separation`` block naming every
    other bucket's rows — so any reader can verify that no V1,
    research, or undeclared row entered the verdict's denominators.
    """
    if cfg.prereg != PREREG_PATH_V2 or cfg.prereg_sha256 != PREREG_SHA256_V2:
        raise ForwardValidationRefusal(
            "CONFIG_INVALID",
            {"field": "prereg_pin", "required": PREREG_ID_V2,
             "found": cfg.prereg, "found_sha256": cfg.prereg_sha256})
    parts = partition_nba_rows(entry_rows)
    counted = parts["v2_counted_rows"]
    kept, exclusions = screen_nba_rows(cfg, counted)
    record = core.evaluate_family(cfg, kept, close_rows, outcomes,
                                  slates_completed=slates_completed)
    record["label"] = (
        "FORWARD VALIDATION — verdict record under PREREG_NBA_PROPS_"
        "FORWARD_V2 (source amendment; FINAL-CANDIDATE — NOT FROZEN; "
        "CLV primary per §6, verdicts per §9; no verdict creates a "
        "PLAY; sample is V2 counted rows only, per §10 separation)")
    record["prereg_id"] = PREREG_ID_V2
    # Provenance of the verdict: exactly the V2 counted rows admitted
    # to scoring (a counted row labeled HISTORICAL is excluded from
    # verdict math by the framework and named in excluded, so it is
    # not listed here — this list is the verdict's row set).
    record["counted_row_ids"] = sorted(
        r.get("row_id") or "<no row_id>" for r in kept
        if (r.get("label") or "PROSPECTIVE") != "HISTORICAL")
    record["separation"] = _separation_block(parts)
    record["excluded"] = {**exclusions, **record["excluded"]}
    return record
