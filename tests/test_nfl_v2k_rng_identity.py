from __future__ import annotations

from sportsedge.sports.nfl.v2k_drive_core import (
    RNG_ALGORITHM_VERSION,
    SEED_DERIVATION_VERSION,
    derive_path_seed,
)


def test_v2k_rng_identity_is_pcg64_seedsequence() -> None:
    assert RNG_ALGORITHM_VERSION == "NUMPY_PCG64_SEEDSEQUENCE_V1"
    assert SEED_DERIVATION_VERSION == "V2K_SHA256_GAME_KEY_SEEDSEQUENCE_SPAWN_V1"


def test_path_seed_derivation_is_stable_and_keyed_by_game_and_path() -> None:
    root = 20261004
    a0 = derive_path_seed(root_seed=root, game_key="2026_05_BUF_NE", path_index=0)
    a0_replay = derive_path_seed(root_seed=root, game_key="2026_05_BUF_NE", path_index=0)
    a1 = derive_path_seed(root_seed=root, game_key="2026_05_BUF_NE", path_index=1)
    b0 = derive_path_seed(root_seed=root, game_key="2026_05_DAL_NYG", path_index=0)
    assert a0 == a0_replay
    assert len({a0, a1, b0}) == 3


def test_seed_derivation_fails_closed_without_explicit_identity() -> None:
    import pytest
    with pytest.raises(ValueError, match="V2K_ROOT_SEED_REQUIRED"):
        derive_path_seed(root_seed=None, game_key="G", path_index=0)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="V2K_GAME_KEY_REQUIRED"):
        derive_path_seed(root_seed=1, game_key="", path_index=0)
    with pytest.raises(ValueError, match="V2K_PATH_INDEX_INVALID"):
        derive_path_seed(root_seed=1, game_key="G", path_index=-1)
