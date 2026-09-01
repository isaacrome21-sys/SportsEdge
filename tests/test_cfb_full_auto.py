import sportsedge.sports.cfb.full_auto as full_auto


def test_full_auto_builds_cfbd_provider_factory_and_zero_game_list(monkeypatch):
    marker = object()
    captured = {}

    def fake_factory(*, cfbd_api_key, opener):
        captured["factory_key"] = cfbd_api_key
        return marker

    def fake_slate(**kwargs):
        captured.update(kwargs)
        return {
            "sport": "CFB",
            "collection_mode": kwargs["mode"],
            "game_count": 0,
            "games": [],
            "model_p_eligible": False,
            "truth_gate_eligible": False,
        }

    monkeypatch.setattr(full_auto, "build_cfbd_provider_factory", fake_factory)
    monkeypatch.setattr(full_auto, "build_cfb_auto_context_slate", fake_slate)

    payload = full_auto.build_cfb_full_auto_slate(
        as_of="2026-09-01T13:00:00+00:00",
        cfbd_api_key="secret",
        season=2026,
        mode="AUTO",
    )

    assert captured["factory_key"] == "secret"
    assert captured["cfbd_api_key"] == "secret"
    assert captured["season"] == 2026
    assert captured["provider_factory"] is marker
    assert "games" not in captured
    assert payload["model_p_eligible"] is False
    assert payload["truth_gate_eligible"] is False


def test_full_auto_does_not_accept_market_or_social_inputs():
    parameter_names = set(full_auto.build_cfb_full_auto_slate.__annotations__)
    prohibited = {
        "odds",
        "quotes",
        "bookmakers",
        "public_betting",
        "ticket_pct",
        "money_pct",
        "social",
        "market_probability",
    }
    assert not (parameter_names & prohibited)
