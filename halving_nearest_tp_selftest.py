"""تست آفلاین V3.44.94: ورود سریع/دستی در مدل نصف‌کردن → TP روی نزدیک‌ترین سطح (نه پرش به سطح دورتر به‌خاطر R:R).
سناریوی JUP: SELL، سطوح 0.2714 (نزدیک، <1.5R) و 0.2643 (دور).   اجرا: python halving_nearest_tp_selftest.py"""
import numpy as np, pandas as pd
import strategy as st

rng = np.random.default_rng(7)
n = 800
t0 = 1_761_000_000_000
close = 0.2785 + np.cumsum(rng.normal(0, 0.0007, n)) * 0.25
close = np.clip(close, 0.272, 0.285)
op = np.r_[close[0], close[:-1]]
hi = np.maximum(op, close) + abs(rng.normal(0, 0.0011, n))
lo = np.minimum(op, close) - abs(rng.normal(0, 0.0011, n))
df = pd.DataFrame({'timestamp': t0 + np.arange(n) * 900_000, 'open': op, 'high': hi, 'low': lo, 'close': close, 'volume': 1000.0})
d = st.calculate_indicators(df)
entry = 0.276845
step = 0.0071; L = 0.2643 - 37 * step; H = L + 256 * step       # شبکه‌ی عمق ۸: 0.2643 و 0.2714 روی شبکه‌اند
# فاصله‌ی SL شبیه کارت JUP (≈0.00562 یعنی ~۲٪ ورود): سطح نزدیک ≈0.94R می‌دهد و سطح دور ≈2.2R
cfg = {'halving_model_enabled': True, 'halving_high': H, 'halving_low': L, 'halving_only_targets': True,
       'min_sl_percent': 0.0203, 'max_sl_atr': 10.0}
lv = sorted(p for p, _ in st._quick_opposing_levels(d, entry, False, None, cfg))
print('levels below entry:', [round(x, 4) for x in lv[-3:]][::-1])
assert abs(max(lv) - 0.2714) < 1e-3, lv                         # نزدیک‌ترین سطح زیر ورود
atr = float(d['atr'].iloc[-2]); buf = atr * st.QUICK_TRADE_TP_BUFFER_ATR

new, why = st.build_quick_trade_plan(d, 'SELL', cfg, live_price=entry)
assert new is not None, why
near = max(lv)
assert abs(new['tp'] - (near + buf)) < 1e-9, (new['tp'], near, buf)     # TP کمی قبل از نزدیک‌ترین سطح
assert new['tp_level_name'].startswith('قبل از') and new['rr'] < 1.5, new['rr']      # نزدیک‌ترین سطح R:R کمتر از ۱.۵ دارد ولی هدف همان است
print('1 nearest level is TP even when R:R < 1.5 -> tp=%.6f rr=%.2f' % (new['tp'], new['rr']))

old, _ = st.build_quick_trade_plan(d, 'SELL', {**cfg, 'halving_tp_nearest': False}, live_price=entry)
assert old is not None and old['tp'] < new['tp'] - 1e-6, (old['tp'], new['tp'])   # رفتار قبلی با کلید خاموش: سطح دورتر
print('2 old behaviour kept with halving_tp_nearest=False -> tp=%.6f' % old['tp'])

assert abs(new['sl'] - old['sl']) < 1e-12                                        # SL (پشت سوینگ) دست نخورده
print('3 SL unchanged ok')

# سطح چسبیده به ورود (کمتر از کف فاصله بعد از بافر) هدف نمی‌شود و نوبت سطح بعدی است
tight_entry = near + buf + 0.05 * atr
t, _ = st.build_quick_trade_plan(d, 'SELL', cfg, live_price=tight_entry)
assert t is not None and t['tp'] < near, (t['tp'], near)
print('4 too-tight level skipped ok')

# غیر halving: بدون تغییر
o, _ = st.build_quick_trade_plan(d, 'SELL', {'halving_model_enabled': False}, live_price=entry)
assert o is not None
print('5 non-halving untouched ok')
print('ALL OK')
