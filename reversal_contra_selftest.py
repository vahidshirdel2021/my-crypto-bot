"""V3.44.88: تست «رأی برگشت» (آزمایشی): معکوس‌شدن رأی‌دهنده‌های مومنتوم فقط در حالت‌های برگشتی و فقط با کلید روشن.

بدون اجرای ربات: همان بلوک کد رأی‌گیری با استاب‌های تست‌های قبلی اجرا می‌شود.
"""
import json
import os
import re
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
# استاب‌ها و بلوک کد را از تست رأی‌گیری قبلی قرض می‌گیریم (تا یک جای واحد نگهداری شوند)
_prefix = open(os.path.join(HERE, 'touch_vote_selftest.py'), encoding='utf-8').read().split('exec(block, g)')[0]
ns = {'__file__': os.path.join(HERE, 'touch_vote_selftest.py')}
exec(_prefix, ns)
g, S, st = ns['g'], ns['S'], ns['st']
ON2 = {f'gate_fc_{k}_enabled': True for k in ('btceth', 'h4', 'tf', 'rsi', 'macd', 'adx', 'level')}
ON2.update({'gate_touch_dir_fixed_enabled': True, 'gate_reversal_contra_enabled': False})
g['gate_on'] = lambda s, k: bool(ON2.get(k, False))
g['funnel_log'] = types.SimpleNamespace(ENABLED=False)
exec(ns['block'], g)
FLIP, ACTIVE, EVAL, SUM = g['_contra_flip_votes'], g['_contra_active'], g['_touch_eval_one'], g['_touch_summarize']

# ---- ۱) تابع معکوس‌کننده
votes = [{'key': k, 'label': k, 'vote': 'SELL', 'detail': 'x'} for k in ('btceth', 'h4', 'tf', 'rsi', 'macd', 'adx')]
votes += [{'key': 'level', 'label': 'level', 'vote': 'BUY', 'detail': ''}, {'key': 'vol', 'label': 'vol', 'vote': 'OK', 'detail': ''},
          {'key': 'tf', 'label': 'tf2', 'vote': None, 'detail': 'نامشخص'}]
before = json.dumps(votes, sort_keys=True)
out = FLIP(votes)
assert json.dumps(votes, sort_keys=True) == before, 'ورودی نباید تغییر کند'
d = {v['label']: v for v in out}
for k in ('btceth', 'tf', 'rsi', 'adx'):
    assert d[k]['vote'] == 'BUY' and d[k].get('flipped') and 'معکوس' in d[k]['detail'], k
for k in ('h4', 'macd'):
    assert d[k]['vote'] == 'SELL' and not d[k].get('flipped'), k
assert d['level']['vote'] == 'BUY' and d['vol']['vote'] == 'OK' and d['tf2']['vote'] is None and not d['tf2'].get('flipped')
print('flip helper OK')

# ---- ۲) جدول درستیِ _contra_active
s0 = {}
ON2['gate_reversal_contra_enabled'] = False
assert not ACTIVE(s0, '2', 'BUY')
ON2['gate_reversal_contra_enabled'] = True
assert ACTIVE(s0, '2', 'BUY') and ACTIVE(s0, '1', 'SELL') and ACTIVE(s0, '5', 'SELL') and ACTIVE(s0, '6', 'BUY')
assert not ACTIVE(s0, '3', 'BUY') and not ACTIVE(s0, '4', 'SELL'), 'ادامه‌ی روند (۳ و ۴) نباید معکوس شود'
assert not ACTIVE(s0, '2', None) and not ACTIVE(s0, None, 'BUY')
print('active truth table OK')

# ---- ۳) خلاصه‌ی رأی‌ها با همان مثالِ بازار ریزشی و خرید از حمایت
def run(scn, contra, fixed=True, sig='BUY'):
    ON2['gate_reversal_contra_enabled'] = contra
    ON2['gate_touch_dir_fixed_enabled'] = fixed
    ON2['gate_touch_pattern_vote_enabled'] = False
    S['touch_auto_mode'] = 'majority'
    st.update({'h4': 'BEARISH', 'tf': {'5min': 'BEARISH', '15min': 'BEARISH'}, 'btc': -2, 'eth': -1,
               'row': {'rsi': 40, 'macd_hist': -1.0, 'adx': 30, 'plus_di': 10, 'minus_di': 25, 'volume_ratio': 2.0, 'close': 99.0}})
    rec = {'id': 'r1', 'symbol': 'XYZ', 'tf': '5min', 'reason': f'x HVL=98.0 y', 'touch_sig': sig, 'scn': scn, 'created_at': time.time()}
    EVAL(1, rec)
    return rec


r = run('2', False)
assert (r['dir'], r['agree'], r['total'], r['auto_ok']) == ('BUY', 1, 3, False), r
assert r['contra'] == {'on': False, 'rev': True, 'n': ['BUY', 1, 3, 0], 'f': ['BUY', 3, 3, 1]}, r['contra']
print('off + reversal scenario: normal vote, counterfactual logged OK', r['contra'])

r = run('2', True)
assert (r['dir'], r['agree'], r['total'], r['auto_ok']) == ('BUY', 3, 3, True), r
assert r['contra'] == {'on': True, 'rev': True, 'n': ['BUY', 1, 3, 0], 'f': ['BUY', 3, 3, 1]}, r['contra']
fl = {v['key']: bool(v.get('flipped')) for v in r['votes']}
assert fl == {'btceth': True, 'h4': False, 'tf': True, 'rsi': True, 'macd': False, 'adx': True, 'level': False}, fl
print('on + reversal scenario: flipped vote passes OK', r['contra'])

r = run('3', True)
assert (r['agree'], r['total'], r['auto_ok']) == (1, 3, False), r
assert r['contra']['on'] is False and r['contra']['rev'] is False and r['contra']['f'] == [ 'BUY', 3, 3, 1], r['contra']
assert not any(v.get('flipped') for v in r['votes'])
print('on + continuation scenario: not applied, counterfactual still logged OK')

r = run('2', True, fixed=False)
assert 'contra' not in r and r['dir'] == 'SELL' and not any(v.get('flipped') for v in r['votes']), r
print('fixed-direction off: not applied OK')

r = run('1', True, sig='SELL')       # فروش از سقف در بازار ریزشی: رأی‌ها همه SELL و «کلوز سطح» پایین سطح → هم‌جهت؛ معکوس‌شدن مومنتوم نباید این را خراب کند
assert r['contra']['on'] is True and r['dir'] == 'SELL', r
print('sell reversal OK', r['contra'], 'agree', r['agree'], '/', r['total'])

# ---- ۴) ثبت قیف: فیلد cx و عوض‌شدن امضا
_src = open(os.path.join(HERE, 'bot.py'), encoding='utf-8').read()
_a = _src.index('def _fn_after_eval(')
_b = _src.index('\ndef _fn_touch_created(', _a)
emitted = []
fg = dict(json=json, time=time, funnel_log=types.SimpleNamespace(ENABLED=True), _fn_cf=lambda *a: {},
          _fn_emit=lambda chat, kind, **kw: emitted.append((kind, kw)))
exec(_src[_a:_b], fg)
rec = {'id': 'z', 'touch_sig': 'BUY', 'symbol': 'XYZ', 'created_at': time.time(), 'contra': {'on': False, 'rev': True, 'n': ['BUY', 1, 3, 0], 'f': ['BUY', 3, 3, 1]}}
summ = {'dir': 'BUY', 'agree': 1, 'total': 3, 'auto_ok': False, 'groups': {}}
fg['_fn_after_eval'](1, {'touch_auto_mode': 'majority'}, rec, [{'key': 'tf', 'status': 'against'}], [{'key': 'tf', 'vote': 'SELL'}], summ)
assert len(emitted) == 1 and emitted[0][1]['cx'] == rec['contra'], emitted
fg['_fn_after_eval'](1, {'touch_auto_mode': 'majority'}, rec, [{'key': 'tf', 'status': 'against'}], [{'key': 'tf', 'vote': 'SELL'}], summ)
assert len(emitted) == 1, 'بدون تغییر نباید دوباره ثبت شود'
rec['contra'] = dict(rec['contra'], f=['BUY', 2, 3, 1])
fg['_fn_after_eval'](1, {'touch_auto_mode': 'majority'}, rec, [{'key': 'tf', 'status': 'against'}], [{'key': 'tf', 'vote': 'SELL'}], summ)
assert len(emitted) == 2, 'تغییر در cx باید ثبت شود'
print('funnel cx field OK')

# ---- ۵) رجیستری: کلید هست، پیش‌فرض خاموش، در دسته‌ی آزمایشی
m = re.search(r"'gate_reversal_contra_enabled': \('([^']+)', (True|False), '([a-z_]+)'", _src)
assert m and m.group(2) == 'False' and m.group(3) == 'experimental', m and m.groups()
assert "BOT_VERSION = '3.44.88'" in _src
print('registry OK (default OFF, experimental)')
print('reversal_contra_selftest: ALL OK')
