import numpy as np
import pandas as pd
import strategy as s


def test_confirmed_swings_are_causal():
    n = 40
    x = np.arange(n, dtype=float)
    df = pd.DataFrame({
        "open": x, "high": x + 1, "low": x - 1,
        "close": x + 0.5, "volume": np.ones(n) * 100,
        "atr": np.ones(n), "volume_ratio": np.ones(n),
    })
    swings = s._enhanced_confirmed_swings(df, left=2, right=2)
    assert all(item["index"] + 2 < n for item in swings)


def test_key_levels_ignore_future_rows():
    n = 40
    x = np.arange(n, dtype=float)
    df = pd.DataFrame({
        "open": x, "high": x + 1, "low": x - 1,
        "close": x + 0.5, "volume": np.ones(n) * 100,
        "atr": np.ones(n), "volume_ratio": np.ones(n),
    })
    before = s._enhanced_key_levels(df, 20)
    df.loc[39, "high"] = 10000
    after = s._enhanced_key_levels(df, 20)
    assert before == after


def test_v1_first_defaults():
    cfg = s.get_v2_config()
    assert cfg["v2_enabled"] is True
    assert cfg["enhanced_v1_enabled"] is True
    assert cfg["enhanced_orb_enabled"] is False
