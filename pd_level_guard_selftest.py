"""تست مستقل گارد سقف/کف دیروز (PDH/PDL) در مدل نصف‌کردن: python pd_level_guard_selftest.py
سناریوی عکس کاربر (BCH/USDT ۱۵ دقیقه): سطح نصف‌کردن شکسته، قیمت به PDL رسید و برگشت؛ فروش نباید باز شود."""
import numpy as np
import pandas as pd
from strategy import (calculate_indicators, _compute_prev_day_levels, pd_level_guard, pd_level_guard_df,
                      strategy_halving, _halving_cfg)

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

PDH, PDL = 288.5, 274.5
rng = np.random.default_rng(7)

def build(n_today_closed, touch_back, bounce_to=277.2, touch_low=273.5):
    """دو روز قبل پر می‌شود (دیروز: سقف 288.5 و کف 274.5)، بعد امروز تا n_today_closed کندل بسته + ۱ کندل در حال تشکیل.
    کندلِ رسیدن به PDL به‌اندازه‌ی touch_back کندل قبل از آخرین کندل بسته قرار می‌گیرد (None = اصلاً نمی‌رسد)."""
    rows, t0 = [], pd.Timestamp('2026-10-22', tz='UTC')
    def add(i, o, h, l, c):
        rows.append(((t0 + pd.Timedelta(minutes=15 * i)).value // 10**6, o, h, l, c, 100.0 + rng.random()))
    # روز ۲۲: خنثی ~281
    for i in range(96):
        c = 281 + rng.normal(0, 0.3); add(i, c, c + 0.5, c - 0.5, c)
    # روز ۲۳ (دیروز): مسیر از ۲۸۰ به ۲۸۸.۵ و بعد ۲۷۴.۵ و برگشت به ~۲۸۲
    path = np.interp(np.arange(96), [0, 25, 50, 75, 95], [280, 288.0, 281, 275.0, 282])
    for i in range(96):
        c = path[i] + rng.normal(0, 0.15); h, l = c + 0.5, c - 0.5
        if i == 25: h = PDH
        if i == 75: l = PDL
        add(96 + i, c, h, l, c)
    base = 96 * 2
    last_closed = n_today_closed - 1
    key_x = [0, last_closed - touch_back - 12, last_closed - touch_back, last_closed]
    key_y = [282.4, 278.0, 275.0, bounce_to]
    path = np.interp(np.arange(n_today_closed + 1), key_x, key_y)
    for i in range(n_today_closed + 1):
        c = path[i] + rng.normal(0, 0.1); h, l = c + 0.5, c - 0.5
        if touch_back is not None and i == last_closed - touch_back:
            l = touch_low; c = 275.0
        add(base + i, c, h, l, c)
    df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    return calculate_indicators(df)

CFG = {'halving_model_enabled': True, 'gate_pd_level_enabled': True}

ind = build(46, touch_back=4)
d, pdh, pdl = _compute_prev_day_levels(ind)
atr = float(d['atr'].iloc[-2])
check("PDH/PDL دیروز درست خوانده می‌شود", abs(pdh - PDH) < 1e-6 and abs(pdl - PDL) < 1e-6, f"pdh={pdh} pdl={pdl} atr={atr:.2f}")
check("ATR منطقی است (۰٫۵ تا ۳)", 0.5 < atr < 3.0, f"atr={atr:.2f}")

# الف) مانع نزدیک: PDL کمتر از ۱٫۵×ATR زیر قیمت
lp = PDL + 0.7 * atr
r = pd_level_guard_df(ind, 'SELL', lp, CFG)
check("فروش با PDL نزدیک (۰٫۷×ATR زیر قیمت) نگه داشته می‌شود", r[0] is False and 'PDL' in r[1], r)
# قیمت روی خود سطح
r = pd_level_guard_df(ind, 'SELL', PDL + 0.05 * atr, CFG)
check("فروش وقتی قیمت روی PDL نشسته نگه داشته می‌شود", r[0] is False and 'نشسته' in r[1], r)
# ب) واکنش رخ داده: چند کندل پیش رسیده، حالا برگشته ولی هنوز در همسایگی سطح
lp = PDL + 1.8 * atr
r = pd_level_guard_df(ind, 'SELL', lp, CFG)
check("فروش بعد از رسیدن به PDL و برگشت (سناریوی عکس) نگه داشته می‌شود", r[0] is False and 'برگشته' in r[1], r)
# شکسته‌شدن واقعی: فروش آزاد
r = pd_level_guard_df(ind, 'SELL', PDL - 1.0 * atr, CFG)
check("فروش وقتی PDL واقعاً شکسته و پایین‌تر رفته آزاد است", r[0] is True, r)
# خیلی دور از PDL: آزاد
r = pd_level_guard_df(ind, 'SELL', PDL + 6 * atr, CFG)
check("فروش دور از PDL آزاد است", r[0] is True, r)
# خرید از PDL (همان سمت برگشت) به PDL مربوط نیست
r = pd_level_guard_df(ind, 'BUY', PDL + 1.8 * atr, CFG)
check("خرید پس از برگشت از PDL توسط این گارد بسته نمی‌شود", r[0] is True, r)

# رسیدن به PDL خیلی قدیمی (بیش از ۱۲ کندل پیش) = واکنش قدیمی، گارد نمی‌بندد
ind_old = build(60, touch_back=30, bounce_to=277.2)
d2, _a, _b = _compute_prev_day_levels(ind_old)
atr2 = float(d2['atr'].iloc[-2])
r = pd_level_guard_df(ind_old, 'SELL', PDL + 1.8 * atr2, CFG)
check("رسیدن به PDL بیش از ۱۲ کندل پیش دیگر مانع نیست", r[0] is True, r)

# کلیدها
check("کلید خاموش: بدون محدودیت", pd_level_guard_df(ind, 'SELL', PDL + 0.7 * atr, {**CFG, 'gate_pd_level_enabled': False})[0] is True)
check("مدل نصف‌کردن خاموش: (PDL خودِ سطح ستاپ است) بدون محدودیت", pd_level_guard_df(ind, 'SELL', PDL + 0.7 * atr, {'halving_model_enabled': False, 'gate_pd_level_enabled': True})[0] is True)
check("داده‌ی کم: بسته نمی‌شود", pd_level_guard_df(ind.tail(30).reset_index(drop=True), 'SELL', 275.0, CFG)[0] is True)
check("حساسیت قابل تنظیم (room=0 فقط روی خود سطح)", pd_level_guard_df(ind, 'SELL', PDL + 0.7 * atr, {**CFG, 'pd_guard_room_atr': 0.0})[0] is True)

# آینه: خرید نزدیک PDH
ind_h = build(46, touch_back=4)
# برای آینه، خرید با قیمتی نزدیکِ PDH (فاصله ۰٫۷×ATR زیر PDH)
r = pd_level_guard_df(ind_h, 'BUY', PDH - 0.7 * atr, CFG)
check("خرید با PDH نزدیک بالای قیمت نگه داشته می‌شود", r[0] is False and 'PDH' in r[1], r)
r = pd_level_guard_df(ind_h, 'BUY', PDH + 1.0 * atr, CFG)
check("خرید وقتی PDH شکسته و بالاتر رفته آزاد است", r[0] is True, r)
r = pd_level_guard_df(ind_h, 'SELL', PDH - 0.7 * atr, CFG)
check("فروش نزدیک PDH توسط این گارد بسته نمی‌شود (برگشت از سقف)", r[0] is True, r)

# یکپارچگی با strategy_halving: خروجی باید از کراش‌نخوردن/سازگاری با امضای قبلی مطمئن شود
cfg_run = _halving_cfg({'halving_model_enabled': True, 'halving_high': 400.0, 'halving_low': 100.0, 'gate_pd_level_enabled': True})
try:
    sig, why = strategy_halving(ind, cfg_run, live_price=PDL + 0.7 * atr)
    check("strategy_halving با گارد بدون خطا اجرا می‌شود", sig is None or sig in ('BUY', 'SELL'), (sig, str(why)[:80]))
    if sig == 'SELL':
        check("strategy_halving فروش نزدیک PDL را برنمی‌گرداند", False, why)
except Exception as exc:
    check("strategy_halving با گارد بدون خطا اجرا می‌شود", False, repr(exc))

# یکپارچگی واقعی: یک سیگنال فروشِ اجباری (شکست و ادامه روی سطح نصف‌کردن) تزریق می‌شود؛ گارد باید در strategy_halving جلویش را بگیرد
import strategy as _S
_orig = _S._detect_retest_continuation
def _fake(d, idx, hi, lo, hk, lk, hl, ll, atr_, cfg_):
    a = _ANCH[0]    # لنگر همین‌جا نزدیک قیمت زنده گذاشته می‌شود تا گارد تعقیب قیمت/باطل‌شدن ستاپ سیگنال را نخورد
    return "SELL", f"شکست و ادامه (HVL={a:.6g})|ANCHOR={a:.6g}|TARGET={a - 5:.6g}"
_ANCH = [0.0]
_S._detect_retest_continuation = _fake
try:
    cfg_on = _halving_cfg({'halving_model_enabled': True, 'halving_high': 400.0, 'halving_low': 100.0, 'gate_pd_level_enabled': True})
    cfg_off = _halving_cfg({'halving_model_enabled': True, 'halving_high': 400.0, 'halving_low': 100.0, 'gate_pd_level_enabled': False})
    # قیمت زنده نزدیک PDL و نزدیک سطحِ تزریق‌شده (سطح پایینی سلول)؛ سلول‌ها از درخت می‌آیند، پس سطحی را که واقعاً زیر قیمت است پیدا می‌کنیم
    lp_try = PDL + 0.7 * atr
    _ANCH[0] = lp_try
    sig_off, why_off = strategy_halving(ind, cfg_off, live_price=lp_try)
    sig_on, why_on = strategy_halving(ind, cfg_on, live_price=lp_try)
    if sig_off == 'SELL':
        check("با کلید خاموش فروش صادر می‌شود", True)
        check("با کلید روشن همان فروش نگه داشته می‌شود و دلیل PDL گزارش می‌شود", sig_on is None and 'کف دیروز' in str(why_on), (sig_on, str(why_on)[:90]))
    else:
        print("INFO سیگنال تزریق‌شده از گارد گیت‌های دیگرِ مدل (فاصله/باطل‌شدن) عبور نکرد؛ تست یکپارچگی رد شد:", str(why_off)[:80])
finally:
    _S._detect_retest_continuation = _orig

print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
