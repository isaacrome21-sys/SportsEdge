"""Same-matchup disambiguation for the MLB rendered-page capture (t270, auditor MEDIUM on t269).

DK board cards carry no ISO start time, so two cards with the same away/home pair (e.g. World
Series G1 and G2) used to either block every run or risk binding G2 prices to G1. The board does
render a per-event start label (``cb-start-time-<event_id>``) in the browser's local zone. The
capture binds a same-matchup card to a scheduled game only when that label equals the game's
StatsAPI start under exactly one consistent card->game mapping across every candidate UTC offset.
Anything else refuses (BLOCKED_ONE_SIDED). Nothing is guessed. SCREEN / NOT_VALIDATED. No network.
"""
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "capture_mlb_rendered_paired_ml.py"
sys.path.insert(0, str(ROOT))
URL = "https://sportsbook.draftkings.com/leagues/baseball/mlb"
# G1 first pitch 2026-10-24T00:08Z (= Fri Oct 23rd 7:08 PM CT); observed 32 minutes before.
G1 = datetime(2026, 10, 24, 0, 8, tzinfo=timezone.utc)
G2 = G1 + timedelta(days=1)
NOW = G1 - timedelta(minutes=32)
ART = "a" * 64
CT_G1, CT_G2 = "Fri Oct 23rd 7:08 PM", "Sat Oct 24th 7:08 PM"


def _cap():
    spec = importlib.util.spec_from_file_location("capture_mlb_rendered_paired_ml_t270", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _team(name):
    return ('<a data-testid="lp-nav-link" href="/event/x/1"><div>'
            f'<span class="cb-market__label-inner">{name}</span></div></a>')


def _card(eid, ap, hp, start_text=None, start_eid=None, away="TB Rays", home="MIL Brewers"):
    st = (f'<span data-testid="cb-start-time-{start_eid or eid}">{start_text}</span>'
          if start_text is not None else "")
    return (f'<div data-testid="market-mapping-template-210">{st}{_team(away)}{_team(home)}'
            f'<button data-testid="component-builder-market-button-{eid}-0ML1_3">'
            f'<span data-testid="button-odds-market-board">{ap}</span></button>'
            f'<button data-testid="component-builder-market-button-{eid}-0ML1_1">'
            f'<span data-testid="button-odds-market-board">{hp}</span></button></div>')


def _fetch(cards, observed=NOW):
    from sportsedge.dk_rendered_page_fetcher import parse_rendered_board
    html = "<html><body>" + "".join(cards) + "</body></html>"
    return lambda url, sk: parse_rendered_board(html, page_url=url, observed_at=observed, sport_key=sk,
                                                final_url=url, browser={"headless": False})


def _pred(root, game_pk, start):
    p = Path(root) / start.date().isoformat() / f"game_{game_pk}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"market": "MONEYLINE", "game_pk": game_pk, "away_team": "Tampa Bay Rays",
                             "away_team_id": 139, "home_team": "Milwaukee Brewers", "home_team_id": 158,
                             "event_start_ts": start.isoformat(), "model_artifact_sha256": ART,
                             "promotion_authority": False}))


def _run(tmp, cards, observed=NOW):
    cap = _cap()
    return cap.capture(output_dir=str(tmp / "q"), prediction_root=str(tmp / "p"),
                       fetch=_fetch(cards, observed), artifact_binder=lambda: ART, page_url=URL)


def _blocked(tmp, cards):
    with pytest.raises(Exception) as e:
        _run(tmp, cards)
    assert getattr(e.value, "reason", "") == "BLOCKED_ONE_SIDED", e.value
    assert not (tmp / "q").exists() or not any((tmp / "q").rglob("*.json"))
    return e.value


def _ws(tmp):
    _pred(tmp / "p", 9001, G1)
    _pred(tmp / "p", 9002, G2)


# ---- fetcher exposes the raw label; it is not turned into a commence_time ----

def test_fetcher_exposes_raw_start_label_without_inventing_commence_time():
    b = _fetch([_card(111, "+159", "-193", CT_G1)])(URL, "baseball_mlb")
    rows = [r for r in b["rows"] if r["market"] == "h2h"]
    assert len(rows) == 2
    for r in rows:
        assert r["board_start_time_text"] == CT_G1
        assert r["commence_time"] is None and r["commence_time_status"] == "NOT_ON_BOARD_CARD"


def test_fetcher_ignores_start_label_of_a_different_event_id():
    b = _fetch([_card(111, "+159", "-193", CT_G1, start_eid=222)])(URL, "baseball_mlb")
    assert all(r["board_start_time_text"] is None for r in b["rows"])


def test_nfl_fixture_label_is_read():
    from sportsedge.dk_rendered_page_fetcher import parse_rendered_board
    html = (ROOT / "tests/fixtures/dk_rendered/nfl_board_excerpt_20261023.html").read_text()
    b = parse_rendered_board(html, page_url="https://sportsbook.draftkings.com/leagues/football/nfl",
                             observed_at=NOW, sport_key="americanfootball_nfl")
    labels = {r["board_start_time_text"] for r in b["rows"] if r["provider_event_id"] == "34118009"}
    assert labels == {"Sun Oct 25th 8:30 AM"}


# ---- two same-team cards ----

@pytest.mark.parametrize("order", ["g1_first", "g2_first"])
def test_two_same_team_cards_bind_by_start_label(tmp_path, order):
    _ws(tmp_path)
    c1, c2 = _card(111, "+159", "-193", CT_G1), _card(222, "+120", "-140", CT_G2)
    r = _run(tmp_path, [c1, c2] if order == "g1_first" else [c2, c1])
    assert r["status"] == "RETAINED" and r["observations_retained"] == 1, r
    row = json.loads(Path(r["paths"][0]).read_text())
    assert row["game_pk"] == 9001 and row["provider_event_id"] == "111"
    assert row["moneyline"] == {"status": "OK", "home_price_american": -193, "away_price_american": 159}
    assert row["board_start_time_text"] == CT_G1
    assert row["event_match_basis"] == "BOARD_START_LABEL_UNIQUE_ACROSS_OFFSETS"


def test_two_same_team_cards_utc_rendered_labels_also_bind(tmp_path):
    _ws(tmp_path)
    r = _run(tmp_path, [_card(222, "+120", "-140", "Sun Oct 25th 12:08 AM"),
                        _card(111, "+159", "-193", "Sat Oct 24th 12:08 AM")])
    row = json.loads(Path(r["paths"][0]).read_text())
    assert row["game_pk"] == 9001 and row["moneyline"]["away_price_american"] == 159


def test_today_tomorrow_labels_bind(tmp_path):
    _ws(tmp_path)
    r = _run(tmp_path, [_card(111, "+159", "-193", "Today 7:08 PM"), _card(222, "+120", "-140", "Tomorrow 7:08 PM")])
    row = json.loads(Path(r["paths"][0]).read_text())
    assert row["game_pk"] == 9001 and row["provider_event_id"] == "111"


def test_two_same_team_cards_without_labels_refuse(tmp_path):
    _ws(tmp_path)
    _blocked(tmp_path, [_card(111, "+159", "-193"), _card(222, "+120", "-140")])


def test_two_same_team_cards_with_identical_labels_refuse(tmp_path):
    _ws(tmp_path)
    _blocked(tmp_path, [_card(111, "+159", "-193", CT_G1), _card(222, "+120", "-140", CT_G1)])


def test_unparseable_label_refuses(tmp_path):
    _ws(tmp_path)
    _blocked(tmp_path, [_card(111, "+159", "-193", "Game 1"), _card(222, "+120", "-140", CT_G2)])


def test_label_matching_no_game_refuses(tmp_path):
    _ws(tmp_path)
    _blocked(tmp_path, [_card(111, "+159", "-193", "Fri Oct 23rd 7:10 PM"), _card(222, "+120", "-140", CT_G2)])


def test_wrong_weekday_refuses(tmp_path):
    _ws(tmp_path)
    _blocked(tmp_path, [_card(111, "+159", "-193", "Thu Oct 23rd 7:08 PM"), _card(222, "+120", "-140", CT_G2)])


def test_only_g2_card_present_never_records_g2_price_against_g1(tmp_path):
    _ws(tmp_path)
    _blocked(tmp_path, [_card(222, "+120", "-140", CT_G2)])


def test_g2_card_alone_without_label_refuses(tmp_path):
    _ws(tmp_path)
    _blocked(tmp_path, [_card(222, "+120", "-140")])


def test_g2_card_before_g2_schedule_known_still_binds_g1(tmp_path):
    _pred(tmp_path / "p", 9001, G1)
    r = _run(tmp_path, [_card(222, "+120", "-140", CT_G2), _card(111, "+159", "-193", CT_G1)])
    row = json.loads(Path(r["paths"][0]).read_text())
    assert row["game_pk"] == 9001 and row["provider_event_id"] == "111"


def test_offset_dependent_mapping_refuses(tmp_path):
    # Card A reads as G1 in CT, card B reads as G1 in UTC: two offsets give two different bindings.
    _pred(tmp_path / "p", 9001, G1)
    _blocked(tmp_path, [_card(111, "+159", "-193", CT_G1), _card(222, "+120", "-140", "Sat Oct 24th 12:08 AM")])


def test_two_schedules_one_unlabelled_card_still_refuses(tmp_path):
    _ws(tmp_path)
    _blocked(tmp_path, [_card(111, "+159", "-193")])


def test_conflicting_labels_for_one_event_id_are_dropped():
    extra = '<span data-testid="cb-start-time-111">Sat Oct 24th 7:08 PM</span>'
    b = _fetch([_card(111, "+159", "-193", CT_G1), extra])(URL, "baseball_mlb")
    assert all(r["board_start_time_text"] is None for r in b["rows"])


# ---- t270 audit HIGH: the sole-matchup path must verify a present label ----

def test_sole_path_g2_card_only_g1_schedule_refuses(tmp_path):
    # Only G1 scheduled, only G2's card on the board: G2 prices must never bind to G1.
    _pred(tmp_path / "p", 9001, G1)
    _blocked(tmp_path, [_card(222, "+120", "-140", CT_G2)])


def test_sole_path_unparseable_label_refuses(tmp_path):
    _pred(tmp_path / "p", 9001, G1)
    _blocked(tmp_path, [_card(111, "+159", "-193", "Game 1")])


def test_sole_path_matching_label_is_verified(tmp_path):
    _pred(tmp_path / "p", 9001, G1)
    r = _run(tmp_path, [_card(111, "+159", "-193", CT_G1)])
    row = json.loads(Path(r["paths"][0]).read_text())
    assert row["game_pk"] == 9001
    assert row["event_match_basis"] == "BOARD_START_LABEL_UNIQUE_ACROSS_OFFSETS"


def test_sole_path_unlabelled_card_keeps_unverified_basis(tmp_path):
    _pred(tmp_path / "p", 9001, G1)
    r = _run(tmp_path, [_card(111, "+159", "-193")])
    row = json.loads(Path(r["paths"][0]).read_text())
    assert row["event_match_basis"] == "SOLE_MATCHUP_ON_BOARD_AND_SCHEDULE_NO_LABEL"
