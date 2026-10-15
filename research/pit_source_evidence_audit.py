"""Research-only audit of claimed pre-event availability evidence.

Caller-supplied source classes and timestamps are not authenticated.
No pricing, capture, or production availability admission is permitted.
"""
from datetime import datetime, timezone
from ipaddress import ip_address
from urllib.parse import urlsplit

PRIMARY = frozenset({'official_league', 'official_team'})
SECONDARY = frozenset({'verified_reporter', 'secondary_report', 'x_rumor'})
CLASSES = PRIMARY | SECONDARY
FACT_STATUSES = {
    'starter': frozenset({'STARTER', 'NOT_STARTER', 'UNKNOWN', 'PROJECTED'}),
    'lineup': frozenset({'ACTIVE', 'OUT', 'UNKNOWN', 'PROJECTED'}),
    'injury': frozenset({'ACTIVE', 'OUT', 'UNKNOWN', 'PROJECTED'}),
    'qb': frozenset({'ACTIVE', 'OUT', 'STARTER', 'NOT_STARTER', 'UNKNOWN', 'PROJECTED'}),
    'participation': frozenset({'ACTIVE', 'OUT', 'UNKNOWN', 'PROJECTED'}),
    'rotation': frozenset({'ACTIVE', 'OUT', 'UNKNOWN', 'PROJECTED'}),
    'game_status': frozenset({'POSTPONED', 'ON_SCHEDULE', 'UNKNOWN', 'PROJECTED'}),
}
FACTS = frozenset(FACT_STATUSES)
STATUSES = frozenset().union(*FACT_STATUSES.values())
SOCIAL_HOSTS = frozenset({'x.com', 'twitter.com', 't.co'})


def _time(value):
    if not isinstance(value, str):
        raise ValueError('INVALID_TIMESTAMP')
    try:
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('INVALID_TIMESTAMP') from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('NAIVE_TIMESTAMP')
    return instant.astimezone(timezone.utc)


def audit_evidence(records, *, event_id, subject_id, fact_type,
                   as_of, pre_event_cutoff, fresh_after):
    """Report claimed evidence, never authenticated operational availability."""
    now, cutoff, fresh = map(_time, (as_of, pre_event_cutoff, fresh_after))
    if not (fresh <= now < cutoff):
        raise ValueError('INVALID_EVIDENCE_WINDOW')
    if not all(isinstance(x, str) and x for x in (event_id, subject_id)) or fact_type not in FACTS:
        raise ValueError('INVALID_FACT_IDENTITY')
    if not isinstance(records, list):
        raise ValueError('INVALID_RECORDS')

    accepted, rejected, credible_conflicts = [], [], []
    seen = set()
    for idx, r in enumerate(records):
        if not isinstance(r, dict):
            raise ValueError('INVALID_RECORD')
        required = ('event_id', 'subject_id', 'fact_type', 'source_url',
                    'source_class', 'published_at', 'observed_at', 'status')
        if any(k not in r for k in required):
            raise ValueError('MISSING_EVIDENCE_FIELD')
        if (r['event_id'], r['subject_id'], r['fact_type']) != (event_id, subject_id, fact_type):
            raise ValueError('EVIDENCE_IDENTITY_MISMATCH')
        if r['source_class'] not in CLASSES or r['status'] not in STATUSES:
            raise ValueError('INVALID_EVIDENCE_ENUM')
        if r['status'] not in FACT_STATUSES[fact_type]:
            raise ValueError('INCOMPATIBLE_FACT_STATUS')

        url = r['source_url']
        if not isinstance(url, str):
            raise ValueError('INVALID_SOURCE_URL')
        try:
            parsed = urlsplit(url)
            host = (parsed.hostname or '').lower().rstrip('.')
            port = parsed.port
        except ValueError as exc:
            raise ValueError('INVALID_SOURCE_URL') from exc
        try:
            ip_address(host)
        except ValueError:
            is_ip = False
        else:
            is_ip = True
        if (parsed.scheme != 'https' or not host or parsed.username or parsed.password
                or port not in (None, 443) or is_ip
                or host in ('localhost', 'localhost.localdomain')
                or host.endswith(('.localhost', '.local', '.internal'))):
            raise ValueError('INVALID_SOURCE_URL')
        if any(host == d or host.endswith('.' + d) for d in SOCIAL_HOSTS) and r['source_class'] in PRIMARY:
            raise ValueError('SOCIAL_SOURCE_NOT_AUTHENTICATED')

        published, observed = _time(r['published_at']), _time(r['observed_at'])
        if published > observed:
            raise ValueError('EVIDENCE_OBSERVED_BEFORE_PUBLICATION')
        fingerprint = (url, published, r['status'])
        if fingerprint in seen:
            raise ValueError('DUPLICATE_EVIDENCE')
        seen.add(fingerprint)
        reason = None
        if observed > now or published >= cutoff or observed >= cutoff:
            reason = 'POST_CUTOFF_OR_FUTURE'
        elif published < fresh:
            reason = 'STALE'
        elif r['source_class'] not in PRIMARY:
            reason = 'NOT_AUTHENTICATED_PRIMARY'
            if r['source_class'] == 'verified_reporter' and r['status'] not in ('UNKNOWN', 'PROJECTED'):
                credible_conflicts.append(r['status'])
        elif r['status'] in ('UNKNOWN', 'PROJECTED'):
            reason = 'NO_CONFIRMED_STATUS'
        if reason:
            rejected.append({'index': idx, 'reason': reason, 'source_url': url})
        else:
            accepted.append({'index': idx, 'status': r['status'], 'source_url': url,
                             'published_at': published.isoformat(),
                             'observed_at': observed.isoformat()})

    statuses = {r['status'] for r in accepted}
    if len(statuses) > 1:
        reason, candidate = 'CONTRADICTORY_PRIMARY_CLAIMS', 'UNKNOWN'
    elif statuses and any(status not in statuses for status in credible_conflicts):
        reason, candidate = 'CONTRADICTORY_CREDIBLE_CLAIMS', 'UNKNOWN'
    elif not statuses:
        reason, candidate = 'NO_ELIGIBLE_PRIMARY_EVIDENCE', 'UNKNOWN'
    else:
        reason, candidate = 'CONSISTENT_PRIMARY_CLAIMS_UNAUTHENTICATED', next(iter(statuses))
    return {
        'event_id': event_id, 'subject_id': subject_id, 'fact_type': fact_type,
        'as_of': now.isoformat(), 'pre_event_cutoff': cutoff.isoformat(),
        'fresh_after': fresh.isoformat(), 'candidate_status': candidate,
        'operational_status': 'UNKNOWN/BLOCKED', 'reason': reason,
        'eligible_claims': accepted, 'excluded_claims': rejected,
        'source_authentication_verified': False,
        'runtime_admission_authorized': False, 'market_probability_verified': False,
        'play_authorized': False, 'research_only': True,
    }
