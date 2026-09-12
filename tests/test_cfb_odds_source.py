from sportsedge.sports.cfb.odds_source import build_cfb_odds_url, fetch_cfb_odds


def test_bulk_url_is_cfb_draftkings_game_markets_only():
    url = build_cfb_odds_url()
    assert "/sports/americanfootball_ncaaf/odds?" in url
    assert "bookmakers=draftkings" in url
    assert "markets=h2h%2Cspreads%2Ctotals" in url
    assert "alternate_" not in url


def test_event_url_binds_exact_provider_event():
    url = build_cfb_odds_url(event_id="provider-event-123")
    assert "/sports/americanfootball_ncaaf/events/provider-event-123/odds?" in url
    assert "bookmakers=draftkings" in url


def test_invalid_event_id_fails_closed():
    try:
        build_cfb_odds_url(event_id="bad/id")
    except ValueError as exc:
        assert str(exc) == "CFB_FORWARD_EVENT_ID_INVALID"
    else:
        raise AssertionError("invalid provider event id accepted")


def test_fetch_preserves_exact_raw_bytes_and_failover_slot():
    calls = []
    exact = b'[{"id":"event-1","bookmakers":[]}]\n'

    def fetcher(url, key):
        calls.append((url, key))
        if key == "bad":
            raise RuntimeError("temporary credential failure")
        return exact, [{"id": "event-1", "bookmakers": []}]

    result = fetch_cfb_odds(("bad", "good"), fetcher=fetcher)
    assert result.raw == exact
    assert result.payload == [{"id": "event-1", "bookmakers": []}]
    assert result.key_slot == 2
    assert result.prior_key_failures == 1
    assert [key for _, key in calls] == ["bad", "good"]


def test_event_payload_must_be_object():
    def fetcher(url, key):
        return b'[]\n', []

    try:
        fetch_cfb_odds(("key",), event_id="event-1", fetcher=fetcher)
    except ValueError as exc:
        assert str(exc) == "CFB_FORWARD_EVENT_ODDS_NOT_OBJECT"
    else:
        raise AssertionError("non-object event payload accepted")


def test_bulk_payload_must_be_list():
    def fetcher(url, key):
        return b'{}\n', {}

    try:
        fetch_cfb_odds(("key",), fetcher=fetcher)
    except ValueError as exc:
        assert str(exc) == "CFB_FORWARD_SPORT_ODDS_NOT_LIST"
    else:
        raise AssertionError("non-list bulk payload accepted")
