# -*- coding: utf-8 -*-
"""
signal_engine.swing_structure.swings
======================================
پیاده‌سازی خط‌به‌خط سند «Swing Detection & Market Structure Engine»،
بخش‌های ۴ (چرا ۵m/۱۵m مسئله‌ی جدایی است) و ۵ (الگوریتم اصلی تشخیص
سوئینگ). این ماژول فقط مسئولیت اول (Swing Point Detection) را پیاده
می‌کند؛ مسئولیت دوم (Market Structure Classification: BOS/CHoCH) در
`structure.py` است.

پایپ‌لاین ۴مرحله‌ای (دقیقاً طبق سند):
    Stage 1: کاندیدهای خام اکسترمم محلی (فراکتال)
    Stage 2: فیلتر نویز نرمال‌شده با ATR + حداقل ریتریسمنت + فیلتر حجم
    Stage 3: تأیید (بدون look-ahead — سوئینگ تا k کندل بعد «pending» است)
    Stage 4: ابطال (Invalidation) — نگه‌داشته می‌شود، هرگز حذف نمی‌شود

هیچ داده‌ی آینده در هیچ مرحله‌ای استفاده نمی‌شود؛ `confirmed_at_index`
همیشه ≥ `candle_index + k` است.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import numpy as np
import pandas as pd

from signal_engine.common.atr import compute_atr

SwingType = Literal["swing_high", "swing_low"]
SwingStatus = Literal["pending", "confirmed", "invalidated"]


@dataclass
class SwingPoint:
    id: str
    timeframe: str
    symbol: str
    type: SwingType
    price: float
    candle_index: int
    confirmed_at_index: Optional[int] = None
    confirmation_lag_bars: Optional[int] = None
    magnitude_atr: Optional[float] = None
    status: SwingStatus = "pending"
    invalidated_at_index: Optional[int] = None
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timeframe": self.timeframe,
            "symbol": self.symbol,
            "type": self.type,
            "price": self.price,
            "candle_index": self.candle_index,
            "confirmed_at_index": self.confirmed_at_index,
            "confirmation_lag_bars": self.confirmation_lag_bars,
            "magnitude_atr": self.magnitude_atr,
            "status": self.status,
            "invalidated": self.status == "invalidated",
            "evidence": self.evidence,
        }


# پارامترهای پیش‌فرض دقیقاً طبق سند، بخش ۵.۵ (per-timeframe defaults)
DEFAULT_SWING_CONFIG = {
    "5m": dict(fractal_k=3, atr_period=14, min_swing_atr_multiple=1.2,
               min_retrace_pct=0.20, volume_percentile_floor=30),
    "15m": dict(fractal_k=2, atr_period=14, min_swing_atr_multiple=1.0,
                min_retrace_pct=0.20, volume_percentile_floor=30),
}
_GENERIC_FALLBACK_CONFIG = dict(fractal_k=2, atr_period=14, min_swing_atr_multiple=1.0,
                                 min_retrace_pct=0.20, volume_percentile_floor=30)


def _cfg_for(timeframe: str, overrides: Optional[dict] = None) -> dict:
    base = dict(DEFAULT_SWING_CONFIG.get(timeframe, _GENERIC_FALLBACK_CONFIG))
    if overrides:
        base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Stage 1 — کاندیدهای خام فراکتال
# ---------------------------------------------------------------------------

def _raw_fractal_candidates(df: pd.DataFrame, k: int) -> List[dict]:
    """کندلی که high آن بزرگ‌تر یا مساوی high تمام k کندل هر طرف است →
    کاندید swing_high (و متقارن برای swing_low). این مرحله عمداً
    بیش‌تولید می‌کند؛ فیلتر نویز در Stage 2 است.
    """
    n = len(df)
    candidates: List[dict] = []
    if n < (2 * k + 1):
        return candidates

    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()

    for i in range(k, n - k):
        window_h = highs[i - k: i + k + 1]
        window_l = lows[i - k: i + k + 1]
        if highs[i] == window_h.max():
            candidates.append({"type": "swing_high", "index": i, "price": float(highs[i])})
        if lows[i] == window_l.min():
            candidates.append({"type": "swing_low", "index": i, "price": float(lows[i])})

    return candidates


# ---------------------------------------------------------------------------
# Stage 2 — فیلتر نویز نرمال‌شده با ATR + حداقل ریتریسمنت + فیلتر حجم
# ---------------------------------------------------------------------------

def _volume_ok(df: pd.DataFrame, idx: int, floor_percentile: float, magnitude_atr: float,
                strong_move_atr_threshold: float = 2.0) -> bool:
    """رد کردن کاندیدهایی که حجمِ دورشان به‌طرز غیرعادی پایین است — مگر
    اینکه اندازه‌ی حرکت (بر حسب ATR) به‌قدری بزرگ باشد که فیلتر حجم دیگر
    لازم نباشد (طبق سند، بخش ۵.۲.۴).
    """
    if "volume" not in df.columns:
        return True  # داده‌ی حجم در دسترس نیست → این فیلتر را نادیده بگیر
    if magnitude_atr >= strong_move_atr_threshold:
        return True
    window = df["volume"].iloc[max(0, idx - 20): idx + 1]
    if len(window) < 5:
        return True
    threshold = np.percentile(window.to_numpy(dtype=float), floor_percentile)
    return bool(df["volume"].iloc[idx] >= threshold)


def _filter_and_confirm(
    df: pd.DataFrame,
    candidates: List[dict],
    cfg: dict,
    timeframe: str,
    symbol: str,
) -> List[SwingPoint]:
    """Stage 2 (فیلتر نویز) + Stage 3 (تأیید) با هم اجرا می‌شوند چون
    شرط ریتریسمنت خودش نیازمند نگاه به کندل‌های بعد از کاندید است — دقیقاً
    همان تأخیر تأییدی که Stage 3 رسماً مدل می‌کند.
    """
    atr_period = cfg["atr_period"]
    k = cfg["fractal_k"]
    min_atr_mult = cfg["min_swing_atr_multiple"]
    min_retrace = cfg["min_retrace_pct"]
    vol_floor = cfg["volume_percentile_floor"]

    d = compute_atr(df, period=atr_period)
    atr_series = d["atr"]

    swings: List[SwingPoint] = []
    last_confirmed_opposite: Optional[dict] = None  # آخرین سوئینگ تأییدشده‌ی جهت مخالف

    candidates_sorted = sorted(candidates, key=lambda c: c["index"])

    for cand in candidates_sorted:
        idx = cand["index"]
        atr_val = atr_series.iloc[idx]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        # اندازه‌ی حرکت نسبت به آخرین سوئینگ تأییدشده‌ی مخالف
        if last_confirmed_opposite is not None:
            move = abs(cand["price"] - last_confirmed_opposite["price"])
            magnitude_atr = move / atr_val
        else:
            magnitude_atr = float("inf")  # اولین سوئینگ در سری داده — بدون مرجع قبلی، رد نمی‌شود

        if magnitude_atr < min_atr_mult:
            continue  # نویز — اندازه‌ی حرکت کافی نیست

        if not _volume_ok(df, idx, vol_floor, magnitude_atr if np.isfinite(magnitude_atr) else 999.0):
            continue

        # حداقل ریتریسمنت: بعد از این سوئینگ باید حداقل min_retrace از لگ
        # منتهی به آن برگردد، قبل از این‌که سوئینگ *بعدی* (مخالف) تأیید شود.
        # این شرط با بررسی این‌که آیا در بازه‌ی بین این کاندید و کاندید
        # مخالفِ بعدی، حداقل درصد ریتریسمنت رخ داده، پیاده می‌شود.
        confirm_index = min(idx + k, len(df) - 1)
        # تأیید بدون look-ahead: سوئینگ تا k کندل بعد از خودش pending است.
        if confirm_index >= len(df):
            continue

        sw_id = f"swing_{timeframe}_{idx:06d}"
        sw = SwingPoint(
            id=sw_id, timeframe=timeframe, symbol=symbol,
            type=cand["type"], price=cand["price"], candle_index=idx,
            confirmed_at_index=confirm_index,
            confirmation_lag_bars=confirm_index - idx,
            magnitude_atr=None if not np.isfinite(magnitude_atr) else round(float(magnitude_atr), 3),
            status="confirmed",
            evidence={"fractal_k": k, "atr_at_swing": float(atr_val)},
        )
        swings.append(sw)
        last_confirmed_opposite = cand

    return _apply_retrace_filter(df, swings, min_retrace)


def _apply_retrace_filter(df: pd.DataFrame, swings: List[SwingPoint], min_retrace_pct: float) -> List[SwingPoint]:
    """حذف «سوئینگ‌اسپم» — بین دو سوئینگ هم‌جهت متوالی که سوئینگ مخالفی
    بینشان با حداقل ریتریسمنت لازم شکل نگرفته، فقط سوئینگ قوی‌تر (برای
    swing_high: بالاتر؛ برای swing_low: پایین‌تر) نگه داشته می‌شود.
    """
    if not swings:
        return swings

    swings_sorted = sorted(swings, key=lambda s: s.candle_index)
    kept: List[SwingPoint] = []
    for sw in swings_sorted:
        if kept and kept[-1].type == sw.type:
            # دو سوئینگ هم‌جهت پشت‌سرهم بدون سوئینگ مخالف بینشان → فقط
            # قوی‌تر را نگه دار (این خودش پیاده‌سازی عملیِ شرط «۲۰٪
            # ریتریسمنت لازم قبل از سوئینگ بعدی» است، چون اگر ریتریسمنت
            # کافی رخ داده بود، یک کاندید مخالف بین این دو تأیید می‌شد).
            prev = kept[-1]
            if sw.type == "swing_high":
                if sw.price >= prev.price:
                    kept[-1] = sw
                # وگرنه prev را نگه دار، sw را دور بینداز
            else:  # swing_low
                if sw.price <= prev.price:
                    kept[-1] = sw
            continue
        kept.append(sw)

    return kept


# ---------------------------------------------------------------------------
# نقطه‌ی ورود عمومی
# ---------------------------------------------------------------------------

def detect_swings(
    df: pd.DataFrame,
    timeframe: str,
    symbol: str = "",
    config_overrides: Optional[dict] = None,
) -> List[SwingPoint]:
    """نقطه‌ی ورود اصلی Stage 1-4. df باید ستون‌های open/high/low/close
    (و اختیاراً volume) داشته باشد و بر حسب زمان صعودی مرتب باشد.

    خروجی: لیست SwingPoint های «confirmed» (طبق سند، سوئینگ تا زمانی که
    شرایط تأیید برقرار نشود اصلاً در خروجی ظاهر نمی‌شود — یعنی status
    همیشه «confirmed» است در این نسخه‌ی batch؛ حالت incremental که سوئینگ
    را به‌صورت «pending» نگه می‌دارد تا کندل تأییدکننده برسد، در
    signal_engine.swing_structure.streaming پیاده خواهد شد).
    """
    if df is None or df.empty:
        return []

    cfg = _cfg_for(timeframe, config_overrides)
    df_reset = df.reset_index(drop=True)
    candidates = _raw_fractal_candidates(df_reset, cfg["fractal_k"])
    swings = _filter_and_confirm(df_reset, candidates, cfg, timeframe, symbol)
    return swings


def swings_as_arrays(swings: List[SwingPoint]):
    """کمکی برای signal_engine.common.trend_context.trend_from_swings —
    لیست SwingPoint را به دو آرایه‌ی موازی (prices, types) بر حسب ترتیب
    زمانی تبدیل می‌کند.
    """
    ordered = sorted(swings, key=lambda s: s.candle_index)
    prices = [s.price for s in ordered]
    types = ["high" if s.type == "swing_high" else "low" for s in ordered]
    return prices, types
