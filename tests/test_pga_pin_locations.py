from sportsedge.pga.pin_locations import PinLocation, pin_difficulty, round_pin_adjustment


def test_tucked_water_pin_rates_tougher_than_center_pin():
    neutral = PinLocation(hole=1, green_depth_yards=30, front_yards=15, side_yards=12)
    tough = PinLocation(
        hole=2,
        green_depth_yards=30,
        front_yards=5,
        side_yards=5,
        near_water=True,
        edge_pin=True,
        front_pin=True,
    )
    assert pin_difficulty(tough).difficulty_strokes > pin_difficulty(neutral).difficulty_strokes
    assert pin_difficulty(tough).label in {"TOUGH", "VERY_TOUGH"}


def test_round_adjustment_is_additive_and_conservative():
    pins = [
        PinLocation(hole=1, green_depth_yards=29, front_yards=18, side_yards=7),
        PinLocation(hole=2, green_depth_yards=30, front_yards=5, side_yards=7, near_water=True, edge_pin=True),
        PinLocation(hole=3, green_depth_yards=37, front_yards=5, side_yards=13, front_pin=True),
    ]
    adj = round_pin_adjustment(pins)
    assert 0.0 <= adj <= 0.48
