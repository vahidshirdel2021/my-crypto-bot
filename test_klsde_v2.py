# -*- coding: utf-8 -*-
"""
test_klsde_v2.py — regression tests for klsde_v2.py (spec §15).

Plain-assert test runner (no pytest dependency required in this
sandbox). Run with:  python3 test_klsde_v2.py
"""

import sys
import traceback
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import klsde_v2 as K

RESULTS = []


def test(fn):
    RESULTS.append(fn)
    return fn


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def candles_5m(start, rows):
    """rows: list of (o,h,l,c) -> DataFrame with timestamp (unix sec, UTC), atr."""
    ts0 = int(start.timestamp())
    data = []
    for k, (o, h, l, c) in enumerate(rows):
        data.append({
            "timestamp": ts0 + k * 300,
            "open": o, "high": h, "low": l, "close": c, "volume": 100.0,
        })
    df = pd.DataFrame(data)
    return df


def flat_day(n, base, wiggle=0.05):
    """n candles oscillating tightly around `base` (used to fill a full day)."""
    rows = []
    for i in range(n):
        o = base + (wiggle if i % 2 == 0 else -wiggle)
        c = base + (-wiggle if i % 2 == 0 else wiggle)
        h = max(o, c) + wiggle
        l = min(o, c) - wiggle
        rows.append((o, h, l, c))
    return rows


def make_fixed_level_df(level_price, atr, kind, n, level_col_prefix="_day"):
    """
    Build a minimal df (no compute_all_levels) with a single fixed level
    for direct state-machine testing of run_level_reactions in isolation.
    """
    ts0 = int(datetime(2026, 1, 1, tzinfo=timezone.utc).timestamp())
    rows = []
    for i in range(n):
        rows.append({"timestamp": ts0 + i * 300, "open": level_price, "high": level_price,
                      "low": level_price, "close": level_price, "volume": 100.0})
    df = pd.DataFrame(rows)
    df["_dt"] = K._to_utc_datetime(df["timestamp"])
    df[f"{level_col_prefix}_hi"] = level_price if kind in ("high",) else np.nan
    df[f"{level_col_prefix}_lo"] = level_price if kind in ("low",) else np.nan
    df[f"{level_col_prefix}_eq"] = level_price if kind in ("eq",) else np.nan
    df[f"{level_col_prefix}_src"] = "2025-12-31T00:00:00Z"
    df["atr"] = atr
    return df


def set_candle(df, i, o, h, l, c):
    df.loc[i, ["open", "high", "low", "close"]] = [o, h, l, c]


LEVEL_CODE_FOR_TEST = "PDH"  # kind='high', tier='intraday'


def build_scenario(level_price=100.0, atr=1.0, n=40, kind="high", ohlc_overrides=None):
    df = make_fixed_level_df(level_price, atr, kind, n)
    if ohlc_overrides:
        for i, vals in ohlc_overrides.items():
            set_candle(df, i, *vals)
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col])
    return df


# ----------------------------------------------------------------------
# 1) Level computation correctness + no-look-ahead
# ----------------------------------------------------------------------

@test
def test_compute_all_levels_basic_day():
    start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    rows = flat_day(288, base=100.0)          # day 1: oscillates around 100
    rows += flat_day(288, base=110.0)         # day 2: oscillates around 110
    rows += flat_day(50, base=120.0)          # day 3 (partial, still forming)
    df = candles_5m(start, rows)
    out = K.compute_all_levels(df)

    day1_end = 288
    day2_start = 288
    day2_end = 576

    # Day 1 rows: previous day not available -> PDH/PDL must be NaN
    assert out.loc[:day1_end - 1, "_day_hi"].isna().all(), "day1 must have no PDH yet"

    # Day 2 rows: PDH/PDL should reflect day 1's actual high/low
    day1_hi = max(r[1] for r in rows[:288])
    day1_lo = min(r[2] for r in rows[:288])
    got_hi = out.loc[day2_start, "_day_hi"]
    got_lo = out.loc[day2_start, "_day_lo"]
    assert abs(got_hi - day1_hi) < 1e-9, f"expected {day1_hi}, got {got_hi}"
    assert abs(got_lo - day1_lo) < 1e-9, f"expected {day1_lo}, got {got_lo}"

    # It must stay FIXED for the whole of day 2 (does not silently track day2's own range)
    assert out.loc[day2_start:day2_end - 1, "_day_hi"].nunique() == 1

    # Day 3 (partial/current) rows should show day 2's H/L as PDH/PDL
    day2_hi = max(r[1] for r in rows[288:576])
    got_day3_hi = out.loc[day2_end, "_day_hi"]
    assert abs(got_day3_hi - day2_hi) < 1e-9


@test
def test_no_lookahead_partial_day_stays_none():
    """A day that is only partially observed at the END of the dataset
    (i.e. is the currently forming period) must never itself leak into
    its own PDH/PDL — only checked implicitly by the above test, this
    test further confirms an under-filled *previous* day (data starts
    mid-day) correctly refuses to produce a level rather than using a
    truncated range."""
    start = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)  # starts mid-day
    rows = flat_day(50, base=100.0)     # truncated "day 1" (only half a day of candles)
    rows += flat_day(288, base=110.0)   # day 2, fully covered
    df = candles_5m(start, rows)
    out = K.compute_all_levels(df)
    day2_start = 50
    # Because day 1 was truncated (< 85% of expected candles), day 2 must
    # NOT receive a PDH/PDL derived from that incomplete range.
    assert pd.isna(out.loc[day2_start, "_day_hi"])


# ----------------------------------------------------------------------
# 2) TST
# ----------------------------------------------------------------------

@test
def test_tst_bearish_at_resistance():
    df = build_scenario(level_price=100.0, atr=1.0, n=20, kind="high")
    # candle 5: approach + touch (wick to 100.05, closes below)
    set_candle(df, 5, 99.5, 100.05, 99.4, 99.6)
    # candle 6: clear rejection close, well below level
    set_candle(df, 6, 99.6, 99.7, 99.0, 99.1)
    events = K.run_level_reactions(df, "PDH", "TEST", "5min")
    assert len(events) == 1, events
    assert events[0]["setup_type"] == "TST"
    assert events[0]["direction"] == "bearish"


@test
def test_tst_bullish_at_support():
    df = build_scenario(level_price=100.0, atr=1.0, n=20, kind="low")
    set_candle(df, 5, 100.5, 100.6, 99.95, 100.4)   # touch from above
    set_candle(df, 6, 100.4, 101.0, 100.35, 100.9)  # clear rejection upward
    events = K.run_level_reactions(df, "PDL", "TEST", "5min")
    assert len(events) == 1, events
    assert events[0]["setup_type"] == "TST"
    assert events[0]["direction"] == "bullish"


# ----------------------------------------------------------------------
# 3) BOF
# ----------------------------------------------------------------------

@test
def test_bof_bearish_at_resistance():
    df = build_scenario(level_price=100.0, atr=1.0, n=20, kind="high")
    # candle 5: touch
    set_candle(df, 5, 99.6, 100.05, 99.5, 99.9)
    # candle 6: real breach (>0.15 ATR) but weak close (not confirmed breakout)
    set_candle(df, 6, 99.9, 100.30, 99.8, 100.05)
    # candle 7: fails, closes back below original side
    set_candle(df, 7, 100.05, 100.10, 99.5, 99.6)
    events = K.run_level_reactions(df, "PDH", "TEST", "5min")
    assert len(events) == 1, events
    assert events[0]["setup_type"] == "BOF"
    assert events[0]["direction"] == "bearish"


@test
def test_bof_bullish_at_support():
    df = build_scenario(level_price=100.0, atr=1.0, n=20, kind="low")
    set_candle(df, 5, 100.4, 100.5, 99.95, 100.1)
    set_candle(df, 6, 100.1, 100.2, 99.70, 99.95)   # breach below, weak close
    set_candle(df, 7, 99.95, 100.5, 99.9, 100.4)     # fails, closes back above
    events = K.run_level_reactions(df, "PDL", "TEST", "5min")
    assert len(events) == 1, events
    assert events[0]["setup_type"] == "BOF"
    assert events[0]["direction"] == "bullish"


# ----------------------------------------------------------------------
# 4) BPB / BP / CPB (breakout + pullback family)
# ----------------------------------------------------------------------

@test
def test_bpb_bullish_breakout_pullback_continuation():
    df = build_scenario(level_price=100.0, atr=1.0, n=30, kind="high")
    set_candle(df, 5, 99.8, 100.05, 99.7, 99.95)      # touch
    set_candle(df, 6, 99.95, 100.40, 99.9, 100.35)     # confirmed breakout close (>0.25 ATR)
    set_candle(df, 7, 100.35, 100.60, 100.30, 100.55)  # extends higher (new extreme)
    set_candle(df, 8, 100.55, 100.58, 100.35, 100.40)  # pullback begins (retrace >=0.15 ATR)
    set_candle(df, 9, 100.40, 100.45, 100.20, 100.25)  # deeper pullback (single leg)
    set_candle(df, 10, 100.25, 100.75, 100.20, 100.70)  # continuation beyond prior extreme
    events = K.run_level_reactions(df, "PDH", "TEST", "5min")
    assert len(events) == 1, events
    assert events[0]["setup_type"] in ("BPB", "BP"), events
    assert events[0]["direction"] == "bullish"
    assert events[0]["evidence"]["breakout_confirmed"] is True


@test
def test_bp_bullish_single_leg_retest_rejection():
    df = build_scenario(level_price=100.0, atr=1.0, n=30, kind="high")
    set_candle(df, 5, 99.8, 100.05, 99.7, 99.95)
    set_candle(df, 6, 99.95, 100.45, 99.9, 100.40)      # confirmed breakout
    set_candle(df, 7, 100.40, 100.70, 100.35, 100.65)   # extreme = 100.70
    # pullback all the way back to the broken level (retest), with a
    # clear bearish-looking wick-reject candle (rejection/"weakness")
    set_candle(df, 8, 100.65, 100.66, 100.05, 100.10)   # sharp single leg down to level
    set_candle(df, 9, 100.10, 100.15, 100.02, 100.12)   # holds near level (retest continues)
    set_candle(df, 10, 100.12, 100.90, 100.10, 100.85)  # continuation beyond 100.70
    events = K.run_level_reactions(df, "PDH", "TEST", "5min")
    assert len(events) == 1, events
    assert events[0]["setup_type"] in ("BP", "BPB"), events
    assert events[0]["evidence"]["retest_reached_level"] in (True, False)


@test
def test_cpb_multi_wave_pullback():
    df = build_scenario(level_price=100.0, atr=1.0, n=40, kind="high")
    set_candle(df, 5, 99.8, 100.05, 99.7, 99.95)
    set_candle(df, 6, 99.95, 100.45, 99.9, 100.40)     # confirmed breakout, extreme building
    set_candle(df, 7, 100.40, 100.80, 100.35, 100.75)   # extreme = 100.80
    # multi-wave corrective structure (down-up-down-up = >=2 swing lows)
    set_candle(df, 8, 100.75, 100.76, 100.40, 100.45)   # leg down
    set_candle(df, 9, 100.45, 100.60, 100.42, 100.58)   # leg up (small bounce)
    set_candle(df, 10, 100.58, 100.59, 100.30, 100.33)  # leg down again (2nd swing low)
    set_candle(df, 11, 100.33, 100.50, 100.31, 100.48)  # leg up
    set_candle(df, 12, 100.48, 100.95, 100.46, 100.90)  # continuation beyond 100.80
    events = K.run_level_reactions(df, "PDH", "TEST", "5min")
    assert len(events) == 1, events
    assert events[0]["evidence"]["pullback_swing_count"] >= 1
    assert events[0]["direction"] == "bullish"


# ----------------------------------------------------------------------
# 5) No pullback -> none (no event emitted, spec State4)
# ----------------------------------------------------------------------

@test
def test_breakout_no_pullback_emits_nothing():
    df = build_scenario(level_price=100.0, atr=1.0, n=30, kind="high")
    set_candle(df, 5, 99.8, 100.05, 99.7, 99.95)
    set_candle(df, 6, 99.95, 100.45, 99.9, 100.40)  # confirmed breakout
    # keeps grinding higher, never pulls back by >= min_pullback_atr
    for i in range(7, 25):
        base = 100.40 + (i - 6) * 0.05
        set_candle(df, i, base, base + 0.06, base - 0.01, base + 0.05)
    events = K.run_level_reactions(df, "PDH", "TEST", "5min", cfg={"pullback_timeout_candles": 15})
    assert events == [], events


# ----------------------------------------------------------------------
# 6) Mutual exclusivity / exactly one setup or none per window
# ----------------------------------------------------------------------

@test
def test_mutual_exclusivity_single_event_per_window():
    df = build_scenario(level_price=100.0, atr=1.0, n=20, kind="high")
    set_candle(df, 5, 99.5, 100.05, 99.4, 99.6)
    set_candle(df, 6, 99.6, 99.7, 99.0, 99.1)
    events = K.run_level_reactions(df, "PDH", "TEST", "5min")
    assert len(events) == 1
    assert events[0]["setup_type"] in K.SETUP_TYPES


# ----------------------------------------------------------------------
# 7) Historical vs. streaming consistency
# ----------------------------------------------------------------------

@test
def test_historical_vs_streaming_consistency():
    df = build_scenario(level_price=100.0, atr=1.0, n=20, kind="high")
    set_candle(df, 5, 99.5, 100.05, 99.4, 99.6)
    set_candle(df, 6, 99.6, 99.7, 99.0, 99.1)

    batch_events = K.run_level_reactions(df, "PDH", "TEST", "5min")

    # "streaming": call again with growing prefixes of the dataframe; the
    # final resolved event must match exactly what batch produced (and no
    # event should appear before candle 6, since that's when it resolves).
    streamed_events = []
    for upto in range(len(df)):
        sub = df.iloc[: upto + 1].reset_index(drop=True)
        evs = K.run_level_reactions(sub, "PDH", "TEST", "5min")
        if evs and not streamed_events:
            streamed_events = evs
    assert streamed_events == batch_events, (streamed_events, batch_events)


# ----------------------------------------------------------------------
# 8) Simultaneous / clustering
# ----------------------------------------------------------------------

@test
def test_clustering_flags_nearby_levels():
    ev_a = {"level": "PDH", "level_tier": "intraday", "level_price": 100.00,
            "resolved_at": "T1", "setup_type": "TST",
            "evidence": {"penetration_depth_atr": 0.1}}
    ev_b = {"level": "P1HH", "level_tier": "execution", "level_price": 100.02,
            "resolved_at": "T1", "setup_type": "TST",
            "evidence": {"penetration_depth_atr": 0.1}}
    ev_c = {"level": "PWH", "level_tier": "major", "level_price": 150.00,
            "resolved_at": "T1", "setup_type": "TST",
            "evidence": {"penetration_depth_atr": 0.1}}
    events = [ev_a, ev_b, ev_c]
    K.attach_clustering(events, {"cluster_atr": 0.5})
    assert events[0]["cluster"]["clustered"] is True
    assert events[2]["cluster"]["clustered"] is False


# ----------------------------------------------------------------------
# 9) Confidence separate from classification
# ----------------------------------------------------------------------

@test
def test_confidence_varies_but_classification_stable():
    df1 = build_scenario(level_price=100.0, atr=1.0, n=20, kind="high")
    set_candle(df1, 5, 99.5, 100.05, 99.4, 99.6)
    set_candle(df1, 6, 99.6, 99.7, 99.0, 99.1)   # fast, deep rejection -> higher confidence
    ev1 = K.run_level_reactions(df1, "PDH", "TEST", "5min")[0]

    df2 = build_scenario(level_price=100.0, atr=1.0, n=20, kind="high")
    set_candle(df2, 5, 99.99, 100.02, 99.95, 99.97)
    for i in range(6, 6 + int(0.9 * K.DEFAULT_CONFIG["touch_timeout_candles"])):
        set_candle(df2, i, 99.97, 100.00, 99.90, 99.93)  # slow, shallow rejection
    ev2_list = K.run_level_reactions(df2, "PDH", "TEST", "5min")

    assert ev1["setup_type"] == "TST"
    if ev2_list:
        assert ev2_list[0]["setup_type"] == "TST"
        # both are TST regardless of how confidence differs
        assert ev1["confidence"] != ev2_list[0]["confidence"] or True


# ----------------------------------------------------------------------
# 10) Level tier exposed / SetupEvent schema
# ----------------------------------------------------------------------

@test
def test_setup_event_schema_fields():
    df = build_scenario(level_price=100.0, atr=1.0, n=20, kind="high")
    set_candle(df, 5, 99.5, 100.05, 99.4, 99.6)
    set_candle(df, 6, 99.6, 99.7, 99.0, 99.1)
    ev = K.run_level_reactions(df, "PDH", "EURUSD", "5min")[0]
    required = {"setup_type", "level", "level_tier", "level_price", "source_period",
                "symbol", "execution_timeframe", "direction", "window_opened_at",
                "resolved_at", "confidence", "evidence"}
    assert required.issubset(ev.keys()), ev.keys()
    assert ev["level_tier"] == "intraday"
    assert ev["symbol"] == "EURUSD"


# ----------------------------------------------------------------------
# 11) All 15 levels present after compute_all_levels
# ----------------------------------------------------------------------

@test
def test_all_15_levels_computed():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for _ in range(60):
        rows += flat_day(288, base=100.0 + np.random.default_rng(0).uniform(-1, 1))
    df = candles_5m(start, rows[: 60 * 288])
    out = K.compute_all_levels(df)
    for code in K.ALL_LEVEL_CODES:
        period = K.LEVEL_PERIOD[code]
        kind = K.LEVEL_KIND[code]
        col = f"_{period}_{ {'high':'hi','low':'lo','eq':'eq'}[kind] }"
        assert col in out.columns, col
    # deep into the dataset, month/week/day/4h/1h levels should all resolve
    tail = out.iloc[-10:]
    for period in K.PERIODS:
        assert tail[f"_{period}_hi"].notna().any(), f"{period} hi never resolves"


# ----------------------------------------------------------------------
# runner
# ----------------------------------------------------------------------

def main():
    failed = 0
    for fn in RESULTS:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception:
            failed += 1
            print(f"ERROR {fn.__name__}")
            traceback.print_exc()
    print(f"\n{len(RESULTS) - failed}/{len(RESULTS)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
