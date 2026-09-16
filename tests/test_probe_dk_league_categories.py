from scripts.probe_dk_league_categories import _category_candidates


def test_category_candidates_are_discovered_without_name_guessing():
    payload = {
        "categories": [
            {"id": 100, "name": "Something"},
            {"id": 200, "name": "Game Lines"},
        ],
        "navigation": {"categoryId": 300, "displayName": "Other"},
    }
    rows = _category_candidates(payload)
    assert {r["category_id"] for r in rows} == {100, 200, 300}
