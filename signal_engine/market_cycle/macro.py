# -*- coding: utf-8 -*-
"""
signal_engine.market_cycle.macro
===================================
پیاده‌سازی بخش ۴ سند «Market Cycle Engine»: چهار فاز کلان Wyckoff-style
(Accumulation/Markup/Distribution/Markdown) — بر اساس روند حجم، رابطه‌ی
قیمت با EMA50/EMA200، RSI/MACD، و رنج بودن قیمت (با فیلتر صریح شکست
کاذب طبق سند، بخش ۴.۱/۴.۳).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import numpy as np
import pandas as pd

from signal_engine.common.atr import compute_atr
from signal_engine.swing_structure.swings import detect_swings

MacroPhase = Literal["accumulation", "markup", "distribution", "markdown"]

DEFAULT_MACRO_CONFIG = {
    "ema_fast": 50, "ema_slow": 200, "rsi_period": 14,
    "macd_fast": 12, "macd_slow": 26, "macd_signal": 9,
    "atr_period": 14, "volume_smoothing_period": 20,
    "markup_volume_slope_threshold": 0.02,
    "accumulation_volume_slope_threshold": 0.005,
    "shallow_pullback_max_pct": 0.38,
    "false_breakout_revert_bars": 3,
    "min_phase_dwell_bars": 20,
}


@dataclass
class MacroPhaseEvent:
    id: str
    timeframe: str
    symbol: str
    phase: MacroPhase
    start_index: int
    end_index: Optional[int]
    confidence: float
    evidence: dict = field(default_factory=dict)
    status: Literal["active", "closed"] = "active"
    non_canonical_transition: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id, "timeframe": self.timeframe, "symbol": self.symbol, "phase": self.phase,
            "start_index": self.start_index, "end_index": self.end_index, "confidence": self.confidence,
            "evidence": self.evidence, "status": self.status,
            "non_canonical_transition": self.non_canonical_transition,
        }


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series, fast: int, slow: int, signal: int):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line


def _volume_slope(volume: pd.Series, idx: int, smoothing: int, lookback: int = 20) -> float:
    smoothed = volume.rolling(smoothing, min_periods=max(3, smoothing // 3)).mean()
    window = smoothed.iloc[max(0, idx - lookback): idx + 1].dropna()
    if len(window) < 3:
        return 0.0
    y = window.to_numpy()
    x = np.arange(len(y), dtype=float)
    slope = np.polyfit(x, y, 1)[0]
    return float(slope / max(abs(y.mean()), 1e-9))


def _range_bounds(swings, up_to_index: int, lookback_swings: int = 6):
    relevant = [s for s in swings if s.candle_index <= up_to_index][-lookback_swings:]
    if len(relevant) < 2:
        return None, None
    highs = [s.price for s in relevant if s.type == "swing_high"]
    lows = [s.price for s in relevant if s.type == "swing_low"]
    if not highs or not lows:
        return None, None
    return max(highs), min(lows)


def classify_macro_cycle(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None,
) -> List[MacroPhaseEvent]:
    """پیمایش کندل‌به‌کندل و تشخیص فاز فعلی + گذارها — طبق درخت منطقی
    بخش ۴ سند. برای سادگی و صحت، این پیاده‌سازی «فاز غالب» را در هر لحظه
    از روی رأی‌گیریِ وزن‌دارِ سیگنال‌های evidence مشخص می‌کند (نه یک
    if/elif ساده)، دقیقاً طبق تأکید سند بر «ترکیبی از سیگنال‌ها، نه یک
    شرط تنها».
    """
    cfg = {**DEFAULT_MACRO_CONFIG, **(config or {})}
    d = compute_atr(df.reset_index(drop=True), period=cfg["atr_period"])
    close = d["close"].astype(float)

    ema_fast = close.ewm(span=cfg["ema_fast"], adjust=False).mean()
    ema_slow = close.ewm(span=cfg["ema_slow"], adjust=False).mean()
    rsi = _rsi(close, cfg["rsi_period"])
    macd_line, macd_signal = _macd(close, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"])
    has_volume = "volume" in d.columns

    swings = detect_swings(d, timeframe=timeframe, symbol=symbol)

    n = len(d)
    min_bars = max(cfg["ema_slow"], cfg["rsi_period"]) + 5
    if n < min_bars:
        return []

    events: List[MacroPhaseEvent] = []
    current_phase: Optional[MacroPhase] = None
    current_start = min_bars
    last_transition_index = min_bars
    false_breakout_counts = {"accumulation": 0, "distribution": 0}
    event_counter = 0

    canonical_next = {"accumulation": "markup", "markup": "distribution", "distribution": "markdown", "markdown": "accumulation"}

    for i in range(min_bars, n):
        above_both = close.iloc[i] > ema_fast.iloc[i] and close.iloc[i] > ema_slow.iloc[i] and ema_fast.iloc[i] > ema_slow.iloc[i]
        below_both = close.iloc[i] < ema_fast.iloc[i] and close.iloc[i] < ema_slow.iloc[i] and ema_fast.iloc[i] < ema_slow.iloc[i]
        vol_slope = _volume_slope(d["volume"], i, cfg["volume_smoothing_period"]) if has_volume else 0.0
        range_hi, range_lo = _range_bounds(swings, i)

        scores = {"accumulation": 0.0, "markup": 0.0, "distribution": 0.0, "markdown": 0.0}

        if above_both:
            scores["markup"] += 0.4
        if below_both:
            scores["markdown"] += 0.4
        if vol_slope >= cfg["markup_volume_slope_threshold"] and above_both:
            scores["markup"] += 0.3
        if vol_slope >= cfg["markup_volume_slope_threshold"] and below_both:
            scores["markdown"] += 0.3
        if cfg["accumulation_volume_slope_threshold"] <= vol_slope < cfg["markup_volume_slope_threshold"]:
            scores["accumulation"] += 0.2
            scores["distribution"] += 0.2

        if range_hi is not None and range_lo is not None and range_hi > range_lo:
            in_range = range_lo <= close.iloc[i] <= range_hi
            near_bottom = (close.iloc[i] - range_lo) / (range_hi - range_lo) < 0.4
            near_top = (close.iloc[i] - range_lo) / (range_hi - range_lo) > 0.6
            if in_range and near_bottom and current_phase in (None, "markdown", "accumulation"):
                scores["accumulation"] += 0.3
            if in_range and near_top and current_phase in ("markup", "distribution"):
                scores["distribution"] += 0.3
            # فیلتر شکست کاذب: عبور گذرا از رنج که به‌سرعت برگردد، شواهد فاز
            # فعلی را تقویت می‌کند نه پایان آن را (طبق سند، بخش ۴.۱/۴.۳)
            if close.iloc[i] > range_hi:
                revert = i + cfg["false_breakout_revert_bars"] < n and close.iloc[i + cfg["false_breakout_revert_bars"]] < range_hi
                if revert and current_phase == "accumulation":
                    false_breakout_counts["accumulation"] += 1
                    scores["accumulation"] += 0.2
            if close.iloc[i] < range_lo:
                revert = i + cfg["false_breakout_revert_bars"] < n and close.iloc[i + cfg["false_breakout_revert_bars"]] > range_lo
                if revert and current_phase == "distribution":
                    false_breakout_counts["distribution"] += 1
                    scores["distribution"] += 0.2

        if not pd.isna(rsi.iloc[i]):
            if rsi.iloc[i] > 50:
                scores["markup"] += 0.1
            elif rsi.iloc[i] < 50:
                scores["markdown"] += 0.1

        winner = max(scores, key=scores.get)
        if scores[winner] <= 0:
            continue

        if current_phase is None:
            current_phase = winner
            current_start = i
            last_transition_index = i
            continue

        if winner == current_phase:
            continue

        # کاندید گذار به فاز جدید — حداقل dwell time را رعایت کن
        if (i - last_transition_index) < cfg["min_phase_dwell_bars"]:
            continue

        is_canonical = canonical_next[current_phase] == winner
        event_counter += 1
        events.append(MacroPhaseEvent(
            id=f"macro_{timeframe}_{event_counter:05d}", timeframe=timeframe, symbol=symbol,
            phase=current_phase, start_index=current_start, end_index=i, status="closed",
            confidence=round(min(1.0, 0.4 + scores.get(current_phase, 0.0)), 3),
            evidence={
                "false_breakout_count": false_breakout_counts.get(current_phase, 0),
                "range_high": range_hi, "range_low": range_lo,
            },
            non_canonical_transition=not is_canonical,
        ))
        current_phase = winner
        current_start = i
        last_transition_index = i

    if current_phase is not None:
        event_counter += 1
        events.append(MacroPhaseEvent(
            id=f"macro_{timeframe}_{event_counter:05d}", timeframe=timeframe, symbol=symbol,
            phase=current_phase, start_index=current_start, end_index=None, status="active",
            confidence=round(min(1.0, 0.4 + 0.3), 3),
            evidence={"false_breakout_count": false_breakout_counts.get(current_phase, 0)},
        ))

    return events
