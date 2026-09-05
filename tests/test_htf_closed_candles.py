import pandas as pd

from signal_engine.common.htf import closed_htf_slice


def _df(opens):
    return pd.DataFrame({"timestamp": opens, "open": [1]*len(opens), "high":[2]*len(opens), "low":[0]*len(opens), "close":[1]*len(opens), "volume":[1]*len(opens)})


def test_1h_forming_candle_excluded_at_14_00():
    # 13:00 candle closes at 14:00, 14:00 candle is forming.
    h = _df([1704110400000, 1704114000000, 1704117600000])
    out = closed_htf_slice(h, 1704117600000, "1h")
    assert list(out.timestamp) == [1704110400000, 1704114000000]


def test_1h_exact_boundary_included():
    h = _df([1704110400000, 1704114000000, 1704117600000])
    out = closed_htf_slice(h, 1704121200000, "1h")
    assert list(out.timestamp) == [1704110400000, 1704114000000, 1704117600000]


def test_4h_and_1d_boundaries():
    h4 = _df([1704067200000, 1704081600000, 1704096000000, 1704110400000])
    assert list(closed_htf_slice(h4, 1704110400000, "4h").timestamp) == [1704067200000, 1704081600000, 1704096000000]
    d = _df([1704067200000, 1704153600000])
    assert list(closed_htf_slice(d, 1704153600000, "1d").timestamp) == [1704067200000]
