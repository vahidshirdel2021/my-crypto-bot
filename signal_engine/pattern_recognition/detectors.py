# -*- coding: utf-8 -*-
"""
signal_engine.pattern_recognition.detectors
==============================================
پیاده‌سازی خط‌به‌خط سند «Pattern Recognition Engine». بر خلاف CPDE (که
مستقیماً هندسه‌ی کندل را می‌خواند)، این موتور عمدتاً بر پایه‌ی جریان
سوئینگ‌های تأییدشده (signal_engine.swing_structure) و رگرسیون خطی روی
سوئینگ‌ها برای برازش خطوط روند کار می‌کند — دقیقاً طبق تعاریف هندسی سند.

طبق یادداشت صریح سند و سند CPDE: تشخیص‌گر هارامی اینجا تکرار نمی‌شود؛
از signal_engine.candlestick.detectors.detect_harami استفاده می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import numpy as np
import pandas as pd

from signal_engine.common.atr import compute_atr
from signal_engine.candlestick.detectors import detect_harami, CandlestickPatternEvent
from signal_engine.swing_structure.swings import detect_swings, SwingPoint
from signal_engine.swing_structure.structure import trend_state_from_swings

Direction = Literal["bullish", "bearish"]
PatternType = Literal["continuation", "reversal"]

DEFAULT_CONFIG = {
    "flag_pennant": {
        "flagpole_min_atr_multiple": 3.0, "flagpole_max_bars": 10,
        "consolidation_min_bars": 5, "consolidation_max_bars": 20, "channel_r2_min": 0.6,
        "parallel_slope_tolerance": 0.4,  # نسبت اختلاف شیب برای «موازی» تلقی‌شدن
    },
    "cup_and_handle": {
        "rim_tolerance_pct": 0.05, "handle_max_retrace_pct": 0.5,
        "min_bars_each_side_of_low": 7, "handle_max_duration_ratio": 0.33,
    },
    "ascending_triangle": {
        "level_tolerance_atr_multiple": 0.75, "min_touches": 2, "r2_min": 0.5,
    },
    "three_valleys_peaks": {
        "similarity_tolerance_pct": 0.5, "target_multiplier": 0.48,
    },
}


@dataclass
class PatternEvent:
    pattern_name: str
    direction: Direction
    type: PatternType
    timeframe: str
    symbol: str
    start_index: int
    end_index: int
    confidence: float
    key_levels: dict = field(default_factory=dict)
    confirmation_status: Literal["confirmed", "unconfirmed"] = "unconfirmed"
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "pattern_name": self.pattern_name, "direction": self.direction, "type": self.type,
            "timeframe": self.timeframe, "symbol": self.symbol,
            "start_index": self.start_index, "end_index": self.end_index,
            "confidence": self.confidence, "key_levels": self.key_levels,
            "confirmation_status": self.confirmation_status, "notes": self.notes,
        }


def _linreg(y: np.ndarray) -> tuple:
    """رگرسیون خطی ساده روی y نسبت به x=0..n-1. خروجی (slope, intercept, r2)."""
    n = len(y)
    if n < 2:
        return 0.0, float(y[0]) if n else 0.0, 0.0
    x = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    y_hat = slope * x + intercept
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else (1.0 if ss_res < 1e-9 else 0.0)
    return float(slope), float(intercept), float(r2)


# ---------------------------------------------------------------------------
# هارامی (تکرار نمی‌شود — از CPDE استفاده می‌کند)
# ---------------------------------------------------------------------------

def detect_harami_via_candlestick_engine(
    df: pd.DataFrame, timeframe: str, symbol: str = ""
) -> List[CandlestickPatternEvent]:
    """طبق سند: PRE برای هارامی دوباره پیاده‌سازی نمی‌کند — منبع حقیقت
    signal_engine.candlestick.detectors.detect_harami است.
    """
    return detect_harami(df, timeframe, symbol)


# ---------------------------------------------------------------------------
# پرچم مستطیلی / پرچم سه‌گوش (Flag / Pennant)
# ---------------------------------------------------------------------------

def detect_flag_pennant(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None
) -> List[PatternEvent]:
    cfg = {**DEFAULT_CONFIG["flag_pennant"], **((config or {}).get("flag_pennant", {}))}
    d = compute_atr(df.reset_index(drop=True), period=14)
    events: List[PatternEvent] = []
    n = len(d)

    for pole_start in range(0, n - cfg["consolidation_min_bars"] - 2):
        atr_val = d["atr"].iloc[pole_start]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        for pole_len in range(3, cfg["flagpole_max_bars"] + 1):
            pole_end = pole_start + pole_len
            if pole_end >= n:
                break
            move = d["close"].iloc[pole_end] - d["close"].iloc[pole_start]
            if abs(move) < cfg["flagpole_min_atr_multiple"] * atr_val:
                continue
            direction: Direction = "bullish" if move > 0 else "bearish"

            for cons_len in range(cfg["consolidation_min_bars"], cfg["consolidation_max_bars"] + 1):
                cons_end = pole_end + cons_len
                if cons_end >= n:
                    break
                cons = d.iloc[pole_end:cons_end]
                if len(cons) < cfg["consolidation_min_bars"]:
                    continue
                hi_slope, _, hi_r2 = _linreg(cons["high"].to_numpy())
                lo_slope, _, lo_r2 = _linreg(cons["low"].to_numpy())
                if hi_r2 < cfg["channel_r2_min"] or lo_r2 < cfg["channel_r2_min"]:
                    continue

                slope_diff = abs(hi_slope - lo_slope)
                slope_scale = max(abs(hi_slope), abs(lo_slope), 1e-9)
                is_parallel = (slope_diff / slope_scale) <= cfg["parallel_slope_tolerance"]
                is_converging = (hi_slope < 0 and lo_slope > 0) if direction == "bullish" else (hi_slope > 0 and lo_slope < 0)
                # طبق سند: پرچم = موازی، پرچم سه‌گوش = همگرا
                if direction == "bullish":
                    consolidation_ok = (hi_slope <= 0 and lo_slope <= 0) if is_parallel else is_converging
                else:
                    consolidation_ok = (hi_slope >= 0 and lo_slope >= 0) if is_parallel else is_converging
                if not consolidation_ok:
                    continue

                shape = "pennant" if not is_parallel and is_converging else "flag"
                confidence = round(min(1.0, 0.5 + 0.25 * min(hi_r2, lo_r2) + 0.15 * min(abs(move) / (cfg["flagpole_min_atr_multiple"] * atr_val), 2.0) / 2.0), 3)

                flagpole_height = abs(move)
                breakout_price = float(cons["high" if direction == "bullish" else "low"].iloc[-1])
                target = breakout_price + flagpole_height if direction == "bullish" else breakout_price - flagpole_height

                events.append(PatternEvent(
                    pattern_name=f"{shape}_pennant" if shape == "pennant" else "flag",
                    direction=direction, type="continuation", timeframe=timeframe, symbol=symbol,
                    start_index=pole_start, end_index=cons_end, confidence=confidence,
                    key_levels={"flagpole_height": flagpole_height, "breakout_level": breakout_price, "measured_move_target": target},
                    confirmation_status="unconfirmed",
                    notes=f"flagpole {pole_len} bars, consolidation {cons_len} bars, shape={shape}",
                ))
    return events


# ---------------------------------------------------------------------------
# مثلث صعودی / نزولی
# ---------------------------------------------------------------------------

def _detect_triangle(
    df: pd.DataFrame, timeframe: str, symbol: str, cfg: dict, direction: Direction
) -> List[PatternEvent]:
    d = compute_atr(df.reset_index(drop=True), period=14)
    events: List[PatternEvent] = []
    swings = detect_swings(d, timeframe=timeframe, symbol=symbol)
    highs = sorted([s for s in swings if s.type == "swing_high"], key=lambda s: s.candle_index)
    lows = sorted([s for s in swings if s.type == "swing_low"], key=lambda s: s.candle_index)
    if len(highs) < cfg["min_touches"] or len(lows) < cfg["min_touches"]:
        return events

    window_size = min(len(highs), len(lows), 6)
    for i in range(len(highs) - window_size + 1):
        h_window = highs[i:i + window_size]
        l_candidates = [s for s in lows if h_window[0].candle_index <= s.candle_index <= h_window[-1].candle_index]
        if len(l_candidates) < cfg["min_touches"]:
            continue
        atr_val = d["atr"].iloc[h_window[-1].candle_index]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        h_prices = np.array([s.price for s in h_window])
        l_prices = np.array([s.price for s in l_candidates])
        h_slope, _, h_r2 = _linreg(h_prices)
        l_slope, _, l_r2 = _linreg(l_prices)

        if direction == "bullish":
            # مثلث صعودی: مقاومت افقی (شیب هایز ~۰) + حمایت صعودی
            flat_ok = abs(h_slope) <= cfg["level_tolerance_atr_multiple"] * atr_val
            rising_ok = l_slope > 0 and l_r2 >= cfg["r2_min"]
            level = float(np.mean(h_prices))
        else:
            flat_ok = abs(l_slope) <= cfg["level_tolerance_atr_multiple"] * atr_val
            rising_ok = h_slope < 0 and h_r2 >= cfg["r2_min"]
            level = float(np.mean(l_prices))

        if not (flat_ok and rising_ok):
            continue

        confidence = round(min(1.0, 0.5 + 0.3 * (l_r2 if direction == "bullish" else h_r2) + 0.1 * min(len(h_window), len(l_candidates)) / 6.0), 3)
        pattern_name = "ascending_triangle" if direction == "bullish" else "descending_triangle"
        start_idx = min(h_window[0].candle_index, l_candidates[0].candle_index)
        end_idx = max(h_window[-1].candle_index, l_candidates[-1].candle_index)
        height = abs(h_prices.max() - l_prices.min())
        target = level + height if direction == "bullish" else level - height

        events.append(PatternEvent(
            pattern_name=pattern_name, direction=direction, type="continuation",
            timeframe=timeframe, symbol=symbol, start_index=start_idx, end_index=end_idx,
            confidence=confidence,
            key_levels={"horizontal_level": level, "triangle_height": height, "measured_move_target": target},
            confirmation_status="unconfirmed",
            notes=f"{len(h_window)} highs / {len(l_candidates)} lows used",
        ))
    return events


def detect_ascending_triangle(df, timeframe, symbol="", config=None) -> List[PatternEvent]:
    cfg = {**DEFAULT_CONFIG["ascending_triangle"], **((config or {}).get("ascending_triangle", {}))}
    return _detect_triangle(df, timeframe, symbol, cfg, "bullish")


def detect_descending_triangle(df, timeframe, symbol="", config=None) -> List[PatternEvent]:
    cfg = {**DEFAULT_CONFIG["ascending_triangle"], **((config or {}).get("ascending_triangle", {}))}
    return _detect_triangle(df, timeframe, symbol, cfg, "bearish")


# ---------------------------------------------------------------------------
# فنجان و دستگیره (Cup and Handle) + آینه‌ی نزولی
# ---------------------------------------------------------------------------

def _detect_cup_and_handle(df, timeframe, symbol, cfg, direction: Direction) -> List[PatternEvent]:
    d = df.reset_index(drop=True)
    events: List[PatternEvent] = []
    swings = detect_swings(d, timeframe=timeframe, symbol=symbol)
    rim_type = "swing_high" if direction == "bullish" else "swing_low"
    extreme_type = "swing_low" if direction == "bullish" else "swing_high"
    rims = sorted([s for s in swings if s.type == rim_type], key=lambda s: s.candle_index)

    for i in range(len(rims) - 1):
        left_rim, right_rim = rims[i], rims[i + 1]
        if abs(left_rim.price - right_rim.price) / max(abs(left_rim.price), 1e-9) > cfg["rim_tolerance_pct"]:
            continue
        between = d.iloc[left_rim.candle_index:right_rim.candle_index + 1]
        if between.empty:
            continue
        extreme_col = "low" if direction == "bullish" else "high"
        extreme_idx_local = between[extreme_col].idxmin() if direction == "bullish" else between[extreme_col].idxmax()
        left_span = extreme_idx_local - left_rim.candle_index
        right_span = right_rim.candle_index - extreme_idx_local
        if left_span < cfg["min_bars_each_side_of_low"] or right_span < cfg["min_bars_each_side_of_low"]:
            continue  # رد V-bottom تیز — باید U شکل باشد

        cup_duration = right_rim.candle_index - left_rim.candle_index
        cup_depth = abs(left_rim.price - float(between[extreme_col].loc[extreme_idx_local]))

        # دسته (Handle): بعد از rim راست
        handle_end = min(len(d) - 1, right_rim.candle_index + max(1, int(cup_duration * cfg["handle_max_duration_ratio"])))
        handle = d.iloc[right_rim.candle_index:handle_end + 1]
        if len(handle) < 2:
            continue
        handle_extreme = handle[extreme_col].min() if direction == "bullish" else handle[extreme_col].max()
        handle_retrace = abs(right_rim.price - handle_extreme)
        if cup_depth <= 0 or handle_retrace / cup_depth > cfg["handle_max_retrace_pct"]:
            continue

        confidence = round(min(1.0, 0.5 + 0.2 * (1 - handle_retrace / max(cup_depth, 1e-9)) + 0.1), 3)
        pattern_name = "cup_and_handle" if direction == "bullish" else "inverted_cup_and_handle"
        target = right_rim.price + cup_depth if direction == "bullish" else right_rim.price - cup_depth

        events.append(PatternEvent(
            pattern_name=pattern_name, direction=direction, type="continuation",
            timeframe=timeframe, symbol=symbol, start_index=left_rim.candle_index, end_index=handle_end,
            confidence=confidence,
            key_levels={"rim_level": right_rim.price, "cup_depth": cup_depth, "measured_move_target": target},
            confirmation_status="unconfirmed",
            notes=f"cup_duration={cup_duration} bars, handle_retrace_pct={round(handle_retrace/max(cup_depth,1e-9),2)}",
        ))
    return events


def detect_cup_and_handle(df, timeframe, symbol="", config=None) -> List[PatternEvent]:
    cfg = {**DEFAULT_CONFIG["cup_and_handle"], **((config or {}).get("cup_and_handle", {}))}
    return _detect_cup_and_handle(df, timeframe, symbol, cfg, "bullish")


def detect_inverted_cup_and_handle(df, timeframe, symbol="", config=None) -> List[PatternEvent]:
    cfg = {**DEFAULT_CONFIG["cup_and_handle"], **((config or {}).get("cup_and_handle", {}))}
    return _detect_cup_and_handle(df, timeframe, symbol, cfg, "bearish")


# ---------------------------------------------------------------------------
# سه دره‌ی رو به افزایش / سه قله‌ی رو به کاهش
# ---------------------------------------------------------------------------

def _detect_three_valleys_peaks(df, timeframe, symbol, cfg, direction: Direction) -> List[PatternEvent]:
    events: List[PatternEvent] = []
    swings = detect_swings(df.reset_index(drop=True), timeframe=timeframe, symbol=symbol)
    extreme_type = "swing_low" if direction == "bullish" else "swing_high"
    peak_type = "swing_high" if direction == "bullish" else "swing_low"
    extremes = sorted([s for s in swings if s.type == extreme_type], key=lambda s: s.candle_index)
    peaks = sorted([s for s in swings if s.type == peak_type], key=lambda s: s.candle_index)

    for i in range(len(extremes) - 2):
        v1, v2, v3 = extremes[i], extremes[i + 1], extremes[i + 2]
        monotonic_ok = (v1.price < v2.price < v3.price) if direction == "bullish" else (v1.price > v2.price > v3.price)
        if not monotonic_ok:
            continue
        between_peaks = [p for p in peaks if v1.candle_index < p.candle_index < v3.candle_index]
        if len(between_peaks) < 2:
            continue
        p1, p2 = between_peaks[0], between_peaks[-1]
        breakout_level = max(p1.price, p2.price) if direction == "bullish" else min(p1.price, p2.price)

        confidence = round(min(1.0, 0.5 + 0.25 + 0.1), 3)  # ساده‌سازی؛ می‌تواند بعداً با similarity واقعی تقویت شود
        pattern_name = "three_rising_valleys" if direction == "bullish" else "three_declining_peaks"
        extreme_range = abs(breakout_level - (v1.price if direction == "bullish" else v3.price))
        target = breakout_level + extreme_range * cfg["target_multiplier"] if direction == "bullish" \
            else breakout_level - extreme_range * cfg["target_multiplier"]

        events.append(PatternEvent(
            pattern_name=pattern_name, direction=direction, type="reversal",
            timeframe=timeframe, symbol=symbol, start_index=v1.candle_index, end_index=v3.candle_index,
            confidence=confidence,
            key_levels={"breakout_level": breakout_level, "measured_move_target": target},
            confirmation_status="unconfirmed",
            notes=f"v1={v1.price:.4f} v2={v2.price:.4f} v3={v3.price:.4f}",
        ))
    return events


def detect_three_rising_valleys(df, timeframe, symbol="", config=None) -> List[PatternEvent]:
    cfg = {**DEFAULT_CONFIG["three_valleys_peaks"], **((config or {}).get("three_valleys_peaks", {}))}
    return _detect_three_valleys_peaks(df, timeframe, symbol, cfg, "bullish")


def detect_three_declining_peaks(df, timeframe, symbol="", config=None) -> List[PatternEvent]:
    cfg = {**DEFAULT_CONFIG["three_valleys_peaks"], **((config or {}).get("three_valleys_peaks", {}))}
    return _detect_three_valleys_peaks(df, timeframe, symbol, cfg, "bearish")


def detect_all(df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None) -> List[PatternEvent]:
    events: List[PatternEvent] = []
    events += detect_flag_pennant(df, timeframe, symbol, config)
    events += detect_ascending_triangle(df, timeframe, symbol, config)
    events += detect_descending_triangle(df, timeframe, symbol, config)
    events += detect_cup_and_handle(df, timeframe, symbol, config)
    events += detect_inverted_cup_and_handle(df, timeframe, symbol, config)
    events += detect_three_rising_valleys(df, timeframe, symbol, config)
    events += detect_three_declining_peaks(df, timeframe, symbol, config)
    return events
