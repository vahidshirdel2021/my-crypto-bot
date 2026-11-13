# -*- coding: utf-8 -*-
"""V3.44.163: تایید FVG / IFVG برای ۶ سناریو (کلید fvg_enabled، پیش‌فرض خاموش).

FVG: شکاف سه‌کندلی.  صعودی: low[i] > high[i-2]  (ناحیه = high[i-2] .. low[i])
                      نزولی: high[i] < low[i-2] (ناحیه = high[i] .. low[i-2])
IFVG: FVG که یک کندل «با بدنه» (close) از سمت دور آن عبور کرده؛ صعودیِ شکسته‌شده = ناحیه‌ی مقاومت، و برعکس.

قوانین (kind همان نوع تشخیص در strategy.py است):
  simple       (۱/۲ برخورد و برگشت): FVG هم‌جهت معامله (فروش=نزولی، خرید=صعودی) در چند کندل اخیر، نزدیک سطح، شکسته‌نشده.
  continuation (۳/۴ شکست و ادامه):   FVG ساخته‌شده توسط شکست (هم‌جهت معامله) نزدیک سطح وجود دارد و با بدنه شکسته نشده.
  fakeout      (۵/۶ شکست کاذب):      IFVG هم‌جهت معامله نزدیک سطح (FVG شکست با بدنه برگشته)،
                                      یا FVG تازه‌ی هم‌جهت معامله در چند کندل اخیر.
خطا/داده‌ی ناقص = ایمن‌باز (سیگنال بلاک نمی‌شود).
"""
import numpy as np


def _f(v, default):
    try:
        x = float(v)
        return x if np.isfinite(x) else default
    except (TypeError, ValueError):
        return default


def find_fvgs(d, end_idx, lookback=30, min_size=0.0):
    """همه‌ی FVGهای کندل‌های (end_idx-lookback .. end_idx). هر مورد: dict(i, side, lo, hi, inv_idx)."""
    h = d["high"].to_numpy(dtype=float)
    l = d["low"].to_numpy(dtype=float)
    c = d["close"].to_numpy(dtype=float)
    end_idx = min(int(end_idx), len(d) - 1)
    out = []
    for i in range(max(2, end_idx - int(lookback)), end_idx + 1):
        if l[i] > h[i - 2]:
            side, lo, hi = "bull", h[i - 2], l[i]
        elif h[i] < l[i - 2]:
            side, lo, hi = "bear", h[i], l[i - 2]
        else:
            continue
        if hi - lo < min_size:
            continue
        inv = None
        for j in range(i + 1, end_idx + 1):
            if (side == "bull" and c[j] < lo) or (side == "bear" and c[j] > hi):
                inv = j
                break
        out.append({"i": i, "side": side, "lo": float(lo), "hi": float(hi), "inv_idx": inv})
    return out


def _near(z, level, tol):
    if z["lo"] <= level <= z["hi"]:
        return True
    return min(abs(z["lo"] - level), abs(z["hi"] - level)) <= tol


def fvg_confirm(d, idx, kind, sig, level, atr, cfg):
    """(ok, توضیح). kind: simple | continuation | fakeout. sig: BUY | SELL. level: سطح مرجع (ANCHOR)."""
    try:
        if not bool((cfg or {}).get("fvg_enabled", False)):
            return True, ""
        if level is None or not np.isfinite(level) or not atr or not np.isfinite(atr) or atr <= 0:
            return True, ""
        lookback = int(cfg.get("fvg_lookback_candles", 30))
        recent = max(1, int(cfg.get("fvg_recent_candles", 5)))
        min_size = _f(cfg.get("fvg_min_size_atr", 0.15), 0.15) * atr
        tol = _f(cfg.get("fvg_level_tol_atr", 1.0), 1.0) * atr
        zones = [z for z in find_fvgs(d, idx, lookback, min_size) if _near(z, level, tol)]
        want = "bull" if sig == "BUY" else "bear"      # FVG هم‌جهت معامله
        against = "bear" if sig == "BUY" else "bull"   # FVG خلاف جهت معامله (برای IFVG)
        if kind == "continuation":
            ok = [z for z in zones if z["side"] == want and z["inv_idx"] is None]
            if ok:
                return True, "FVG شکست نگه داشته شد"
            return False, "FVG: شکستِ بدون FVG سالم (یا FVG با بدنه شکسته شده)"
        if kind == "fakeout":
            ifvg = [z for z in zones if z["side"] == against and z["inv_idx"] is not None]
            if ifvg:
                return True, "IFVG: FVG شکست با بدنه برگشت"
            fresh = [z for z in zones if z["side"] == want and z["inv_idx"] is None and z["i"] >= idx - recent + 1]
            if fresh:
                return True, "FVG تازه‌ی هم‌جهت برگشت"
            return False, "FVG: نه IFVG و نه FVG تازه‌ی هم‌جهت"
        # simple (۱/۲)
        fresh = [z for z in zones if z["side"] == want and z["inv_idx"] is None and z["i"] >= idx - recent + 1]
        if fresh:
            return True, "FVG هم‌جهت بعد از برگشت"
        return False, "FVG: بعد از برخورد، شکاف هم‌جهت ساخته نشد"
    except Exception:
        return True, ""
