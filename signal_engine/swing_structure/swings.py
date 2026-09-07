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
    """Causal Stage 2-4 processing.

    A candidate becomes observable only at ``candidate_index + k``.  All
    filtering decisions are made from information available by that
    confirmation index.  In particular, we never run a final pass that can
    replace/remove an already-confirmed swing because of a later swing.
    """
    atr_period = cfg["atr_period"]
    k = cfg["fractal_k"]
    min_atr_mult = cfg["min_swing_atr_multiple"]
    min_retrace = cfg["min_retrace_pct"]
    vol_floor = cfg["volume_percentile_floor"]

    d = compute_atr(df.reset_index(drop=True), period=atr_period)
    atr_series = d["atr"]
    candidates_sorted = sorted(candidates, key=lambda c: (c["index"] + k, c["index"]))

    swings: List[SwingPoint] = []
    # Reference leg must always come from the LAST CONFIRMED SWING OF THE
    # OPPOSITE TYPE TO THE CURRENT CANDIDATE — not merely "the last swing
    # whose type differed from whatever was stored before". A single shared
    # variable that flips based on its own previous type breaks as soon as
    # two confirmed swings of the same type occur back-to-back (e.g. a Low
    # between two Highs gets rejected by Stage-2 filters, which happens
    # routinely): it would then hold a same-type swing while still being
    # named/treated as "opposite", corrupting both the ATR-magnitude and the
    # retracement checks. Two separate references (one per type) avoid this.
    last_confirmed_high: Optional[SwingPoint] = None
    last_confirmed_low: Optional[SwingPoint] = None

    for cand in candidates_sorted:
        idx = int(cand["index"])
        confirm_index = idx + k
        if confirm_index >= len(d):
            continue

        atr_val = atr_series.iloc[idx]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        reference = last_confirmed_low if cand["type"] == "swing_high" else last_confirmed_high

        if reference is not None:
            move = abs(float(cand["price"]) - reference.price)
            magnitude_atr = move / float(atr_val)
        else:
            magnitude_atr = float("inf")

        if magnitude_atr < min_atr_mult:
            continue

        if not _volume_ok(
            d, idx, vol_floor,
            magnitude_atr if np.isfinite(magnitude_atr) else 999.0,
        ):
            continue

        # Causal retracement check: only candles between the candidate and
        # its confirmation candle are visible at confirmation time.
        retrace_ok = True
        if reference is not None:
            leg = abs(float(cand["price"]) - reference.price)
            if leg > 0:
                path = d.iloc[idx:confirm_index + 1]
                if cand["type"] == "swing_high":
                    retrace = float(cand["price"]) - float(path["low"].min())
                else:
                    retrace = float(path["high"].max()) - float(cand["price"])
                retrace_ok = retrace / leg >= min_retrace
        if not retrace_ok:
            continue

        sw_id = f"swing_{timeframe}_{idx:06d}"
        sw = SwingPoint(
            id=sw_id,
            timeframe=timeframe,
            symbol=symbol,
            type=cand["type"],
            price=float(cand["price"]),
            candle_index=idx,
            confirmed_at_index=confirm_index,
            confirmation_lag_bars=confirm_index - idx,
            magnitude_atr=None if not np.isfinite(magnitude_atr) else round(float(magnitude_atr), 3),
            status="confirmed",
            evidence={
                "fractal_k": k,
                "atr_at_swing": float(atr_val),
                "causal_confirmation_index": confirm_index,
                "causal_retrace_check": True,
            },
        )
        swings.append(sw)
        if sw.type == "swing_high":
            last_confirmed_high = sw
        else:
            last_confirmed_low = sw

    return swings


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
