"""Owner Oct24 span tiers; separate from quote age and market validation.

Research IDs are deliberately absent from the legacy accepted_event_ids list.
No tier grants ladder eligibility or supplies capture-method evidence.
"""
from .dk_capture_span_manifest import build_capture_span_manifest, CaptureSpanManifestError

METHODS = frozenset({'PRIMARY_BROWSER', 'FALLBACK'})

def build_tiered_capture_span_manifest(records):
    clean, methods = [], {}
    if not isinstance(records, list):
        raise CaptureSpanManifestError('NONEMPTY_SPAN_RECORDS_REQUIRED')
    for record in records:
        if not isinstance(record, dict):
            raise CaptureSpanManifestError('UNEXPECTED_SPAN_RECORD_FIELDS')
        row = dict(record)
        method = row.pop('capture_method', None)
        if method is not None and method not in METHODS:
            raise CaptureSpanManifestError('CAPTURE_METHOD_INVALID')
        methods[str(row.get('event_id')).strip()] = method
        clean.append(row)
    result = build_capture_span_manifest(clean)
    for game in result['games']:
        span = game['span_seconds']
        tier = 'UNAVAILABLE' if span is None else 'FULL' if span <= 150 else 'RESEARCH' if span <= 300 else 'REFUSED'
        game.update(span_tier=tier, capture_method=methods[game['event_id']], ladder_eligible=False)
        if tier == 'RESEARCH':
            game['status'] = 'RESEARCH_ONLY'
    result['research_event_ids'] = [g['event_id'] for g in result['games'] if g['span_tier']=='RESEARCH']
    result['refused'] = [g for g in result['games'] if g['span_tier'] in {'REFUSED','UNAVAILABLE'}]
    result['counts'] = dict(games=len(result['games']), full=len(result['accepted_event_ids']),
                            research=len(result['research_event_ids']), refused=len(result['refused']))
    result['status'] = 'GAMES_REFUSED' if result['refused'] else 'RESEARCH_PRESENT' if result['research_event_ids'] else 'ALL_GAMES_WITHIN_LIMIT'
    result.update(version='DK_CAPTURE_SPAN_TIERS_V2', research_span_limit_seconds=300,
                  quote_max_age_seconds=1800, policy_only=True)
    return result
