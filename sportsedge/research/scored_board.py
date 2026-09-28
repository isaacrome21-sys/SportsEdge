"""All-lines research presentation, independent of production bet eligibility.

Score is an upstream qualification-only field, never a price-value heuristic,
win probability, or calibrated confidence. EV and price edge stay visible as
separate economics fields and never feed Score. Inputs must include an upstream
estimate for the exact quoted contract. This module does not infer probabilities
from odds or invent engines for missing markets.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from math import isfinite

from sportsedge.research.market_value import compare_price
from sportsedge.source_lineage import canonical_json_sha256

VERSION = "RUN_IT_SCORE_V2"
AUTHORITY_LABEL = "EXPERIMENTAL / NOT OFFICIAL"
CONTRACT_FIELDS = ("sport", "event_id", "market", "selection", "entity_id",
                   "line", "period", "rules_id", "payout_type")
SCORE_DESCRIPTION = (
    "Score /100 is supplied upstream from qualification checks only; EV, raw "
    "price edge and win probability do not feed Score. It is not calibrated confidence."
)


def _time(value):
    try:
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp
    except (TypeError, ValueError):
        raise ValueError("AWARE_TIMESTAMP_REQUIRED") from None


def _contract(raw):
    if not isinstance(raw, Mapping) or any(key not in raw for key in CONTRACT_FIELDS):
        raise ValueError("COMPLETE_MARKET_IDENTITY_REQUIRED")
    for key in CONTRACT_FIELDS:
        if key not in {"line", "entity_id"} and (
            not isinstance(raw[key], str) or not raw[key].strip()
        ):
            raise ValueError("COMPLETE_MARKET_IDENTITY_REQUIRED")
    if raw['entity_id'] is not None and (
        not isinstance(raw['entity_id'], str) or not raw['entity_id'].strip()
    ):
        raise ValueError("INVALID_ENTITY_ID")
    line = raw['line']
    if line is not None and (type(line) not in (int, float) or not isfinite(line)):
        raise ValueError("INVALID_LINE")
    return {key: raw[key] for key in CONTRACT_FIELDS}


def _qualification_score(raw):
    """Read, never derive, the qualification-only 0-100 Score.

    The card has no fallback formula. In particular EV, raw edge, odds and model
    probability are intentionally unavailable to this function.
    """
    value = raw.get('qualification_score') if isinstance(raw, Mapping) else None
    if value is None:
        return None
    if isinstance(value, bool) or type(value) not in (int, float) or not isfinite(value):
        raise ValueError("INVALID_QUALIFICATION_SCORE")
    if not 0 <= value <= 100:
        raise ValueError("INVALID_QUALIFICATION_SCORE")
    return round(float(value), 1)


def build_scored_board(rows, *, now, quote_ttl_seconds=300, estimate_ttl_seconds=900):
    """Keep every submitted row; value only current, identity-matched estimates.

    Each row contains a quote and optionally an estimate. Caller-supplied artifact
    hashes are attestations, not proof that the underlying model is calibrated.
    TTLs are explicit operational freshness settings, not replacements for
    upstream sport-specific policies. Score, when present, is caller-supplied
    qualification output and is not recomputed from economics here.
    """
    now = _time(now)
    if not isinstance(rows, list):
        raise ValueError("ROWS_LIST_REQUIRED")
    for ttl in (quote_ttl_seconds, estimate_ttl_seconds):
        if type(ttl) not in (int, float) or not isfinite(ttl) or ttl <= 0:
            raise ValueError("POSITIVE_FINITE_TTL_REQUIRED")
    output = []
    for index, raw in enumerate(rows):
        row = {"input_index": index, "rank": None, "score": None,
               "model_win_probability": None, "push_probability": None,
               "expected_profit_per_unit": None, "score_components": None,
               "estimate_source": None, "contract": None, "quote_id": None,
               "fair_american": None, "break_even_probability": None,
               "raw_price_edge": None, "no_vig_edge": None,
               "conditional_win_probability": None, "quote_at": None, "start": None,
               "book": None, "american_odds": None, "status": "NEEDS_DATA"}
        try:
            if not isinstance(raw, Mapping):
                raise ValueError("ROW_OBJECT_REQUIRED")
            score = _qualification_score(raw)
            quote = raw.get('quote')
            if not isinstance(quote, Mapping):
                raise ValueError("QUOTE_REQUIRED")
            row.update(quote_id=quote.get('quote_id'), book=quote.get('book'),
                       american_odds=quote.get('american_odds'),
                       quote_at=quote.get('quote_at'), start=quote.get('start'))
            contract = _contract(quote.get('contract'))
            row['contract'] = contract
            if contract['payout_type'] != 'WIN_LOSS_PUSH':
                raise ValueError("UNSUPPORTED_PAYOUT_TYPE")
            start = _time(quote.get('start'))
            if now >= start:
                raise ValueError("GAME_STARTED")
            estimate = raw.get('estimate')
            if estimate is None:
                raise ValueError("MODEL_ESTIMATE_NEEDED")
            if not isinstance(estimate, Mapping):
                raise ValueError("ESTIMATE_OBJECT_REQUIRED")
            if _contract(estimate.get('contract')) != contract:
                raise ValueError("MARKET_IDENTITY_MISMATCH")
            for key in ('model_id', 'model_version', 'artifact_sha256'):
                if not isinstance(estimate.get(key), str) or not estimate[key].strip():
                    raise ValueError("MODEL_SOURCE_REQUIRED")
            artifact = estimate['artifact_sha256']
            if len(artifact) != 64 or any(c not in '0123456789abcdef' for c in artifact):
                raise ValueError("INVALID_ARTIFACT_HASH")
            generated = _time(estimate.get('generated_at'))
            features = _time(estimate.get('features_as_of'))
            valid_until = _time(estimate.get('valid_until'))
            if features > generated or generated > now or generated >= start:
                raise ValueError("INVALID_ESTIMATE_CHRONOLOGY")
            if now >= valid_until or (now - generated).total_seconds() > estimate_ttl_seconds:
                raise ValueError("STALE_ESTIMATE")
            if (now - features).total_seconds() > estimate_ttl_seconds:
                raise ValueError("STALE_FEATURE_SNAPSHOT")
            row['estimate_source'] = {key: estimate[key] for key in
                                      ('model_id', 'model_version', 'artifact_sha256')}
            value = compare_price(win=estimate['win'], push=estimate['push'],
                american_odds=quote.get('american_odds'),
                quote_at=_time(quote['quote_at']) if quote.get('quote_at') is not None else None,
                now=now, start=start, ttl_seconds=quote_ttl_seconds)
            row.update(model_win_probability=value['win_probability'],
                       push_probability=value['push_probability'],
                       fair_american=value['fair_american'],
                       conditional_win_probability=value['conditional_win_probability'],
                       break_even_probability=value['break_even_probability'],
                       raw_price_edge=value['raw_price_edge'],
                       no_vig_edge=value['no_vig_edge'])
            if value['expected_profit_per_unit'] is None:
                raise ValueError(value['status'])
            components = None if score is None else {"source": "UPSTREAM_QUALIFICATION_ONLY"}
            row.update(score=score, score_components=components, status="VALUED",
                       expected_profit_per_unit=value['expected_profit_per_unit'],
                       note="Positive price value" if value['expected_profit_per_unit'] > 0
                            else "No positive price value")
        except (KeyError, TypeError, ValueError) as exc:
            row['note'] = str(exc).strip("'") or 'INVALID_ROW'
        output.append(row)
    output.sort(key=lambda r: (
        r['score'] is None,
        -(r['score'] or 0),
        -r['expected_profit_per_unit'] if r['expected_profit_per_unit'] is not None else float('inf'),
        r['input_index'],
    ))
    ranked = [r for r in output if r['score'] is not None]
    for rank, row in enumerate(ranked, 1):
        row['rank'] = rank
    valued = [r for r in output if r['expected_profit_per_unit'] is not None]
    return {"schema": VERSION, "as_of": now.isoformat(),
            "authority_label": AUTHORITY_LABEL, "official": False,
            "score_description": SCORE_DESCRIPTION,
            "score_formula": "UPSTREAM_QUALIFICATION_ONLY; EV_AND_EDGE_EXCLUDED",
            "price_description": ("Fair odds use P(win|no push). Raw edge is "
                "P(win|no push) minus book break-even probability, in probability units; "
                "displayed as percentage points. EV is expected net profit per unit "
                "including pushes. No-vig edge is unavailable without a paired market."),
            "submitted_rows": len(rows), "valued_rows": len(valued),
            "scored_rows": len(ranked), "rows": output,
            "audit": {"input_sha256": canonical_json_sha256(rows),
                      "quote_ttl_seconds": quote_ttl_seconds,
                      "estimate_ttl_seconds": estimate_ttl_seconds,
                      "source_verification": "CALLER_ATTESTED",
                      "score_calibrated": False, "score_uses_ev": False,
                      "score_uses_edge": False, "official_eligible": False,
                      "promotion_authority": False, "stake": 0.0}}


def render_scored_board(board, *, limit=5, min_score=60, show_all=False):
    """Render current positive-value research edges without pick/crown framing."""
    if type(limit) is not int or limit < 1:
        raise ValueError('POSITIVE_LIMIT_REQUIRED')
    if type(min_score) not in (int, float) or not isfinite(min_score) or not 0 <= min_score <= 100:
        raise ValueError('INVALID_MIN_SCORE')
    def cell(value):
        return str(value if value is not None else '—').replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')
    eligible = [r for r in board['rows']
                if r['expected_profit_per_unit'] is not None
                and r['expected_profit_per_unit'] > 0
                and r['raw_price_edge'] is not None
                and r['raw_price_edge'] > 0
                and (r['score'] is None or r['score'] >= min_score)]
    # Alternatives at different books are the same selection, not extra rows.
    unique, seen = [], set()
    for row in eligible:
        key = canonical_json_sha256(row['contract'])
        if key not in seen:
            unique.append(row)
            seen.add(key)
    visible = board['rows'] if show_all else unique[:limit]
    title = 'All lines' if show_all else 'Research edges'
    lines = [f"RUN IT — {AUTHORITY_LABEL} — {title} ({len(visible)})",
             f"As of {board['as_of']}. {board['score_description']}",
             board['price_description'], "",
             "| Game / entity | Market / period | Selection / line | Book / odds | Score /100 | Model % | Fair odds | Raw edge (pp) | EV /unit | Quote time | Start | Note |",
             "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |"]
    if not visible:
        return '\n'.join(lines[:4]) + f'No current positive-EV research edges meet the {min_score:g}/100 qualification cutoff when a Score is supplied.\n'
    for row in visible:
        contract = row['contract'] or {}
        cells = [f"{contract.get('event_id', 'Unknown')} / {contract.get('entity_id') or 'Game'}",
                 f"{contract.get('market', 'Unknown')} / {contract.get('period', '—')}",
                 f"{contract.get('selection', '—')} / {contract.get('line') if contract.get('line') is not None else '—'}",
                 f"{row['book'] or '—'} / {row['american_odds'] if row['american_odds'] is not None else '—'}",
                 row['score'],
                 f"{100 * row['model_win_probability']:.1f}%" if row['model_win_probability'] is not None else None,
                 f"{row['fair_american']:+.1f}" if row['fair_american'] is not None else None,
                 f"{100 * row['raw_price_edge']:+.2f}" if row['raw_price_edge'] is not None else None,
                 f"{row['expected_profit_per_unit']:+.3f}" if row['expected_profit_per_unit'] is not None else None,
                 row['quote_at'], row['start'], row['note']]
        lines.append('| ' + ' | '.join(cell(c) for c in cells) + ' |')
    return '\n'.join(lines) + '\n'
