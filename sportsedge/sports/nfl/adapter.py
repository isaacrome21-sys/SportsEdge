"""NFL adapter for the shared football SportAdapter."""

from __future__ import annotations

from collections.abc import Mapping
from math import isfinite
from typing import Any

from .environment_profile import validate_nfl_environment_profile
from .m2 import build_nfl_m2_features
from .simulator_profile import KEY_NUMBER_CONTRACT


class NFLAdapter:
    sport = "nfl"

    def __init__(
        self,
        history_ingestor: Any | None = None,
        *,
        environment_profile: Mapping[str, Any] | None = None,
        simulator_profile: Mapping[str, Any] | None = None,
    ) -> None:
        self.history_ingestor = history_ingestor
        self.environment_profile = (
            validate_nfl_environment_profile(environment_profile)
            if environment_profile is not None
            else None
        )
        self.simulator_profile = dict(simulator_profile) if simulator_profile is not None else None

    def load_schedule(self, seasons: list[int]) -> Any:
        if self.history_ingestor is None:
            raise NotImplementedError("NFL history ingestor is not configured")
        return self.history_ingestor.load(seasons)

    def load_lines_history(self, seasons: list[int]) -> Any:
        if self.history_ingestor is None:
            raise NotImplementedError("NFL history ingestor is not configured")
        return self.history_ingestor.load(seasons)

    def build_features(self, asof_ts: Any, games: Any) -> Any:
        """Mechanical adapter seam into the already-implemented NFL M2 builder."""

        def one(game: Any) -> dict[str, float | str]:
            if not isinstance(game, dict):
                raise TypeError("NFL feature source must be a mapping")
            source = dict(game)
            source["feature_asof_ts"] = asof_ts
            return build_nfl_m2_features(source)

        if isinstance(games, dict):
            return one(games)
        if isinstance(games, (list, tuple)):
            return [one(game) for game in games]
        raise TypeError("NFL games must be a mapping or sequence of mappings")

    def _environment(self) -> Mapping[str, Any]:
        if self.environment_profile is None:
            raise ValueError("NFL_ENVIRONMENT_PROFILE_REQUIRED")
        return self.environment_profile

    def margin_sigma(self, context: Any) -> float:
        """Return the hash-bound empirical global NFL margin dispersion."""

        return float(self._environment()["margin_sigma"])

    def total_sigma(self, context: Any) -> float:
        """Return the hash-bound empirical global NFL total-score dispersion."""

        return float(self._environment()["total_sigma"])

    def key_number_validation_targets(self) -> dict[int, float]:
        """Return empirical ±3/±7 frequencies for validation only.

        These values are explicitly forbidden as simulator probability inputs.
        They exist only to score whether discrete margins emerge naturally from
        the football path model.
        """

        profile = self.simulator_profile
        if profile is None:
            raise ValueError("NFL_SIMULATOR_PROFILE_REQUIRED")
        if profile.get("key_number_contract") != KEY_NUMBER_CONTRACT:
            raise ValueError("EMERGENT_KEY_NUMBER_CONTRACT_REQUIRED")
        raw = profile.get("validation_target_key_frequency")
        if not isinstance(raw, Mapping):
            raise ValueError("PROFILE_KEY_FREQUENCY_TARGET_MISSING")
        targets: dict[int, float] = {}
        for key in (-7, -3, 3, 7):
            value = raw.get(key, raw.get(str(key)))
            if value is None:
                raise ValueError(f"SIGNED_KEY_FREQUENCY_MISSING:{key}")
            parsed = float(value)
            if not isfinite(parsed) or parsed < 0:
                raise ValueError(f"SIGNED_KEY_FREQUENCY_INVALID:{key}")
            targets[key] = parsed
        if sum(targets.values()) >= 1.0:
            raise ValueError("SIGNED_KEY_FREQUENCY_INVALID_SUM")
        return targets

    def key_numbers(self) -> dict[int, float]:
        """Reject the legacy simulator-input interpretation of key numbers."""

        raise ValueError(
            "HISTORICAL_KEY_NUMBERS_ARE_VALIDATION_ONLY:"
            "use key_number_validation_targets"
        )

    @staticmethod
    def _neutral_flag(value: Any) -> bool | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)) and value in (0, 1):
            return bool(value)
        text = str(value).strip().lower()
        if text in {"true", "yes", "y", "1"}:
            return True
        if text in {"false", "no", "n", "0"}:
            return False
        raise ValueError(f"NEUTRAL_SITE_VALUE_INVALID:{value}")

    def hfa_prior(self, venue: Any, context: Any) -> float:
        """Return zero at neutral sites, otherwise the empirical league HFA prior."""

        flags: list[bool] = []
        for source in (venue, context):
            if not isinstance(source, Mapping):
                continue
            raw = source.get("neutral_site", source.get("neutral"))
            parsed = self._neutral_flag(raw)
            if parsed is not None:
                flags.append(parsed)
        if len(set(flags)) > 1:
            raise ValueError("NEUTRAL_SITE_CONTEXT_CONFLICT")
        if flags and flags[0]:
            return 0.0
        return float(self._environment()["hfa_points"])
