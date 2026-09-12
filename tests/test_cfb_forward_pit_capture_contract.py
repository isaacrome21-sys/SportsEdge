from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/cfb-forward-pit-source-capture.yml'


def test_forward_pit_capture_is_prospective_and_non_promotional() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    assert "schedule:" in text
    assert "FORWARD_SOURCE_SNAPSHOT_FROM_RETRIEVAL_TIME_ONLY" in text
    assert "point_in_time_from_capture_forward': True" in text
    assert "retroactive_point_in_time_claim': False" in text
    assert "promotion_evidence': False" in text
    assert "model_p_created': False" in text
    assert "eligibility_changed': False" in text


def test_forward_pit_predictive_capture_excludes_betting_dataset() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    capture_block = text.split('Snapshot predictive source bytes', 1)[1].split('Bind capture time', 1)[0]
    assert 'dataset in schedules adv_team adv_situational adv_drives' in capture_block
    assert '--dataset betting' not in capture_block
    assert "dataset == 'betting'" in text
    assert "CFB_FORWARD_PIT_MARKET_CONTAMINATION" in text


def test_forward_pit_persists_immutable_capture_identity() -> None:
    text = WORKFLOW.read_text(encoding='utf-8')
    assert "history/cfb/forward-pit/${capture_id}" in text
    assert "CFB_FORWARD_PIT_CAPTURE_ID_COLLISION" in text
    assert "captured_at_utc" in text
    assert "content_sha256" in text
