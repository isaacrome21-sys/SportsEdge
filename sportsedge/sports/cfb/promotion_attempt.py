"""CFB historical market certification under CFB_TRUTH_GATE_V1.

Historical certification never selects or executes a live bet. The only accepted input
is a completed, attestation-backed certification replay. Live OFFICIAL_BET decisions are
made later by the governed live-decision engine using fresh executable quotes.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .certification_replay import CFBCertificationReplay


@dataclass(frozen=True)
class CFBPromotionAttempt:
    market: str
    as_of_date: str
    stage: str
    official_plays: tuple[dict, ...]
    zero_is_valid: bool
    failures: tuple[str, ...]
    attestation_bundle_sha: str


def run_cfb_promotion_attempt(
    *,
    replay: CFBCertificationReplay,
    as_of_date: str,
) -> CFBPromotionAttempt:
    if not isinstance(replay, CFBCertificationReplay):
        raise ValueError("CFB_PROMOTION_REPLAY_REQUIRED")
    parsed = date.fromisoformat(str(as_of_date))
    market_name = str(replay.market).upper()
    if replay.gate_result.market != market_name or replay.evidence.market != market_name:
        raise ValueError("CFB_PROMOTION_REPLAY_MARKET_MISMATCH")
    if replay.attestation_bundle_sha == "" or len(replay.attestation_bundle_sha) != 64:
        raise ValueError("CFB_PROMOTION_ATTESTATION_BUNDLE_REQUIRED")
    # Historical certification creates a persistent MARKET state, not a list of bets.
    # Live candidate selection remains downstream and quote-dependent.
    return CFBPromotionAttempt(
        market=market_name,
        as_of_date=parsed.isoformat(),
        stage=replay.gate_result.status,
        official_plays=(),
        zero_is_valid=True,
        failures=replay.gate_result.failures,
        attestation_bundle_sha=replay.attestation_bundle_sha,
    )
