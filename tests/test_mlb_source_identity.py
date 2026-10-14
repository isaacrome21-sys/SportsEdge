import pytest

from sportsedge.mlb_source_identity import (
    MLBSourceIdentityError, bind_source_record, check_split_identity, refuse_conflicting_game_pk,
)


def _split(pk, day, pid=None, team=None, k=5):
    s = {"date": day, "game": {"gamePk": pk}, "stat": {"strikeOuts": k}}
    if pid is not None:
        s["player"] = {"id": pid}
    if team is not None:
        s["team"] = {"id": team}
    return s


def test_split_identity_match_absent_and_mismatch():
    check_split_identity(_split(1, "2026-05-01", 10), expected_player_id=10)
    check_split_identity(_split(1, "2026-05-01"), expected_player_id=10)
    with pytest.raises(MLBSourceIdentityError, match="PLAYER_ID_MISMATCH"):
        check_split_identity(_split(1, "2026-05-01", 11), expected_player_id=10)
    with pytest.raises(MLBSourceIdentityError, match="TEAM_ID_MISMATCH"):
        check_split_identity(_split(1, "2026-05-01", team=147), expected_team_id=111)
    with pytest.raises(MLBSourceIdentityError, match="MALFORMED"):
        check_split_identity({"player": "Gerrit Cole"}, expected_player_id=10)
    with pytest.raises(MLBSourceIdentityError, match="INVALID"):
        check_split_identity({"player": {"id": True}}, expected_player_id=10)


def test_game_pk_duplicates():
    assert len(refuse_conflicting_game_pk([(1, {"k": 5}), (1, {"k": 5}), (2, {"k": 3})])) == 2
    with pytest.raises(MLBSourceIdentityError, match="CONFLICTING"):
        refuse_conflicting_game_pk([(1, {"k": 5}), (1, {"k": 6})])
    with pytest.raises(MLBSourceIdentityError, match="GAME_PK_INVALID"):
        refuse_conflicting_game_pk([("abc", {"k": 5})])


def test_bind_source_record():
    rec = {"game_pk": 776655, "player_id": "543037", "team_id": 147}
    assert bind_source_record(rec, expected_game_pk=776655, expected_player_id=543037, expected_team_id=147)["player_id"] == 543037
    for field, val, reason in (("game_pk", 1, "GAME_PK_MISMATCH"), ("player_id", 2, "PLAYER_ID_MISMATCH"),
                               ("team_id", 3, "TEAM_ID_MISMATCH"), ("team_id", None, "TEAM_ID_MISSING"),
                               ("player_id", 5.0, "PLAYER_ID_INVALID")):
        with pytest.raises(MLBSourceIdentityError, match=reason):
            bind_source_record({**rec, field: val}, expected_game_pk=776655, expected_player_id=543037, expected_team_id=147)
    with pytest.raises(MLBSourceIdentityError, match="NOT_OBJECT"):
        bind_source_record(None, expected_game_pk=1, expected_player_id=1, expected_team_id=1)


# --- public pitcher history wiring (offline fixtures reused) ---
from tests.test_mlb_phone_pitcher_real_public_history import AS_OF, KICKOFF, logs, schedule  # noqa: E402
from sportsedge.mlb_public_pitcher_history import MLBPitcherPublicSource, MissingMLBHistory  # noqa: E402


def _pitcher_getter(mutate):
    def g(url):
        if url.split("?")[0].endswith("/schedule"):
            return schedule()
        data = logs(starts=7)
        mutate(data["stats"][0]["splits"])
        return data
    return g


def _prior(mutate):
    return MLBPitcherPublicSource(getter=_pitcher_getter(mutate)).prior_starts(
        away="Los Angeles Dodgers", home="Milwaukee Brewers", player_name="Jacob Misiorowski",
        owner_kickoff=KICKOFF, as_of=AS_OF.isoformat())


def test_public_pitcher_history_accepts_matching_player_ids():
    def m(splits):
        for s in splits:
            s["player"] = {"id": 800222}
    assert _prior(m)["prior_start_count"] == 7


def test_public_pitcher_history_refuses_foreign_player_split():
    def m(splits):
        splits[2]["player"] = {"id": 800111}
    with pytest.raises(MissingMLBHistory, match="SOURCE_IDENTITY_SPLIT_PLAYER_ID_MISMATCH"):
        _prior(m)


def test_public_pitcher_history_refuses_conflicting_duplicate_game_pk():
    def m(splits):
        dup = {**splits[0], "stat": {**splits[0]["stat"], "strikeOuts": 12}}
        splits.append(dup)
    with pytest.raises(MissingMLBHistory, match="GAME_PK_DUPLICATE_CONFLICTING"):
        _prior(m)


def test_public_pitcher_history_collapses_identical_duplicate():
    def m(splits):
        splits.append(dict(splits[0]))
    assert _prior(m)["prior_start_count"] == 7
