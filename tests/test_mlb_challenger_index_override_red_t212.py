"""RED (t212 audit of 4b660033): instance overrides cannot bypass index
verification; attributes are immutable; the threshold config's sha is pinned
in the trusted manifest; test trust() restores the module constants."""
import hashlib
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

import sportsedge.research.mlb_total_offense_defense_challenger as ch
from mlb_statsapi_fixture_helpers import raw_game, row_for, trusted_index, trusted_manifest  # noqa: F401
from test_mlb_challenger_grounded_identity_red_t212 import _base

ROOT = Path(__file__).resolve().parents[1]
DAY = ch.datetime(2027, 5, 16, 18, tzinfo=ch.timezone.utc)


def _setup():
    docs, rows = _base()
    real = docs + [raw_game(820001, "NYY", "BOS", DAY)]
    return trusted_index(real), rows + [row_for(real[-1])], real


def test_instance_verify_override_blocked():
    idx, rows, real = _setup()
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_IMMUTABLE"):
        idx.verify = lambda: None
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_IMMUTABLE"):
        idx.get = lambda pk: None


def test_object_setattr_bypass_still_reverified():
    idx, rows, real = _setup()
    # Even if an attacker forces attributes past __setattr__, load re-derives
    # fixtures from the verified raw games and never calls instance methods.
    for name in ("verify", "get", "has"):
        try:
            object.__setattr__(idx, name, lambda *a, **k: None)
        except AttributeError:
            pass  # __slots__: no instance dict to hold an override
    fake = ch.RawFixture.from_game(raw_game(820099, "NYY", "BOS", DAY)["dates"][0]["games"][0])
    object.__setattr__(idx, "_fixtures", {820099: fake})
    out = ch.load_grounded_finals(rows + [row_for(raw_game(820099, "NYY", "BOS", DAY))],
                                  fixture_index=idx)
    assert len(out.records) == 201
    assert [e["reason"].split(":")[0] for e in out.ledger] == ["GAME_PK_NOT_IN_INDEX"]


def test_tampered_games_refused_even_with_overrides():
    idx, rows, real = _setup()
    games = object.__getattribute__(idx, "_games")
    games[-1]["teams"]["away"]["score"] = 99
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_INDEX_NOT_TRUSTED"):
        ch.load_grounded_finals(rows, fixture_index=idx)


def test_index_has_slots_no_instance_dict():
    idx, _, _ = _setup()
    assert not hasattr(idx, "__dict__")


def test_committed_manifest_pins_identity_config_sha():
    manifest = json.loads((ROOT / "config/research/mlb_challenger_fixture_index_manifest_v1.json").read_text())
    cfg = (ROOT / "config/research/mlb_challenger_fixture_identity_v1.json").read_bytes()
    assert manifest["identity_config_sha256"] == hashlib.sha256(cfg).hexdigest()


def test_unpinned_threshold_config_refused(tmp_path, monkeypatch):
    idx, rows, _ = _setup()
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps({"identity": "STATSAPI_GAMEPK_RAW_RECORD",
                             "max_unverified_rows": 50, "max_unverified_fraction": 0.05}))
    monkeypatch.setattr(ch, "IDENTITY_CONFIG_PATH", p)  # in-bounds but not pinned
    with pytest.raises(ch.MLBTotalCandidateError, match="FIXTURE_IDENTITY_CONFIG_TAMPERED"):
        ch.load_grounded_finals(rows, fixture_index=idx)


def test_after_fixture_constants_are_production():
    import importlib
    src = (ROOT / "sportsedge/research/mlb_total_offense_defense_challenger.py").read_text()
    const = re.search(r'TRUSTED_MANIFEST_SHA256 = "([0-9a-f]{64})"', src).group(1)
    from mlb_statsapi_fixture_helpers import ORIGINALS
    assert ORIGINALS["sha"] == const
    assert ORIGINALS["path"].name == "mlb_challenger_fixture_index_manifest_v1.json"


def test_trust_fixture_teardown_restores(monkeypatch):
    from mlb_statsapi_fixture_helpers import ORIGINALS, _manifest_session
    gen = _manifest_session()
    next(gen)
    assert ch.TRUSTED_MANIFEST_SHA256 != ORIGINALS["sha"]
    with pytest.raises(StopIteration):
        next(gen)
    assert ch.TRUSTED_MANIFEST_SHA256 == ORIGINALS["sha"]
    assert ch.TRUSTED_MANIFEST_PATH == ORIGINALS["path"]
    assert ch.IDENTITY_CONFIG_PATH == ORIGINALS["config"]
