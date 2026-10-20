"""تست آفلاین رأی «برخورد/عبور از سقف و کف دیروز». اجرا: python ylevel_vote_selftest.py"""
import os, sys
here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, here)
import strategy as st
from simple_touch_selftest import make_df          # همان دیتای مصنوعیِ دو روز + روز سوم (اجرای آن تست هم تکرار می‌شود)
src = open(os.path.join(here, 'bot.py'), encoding='utf-8').read()

a = src.index("YLEVEL_TOL_ATR = "); b = src.index("def _touch_votes(")
g = dict(_compute_prev_day_levels=st._compute_prev_day_levels, fmt=lambda v: f'{v:.2f}')
exec(src[a:b], g)
vote = g['_ylevel_vote']

def case(mod=None, px=100.0):
    df, pdh, pdl = make_df()
    for k, v in (mod or {}).items():
        df.loc[df.index[-1], k] = v(pdh, pdl) if callable(v) else v
    return vote(df, px), pdh, pdl

(v, d), pdh, pdl = case(px=100.0);                      assert v is None, (v, d)                     # وسط رنج = بدون رأی
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'high'] = pdh + 2.0; df.loc[df.index[-1], 'close'] = pdh + 1.5
v, d = vote(df, pdh + 1.5);                              assert v == 'BUY' and 'گذشته' in d, (v, d)      # از سقف دیروز گذشته = خرید
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'low'] = pdl - 2.0; df.loc[df.index[-1], 'close'] = pdl - 1.5
v, d = vote(df, pdl - 1.5);                              assert v == 'SELL' and 'از دست' in d, (v, d)    # کف دیروز از دست رفته = فروش
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'high'] = pdh - 0.05
v, d = vote(df, pdh - 0.4);                              assert v == 'SELL' and 'برخورد به سقف' in d, (v, d)   # برخورد به سقف بدون عبور = فروش
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'low'] = pdl + 0.05
v, d = vote(df, pdl + 0.4);                              assert v == 'BUY' and 'برخورد به کف' in d, (v, d)     # برخورد به کف بدون عبور = خرید
# فتیله بالای سقف ولی قیمت لحظه‌ای برگشته داخل = رد از سقف (فروش)
df, pdh, pdl = make_df(); df.loc[df.index[-1], 'high'] = pdh + 1.0; v, d = vote(df, pdh - 0.5)
assert v == 'SELL', (v, d)
# داده‌ی ناقص
assert vote(df.iloc[:30], 100.0)[0] is None and vote(None, 100.0)[0] is None and vote(df, 0)[0] is None

# --- رأی در جمع‌بندی: گروه جدا (بی‌اثرِ خنثی کردن 'level') ---
a = src.index("_TOUCH_GROUP = {"); b = src.index("_TOUCH_ST_TXT = ")
from threading import RLock
g2 = {'RLock': RLock}; exec(src[a:b], g2)
assert g2['_TOUCH_GROUP']['ylevel'] == 'ylevel' and g2['_TOUCH_GROUP_W']['ylevel'] == 1 and 'ylevel' in g2['_TOUCH_KEYS']
a = src.index("def _touch_summarize("); b = src.index("def _touch_eval_one(")
g2.update(_TOUCH_GROUP=g2['_TOUCH_GROUP'], _TOUCH_GROUP_W=g2['_TOUCH_GROUP_W']); exec(src[a:b], g2)
vs = [{'key': 'level', 'vote': 'BUY'}, {'key': 'ylevel', 'vote': 'SELL'}]
r = g2['_touch_summarize'](vs, 'all'); assert r['groups'] == {'structure': 'BUY', 'ylevel': 'SELL'} and r['dir'] is None, r
vs.append({'key': 'pattern', 'vote': 'SELL'}); r = g2['_touch_summarize'](vs, 'all'); assert r['dir'] == 'SELL' and r['agree'] == 2, r
# --- ثبت: کلید، منو، پریست ---
assert "'gate_fc_ylevel_enabled':     ('رأی‌گیری: برخورد/عبور از سقف و کف دیروز', True, 'entry_filter'" in src
assert "if 'ylevel' in keys:" in src and "'ylevel': 'برخورد/عبور از سقف و کف دیروز'" in src
import presets; assert 'gate_fc_ylevel_enabled' in presets._GATES_OFF
print('ALL OK')
