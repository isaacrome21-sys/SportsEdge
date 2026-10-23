import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.capture_mlb_rendered_paired_ml import capture
from sportsedge.mlb_rendered_moneyline_capture import (
    RenderedMLBCaptureBlocked,
    adapt_rendered_moneylines,
    persist_create_only,
)
from sportsedge.mlb_source import GameSnapshot


NOW = datetime(2026, 10, 23, 20, 0, tzinfo=timezone.utc)


def _game(game_pk=1, minutes=32, away="Boston Red Sox", home="New York Yankees"):
    return GameSnapshot(
        game_pk=game_pk,
        game_date=(NOW + timedelta(minutes=minutes)).isoformat(),
        status="Preview",
        away_id=1,
        away_name=away,
        home_id=2,
        home_name=home,
        away_probable_pitcher_id=None,
        away_probable_pitcher_name=None,
        home_probable_pitcher_id=None,
        home_probable_pitcher_name=None,
        retrieved_at=NOW.isoformat(),
    )


def _row(outcome, price, *, event_id="dk-1", away="BOS Red Sox", home="NYY Yankees"):
    return {
        "status": "OK",
        "market": "h2h",
        "provider_event_id": event_id,
        "away_team": away,
        "home_team": home,
        "outcome": outcome,
        "price_american": price,
    }


def _board(*, rows=None, refused_rows=None, card_refusals=None):
    return {
        "source_class": "DRAFTKINGS_RENDERED_PAGE_V1",
        "page_status": "OK",
        "observed_at_utc": NOW.isoformat(),
        "page_html_sha256": "b" * 64,
        "source_uri": "https://sportsbook.draftkings.com/leagues/baseball/mlb",
        "final_url": "https://sportsbook.draftkings.com/leagues/baseball/mlb",
        "rows": rows if rows is not None else [
            _row("BOS Red Sox", 120),
            _row("NYY Yankees", -140),
        ],
        "refused_rows": refused_rows or [],
        "card_refusals": card_refusals or [],
    }


def test_exact_schedule_identity_binds_t30_pair():
    rows = adapt_rendered_moneylines(_board(), [_game()], model_artifact_sha256="a" * 64)
    assert len(rows) == 1
    row = rows[0]
    assert row["game_pk"] == 1
    assert row["capture_window"] == "T30"
    assert row["moneyline"] == {
        "status": "OK",
        "home_price_american": -140,
        "away_price_american": 120,
    }
    assert row["promotion_authority"] is False
    assert row["provider_quote_timestamp_available"] is False


@pytest.mark.parametrize("minutes,window", [(60, "T60"), (32, "T30"), (10, "T10")])
def test_capture_window_boundaries_are_explicit(minutes, window):
    row = adapt_rendered_moneylines(
        _board(), [_game(minutes=minutes)], model_artifact_sha256="a" * 64
    )[0]
    assert row["capture_window"] == window


def test_unknown_team_alias_fails_closed():
    board = _board(rows=[_row("Mystery Club", 120, away="Mystery Club"), _row("NYY Yankees", -140, away="Mystery Club")])
    with pytest.raises(RenderedMLBCaptureBlocked, match="TEAM_NAME_UNMAPPED"):
        adapt_rendered_moneylines(board, [_game()], model_artifact_sha256="a" * 64)


def test_same_teams_doubleheader_in_window_is_ambiguous():
    schedule = [_game(game_pk=1, minutes=30), _game(game_pk=2, minutes=70)]
    with pytest.raises(RenderedMLBCaptureBlocked, match="OFFICIAL_SCHEDULE_MATCH_AMBIGUOUS"):
        adapt_rendered_moneylines(_board(), schedule, model_artifact_sha256="a" * 64)


def test_out_of_window_or_started_game_is_not_joined():
    for minutes in (-1, 90):
        with pytest.raises(RenderedMLBCaptureBlocked, match="NOT_IN_CAPTURE_WINDOW"):
            adapt_rendered_moneylines(
                _board(), [_game(minutes=minutes)], model_artifact_sha256="a" * 64
            )


def test_any_refused_moneyline_side_blocks_whole_capture():
    refused = [_row("BOS Red Sox", 120) | {"status": "REFUSED"}]
    with pytest.raises(RenderedMLBCaptureBlocked, match="MONEYLINE_SIDE_REFUSED"):
        adapt_rendered_moneylines(
            _board(refused_rows=refused), [_game()], model_artifact_sha256="a" * 64
        )


def test_exactly_two_sides_required():
    with pytest.raises(RenderedMLBCaptureBlocked, match="NOT_EXACTLY_TWO_SIDED"):
        adapt_rendered_moneylines(
            _board(rows=[_row("BOS Red Sox", 120)]),
            [_game()],
            model_artifact_sha256="a" * 64,
        )


def test_create_only_persistence_deduplicates_exact_bytes(tmp_path):
    rows = adapt_rendered_moneylines(_board(), [_game()], model_artifact_sha256="a" * 64)
    first = persist_create_only(rows, tmp_path)
    second = persist_create_only(rows, tmp_path)
    assert len(first) == 1
    assert second == []
    saved = json.loads(__import__("pathlib").Path(first[0]).read_text())
    assert saved["capture_observation_id"].startswith("1__T30__")


def test_bad_source_class_and_digest_fail_closed():
    with pytest.raises(RenderedMLBCaptureBlocked, match="RENDERED_SOURCE_CLASS_REQUIRED"):
        adapt_rendered_moneylines(_board() | {"source_class": "DIRECT_API"}, [_game()], model_artifact_sha256="a" * 64)
    with pytest.raises(RenderedMLBCaptureBlocked, match="PAGE_HTML_SHA256_INVALID"):
        adapt_rendered_moneylines(_board() | {"page_html_sha256": "bad"}, [_game()], model_artifact_sha256="a" * 64)


def test_capture_cli_contract_uses_chicago_slate_and_create_only(tmp_path):
    seen = {}

    def rendered(url, **kwargs):
        seen["url"] = url
        seen["sport_key"] = kwargs["sport_key"]
        return _board()

    def schedule(day, *, now):
        seen["day"] = day
        seen["now"] = now
        return [_game()]

    first = capture(
        output_dir=str(tmp_path),
        rendered_fetcher=rendered,
        schedule_fetcher=schedule,
        artifact_binder=lambda: "a" * 64,
    )
    second = capture(
        output_dir=str(tmp_path),
        rendered_fetcher=rendered,
        schedule_fetcher=schedule,
        artifact_binder=lambda: "a" * 64,
    )
    assert first["status"] == "RETAINED"
    assert second["status"] == "ALREADY_CAPTURED"
    assert seen["sport_key"] == "baseball_mlb"
    assert seen["day"] == "2026-10-23"
    assert seen["now"] == NOW
