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


def test_full_htf_scan_exposes_all_closed_levels():
    n = 24 * 40
    ts = pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC")
    x = np.linspace(100, 200, n)
    df = pd.DataFrame({
        "timestamp": (ts.view("int64") // 10**6),
        "open": x, "high": x + 2, "low": x - 2,
        "close": x + 0.5, "volume": np.ones(n) * 100,
        "atr": np.ones(n), "volume_ratio": np.ones(n)*2, "body_ratio": np.ones(n)*0.8,
    })
    d, _, _ = s._compute_prev_day_levels(df)
    levels = s._htf_scan_levels(d, len(d)-2)
    assert {"P1H","P1L","P4H","P4L","PWH","PWL","PMH","PML"}.issubset(levels)


def test_htf_path_clearance_blocks_obstacle():
    ok, reason = s._htf_path_clearance(
        100.0, 110.0, 2.0, {"P4H": 105.0}, clearance_atr=0.6
    )
    assert ok is False
    assert "P4H" in reason


def test_setup_tags():
    assert s._setup_tag_for_level("P1H") == "[SETUP 1h]"
    assert s._setup_tag_for_level("P4L") == "[SETUP 4h]"
    assert s._setup_tag_for_level("PWH") == "[SETUP Weekly]"
    assert s._setup_tag_for_level("PMH") == "[SETUP Monthly]"
    assert s._setup_tag_for_level("PDH") == "[SETUP Daily]"
