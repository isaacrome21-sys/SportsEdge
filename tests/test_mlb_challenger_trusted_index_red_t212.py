"""RED (t212 audit of 0546a0dd): the fixture index hash is pinned outside the
caller's reach (trusted manifest whose own sha is a code constant), the
FixtureIndex constructor is private and re-verified on every load, and ledger
thresholds come from config only with bounds."""
import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

import sportsedge.research.mlb_total_offense_defense_challenger as ch
from mlb_statsapi_fixture_helpers import raw_game, row_for, trusted_index
from test_mlb_total_offense_defense_challenger import BASE, index_for, sample_games, target
from test_mlb_challenger_grounded_identity_red_t212 import _base

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "sportsedge/research/mlb_total_offense_defense_challenger.py").read_text()
DAY = BASE + timedelta(days=500)


def test_committed_manifest_matches_code_constant_and_pins_stored_raw():
    const = re.search(r'TRUSTED_MANIFEST_SHA256 = "([0-9a-f]{64})"', SRC).group(1)
    raw = (ROOT / "config/research/mlb_challenger_fixture_index_manifest_v1.json").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == const
    manifest = json.loads(raw)
    assert manifest["pinned_index_sha256"] == [
        "2db433d394e086e65200cf8c8b3d74db737af4fd4402d9f48f6ead3baaebb362"]


def test_public_api_takes_no_caller_hash_or_thresholds():
    import inspect
    for fn in (ch.FixtureIndex.from_statsapi_documents, ch.FixtureIndex.from_raw_dir,
               ch.load_grounded_finals, ch.predict_total, ch.prequential_backtest):
        params = inspect.signature(fn).parameters
        assert not {"expected_sha256", "max_unverified_rows", "max_unverified_fraction"} & set(params)


def test_fabricated_game_with_recomputed_hash_refused():
    docs = [raw_game(810001, "NYY", "BOS", DAY)]
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_NOT_TRUSTED"):
        ch.FixtureIndex.from_statsapi_documents(docs)


def test_duplicate_under_new_game_pk_refused():
    base_docs, base_rows = _base()
    real = base_docs + [raw_game(810011, "NYY", "BOS", DAY)]
    idx = trusted_index(real)
    forged = real + [raw_game(810012, "NYY", "BOS", DAY)]
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_NOT_TRUSTED"):
        ch.FixtureIndex.from_statsapi_documents(forged)
    row = row_for(forged[-1])
    out = ch.load_grounded_finals(base_rows + [row_for(real[-1]), row], fixture_index=idx)
    assert [e["reason"].split(":")[0] for e in out.ledger] == ["GAME_PK_NOT_IN_INDEX"]


def test_direct_constructor_with_fake_hash_refused():
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_PRIVATE_CONSTRUCTOR"):
        ch.FixtureIndex({}, "0" * 64)
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_PRIVATE_CONSTRUCTOR"):
        ch.FixtureIndex(games=[], sha256="f" * 64)


def test_mutated_index_reverified_on_every_load():
    base_docs, base_rows = _base()
    real = base_docs + [raw_game(810021, "NYY", "BOS", DAY)]
    idx = trusted_index(real)
    idx._games[-1]["teams"]["away"]["score"] = 99  # tamper after construction
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_NOT_TRUSTED"):
        ch.load_grounded_finals(base_rows + [row_for(real[-1])], fixture_index=idx)
    idx2 = trusted_index(real)
    fake = ch.RawFixture.from_game(raw_game(810099, "NYY", "BOS", DAY)["dates"][0]["games"][0])
    idx2._fixtures[810099] = fake  # inject a fixture without touching games
    out = ch.load_grounded_finals(base_rows + [row_for(real[-1]),
                                               row_for(raw_game(810099, "NYY", "BOS", DAY))],
                                  fixture_index=idx2)
    assert [e["reason"].split(":")[0] for e in out.ledger] == ["GAME_PK_NOT_IN_INDEX"]


def test_non_index_object_refused():
    class Fake:
        sha256 = "0" * 64
        def get(self, pk):
            return None
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_REQUIRED"):
        ch.load_grounded_finals([], fixture_index=Fake())


@pytest.mark.parametrize("rows,frac", [(1e9, 0.01), (5, float("nan")), (5, float("inf")),
                                       (float("nan"), 0.01), (float("inf"), 0.01),
                                       (10 ** 9, 0.01), (5, 1e9), (-1, 0.01), (5, -0.1),
                                       (True, 0.01), ("5", 0.01)])
def test_config_thresholds_bounded(tmp_path, monkeypatch, rows, frac):
    cfg = {"identity": "STATSAPI_GAMEPK_RAW_RECORD", "max_unverified_rows": rows,
           "max_unverified_fraction": frac}
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg, allow_nan=True))
    monkeypatch.setattr(ch, "IDENTITY_CONFIG_PATH", p)
    real = [raw_game(810031, "NYY", "BOS", DAY)]
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_IDENTITY_CONFIG_INVALID"):
        ch.load_grounded_finals([row_for(real[0])], fixture_index=trusted_index(real))


def test_caller_cannot_pass_thresholds():
    hist = sample_games()
    with pytest.raises(TypeError):
        ch.predict_total(hist, target(), fixture_index=index_for(hist), max_unverified_rows=10 ** 9)
