"""تست آفلاین حالت ۷ «برخورد ساده». اجرا: python simple_touch_selftest.py"""
import os, sys, calendar
import numpy as np, pandas as pd
here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, here)
import strategy as st, ui

def make_df(n_days=3, last_high=None, last_low=None, last_close=None, atr=1.0):
    """کندل ۵ دقیقه‌ای؛ روز اول و دوم رنج 95..105 (PDH=105 / PDL=95 برای روز سوم)، روز سوم فقط چند کندل (کندل آخر = در حال تشکیل)."""
    start = calendar.timegm((2026, 10, 17, 0, 0, 0)) * 1000
    rows = []
    for i in range(288 * 2):                              # دو روز کامل
        t = start + i * 300000
        phase = (i % 288) / 288.0
        mid = 100 + 5 * np.sin(phase * 2 * np.pi)
        rows.append([t, mid, mid + 0.3, mid - 0.3, mid, 100.0])
    day2 = [r for r in rows[288:]]
    # مطمئن شو سقف/کف روز دوم دقیقاً 105.3 و 94.7 است
    pdh = max(r[2] for r in day2); pdl = min(r[3] for r in day2)
    t0 = start + 288 * 2 * 300000
    for k in range(40):                                   # روز سوم: ۴۰ کندل وسط رنج
        t = t0 + k * 300000
        rows.append([t, 100.0, 100.4, 99.6, 100.0, 100.0])
    t = t0 + 40 * 300000                                  # کندل در حال تشکیل
    rows.append([t, 100.0, last_high or 100.4, last_low or 99.6, last_close or 100.0, 50.0])
    df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['atr'] = atr
    return df, pdh, pdl

CFG = {'scenario_7_enabled': True}
# خاموش = هیچ
df, pdh, pdl = make_df()
assert st.simple_touch_signal(df, {}, None, '5min')[0] is None
assert st.simple_touch_signal(df, {'scenario_7_enabled': False}, None, '5min')[0] is None
# وسط رنج: برخورد نیست
sig, why = st.simple_touch_signal(df, CFG, 100.0, '5min'); assert sig is None, (sig, why)
# رسیدن به سقف روز قبل (فتیله بدون هیچ بسته‌شدن بیرون سطح): فروش پیشنهادی
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'high'] = pdh - 0.05; df.loc[df.index[-1], 'close'] = pdh - 0.5
sig, why = st.simple_touch_signal(df, CFG, pdh - 0.5, '5min')
assert sig == 'SELL', (sig, why)
tag, key, val = st.extract_setup_level(why); assert (tag, key) == ('Daily', 'PDH') and abs(val - pdh) < 1e-6, why
assert st.extract_scenario_tag(why) == '7' and '[SETUP Daily]' in why and f'ANCHOR={pdh:.10g}' in why, why
print('SELL:', why)
# نزدیک شدن بدون رسیدن: خارج از تلورانس (0.15×ATR=0.15 یا 0.0003×قیمت≈0.03) برخورد نیست
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'high'] = pdh - 1.0
assert st.simple_touch_signal(df, CFG, pdh - 1.2, '5min')[0] is None
# داخل تلورانس (0.1 مانده) هم برخورد است
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'high'] = pdh - 0.10
assert st.simple_touch_signal(df, CFG, pdh - 0.4, '5min')[0] == 'SELL'
# رد شدن کامل از سطح (نفوذ) هم برخورد است - نیازی به «نفوذ نکردن» نیست
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'high'] = pdh + 1.0; df.loc[df.index[-1], 'close'] = pdh + 0.6
assert st.simple_touch_signal(df, CFG, pdh + 0.6, '5min')[0] == 'SELL'
# قیمت زنده به‌تنهایی (قبل از ثبت در کندل) برخورد را می‌سازد
df, pdh, pdl = make_df(); assert st.simple_touch_signal(df, CFG, pdl + 0.02, '5min')[0] == 'BUY'
# کف روز قبل: خرید پیشنهادی
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'low'] = pdl + 0.05
sig, why = st.simple_touch_signal(df, CFG, pdl + 0.3, '5min'); assert sig == 'BUY' and 'PDL=' in why, (sig, why)
# مدل نصف‌کردن پشتیبانی نمی‌شود؛ داده کم = هیچ
assert st.simple_touch_signal(df, {**CFG, 'halving_model_enabled': True}, pdl, '5min')[0] is None
assert st.simple_touch_signal(df.iloc[:50], CFG, pdl, '5min')[0] is None
# منو و ثبت در همه‌ی جدول‌ها
cb = {b['callback_data']: b['text'] for row in ui.get_scenario_management_keyboard({'strategy_config': {}})['inline_keyboard'] for b in row}
assert '/toggle_scenario_7' in cb and cb['/toggle_scenario_7'].startswith('🔴'), cb       # پیش‌فرض خاموش
assert cb['/toggle_scenario_1'].startswith('🟢')
cb2 = ui.get_scenario_management_keyboard({'strategy_config': {'scenario_7_enabled': True}})['inline_keyboard']
assert any(b['callback_data'] == '/toggle_scenario_7' and b['text'].startswith('🟢') for row in cb2 for b in row)
src = open(os.path.join(here, 'bot.py'), encoding='utf-8').read()
for needle in ["'7': 'برخورد ساده" if False else '"7": "برخورد ساده با سطح', "in ('1', '2', '3', '4', '5', '6', '7')", "simple_touch_signal(primary, cfg_entry, live_entry_price, primary_tf)", "if _simple_touch or gate_on(s, 'gate_touch_vote_enabled'):"]:
    assert needle in src, needle
assert st._SCENARIO_TOGGLE_KEYS['7'] == 'scenario_7_enabled' and st.STRATEGY_DEFAULTS['scenario_7_enabled'] is False
print('ALL OK')

# برچسب سناریو در پیام‌ها
import re
seg = src[src.index("_SCENARIO_LABELS_PLAIN = {"):][:900]
assert '"7": "برخورد ساده با سطح' in seg
