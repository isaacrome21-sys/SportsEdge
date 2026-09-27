"""PIT-safe orchestration from raw NBA model probability to a bound quote.

The sportsbook quote never creates or calibrates model probability. Calibration is
optional and must be an already-fitted temporal calibrator whose history digest is
recorded in provenance. Missing calibration leaves the raw path probability intact.
"""
from dataclasses import dataclass
import math

from .binding import NBAQuote, NBABoundEdge, bind_quote
from .calibration import NBACalibrator
from .pricing import NBAFairPrice


@dataclass(frozen=True)
class NBAProbabilityProvenance:
    raw_probability: float
    calibrated_probability: float
    model_version: str
    simulation_sha256: str
    calibration_version: str | None
    calibration_sha256: str | None


def calibrated_fair_price(
    fair: NBAFairPrice,
    *,
    model_version: str,
    simulation_sha256: str,
    calibrator: NBACalibrator | None = None,
) -> tuple[NBAFairPrice, NBAProbabilityProvenance]:
    if not model_version or not simulation_sha256:
        raise ValueError("model version and simulation digest are required")
    if not math.isfinite(fair.win_probability) or not math.isfinite(fair.push_probability) or not math.isfinite(fair.lose_probability):
        raise ValueError("fair probabilities must be finite")
    if min(fair.win_probability, fair.push_probability, fair.lose_probability) < 0:
        raise ValueError("fair probabilities cannot be negative")
    if not math.isclose(fair.win_probability + fair.push_probability + fair.lose_probability, 1.0, abs_tol=1e-9):
        raise ValueError("fair probabilities must sum to one")

    resolved = fair.win_probability + fair.lose_probability
    if resolved <= 0:
        raise ValueError("market must contain resolved outcome mass")

    # No calibrator means a true identity transform. Besides being semantically
    # cleaner, returning the original immutable fair-price object avoids tiny
    # floating-point drift from unnecessarily reconstructing W/L mass.
    if calibrator is None:
        provenance = NBAProbabilityProvenance(
            raw_probability=fair.win_probability,
            calibrated_probability=fair.win_probability,
            model_version=model_version,
            simulation_sha256=simulation_sha256,
            calibration_version=None,
            calibration_sha256=None,
        )
        return fair, provenance

    raw_conditional = fair.win_probability / resolved
    calibrated_conditional = calibrator.calibrate(raw_conditional)

    # Preserve push mass exactly. Calibration only redistributes resolved W/L mass.
    wp = resolved * calibrated_conditional
    lp = resolved * (1.0 - calibrated_conditional)
    pp = fair.push_probability
    fair_decimal = math.inf if wp == 0 else resolved / wp
    calibrated = NBAFairPrice(wp, pp, lp, fair_decimal)
    provenance = NBAProbabilityProvenance(
        raw_probability=fair.win_probability,
        calibrated_probability=wp,
        model_version=model_version,
        simulation_sha256=simulation_sha256,
        calibration_version=calibrator.version,
        calibration_sha256=calibrator.training_sha256,
    )
    return calibrated, provenance


def bind_calibrated_quote(
    quote: NBAQuote,
    fair: NBAFairPrice,
    *,
    as_of,
    model_version: str,
    simulation_sha256: str,
    model_quality: float,
    context_quality: float,
    calibrator: NBACalibrator | None = None,
    max_age_seconds: int = 300,
) -> tuple[NBABoundEdge, NBAProbabilityProvenance]:
    calibrated, provenance = calibrated_fair_price(
        fair,
        model_version=model_version,
        simulation_sha256=simulation_sha256,
        calibrator=calibrator,
    )
    edge = bind_quote(
        quote,
        calibrated,
        as_of=as_of,
        max_age_seconds=max_age_seconds,
        model_quality=model_quality,
        context_quality=context_quality,
    )
    return edge, provenance
