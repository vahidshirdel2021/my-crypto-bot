"""تست مستقل مدل سطوح نصف‌کردن (بدون شبکه و بدون تلگرام).
اجرا:  python halving_selftest.py
"""
import numpy as np, pandas as pd
import halving_levels as hv
from strategy import (calculate_indicators, get_signal_with_reason, build_trade_plan,
                      FILTER_DEFAULTS, STRATEGY_DEFAULTS, extract_setup_tag, extract_scenario_tag)

H, L = 125670.0, 3145.0
ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

# --- ریاضی درخت ---
lv = {round(x["price"], 2): x["depth"] for x in hv.levels_near(H, L, 4, L, H)}
check("EQ کل = 64407.5 با عمق ۱", lv.get(64407.5) == 1)
check("چارک‌ها عمق ۲", lv.get(33776.25) == 2 and lv.get(95038.75) == 2)
check("سقف و کف عمق ۰", lv.get(125670.0) == 0 and lv.get(3145.0) == 0)
check("79723.12 عمق ۳", lv.get(79723.12) == 3)
check("تعداد سطوح عمق ۴ = 17", len(lv) == 17)
check("choose_depth ATR=100 → 8", hv.choose_depth(H, L, 100) == 8)
check("choose_depth ATR=180 → 7", hv.choose_depth(H, L, 180) == 7)
check("choose_depth ATR نامعتبر → min", hv.choose_depth(H, L, 0) == hv.DEFAULT_MIN_DEPTH)
check("سقف عمق رعایت می‌شود", hv.choose_depth(H, L, 0.5, max_depth=10) == 10)

# --- دادهٔ مصنوعی ۵ دقیقه‌ای: صعود تا زیر یک سطح و رد از آن ---
D = 8
step = (H - L) / 2 ** D
level = L + int((83400 - L) / step + 1) * step     # اولین سطح عمق ۸ بالای ۸۳٬۴۰۰
rng = np.random.default_rng(7)
n = 700
ts0 = pd.Timestamp("2026-10-05 00:00", tz="UTC")
close = 83000 + np.cumsum(rng.normal(0, 55, n))
close = close - (close[-3] - (level - 60))        # کندل‌های آخر درست زیر سطح
rows = []
for i in range(n):
    c = close[i]; o = close[i - 1] if i else c
    hi_ = max(o, c) + abs(rng.normal(0, 40)); lo_ = min(o, c) - abs(rng.normal(0, 40))
    rows.append([int((ts0 + pd.Timedelta(minutes=5 * i)).timestamp() * 1000), o, hi_, lo_, c, 100 + abs(rng.normal(0, 10))])
df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
# کندل بسته‌شدهٔ آخر (iloc[-2]): فتیله از سطح رد می‌شود ولی زیرش بسته می‌شود (نزولی)
df.loc[n - 2, ["open", "high", "low", "close"]] = [level - 70, level + 45, level - 130, level - 115]
df.loc[n - 2, "volume"] = 220
df.loc[n - 1, ["open", "high", "low", "close"]] = [level - 115, level - 55, level - 125, level - 70]
d = calculate_indicators(df)
# min_sl_percent پیش‌فرض بات ۰.۵٪ است که روی ATR کوچک ۵ دقیقه‌ی بیت‌کوین استاپ را بزرگ‌تر از سقف 3×ATR می‌کند؛
# برای تست پلنر، فقط همین گیتِ موجود (و گیت نسبت کارمزد به ریسک) را شل می‌کنیم تا مسیر TP روی سطوح دیده شود.
cfg = {**STRATEGY_DEFAULTS, "halving_model_enabled": True, "halving_high": H, "halving_low": L, "min_sl_percent": 0.0015,
       "gate_fee_ratio_enabled": False}
sig, reason = get_signal_with_reason(d, None, "single", "5min", "dynamic", FILTER_DEFAULTS, cfg, None, live_price=level - 70)
print("signal:", sig, "|", reason)
check("سیگنال SELL روی سطح نصف‌کردن", sig == "SELL" and extract_setup_tag(reason) == "Halving")
check("تگ سناریو در reason هست", extract_scenario_tag(reason) in ("1", "5", "6", "2", "3", "4"))
plan, why = build_trade_plan(d, sig, cfg, "dynamic", strategy_timeframe="5min", live_price=level - 70) if sig else (None, "no signal")
print("plan:", {k: plan[k] for k in ("entry", "sl", "tp", "rr")} if plan else why)
if plan:
    levels_all = [x["price"] for x in hv.levels_near(H, L, 8, level - 5 * step, level + 5 * step)]
    check("TP روی یکی از سطوح نصف‌کردن است", any(abs(plan["tp"] - x) < 1e-6 * x for x in levels_all), f"tp={plan['tp']:.2f}")
else:
    print("NOTE: طرح معامله رد شد (مثلاً R:R یا فاصله‌ی استاپ) - دلیل بالا")

# --- مدل خاموش: رفتار قبلی دست‌نخورده ---
cfg_off = {**STRATEGY_DEFAULTS}
s2, r2 = get_signal_with_reason(d, None, "single", "5min", "dynamic", FILTER_DEFAULTS, cfg_off, None, live_price=level - 70)
check("با مدل خاموش، تگ Halving ظاهر نمی‌شود", "Halving" not in str(r2))
# --- بدون سقف/کف: ردِ ایمن ---
cfg_nr = {**STRATEGY_DEFAULTS, "halving_model_enabled": True}
s3, r3 = get_signal_with_reason(d, None, "single", "5min", "dynamic", FILTER_DEFAULTS, cfg_nr, None)
check("بدون سقف/کف: سیگنال نمی‌دهد", s3 is None, r3)

# --- V3.44.3: ستاپِ «باطل‌شده» (قیمت چند ATR بالای سطح بالایی) نباید فروش بدهد، حتی با خاموش‌بودن سخت‌گیری‌ها ---
atr_ = float(d["atr"].iloc[-2]); up_ = level + 3 * atr_
df_w = df.copy()
for i in range(n - 8, n):
    o_ = up_ + (n - i) * 3; c_ = o_ - 5
    df_w.loc[i, ["open", "high", "low", "close"]] = [o_, o_ + atr_ * 0.4, c_ - atr_ * 0.2, c_]
df_w.loc[n - 2, ["open", "high", "low", "close"]] = [up_ + atr_ * 0.3, up_ + atr_ * 0.8, up_ - atr_ * 0.3, up_ - atr_ * 0.1]
d_w = calculate_indicators(df_w)
cfg_loose = {**cfg, "sweep_require_reclaim": False, "sweep_require_reversal_candle": False, "scenario_precision_v2": False}
s4, r4 = get_signal_with_reason(d_w, None, "single", "5min", "dynamic", FILTER_DEFAULTS, cfg_loose, None, live_price=up_ - atr_ * 0.1)
check("فروش با سطحِ بالایی «زیر» قیمت (ستاپ باطل‌شده) صادر نمی‌شود", s4 is None, str(r4)[:90])
print("\nALL PASS" if ok else "\nSOME FAILED")


# --- k پویا (halving_dynamic_k) ---
from strategy import _halving_context, _halving_cfg
def _mk(n, atr_old, atr_new, fast_n=30):
    px = 80000 + np.cumsum(np.random.default_rng(3).normal(0, 20, n))
    df = pd.DataFrame({"high": px + 10, "low": px - 10, "close": px, "open": px,
                       "volume": 1.0, "atr": [atr_old] * (n - fast_n) + [atr_new] * fast_n})
    return df
_base = {"halving_high": H, "halving_low": L, "halving_k_atr": 3.0, "halving_max_depth": 12}
_df_hot = _mk(400, 100.0, 200.0)     # نوسان اخیر دو برابر
_df_calm = _mk(400, 100.0, 50.0)     # نوسان اخیر نصف
_idx = len(_df_hot) - 1
c_off = _halving_context(_df_hot, _idx, _halving_cfg({**_base, "halving_dynamic_k": False}))
c_hot = _halving_context(_df_hot, _idx, _halving_cfg({**_base, "halving_dynamic_k": True}))
c_calm = _halving_context(_df_calm, _idx, _halving_cfg({**_base, "halving_dynamic_k": True}))
check("k پویا خاموش: ضریب ۱ و عمق بدون تغییر", c_off["dyn_ratio"] == 1.0)
check("نوسان بالا → سطوح درشت‌تر (عمق کمتر)", c_hot["depth"] < c_off["depth"], f"{c_hot['depth']} < {c_off['depth']}")
check("ضریب به سقف clamp می‌شود (۱٫۶)", abs(c_hot["dyn_ratio"] - 1.6) < 1e-9, c_hot["dyn_ratio"])
check("بازار آرام → سطوح ریزتر (عمق بیشتر)", c_calm["depth"] > c_off["depth"], f"{c_calm['depth']} > {c_off['depth']}")
check("ضریب به کف clamp می‌شود (۰٫۷)", abs(c_calm["dyn_ratio"] - 0.7) < 1e-9, c_calm["dyn_ratio"])
# سطوح عمیق‌تر شامل همان سطوح کم‌عمق‌ترند (برچسب عمقِ هر قیمت ثابت می‌ماند)
_p_hot = {round(x["price"], 4): x["depth"] for x in c_hot["levels"]}
_p_calm = {round(x["price"], 4): x["depth"] for x in c_calm["levels"]}
check("برچسب عمق هر سطح مشترک ثابت است", all(_p_calm[p] == dd for p, dd in _p_hot.items() if p in _p_calm))
# علّی بودن: تغییر کندل‌های بعد از idx روی نتیجه اثر ندارد
_df_fut = _df_hot.copy(); _df_fut.loc[_idx + 1:, "atr"] = 9999
check("بدون نگاه به آینده", _halving_context(_df_fut, _idx, _halving_cfg({**_base, "halving_dynamic_k": True}))["depth"] == c_hot["depth"])
print("ALL OK" if ok else "SOME FAILED")
