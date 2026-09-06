import pandas as pd

from signal_engine.swing_structure.swings import detect_swings, select_significant_swings


def _frame(highs, lows, volumes=None):
    n = len(highs)
    closes = [(h + l) / 2 for h, l in zip(highs, lows)]
    data = {
        "open": closes,
        "high": highs,
        "low": lows,
        "close": closes,
    }
    if volumes is not None:
        data["volume"] = volumes
    return pd.DataFrame(data)


def test_quality_is_present_and_lookahead_safe():
    # Clear peak at index 5; only bars through 5+k may affect its quality.
    highs = [100, 101, 102, 103, 104, 112, 104, 103, 102, 101, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91]
    lows  = [ 98,  99, 100, 101, 102, 103, 101, 100,  99,  98,  97, 96, 95, 94, 93, 92, 91, 90, 89, 88]
    df = _frame(highs, lows, [100] * len(highs))
    swings = detect_swings(df, "5m", "X", {"fractal_k": 2, "atr_period": 3})
    peak = next(s for s in swings if s.candle_index == 5)
    assert peak.status == "confirmed"
    assert peak.confirmed_at_index == 7
    assert peak.evidence["quality_lookahead_safe"] is True
    assert peak.evidence["quality_calculated_through_index"] == 7
    assert peak.quality_score is not None
    assert peak.quality_label in {"weak", "confirmed", "significant"}


def test_significant_selector_only_returns_quality_swings():
    highs = [100, 101, 102, 103, 104, 112, 104, 103, 102, 101, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91]
    lows  = [ 98,  99, 100, 101, 102, 103, 101, 100,  99,  98,  97, 96, 95, 94, 93, 92, 91, 90, 89, 88]
    swings = detect_swings(_frame(highs, lows), "5m", "X", {"fractal_k": 2, "atr_period": 3})
    significant = select_significant_swings(swings, min_score=70)
    assert all(s.status == "confirmed" and s.quality_score >= 70 for s in significant)


def test_quality_does_not_change_when_future_after_confirmation_changes():
    base_highs = [100,101,102,103,104,112,104,103,102,101,100,99,98,97,96,95,94,93,92,91]
    base_lows  = [ 98, 99,100,101,102,103,101,100, 99, 98, 97,96,95,94,93,92,91,90,89,88]
    extended_highs = base_highs + [200, 201, 202, 203]
    extended_lows  = base_lows  + [190, 191, 192, 193]
    s1 = next(s for s in detect_swings(_frame(base_highs, base_lows), "5m", "X", {"fractal_k": 2, "atr_period": 3}) if s.candle_index == 5)
    s2 = next(s for s in detect_swings(_frame(extended_highs, extended_lows), "5m", "X", {"fractal_k": 2, "atr_period": 3}) if s.candle_index == 5)
    assert s1.confirmed_at_index == s2.confirmed_at_index == 7
    assert s1.quality_score == s2.quality_score
    assert s1.quality_label == s2.quality_label
