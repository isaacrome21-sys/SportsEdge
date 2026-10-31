"""American odds helpers and de-vig. No network, no state."""


def american_to_prob(odds: float) -> float:
    """Raw implied probability of American odds (includes vig)."""
    odds = float(odds)
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)


def american_to_decimal(odds: float) -> float:
    odds = float(odds)
    return 1.0 + (odds / 100.0 if odds > 0 else 100.0 / -odds)


def devig_pair(odds_a: float, odds_b: float) -> tuple[float, float]:
    """Fair probabilities for a two-way market (multiplicative de-vig)."""
    pa, pb = american_to_prob(odds_a), american_to_prob(odds_b)
    s = pa + pb
    return pa / s, pb / s


def ev_per_unit(p_win: float, odds: float) -> float:
    """Expected profit per 1u staked at these odds, given win probability."""
    return p_win * (american_to_decimal(odds) - 1.0) - (1.0 - p_win)
