# -*- coding: utf-8 -*-
"""
signal_engine.key_level_setup.interactions
=============================================
پیاده‌سازی بخش ۴ سند KLSDE: تشخیص برخورد قیمت با یکی از ۹ سطح مرجع و
مدیریت چرخه‌ی عمر «پنجره‌ی برخورد» (Interaction Window) از لحظه‌ی اولین
لمس تا لحظه‌ای که به یکی از پنج ستاپ (در setups.py) حل می‌شود یا timeout
می‌خورد.

مفهوم کلیدی: approach_direction — این‌که قیمت از پایین به سطح نزدیک شده
(سطح نقش مقاومت دارد) یا از بالا (سطح نقش حمایت دارد). این جهت، علامت
penetration_depth را تعیین می‌کند: مقدار مثبت یعنی قیمت در همان جهت
برخورد از سطح عبور کرده (نه لزوماً به سمت بالا/پایین مطلق).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional

import pandas as pd

from signal_engine.common.atr import compute_atr
from signal_engine.key_level_setup.levels import LevelSet
from signal_engine.key_level_setup.confluence import detect_level_confluence, ConfluenceZone, DEFAULT_CONFLUENCE_CONFIG

ApproachDirection = Literal["from_below", "from_above"]
WindowStatus = Literal["open", "closed"]

# ردیف‌های هر سطح: کدام تایم‌فریم (روزانه/هفتگی/ماهانه) پشتش است — برای
# تلورانس برخورد اختصاصی و وزن‌دهی اهمیت (Section 8، significance_tier_weight)
LEVEL_TIER = {
    "P1H": "1h", "P1L": "1h", "P1EQ": "1h",
    "P4H": "4h", "P4L": "4h", "P4EQ": "4h",
    "PDH": "daily", "PDL": "daily", "PDEQ": "daily",
    "PWH": "weekly", "PWL": "weekly", "PWEQ": "weekly",
    "PMH": "monthly", "PML": "monthly", "PMEQ": "monthly",
}

DEFAULT_APPROACH_TOLERANCE_ATR = {"1h": 0.06, "4h": 0.08, "daily": 0.1, "weekly": 0.15, "monthly": 0.2}
DEFAULT_MAX_WINDOW_DURATION_BARS = 20


@dataclass
class InteractionWindow:
    id: str
    level_name: str
    level_price: float
    level_tier: str
    symbol: str
    timeframe: str
    approach_direction: ApproachDirection
    open_index: int
    candle_indices: List[int] = field(default_factory=list)
    penetration_depth_atr_by_index: Dict[int, float] = field(default_factory=dict)
    max_penetration_atr: float = 0.0
    status: WindowStatus = "open"
    close_index: Optional[int] = None
    close_reason: Optional[str] = None  # مثلاً 'resolved' یا 'unresolved_timeout'
    # طبق درخواست کاربر: اگر این سطح بخشی از یک «سطح قوی» (هم‌گرایی چند
    # لایه) باشد، این فیلدها پر می‌شوند — تا هم تلورانس برخورد و هم
    # اطمینان نهایی ستاپ (در setups.py) بتوانند حساس‌تر/قوی‌تر شوند.
    is_confluent: bool = False
    confluent_with: List[str] = field(default_factory=list)
    confluence_strength: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id, "level_name": self.level_name, "level_price": self.level_price,
            "level_tier": self.level_tier, "symbol": self.symbol, "timeframe": self.timeframe,
            "approach_direction": self.approach_direction, "open_index": self.open_index,
            "candle_indices": list(self.candle_indices),
            "max_penetration_atr": self.max_penetration_atr,
            "status": self.status, "close_index": self.close_index, "close_reason": self.close_reason,
            "is_confluent": self.is_confluent, "confluent_with": self.confluent_with,
            "confluence_strength": self.confluence_strength,
        }


def _signed_penetration(close_price: float, level_price: float, approach_direction: ApproachDirection) -> float:
    """مثبت = قیمت در جهت ادامه‌ی برخورد از سطح عبور کرده (شکست واقعی)."""
    if approach_direction == "from_below":
        return close_price - level_price
    return level_price - close_price


def detect_interactions(
    df: pd.DataFrame,
    level_set: LevelSet,
    symbol: str = "",
    timeframe: str = "",
    atr_period: int = 14,
    approach_tolerance_atr: Optional[Dict[str, float]] = None,
    max_window_duration_bars: int = DEFAULT_MAX_WINDOW_DURATION_BARS,
) -> List[InteractionWindow]:
    """پیمایش تمام کندل‌های df و باز/بستن پنجره‌ی برخورد برای هر سطح.

    طبق سند، بخش ۴.۲: فقط یک پنجره‌ی باز به‌ازای هر (level_name) در هر
    لحظه مجاز است؛ اگر بعد از بسته‌شدن یک پنجره، قیمت دوباره به همان سطح
    برخورد کند، پنجره‌ی *جدیدی* باز می‌شود.

    این تابع فقط پنجره‌ها را باز/بسته و tracking می‌کند — طبقه‌بندی
    نهایی به یکی از پنج ستاپ در setups.classify_setup انجام می‌شود؛ اینجا
    صرفاً close_reason='resolved' یا 'unresolved_timeout' ثبت می‌شود و
    تصمیم واقعی به مرحله‌ی بعد واگذار می‌شود (این تابع "بسته شدن" را با
    "چند کندل بدون تغییر معنادار دیگر رخ نداده" تشخیص نمی‌دهد؛ فقط timeout
    یا رسیدن انتهای داده را می‌بندد — بستن معنایی/رفتاری در setups.py رخ
    می‌دهد که این پنجره‌ی باز را می‌خواند و تصمیم می‌گیرد کِی resolved شده).
    """
    tolerance_cfg = approach_tolerance_atr or DEFAULT_APPROACH_TOLERANCE_ATR
    d = compute_atr(df.reset_index(drop=True), period=atr_period)
    atr_series = d["atr"]

    active_windows: Dict[str, InteractionWindow] = {}
    closed_windows: List[InteractionWindow] = []
    window_counter = 0

    valid_levels = {name: info.price for name, info in level_set.levels.items() if info.price is not None}

    # طبق درخواست کاربر: خوشه‌های «سطح قوی» یک‌بار (نه به‌ازای هر کندل)
    # روی قیمت‌های ثابت سطوح محاسبه می‌شوند — چون خودِ سطوح در طول این
    # سری ثابت‌اند (فقط در مرز دوره‌ی بعدی عوض می‌شوند). از آخرین ATR
    # معتبر به‌عنوان مقیاس نزدیکی استفاده می‌شود.
    last_valid_atr = next((v for v in reversed(atr_series.tolist()) if pd.notna(v) and v > 0), None)
    confluence_map = detect_level_confluence(level_set, last_valid_atr, LEVEL_TIER) if last_valid_atr else {}

    n = len(d)
    for i in range(n):
        atr_val = atr_series.iloc[i]
        if pd.isna(atr_val) or atr_val <= 0:
            continue
        close_price = float(d["close"].iloc[i])
        high_price = float(d["high"].iloc[i])
        low_price = float(d["low"].iloc[i])

        for level_name, level_price in valid_levels.items():
            tier = LEVEL_TIER.get(level_name, "daily")
            tol = tolerance_cfg.get(tier, 0.1) * atr_val
            zone = confluence_map.get(level_name)

            window = active_windows.get(level_name)

            if zone is not None:
                # طبق درخواست کاربر («حساس‌تر»): برخورد با *هر نقطه‌ای* از
                # کل بازه‌ی خوشه (نه فقط تلورانس تنگ این یک سطح) به‌عنوان
                # برخورد با این سطح تلقی می‌شود — چون از نظر معنایی، این
                # سطح دیگر تنها نیست، بخشی از یک ناحیه‌ی قیمتی قوی‌تر است.
                # این یک چک هم‌پوشانی بازه است: [low-buffer, high+buffer]
                # کندل با [price_low, price_high] ناحیه‌ی هم‌گرایی.
                buffer = max(tol, DEFAULT_CONFLUENCE_CONFIG["zone_buffer_atr_multiple"] * atr_val)
                touches = (low_price - buffer) <= zone.price_high and (high_price + buffer) >= zone.price_low
            else:
                touches = (low_price - tol) <= level_price <= (high_price + tol)

            if window is None:
                if touches:
                    approach_dir: ApproachDirection = "from_below" if close_price < level_price else "from_above"
                    window_counter += 1
                    window = InteractionWindow(
                        id=f"win_{timeframe}_{level_name}_{window_counter:05d}",
                        level_name=level_name, level_price=level_price, level_tier=tier,
                        symbol=symbol, timeframe=timeframe, approach_direction=approach_dir,
                        open_index=i,
                        is_confluent=zone is not None,
                        confluent_with=[n for n in zone.level_names if n != level_name] if zone else [],
                        confluence_strength=zone.strength if zone else 0.0,
                    )
                    window.candle_indices.append(i)
                    pen = _signed_penetration(close_price, level_price, approach_dir) / atr_val
                    window.penetration_depth_atr_by_index[i] = pen
                    window.max_penetration_atr = max(window.max_penetration_atr, pen)
                    active_windows[level_name] = window
                continue

            # پنجره از قبل باز است — ادامه‌ی ردیابی
            window.candle_indices.append(i)
            pen = _signed_penetration(close_price, level_price, window.approach_direction) / atr_val
            window.penetration_depth_atr_by_index[i] = pen
            window.max_penetration_atr = max(window.max_penetration_atr, pen)

            elapsed = i - window.open_index
            if elapsed >= max_window_duration_bars:
                window.status = "closed"
                window.close_index = i
                window.close_reason = "unresolved_timeout"
                closed_windows.append(window)
                del active_windows[level_name]

    # پنجره‌های هنوز بازِ باقی‌مانده در انتهای داده (batch mode) را نیز
    # به‌عنوان timeout می‌بندیم تا هیچ برخوردی بدون نتیجه‌ی auditable نماند.
    for level_name, window in list(active_windows.items()):
        window.status = "closed"
        window.close_index = window.candle_indices[-1]
        window.close_reason = "unresolved_timeout"
        closed_windows.append(window)

    return sorted(closed_windows, key=lambda w: w.open_index)
