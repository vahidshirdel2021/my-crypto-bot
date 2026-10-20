"""تست آفلاین حالت ۷ (برخورد ساده) روی سطوح نصف‌کردن. اجرا: python simple_touch_halving_selftest.py"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, here)
import strategy as st
from simple_touch_selftest import make_df

HV = {'scenario_7_enabled': True, 'halving_model_enabled': True, 'halving_high': 200.0, 'halving_low': 50.0}
df, _, _ = make_df()
d, _, _ = st._compute_prev_day_levels(df)
ctx = st._halving_context(d, len(d) - 2, st._halving_cfg(HV))
assert ctx and ctx['levels'], ctx
lv = sorted(float(x['price']) for x in ctx['levels'])
up = [p for p in lv if p > 100.5]; dn = [p for p in lv if p < 99.5]
assert up and dn, lv
L_up, L_dn = min(up), max(dn)            # نزدیک‌ترین سطح بالا/پایین قیمت 100
print('سطوح اطراف 100:', [round(x, 3) for x in lv if 80 < x < 125], '| step', round(ctx['step'], 3))

def touch(price, side):
    x = make_df()[0]
    x.loc[x.index[-1], 'high' if side == 'up' else 'low'] = price
    return x

# رسیدن به سطح بالای قیمت = رأی فروش؛ توکن HVH و برچسب Halving
sig, why = st.simple_touch_signal(touch(L_up - 0.02, 'up'), HV, L_up - 0.3, '5min')
assert sig == 'SELL', (sig, why)
tag, key, val = st.extract_setup_level(why); assert (tag, key) == ('Halving', 'HVH') and abs(val - L_up) < 1e-6, why
assert st.extract_scenario_tag(why) == '7' and 'HVDEPTH=' in why and 'HVTREE=' in why and 'سطح نصف‌کردن' in why, why
print('SELL:', why)
# رسیدن به سطح پایین قیمت = رأی خرید
sig, why = st.simple_touch_signal(touch(L_dn + 0.02, 'dn'), HV, L_dn + 0.3, '5min')
assert sig == 'BUY' and st.extract_setup_level(why)[1] == 'HVL', (sig, why)
# وسط دو سطح: برخورد نیست
mid = (L_up + L_dn) / 2
sig, why = st.simple_touch_signal(make_df()[0], HV, 100.0, '5min'); assert sig is None and 'نرسیده' in why, (sig, why)
# عبور کامل از سطح (نفوذ) هم برخورد است؛ قیمت زنده به‌تنهایی هم کافی است
assert st.simple_touch_signal(touch(L_up + 1.5, 'up'), HV, L_up + 1.0, '5min')[0] == 'BUY'
assert st.simple_touch_signal(make_df()[0], HV, L_up - 0.05, '5min')[0] == 'SELL'
# عمق مجاز معامله: فقط سطوح کم‌عمق
deep = {**HV, 'halving_max_trade_depth': 1}
depths = {round(float(x['price']), 6): int(x['depth']) for x in ctx['levels']}
sig, why = st.simple_touch_signal(touch(L_up - 0.02, 'up'), deep, L_up - 0.1, '5min')
assert (sig is None) == (depths[round(L_up, 6)] > 1), (sig, why, depths)
# بدون سقف/کف تاریخی: بی‌سیگنال، بدون خطا
assert st.simple_touch_signal(touch(L_up, 'up'), {'scenario_7_enabled': True, 'halving_model_enabled': True}, L_up, '5min')[0] is None
# خاموش = هیچ
assert st.simple_touch_signal(touch(L_up, 'up'), {**HV, 'scenario_7_enabled': False}, L_up, '5min')[0] is None
print('ALL OK')
