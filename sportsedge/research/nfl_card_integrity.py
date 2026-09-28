"""NFL-specific fail-closed publishing contract for research cards."""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from sportsedge.research.scored_board import AUTHORITY_LABEL, build_scored_board
from sportsedge.source_lineage import canonical_json_sha256

SPLITS_SOURCE = "ScoresAndOdds"
VERSION = "NFL_RESEARCH_CARD_V2"


class NFLCardIntegrityError(ValueError):
    """Raised when current NFL card provenance cannot support publication."""


def _time(value, code):
    try:
        stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError
        return stamp
    except (TypeError, ValueError):
        raise NFLCardIntegrityError(code) from None


def _forecast_provenance(forecast, current_input_snapshot):
    if not isinstance(forecast, Mapping):
        raise NFLCardIntegrityError("NFL_CARD_FORECAST_PROVENANCE_REQUIRED")
    if not isinstance(current_input_snapshot, Mapping):
        raise NFLCardIntegrityError("NFL_CARD_CURRENT_INPUT_SNAPSHOT_REQUIRED")
    current_sha = canonical_json_sha256(current_input_snapshot)
    forecast_sha = str(forecast.get('input_sha256') or '').strip().lower()
    if not forecast_sha or forecast_sha != current_sha:
        raise NFLCardIntegrityError("NFL_CARD_RECOMPUTE_OR_BLOCK:INPUT_FINGERPRINT_MISMATCH")
    generated = _time(forecast.get('generated_at'), "NFL_CARD_FORECAST_GENERATED_AT_REQUIRED")
    snapshot_at = _time(current_input_snapshot.get('as_of'), "NFL_CARD_CURRENT_INPUT_AS_OF_REQUIRED")
    if generated < snapshot_at:
        raise NFLCardIntegrityError("NFL_CARD_RECOMPUTE_OR_BLOCK:FORECAST_PREDATES_INPUTS")
    out = dict(forecast)
    out['input_sha256'] = current_sha
    out['generated_at'] = generated.isoformat()
    out['validated_against_current_inputs'] = True
    return out


def _splits(context):
    if context is None:
        return None
    if not isinstance(context, Mapping):
        raise NFLCardIntegrityError("NFL_CARD_SPLITS_CONTEXT_INVALID")
    source = str(context.get('source') or '').strip()
    if source and source.casefold() != SPLITS_SOURCE.casefold():
        raise NFLCardIntegrityError("NFL_CARD_SPLITS_SOURCE_MISMATCH")
    out = dict(context)
    out.update(source=SPLITS_SOURCE, promotion_authority=False,
               used_in_model_probability=False, used_in_score=False)
    return out


def _bind_team(scored_row, raw_row, roster_team_by_entity_id):
    contract = scored_row.get('contract') or {}
    entity_id = str(contract.get('entity_id') or '').strip()
    raw_team = str(raw_row.get('team') or '').strip().upper() if isinstance(raw_row, Mapping) else ''
    if not entity_id:
        return raw_team or None, bool(raw_team)
    if not isinstance(roster_team_by_entity_id, Mapping):
        return None, False
    bound = str(roster_team_by_entity_id.get(entity_id) or '').strip().upper()
    if not bound:
        return None, False
    if raw_team and raw_team != bound:
        raise NFLCardIntegrityError(
            f"NFL_CARD_PLAYER_TEAM_BINDING_MISMATCH:{entity_id}:{raw_team}:{bound}"
        )
    return bound, True


def build_nfl_research_card(
    rows,
    *,
    now,
    forecast_provenance,
    current_input_snapshot,
    roster_team_by_entity_id=None,
    splits_context=None,
    quote_ttl_seconds=300,
    estimate_ttl_seconds=900,
    min_score=60,
    limit=20,
):
    """Build a current NFL research card from exact-contract board rows.

    The whole card blocks when forecast provenance does not match the current
    injury/role/input snapshot. Individual offers still use the shared board's
    quote/estimate freshness and exact-contract checks. Only strictly positive
    EV and strictly positive raw price edge can enter `research_edges`.
    """
    if not isinstance(rows, list):
        raise NFLCardIntegrityError("NFL_CARD_ROWS_LIST_REQUIRED")
    if type(limit) is not int or limit < 1:
        raise NFLCardIntegrityError("NFL_CARD_POSITIVE_LIMIT_REQUIRED")
    if type(min_score) not in (int, float) or isinstance(min_score, bool) or not 0 <= min_score <= 100:
        raise NFLCardIntegrityError("NFL_CARD_INVALID_MIN_SCORE")

    forecast = _forecast_provenance(forecast_provenance, current_input_snapshot)
    board = build_scored_board(rows, now=now, quote_ttl_seconds=quote_ttl_seconds,
                               estimate_ttl_seconds=estimate_ttl_seconds)

    research_edges = []
    excluded = []
    seen = set()
    for scored in board['rows']:
        contract = scored.get('contract') or {}
        if contract and str(contract.get('sport') or '').upper() != 'NFL':
            raise NFLCardIntegrityError("NFL_CARD_NON_NFL_CONTRACT")
        raw = rows[scored['input_index']] if 0 <= scored['input_index'] < len(rows) else {}
        display_team, team_verified = _bind_team(scored, raw, roster_team_by_entity_id)
        ev = scored.get('expected_profit_per_unit')
        edge = scored.get('raw_price_edge')
        score = scored.get('score')
        reasons = []
        if ev is None or ev <= 0:
            reasons.append('NON_POSITIVE_EV')
        if edge is None or edge <= 0:
            reasons.append('NO_BREAK_EVEN_EDGE')
        if score is not None and score < min_score:
            reasons.append('QUALIFICATION_SCORE_BELOW_CUTOFF')
        if reasons:
            excluded.append({
                'input_index': scored['input_index'],
                'contract': contract,
                'book': scored.get('book'),
                'american_odds': scored.get('american_odds'),
                'model_win_probability': scored.get('model_win_probability'),
                'break_even_probability': scored.get('break_even_probability'),
                'raw_price_edge': edge,
                'expected_profit_per_unit': ev,
                'quote_at': scored.get('quote_at'),
                'reasons': sorted(set(reasons)),
            })
            continue
        identity = canonical_json_sha256(contract)
        if identity in seen:
            continue
        seen.add(identity)
        row = dict(scored)
        row.update(display_team=display_team, team_binding_verified=team_verified,
                   authority_label=AUTHORITY_LABEL, official=False,
                   crown_allowed=False, display_label='RESEARCH EDGE')
        for key in ('crown', 'pick', 'top_pick', 'best_bet'):
            row.pop(key, None)
        research_edges.append(row)
        if len(research_edges) >= limit:
            break

    return {
        'schema': VERSION,
        'sport': 'NFL',
        'authority_label': AUTHORITY_LABEL,
        'official': False,
        'as_of': board['as_of'],
        'forecast': forecast,
        'research_edges': research_edges,
        'excluded': excluded,
        'splits': _splits(splits_context),
        'governance': {
            'crown_allowed': False,
            'pick_language_allowed': False,
            'score_policy': 'UPSTREAM_QUALIFICATION_ONLY',
            'score_uses_ev': False,
            'score_uses_edge': False,
            'forecast_must_match_current_inputs': True,
            'strict_positive_ev_required': True,
            'strict_positive_price_edge_required': True,
            'player_logo_requires_verified_team_binding': True,
            'splits_source': SPLITS_SOURCE,
        },
        'board_audit': board['audit'],
    }
