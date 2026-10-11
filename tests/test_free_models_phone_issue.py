"""Offline phone issue intake and rendering smoke; no sportsbook/API requests."""
import importlib.util
import json
from pathlib import Path

M = Path(__file__).resolve().parents[1] / "scripts" / "free_models_phone_issue.py"
spec = importlib.util.spec_from_file_location("free_models_phone_issue", M)
phone = importlib.util.module_from_spec(spec)
spec.loader.exec_module(phone)

def event(body, title="[FREE RUN IT] NFL"):
    return {"issue": {"title": title, "body": body,
                      "updated_at":"2026-10-11T15:00:00Z"}}

def ticket():
    return {"sport":"NFL", "lines":[
        {"away":"Detroit Lions","home":"Arizona Cardinals",
         "market":"TOTAL","side":"UNDER","line":54.5,"odds":-110,
         "kickoff":"2026-10-11T20:25:00Z"}]}

def test_parse_github_form_fenced_json():
    data=phone.parse_issue(event("### Lines (JSON)\n\n" + "```json\n" +
                               json.dumps(ticket()) + "\n```"))
    assert data == ticket()

def test_plain_json_and_list_are_allowed_with_sport_per_row():
    data=phone.parse_issue(event(json.dumps([
        {"sport":"MLB","game":"A @ B","market":"TOTAL","side":"OVER","line":8.5,"odds":-110}])))
    assert len(data["lines"])==1

def test_wrong_title_and_two_fences_fail_closed():
    text="```json\n"+json.dumps(ticket())+"\n```"
    try:
        phone.parse_issue(event(text,title="[NFL LINES] elsewhere"))
        assert False
    except phone.IntakeError:
        pass
    try:
        phone.parse_issue(event(text+"\n"+text))
        assert False
    except phone.IntakeError:
        pass

def test_missing_price_rejected():
    t=ticket()
    del t["lines"][0]["odds"]
    try:
        phone.parse_issue(event(json.dumps(t)))
        assert False
    except phone.IntakeError as exc:
        assert "ODDS_REQUIRED" in str(exc)

def test_card_render_shows_candidate_and_rejection_diagnostics():
    card={"schema":"SPORTSEDGE_FREE_RESEARCH_CARD_V1",
          "as_of_utc":"2026-10-11T14:00:00Z","min_ev":0.02,
          "summary":{"rows":2,"status_counts":{"RESEARCH_EDGE":1,"BLOCKED_CONTEXT_UNVERIFIED":1}},
          "edges":[{"game":"A @ B","selection":"B -3.5","odds_american":-110,
                    "estimate_p":0.55,"ev_per_dollar":0.05}],
          "diagnostics":[{"input_index":1,"status":"BLOCKED_CONTEXT_UNVERIFIED",
                          "reason":"UNIQUE_FUTURE_ESPN_FIXTURE_MISSING"}],
          "source_receipts":[{"status":"FETCHED_AT_RUNTIME"},{"status":"UNAVAILABLE"}]}
    text=phone.render_card(card,run_url="https://github.com/example/actions/runs/1")
    assert "B -3.5" in text and "5.0%" in text
    assert "BLOCKED_CONTEXT_UNVERIFIED" in text
    assert "1 ESPN/weather retrievals, 0 verified public MLB pitcher-log inputs, 1 unavailable" in text
    assert "not proven +EV" in text

def test_truncated_input_and_dangerous_json_rejected():
    try:
        phone.parse_issue(event("x" * 50001))
        assert False
    except phone.IntakeError:
        pass
    try:
        phone.parse_issue(event('{"lines":[{"sport":"NFL","market":"TOTAL","side":"OVER"}]}'))
        assert False
    except phone.IntakeError:
        pass
