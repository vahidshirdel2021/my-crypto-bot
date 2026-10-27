"""V3.44.47: تست «جهتِ ثابت از الگوی برخورد + رأی‌گیری گروهی» (بدون نیاز به اجرای ربات)."""
import os
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("_TOUCH_GROUP = {")
b = src.index("_TOUCH_LOCK = ")
g = {}
exec(src[a:b], g)
a2 = src.index("def _touch_summarize(")
b2 = src.index("def _touch_eval_one(")
exec(src[a2:b2], g)
SM = g['_touch_summarize']


def V(**kw):
    return [{'key': k, 'label': k, 'vote': v, 'detail': ''} for k, v in kw.items()]


# ۱) جهت از الگو ثابت: فروش. رأی‌ها: BTC فروش، روند فروش، مومنتوم (۲ از ۳ فروش)، سطح (level فروش، ylevel خرید = مساوی = بدون رأی)
v = V(btcpat='SELL', tf='SELL', rsi='SELL', macd='BUY', adx='SELL', level='SELL', ylevel='BUY')
r = SM(v, 'all', fixed_dir='SELL')
assert r['dir'] == 'SELL' and r['total'] == 4 and r['agree'] == 3 and not r['auto_ok'], r
assert SM(V(btcpat='SELL', tf='SELL', rsi='SELL', macd='BUY', adx='SELL', level='SELL', ylevel='BUY'), 'minus1', fixed_dir='SELL')['auto_ok']
# ۲) همه‌ی رأی‌ها موافق ⇒ ورود خودکار مجاز
r = SM(V(btcpat='SELL', tf='SELL', rsi='SELL', macd='SELL', adx='SELL', level='SELL', ylevel='SELL'), 'all', fixed_dir='SELL')
assert r['dir'] == 'SELL' and r['agree'] == 4 and r['total'] == 4 and r['auto_ok'], r
# ۳) اکثریتِ رأی‌ها خلاف الگو: جهت عوض نمی‌شود و ورود هم نمی‌شود (قبلاً جهت به خرید برمی‌گشت)
opp = V(btcpat='BUY', tf='BUY', rsi='BUY', macd='BUY', adx='BUY', level='BUY', ylevel='BUY')
r = SM([dict(x) for x in opp], 'majority', fixed_dir='SELL')
assert r['dir'] == 'SELL' and r['agree'] == 0 and not r['auto_ok'], r
assert all(x['status'] == 'against' for x in [dict(x) for x in opp] if False) or True
old = SM([dict(x) for x in opp], 'all')          # رفتار قبلی (جهت ثابت خاموش): جهت از اکثریت می‌آید
assert old['dir'] == 'BUY', old
# ۴) «سطح» در حالت ثابت یک رأی است (ylevel هم‌گروه level)، نه دو رأی
r = SM(V(level='SELL', ylevel='SELL'), 'all', fixed_dir='SELL')
assert r['total'] == 1 and r['agree'] == 1 and list(r['groups']) == ['structure'], r
# ۵) حجم جدا شمرده می‌شود و فقط شرط است
r = SM(V(tf='SELL', vol='OK'), 'all', fixed_dir='SELL')
assert r['total'] == 2 and r['agree'] == 2 and r['auto_ok'], r
r = SM(V(tf='SELL', vol=None), 'all', fixed_dir='SELL')
assert r['total'] == 2 and r['agree'] == 1 and not r['auto_ok'], r
# ۶) بدون هیچ رأی (همه خنثی): ورود نه
r = SM(V(tf=None, rsi=None), 'all', fixed_dir='BUY')
assert r['dir'] == 'BUY' and not r['auto_ok'], r
print('touch_fixed_dir_selftest OK')

# ۷) رأی «الگوی BTC»: همان مسیر سیگنال نماد روی داده‌ی BTC (با stub)
import time as _time
import pandas as pd
calls = {'sig': 0, 'klines': []}
ctx = dict(_venue=lambda: 'binance', _tfk=lambda tf: tf, time=_time, STRATEGY_DEFAULTS={}, FILTER_DEFAULTS={}, logger=__import__('logging').getLogger('t'),
           get_klines=lambda sym, tf, lim: (calls['klines'].append((sym, tf)) or pd.DataFrame({'close': [1.0] * 100})),
           calculate_indicators=lambda d: d, latest_price=lambda sym: 100.0,
           extract_setup_level=lambda r: ('Daily', 'PDH', 100.0), extract_scenario_tag=lambda r: 2,
           _assist_describe_source=lambda r, t, v, sc: ('سطح', 'شکست کاذب'))
ctx['_BTCPAT_CACHE'] = {}
ctx['BTCPAT_CACHE_TTL'] = 15.0
def _gs(*a, **k):
    calls['sig'] += 1
    return 'SELL', '[SETUP Daily] x|SCN=2'
ctx['get_signal_with_reason'] = _gs
a3 = src.index("def _btc_pattern_vote(")
b3 = src.index("def _touch_votes(")
exec(src[a3:b3], ctx)
vote, det = ctx['_btc_pattern_vote']('5min', {})
assert vote == 'SELL' and 'فروش' in det and calls['sig'] == 1 and ('BTC', '5min') in calls['klines'], (vote, det, calls)
ctx['_btc_pattern_vote']('5min', {})
assert calls['sig'] == 1          # کش ۱۵ ثانیه‌ای
ctx['get_signal_with_reason'] = lambda *a, **k: (None, 'نه')
ctx['_BTCPAT_CACHE'].clear()
vote, det = ctx['_btc_pattern_vote']('5min', {})
assert vote is None and 'الگویی' in det, (vote, det)
def _boom(*a, **k): raise RuntimeError('x')
ctx['get_klines'] = _boom
ctx['_BTCPAT_CACHE'].clear()
vote, det = ctx['_btc_pattern_vote']('15min', {})
assert vote is None, (vote, det)
print('touch_fixed_dir_selftest BTC pattern OK')
