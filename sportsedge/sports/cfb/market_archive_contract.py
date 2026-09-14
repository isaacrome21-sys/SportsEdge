"""Single deny-by-default authority for the retrospective CFB market archive.

The enum is the complete use vocabulary and owns each use's one disposition.
JSON lists are compatibility projections, never independent permission sources.
"""
from enum import Enum
from hashlib import sha256
import json
from pathlib import Path


class ArchiveUse(str, Enum):
    def __new__(cls, value, disposition):
        obj = str.__new__(cls, value)
        obj._value_ = value
        obj.disposition = disposition
        return obj

    COVERAGE = ("historical_market_coverage_profiling", "ALLOW")
    CONTEXT = ("research_backtesting_context", "ALLOW")
    AVAILABILITY = ("book_and_market_availability_research", "ALLOW")
    KEY_NUMBER_CONTEXT = ("signed_key_number_reference_context", "ALLOW")
    REALISM = ("simulated_distribution_realism_benchmark", "ALLOW")
    FEATURES = ("predictive_model_features", "DENY")
    TRAINING = ("model_training_inputs", "DENY")
    CALIBRATION = ("model_calibration_inputs", "DENY")
    MODEL_P = ("model_p_generation", "DENY")
    PAIRED_BENCHMARK = ("paired_no_vig_market_benchmark", "DENY")
    CLV = ("decision_close_clv_evidence", "DENY")
    TRUTH_GATE = ("truth_gate_evidence", "DENY")
    PROMOTION = ("promotion_evidence", "DENY")
    STAKING = ("staking_authority", "DENY")
    OFFICIAL = ("official_bet_authority", "DENY")


class ArchiveContractError(ValueError):
    pass


def digest(payload):
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def restriction_block():
    return {
        "version": "CFB_MARKET_RESTRICTIONS_V2",
        "uses": {use.value: use.disposition for use in ArchiveUse},
        "authority": {key: False for key in (
            "feature_authority", "model_p_authority", "truth_gate_authority",
            "promotion_authority", "staking_authority", "official_bet_authority")},
        "evidence_limitations": {
            "retrospective_archive": True, "per_row_pit_certified": False,
            "decision_time_certified": False, "close_time_certified": False,
            "clv_authority": False, "paired_two_sided_quote_certified": False,
            "git_commit_time_is_not_row_capture_time": True,
            "opening_or_closing_semantics_must_not_be_inferred_beyond_documented_fields": True,
        },
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveContractError("CFB_MARKET_DUPLICATE_KEY:" + key)
        result[key] = value
    return result


def load_contract(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    if (payload.get("schema_version") != 1 or payload.get("source_id") != "CFB_HISTORICAL_MARKET_SOURCE_V1"
            or payload.get("sport") != "cfb" or payload.get("mode") != "RESEARCH_ONLY"
            or payload.get("status") != "FROZEN_RESEARCH_SOURCE"):
        raise ArchiveContractError("CFB_MARKET_CONTRACT_IDENTITY_INVALID")
    validate_restrictions(payload)
    return payload


def validate_restrictions(payload):
    expected = restriction_block()
    # Canonical serialization distinguishes false from 0 and true from 1.
    if digest(payload.get("restrictions")) != digest(expected):
        raise ArchiveContractError("CFB_MARKET_RESTRICTIONS_INVALID")
    for field in ("authority", "evidence_limitations"):
        if digest(payload.get(field)) != digest(expected[field]):
            raise ArchiveContractError("CFB_MARKET_FORBIDDEN_AUTHORITY_OR_LIMIT:" + field)
    for field, disposition in (("allowed_uses", "ALLOW"), ("forbidden_uses", "DENY")):
        actual = payload.get(field)
        wanted = [u.value for u in ArchiveUse if u.disposition == disposition]
        if not isinstance(actual, list) or any(type(x) is not str for x in actual) or sorted(actual) != sorted(wanted):
            raise ArchiveContractError("CFB_MARKET_USE_PROJECTION_INVALID:" + field)
    if payload.get("restriction_sha256") != digest(expected):
        raise ArchiveContractError("CFB_MARKET_RESTRICTION_HASH_MISMATCH")


def require_use(payload, use):
    validate_restrictions(payload)
    try:
        selected = ArchiveUse(use)
    except (ValueError, TypeError):
        raise ArchiveContractError("CFB_MARKET_UNKNOWN_USE:" + str(use)) from None
    if selected.disposition != "ALLOW":
        raise ArchiveContractError("CFB_MARKET_FORBIDDEN_USE:" + selected.value)
    return selected


def restriction_fields(payload):
    validate_restrictions(payload)
    return {key: payload[key] for key in (
        "restrictions", "restriction_sha256", "allowed_uses", "forbidden_uses",
        "authority", "evidence_limitations")}
