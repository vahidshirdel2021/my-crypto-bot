from signal_engine.bridge import _execution_target_levels
from signal_engine.key_level_setup.levels import LevelSet, LevelInfo


def test_low_timeframe_targets_do_not_use_nearby_1h_4h_levels():
    levels = LevelSet(
        symbol="TEST",
        as_of_time=None,
        levels={
            "P1H": LevelInfo(101.0),
            "P4H": LevelInfo(102.0),
            "PDH": LevelInfo(105.0),
            "PWH": LevelInfo(110.0),
            "PMH": LevelInfo(120.0),
        },
    )
    got = _execution_target_levels("5min", True, levels)
    assert got[0] == ("PDH", 105.0)
    assert ("P1H", 101.0) not in got
    assert ("P4H", 102.0) not in got
