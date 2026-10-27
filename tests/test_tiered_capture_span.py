from datetime import datetime, timezone, timedelta
import pytest
from sportsedge.tiered_capture_span import build_tiered_capture_span_manifest
from sportsedge.dk_capture_span_manifest import CaptureSpanManifestError

@pytest.mark.parametrize('span,tier',[(150,'FULL'),(150.001,'RESEARCH'),(300,'RESEARCH'),(300.001,'REFUSED')])
def test_boundaries_never_count_research(span,tier):
    start=datetime(2026,10,25,tzinfo=timezone.utc)
    row=dict(event_id='E',capture_started_at=start.isoformat(),capture_finished_at=(start+timedelta(seconds=span)).isoformat(),capture_method='FALLBACK')
    m=build_tiered_capture_span_manifest([row]);g=m['games'][0]
    assert g['span_tier']==tier and g['span_seconds']==span
    assert g['capture_method']=='FALLBACK' and g['ladder_eligible'] is False
    assert ('E' in m['accepted_event_ids']) == (tier=='FULL')
    assert ('E' in m['research_event_ids']) == (tier=='RESEARCH')
    assert bool(m['refused']) == (tier=='REFUSED')

def test_no_invented_capture_method():
    row=dict(event_id='E',capture_started_at='2026-10-25T00:00:00Z',capture_finished_at='2026-10-25T00:01:00Z')
    assert build_tiered_capture_span_manifest([row])['games'][0]['capture_method'] is None
    row['capture_method']='CLAIMED'
    with pytest.raises(CaptureSpanManifestError):build_tiered_capture_span_manifest([row])

@pytest.mark.parametrize("method", [[], {}, True, 1])
def test_malformed_method_refuses_with_policy_error(method):
    row=dict(event_id="E",capture_started_at="2026-10-25T00:00:00Z",capture_finished_at="2026-10-25T00:01:00Z",capture_method=method)
    with pytest.raises(CaptureSpanManifestError, match="CAPTURE_METHOD_INVALID"):
        build_tiered_capture_span_manifest([row])

def test_failed_capture_remains_failed_and_excluded():
    row=dict(event_id="E",capture_started_at="2026-10-25T00:00:00Z",capture_finished_at=None,failure_reason="UNREACHABLE")
    m=build_tiered_capture_span_manifest([row])
    assert m["games"][0]["status"]=="FAILED"
    assert not m["accepted_event_ids"] and not m["research_event_ids"]
    assert m["games"][0]["ladder_eligible"] is False
