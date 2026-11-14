"""V3.44.102: رأی «سمت BTC نسبت به نزدیک‌ترین سطح» + خط «حالت معامله» پنل اصلی. اجرا: python3 btc_side_vote_selftest.py"""
import os, logging
here = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(here, 'bot.py'), encoding='utf-8').read()
a = src.index("def _btc_side_vote("); b = src.index("def _touch_votes(")
state = {'info': None, 'raise': False}
def fake_info(s, tf, is_long):
    if state['raise']:
        raise RuntimeError('x')
    return state['info']
g = dict(btc_front_level_info=fake_info, fmt=lambda v: f'{v:g}', logger=logging.getLogger('t'))
exec(src[a:b], g)
V = g['_btc_side_vote']
state['info'] = {'close': 101.0, 'ref_price': 100.0, 'ref_label': 'سطح نصف‌کردن', 'ref_above': False}
v, d = V('15min', {}); assert v == 'BUY' and 'بالای' in d, (v, d)
state['info'] = {'close': 99.0, 'ref_price': 100.0, 'ref_label': 'سطح نصف‌کردن', 'ref_above': True}
v, d = V('1hour', {}); assert v == 'SELL' and 'پایین' in d, (v, d)
state['info'] = {'close': 100.0, 'ref_price': 100.0}; assert V('15min')[0] is None            # روی سطح
state['info'] = None; assert V('15min')[0] is None                                           # نبود داده
state['info'] = {'close': 100.0, 'ref_price': None}; assert V('15min')[0] is None
state['raise'] = True; assert V('15min')[0] is None                                          # خطا = بدون رأی، بدون کرش
# --- سیم‌کشی ---
assert "'btcside'" in src and "'gate_fc_btcside_enabled'" in src
assert "if 'btcside' in keys and sym_u != 'BTC':" in src            # برای خود BTC رأی نمی‌دهد
# --- پریست‌ها: کلید مدیریت‌شده و پیش‌فرض خاموش ---
import presets
assert presets.BASE_CFG.get('gate_fc_btcside_enabled') is False
# --- V3.44.169: خط «حالت معامله» از پنل اصلی حذف شد ---
assert not hasattr(presets, 'panel_line') and 'panel_line' not in src and '{mode_line}' not in src
print('btc_side_vote_selftest ALL OK')
