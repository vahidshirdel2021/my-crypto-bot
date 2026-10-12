# -*- coding: utf-8 -*-
"""تست تعریف «شکست کاذب» (حالت ۵/۶).

شکست کاذب واقعی = قیمت از «داخل محدوده» به بیرونِ سطح می‌رود، فقط چند کندلِ کوتاه آن‌طرف می‌ماند
و دوباره داخل محدوده بسته می‌شود. اگر قیمت ساعت‌ها بالای سطح بوده و حالا فقط دارد از بالا
وارد محدوده می‌شود، این «برگشت از شکست» نیست و شکست کاذب حساب نمی‌شود.

اجرا:  python fakeout_leg_tests.py
"""
import numpy as np
import pandas as pd

import strategy as S

HI, LO = 0.674124, 0.663877
ATR = 0.0015
CFG = {"scenario_precision_v2": True, "scenario_penetration_min_atr": 0.10,
       "retest_lookback_candles": 48, "retest_tolerance_atr": 0.25}


def _candles(closes, wick=0.0004):
    rows, prev = [], closes[0]
    for c in closes:
        o = prev
        rows.append({"open": o, "high": max(o, c) + wick, "low": min(o, c) - wick,
                     "close": c, "volume": 1000.0})
        prev = c
    return pd.DataFrame(rows)


def _run(closes, mirror=False):
    d = _candles(closes)
    if mirror:   # آینه‌ی قیمت نسبت به وسط محدوده، تا سمت BUY هم تست شود
        mid = (HI + LO) / 2.0
        for col in ("open", "close"):
            d[col] = 2 * mid - d[col]
        hi_, lo_ = d["high"].copy(), d["low"].copy()
        d["high"], d["low"] = 2 * mid - lo_, 2 * mid - hi_
    d = pd.concat([d, d.iloc[[-1]]], ignore_index=True)   # کندل در حال تشکیل (نادیده گرفته می‌شود)
    before_idx = len(d) - 2
    return S._detect_failed_retest_reversal(d, before_idx, HI, LO, "HVH", "HVL", "H", "L", ATR, dict(CFG))


def case_user_chart():
    """نمودار کاربر: قیمت ساعت‌ها بالای HVH بوده، کندل آخر از بالا وارد محدوده شده."""
    above = list(np.linspace(0.688, 0.6775, 70))
    return above + [0.67405]


def case_real_fakeout_top():
    """قیمت داخل محدوده، ۲ کندل بالای سقف بسته می‌شود، سپس برمی‌گردد داخل."""
    inside = list(np.linspace(0.668, 0.6730, 20))
    poke = [0.6750, 0.6756]
    back = [0.6735]
    return inside + poke + back


def case_long_leg_but_started_inside():
    """از داخل شروع شده ولی ۱۵ کندل بالای سطح مانده: دیگر «کاذب» نیست (شکست پذیرفته شده)."""
    inside = list(np.linspace(0.668, 0.6730, 20))
    beyond = list(np.linspace(0.6750, 0.6790, 15))
    return inside + beyond + [0.6735]


def main():
    ok = True

    sig, _ = _run(case_user_chart())
    print("نمودار کاربر (باید رد شود)           ->", sig)
    ok &= sig is None

    sig, _ = _run(case_real_fakeout_top())
    print("شکست کاذب واقعی سقف (باید SELL)      ->", sig)
    ok &= sig == "SELL"

    sig, _ = _run(case_real_fakeout_top(), mirror=True)
    print("شکست کاذب واقعی کف (باید BUY)        ->", sig)
    ok &= sig == "BUY"

    sig, _ = _run(case_user_chart(), mirror=True)
    print("آینه‌ی نمودار کاربر (باید رد شود)     ->", sig)
    ok &= sig is None

    sig, _ = _run(case_long_leg_but_started_inside())
    print("بیرون‌ماندن طولانی (باید رد شود)      ->", sig)
    ok &= sig is None

    print("\nنتیجه:", "همه‌ی تست‌ها درست‌اند ✅" if ok else "یک یا چند تست شکست خورد ❌")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
