# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.lmp
==============================
پیاده‌سازی بخش ۱ سند اصلاحی (Architectural Addendum): «Lightweight
Market Pulse» — راه‌حل حلقه‌ی وابستگی دوری بین بخش ۴.۵ و ۱۳ سند اصلی:

    نماد Dormant نمی‌تواند رویداد موتور بالادستی تولید کند چون موتورها
    روی آن اجرا نمی‌شوند؛ بدون رویداد بالادستی، نمی‌تواند ترفیع بگیرد
    تا موتورها رویش اجرا شوند.

LMP این حلقه را با یک لایه‌ی *بسیار ارزان* (فقط چند آمار غلتان ساده،
نه ۵ موتور سنگین) که روی *کل* دامنه (حتی نمادهای Dormant) اجرا می‌شود،
می‌شکند — طبق بخش ۱.۲.۱ سند اصلاحی، فقط از کندل کامل‌شده (نه تیک خام،
هرچند معماری آن را هم پشتیبانی می‌کند) استفاده می‌کند.

طبق تأکید صریح سند: این لایه هرگز جایگزین ۵ موتور نمی‌شود و هرگز
TradeSignal تولید نمی‌کند — فقط یک «احتمال اولیه‌ی ارزان» است که در
صورت درست بودن، بودجه‌ی محاسباتی برای بررسی واقعی توسط ۵ موتور را باز
می‌کند؛ اگر طی TTL سریع هیچ موتوری ساختار واقعی را تأیید نکرد، نماد
خودکار به Dormant برمی‌گردد (بخش ۱.۲.۳).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional

import numpy as np
import pandas as pd

from signal_engine.common.atr import compute_atr

LMPTriggerType = Literal["volume_anomaly", "range_expansion", "key_level_probe"]

DEFAULT_LMP_CONFIG = {
    "enabled": True,
    "volume_zscore_window": 20,
    "volume_zscore_threshold": 3.0,
    "atr_period": 14,
    "range_expansion_atr_multiple": 2.5,
    "key_level_proximity_pct": 0.0015,  # ±۰.۱۵٪
    # طبق بخش ۱.۲.۳ سند اصلاحی: TTL سریع اولیه — به دقیقه (نه بار)، چون
    # این پارامتر مستقل از تایم‌فریم اجرا تعریف شده و باید به تعداد کندل
    # متناظر با تایم‌فریم واقعی تبدیل شود (helper پایین).
    "fast_ttl_minutes": 10,
}


@dataclass
class LMPTrigger:
    trigger_type: LMPTriggerType
    symbol: str
    value: float
    threshold: float
    candle_index: int

    def to_dict(self) -> dict:
        return {
            "event_type": "watchlist_market_pulse_triggered",
            "trigger_type": self.trigger_type, "symbol": self.symbol,
            "value": round(self.value, 6), "threshold": self.threshold,
            "candle_index": self.candle_index,
        }


def minutes_to_bars(minutes: float, timeframe_minutes: float) -> int:
    """تبدیل TTL بر حسب دقیقه به تعداد کندل تایم‌فریم اجرا — طبق قرارداد
    کل این پروژه (بازپخش قطعی بر اساس ایندکس کندل، نه wall-clock).
    حداقل ۱ کندل (هرگز صفر) تا TTL معنادار بماند.
    """
    if timeframe_minutes <= 0:
        return max(1, int(round(minutes)))
    return max(1, int(round(minutes / timeframe_minutes)))


def _volume_zscore(volume: pd.Series, window: int) -> pd.Series:
    mean = volume.rolling(window, min_periods=max(3, window // 3)).mean()
    std = volume.rolling(window, min_periods=max(3, window // 3)).std(ddof=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (volume - mean) / std.replace(0, np.nan)
    return z


def detect_pulse(
    df: pd.DataFrame,
    symbol: str,
    key_level_prices: Optional[List[float]] = None,
    config: Optional[dict] = None,
) -> Optional[LMPTrigger]:
    """طبق بخش ۱.۲.۲ سند اصلاحی — فقط روی *آخرین کندل کامل‌شده* (بدون
    look-ahead) سه شرط را چک می‌کند و در صورت برقراری هرکدام (اولویت با
    ترتیب لیست: حجم غیرعادی، انبساط رنج، سپس نزدیکی به سطح کلیدی)، یک
    LMPTrigger برمی‌گرداند؛ وگرنه None.

    key_level_prices: طبق تأکید سند اصلاحی (بخش ۱، پیرو تأکید سند اصلی
    KLSDE)، این‌ها باید از خروجی مستند KLSDE (compute_key_levels) گرفته
    شوند، نه این‌که این ماژول خودش سطح جدید محاسبه کند.
    """
    cfg = {**DEFAULT_LMP_CONFIG, **(config or {})}
    if not cfg["enabled"] or df is None or df.empty:
        return None

    d = df.reset_index(drop=True)
    idx = len(d) - 1  # آخرین کندل کامل‌شده (طبق قرارداد پروژه)

    # --- شرط ۱: ناهنجاری حجم ---
    if "volume" in d.columns:
        zscores = _volume_zscore(d["volume"], cfg["volume_zscore_window"])
        z = zscores.iloc[idx]
        if pd.notna(z) and z > cfg["volume_zscore_threshold"]:
            return LMPTrigger("volume_anomaly", symbol, float(z), cfg["volume_zscore_threshold"], idx)

    # --- شرط ۲: انبساط رنج نسبت به ATR ---
    atr_df = compute_atr(d, period=cfg["atr_period"])
    atr_val = atr_df["atr"].iloc[idx]
    if pd.notna(atr_val) and atr_val > 0:
        candle_range = float(d["high"].iloc[idx] - d["low"].iloc[idx])
        ratio = candle_range / atr_val
        if ratio > cfg["range_expansion_atr_multiple"]:
            return LMPTrigger("range_expansion", symbol, ratio, cfg["range_expansion_atr_multiple"], idx)

    # --- شرط ۳: پروب نزدیکی به سطح کلیدی (PDH/PDL/PWH/PWL/...) ---
    if key_level_prices:
        close_price = float(d["close"].iloc[idx])
        for level in key_level_prices:
            if level is None or level <= 0:
                continue
            distance_pct = abs(close_price - level) / level
            if distance_pct <= cfg["key_level_proximity_pct"]:
                return LMPTrigger("key_level_probe", symbol, distance_pct, cfg["key_level_proximity_pct"], idx)

    return None


def detect_pulses_for_universe(
    snapshots: Dict[str, pd.DataFrame],
    key_levels_by_symbol: Optional[Dict[str, List[float]]] = None,
    config: Optional[dict] = None,
) -> List[LMPTrigger]:
    """طبق بخش ۱.۲.۱ سند اصلاحی: این تابع باید بتواند روی *کل* دامنه
    (شامل نمادهای Dormant) اجرا شود — چون فقط آمار غلتان ارزان محاسبه
    می‌کند (نه ۵ موتور سنگین)، این مقیاس‌پذیری واقعاً ارزان است.
    """
    triggers: List[LMPTrigger] = []
    kl_map = key_levels_by_symbol or {}
    for symbol, df in snapshots.items():
        trig = detect_pulse(df, symbol, kl_map.get(symbol), config)
        if trig is not None:
            triggers.append(trig)
    return triggers
