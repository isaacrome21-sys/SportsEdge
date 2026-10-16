"""RED (t212 audit of 3b40ff08): a dict subclass with an overridden .get()
must not carry a forged score past the hash check.  Stored games are the
canonical JSON bytes and are parsed fresh (plain dicts) on every load."""
import json
from datetime import timedelta

import pytest

import sportsedge.research.mlb_total_offense_defense_challenger as ch
from mlb_statsapi_fixture_helpers import raw_game, row_for, trusted_index, trusted_manifest  # noqa: F401
from test_mlb_challenger_grounded_identity_red_t212 import _base

DAY = ch.datetime(2027, 5, 16, 18, tzinfo=ch.timezone.utc)


class _Forged(dict):
    """json.dumps sees the real items; .get() lies."""
    def get(self, key, default=None):
        val = dict.get(self, key, default)
        if key == "teams":
            val = json.loads(json.dumps(val))
            val["away"]["score"] = 99
        return val

    def __getitem__(self, key):
        return self.get(key)


def _setup():
    docs, rows = _base()
    real = docs + [raw_game(820001, "NYY", "BOS", DAY)]
    return trusted_index(real), rows + [row_for(real[-1])], real


def test_stored_games_are_immutable_canonical_bytes():
    idx, _, _ = _setup()
    games = object.__getattribute__(idx, "_games")
    assert type(games) is bytes
    assert json.dumps(json.loads(games), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8") == games


def test_dict_subclass_get_override_cannot_forge_score():
    idx, rows, real = _setup()
    games = json.loads(object.__getattribute__(idx, "_games"))
    games[-1] = _Forged(games[-1])
    object.__setattr__(idx, "_games", games)  # non-bytes injection
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_INVALID"):
        ch.load_grounded_finals(rows, fixture_index=idx)


def test_canonicalize_strips_subclass_before_hash_and_build():
    games = [_Forged(g) for g in json.loads(
        ch._canonical_games_bytes(ch._documents_games([raw_game(820001, "NYY", "BOS", DAY)])))]
    blob = ch._canonical_games_bytes(games)
    parsed = json.loads(blob)
    assert all(type(g) is dict for g in parsed)
    fx = ch._build_fixtures(parsed)[820001]
    assert 99 not in (fx.away_runs, fx.home_runs)


def test_tampered_bytes_refused():
    idx, rows, _ = _setup()
    games = json.loads(object.__getattribute__(idx, "_games"))
    games[-1]["teams"]["away"]["score"] = 99
    object.__setattr__(idx, "_games", ch._canonical_games_bytes(games))
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_NOT_TRUSTED"):
        ch.load_grounded_finals(rows, fixture_index=idx)


def test_loaded_records_carry_real_scores():
    idx, rows, real = _setup()
    out = ch.load_grounded_finals(rows, fixture_index=idx)
    assert out.ledger == []
    assert all(99 not in (r.away_runs, r.home_runs) for r in out.records)
