# -*- coding: utf-8 -*-
"""V3.44.163 selftest: FVG/IFVG confirmation (fvg_ifvg.py + _fvg_apply in strategy.py)."""
import pandas as pd
from fvg_ifvg import find_fvgs, fvg_confirm
import strategy as S

ON = {"fvg_enabled": True, "fvg_lookback_candles": 30, "fvg_min_size_atr": 0.15, "fvg_level_tol_atr": 1.0, "fvg_recent_candles": 5}
ATR = 1.0

def mk(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])

def flat(n, p=95.0):
    return [(p, p + 0.3, p - 0.3, p)] * n

# --- find_fvgs ---------------------------------------------------------------------------
bull = flat(3, 99.5) + [(99.5, 100.0, 99.0, 99.8), (99.8, 103.0, 99.8, 102.8), (102.8, 103.5, 102.0, 103.0)]
d = mk(bull)
z = find_fvgs(d, len(d) - 1, 30, 0.15)
assert len(z) == 1 and z[0]["side"] == "bull" and abs(z[0]["lo"] - 100.0) < 1e-9 and abs(z[0]["hi"] - 102.0) < 1e-9 and z[0]["inv_idx"] is None, z
# جهش اول از flat به کندل 99.5/100 هم شکاف می‌سازد؟ نه: low=99.0 < high(flat)=95.3 false → فقط یک FVG
# inverted: close below zone low
d2 = mk(bull + [(103.0, 103.0, 98.0, 98.5)])
z2 = find_fvgs(d2, len(d2) - 1, 30, 0.15)
assert z2[0]["inv_idx"] == len(d2) - 1, z2
# اندازه‌ی کوچک نادیده گرفته می‌شود
assert find_fvgs(d, len(d) - 1, 30, 5.0) == []

# --- continuation (۳/۴) ------------------------------------------------------------------
assert fvg_confirm(d, len(d) - 1, "continuation", "BUY", 101.0, ATR, ON)[0] is True
assert fvg_confirm(d2, len(d2) - 1, "continuation", "BUY", 101.0, ATR, ON)[0] is False      # FVG با بدنه شکسته
assert fvg_confirm(d, len(d) - 1, "continuation", "SELL", 101.0, ATR, ON)[0] is False       # FVG خلاف جهت
assert fvg_confirm(mk(flat(10)), 9, "continuation", "BUY", 95.0, ATR, ON)[0] is False        # بدون FVG
# سطح دور از FVG
assert fvg_confirm(d, len(d) - 1, "continuation", "BUY", 90.0, ATR, ON)[0] is False

# --- fakeout (۵/۶) -----------------------------------------------------------------------
# SELL: FVG صعودی شکست، بعد با بدنه شکسته → IFVG
assert fvg_confirm(d2, len(d2) - 1, "fakeout", "SELL", 101.0, ATR, ON)[0] is True
# FVG صعودی هنوز سالم → IFVG نیست
assert fvg_confirm(d, len(d) - 1, "fakeout", "SELL", 101.0, ATR, ON)[0] is False
# BUY آینه‌ای: FVG نزولی که با بدنه به بالا شکسته شد
bear = flat(3, 100.5) + [(100.5, 101.0, 100.0, 100.2), (100.2, 100.2, 97.0, 97.2), (97.2, 98.0, 96.5, 97.0)]
db = mk(bear + [(97.0, 102.0, 97.0, 101.5)])
assert fvg_confirm(db, len(db) - 1, "fakeout", "BUY", 99.0, ATR, ON)[0] is True
# FVG تازه‌ی هم‌جهت (SELL → نزولی) نزدیک سطح
fresh = flat(3, 100.5) + [(100.5, 101.0, 100.0, 100.2), (100.2, 100.2, 97.0, 97.2), (97.2, 98.0, 96.5, 97.0)]
dfz = mk(fresh)
assert fvg_confirm(dfz, len(dfz) - 1, "fakeout", "SELL", 99.0, ATR, ON)[0] is True

# --- simple (۱/۲) ------------------------------------------------------------------------
assert fvg_confirm(dfz, len(dfz) - 1, "simple", "SELL", 99.0, ATR, ON)[0] is True            # نزولیِ تازه
assert fvg_confirm(dfz, len(dfz) - 1, "simple", "BUY", 99.0, ATR, ON)[0] is False           # خلاف جهت
old = mk(fresh + flat(8, 97.0))                                                               # FVG قدیمی‌تر از recent
assert fvg_confirm(old, len(old) - 1, "simple", "SELL", 99.0, ATR, {**ON, "fvg_level_tol_atr": 3.0})[0] is False

# --- خاموش = هیچ تغییری -----------------------------------------------------------------
OFF = {**ON, "fvg_enabled": False}
for kind in ("simple", "continuation", "fakeout"):
    assert fvg_confirm(mk(flat(10)), 9, kind, "BUY", 95.0, ATR, OFF) == (True, "")
assert S.STRATEGY_DEFAULTS["fvg_enabled"] is False

# --- _fvg_apply: توضیح قبل از اولین | و حفظ ANCHOR/TARGET ---------------------------------
reason = "شکست PDH + پولبک|ANCHOR=101|TARGET=95"
assert S._fvg_apply(d, len(d) - 1, "continuation", "BUY", reason, ATR, OFF) == reason
r2 = S._fvg_apply(d, len(d) - 1, "continuation", "BUY", reason, ATR, ON)
assert r2 and r2.endswith("|ANCHOR=101|TARGET=95") and "FVG" in r2.split("|")[0], r2
assert S.extract_sweep_anchor_target(r2) == (101.0, 95.0)
assert S._fvg_apply(mk(flat(10)), 9, "continuation", "BUY", reason, ATR, ON) is None

# --- سیمی ساده‌شده حذف شده -----------------------------------------------------------------
assert not hasattr(S, "simple_mode_on") and "simple_scenario_mode" not in S.STRATEGY_DEFAULTS
print("fvg_selftest OK")
