# -*- coding: utf-8 -*-
"""V3.44.165 selftest: ثبت سمت BTC/ETH/SOL نسبت به سطح خودشان + بخش ۷ گزارش قیف."""
import json, os, re, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'bot.py'), encoding='utf-8').read()

# 1) امضای btc_front_level_info: پارامتر symbol با پیش‌فرض BTC و هیچ 'BTC' سخت‌کدشده‌ای داخل بدنه‌اش نمانده
a = src.index("def btc_front_level_info(")
b = src.index("def _gate_label(key):")
body = src[a:b]
assert "symbol='BTC')" in body.split('\n')[0], body.split('\n')[0]
code_only = '\n'.join(l for l in body.split('\n') if not l.strip().startswith('#') and '"""' not in l)
assert "get_klines('BTC'" not in code_only and "get_halving_range_sync('BTC')" not in code_only and "_log_grid_levels_sync('BTC')" not in code_only
assert "get_klines(symbol, tf, limit)" in body and "ckey = (symbol," in body

# 2) _core3_sides با نسخه‌ی ساختگی btc_front_level_info
a = src.index("def _core3_sides(")
b = src.index("def _fn_core3_stamp(")
calls = []
fake = {'BTC': (68255.1, 68746.0), 'ETH': (1929.87, 1949.84), 'SOL': (79.30, 79.30)}
def fake_info(s, tf, is_long, symbol='BTC'):
    calls.append(symbol)
    if symbol not in fake:
        return None
    c, r = fake[symbol]
    return {'close': c, 'ref_price': r}
g = {'btc_front_level_info': fake_info}
exec(src[a:b], g)
r = g['_core3_sides']('15min', {})
assert r == {'BTC': 'D', 'ETH': 'D', 'SOL': 'E'}, r
assert calls == ['BTC', 'ETH', 'SOL']
fake['SOL'] = (81.0, 79.3); fake['ETH'] = (2000.0, 1949.84)
assert g['_core3_sides']('15min', {}) == {'BTC': 'D', 'ETH': 'U', 'SOL': 'U'}
def boom(s, tf, is_long, symbol='BTC'):
    raise RuntimeError('x')
g['btc_front_level_info'] = boom
assert g['_core3_sides']('15min', {}) == {'BTC': None, 'ETH': None, 'SOL': None}     # خطا = None، هیچ‌وقت پرتاب نمی‌شود

# 3) رویداد core3 فقط ثبت است: بدون هیچ gate_on/بلاک در _fn_core3_stamp
a = src.index("def _fn_core3_stamp(")
b = src.index("def _fn_fvgv(")
stamp = src[a:b]
assert 'gate_on' not in stamp and 'return False' not in stamp and "threading.Thread(target=_run" in stamp and "'core3'" in stamp

# 4) بخش ۷ گزارش قیف
import funnel_report as FR
tmp = tempfile.mkdtemp(); now = time.time(); ev = []
def add(kind, **k):
    ev.append({'ts': now - 100 + len(ev) * 0.01, 'kind': kind, 'preset': '3', **k})
# (tid, جهت، c3، نتیجه، R)
specs = [
    ('a1', 'SELL', {'BTC': 'D', 'ETH': 'D', 'SOL': 'D'}, 'tp', 1.5),      # هر سه هم‌جهت
    ('a2', 'SELL', {'BTC': 'D', 'ETH': 'D', 'SOL': 'D'}, 'tp', 1.5),
    ('b1', 'SELL', {'BTC': 'U', 'ETH': 'U', 'SOL': 'D'}, 'tp', 2.0),      # SOL هم‌جهت، BTC/ETH مخالف
    ('c1', 'SELL', {'BTC': 'D', 'ETH': 'D', 'SOL': 'U'}, 'sl', -1.0),     # SOL مخالف
    ('c2', 'BUY',  {'BTC': 'D', 'ETH': 'U', 'SOL': 'D'}, 'sl', -1.0),     # خرید، SOL مخالف
    ('d1', 'BUY',  {'BTC': 'U', 'ETH': 'U', 'SOL': 'E'}, 'tp', 1.0),      # SOL روی سطح
]
for i, (tid, side, c3, out, rr) in enumerate(specs):
    add('touch', tid=tid, symbol='XRPUSDT', touch_sig=side, scn='1', level_token='HVL', level_value=100 + i, ts=now - 100 + i)
    add('vote', tid=tid, cf={})
    add('core3', tid=tid, c3=c3)
    add('shadow', tid=tid, sk='touch', outcome=out, r_end=rr)
with open(os.path.join(tmp, 'funnel_t.jsonl'), 'w', encoding='utf-8') as f:
    for e in ev:
        f.write(json.dumps(e, ensure_ascii=False) + '\n')
txt = FR.build_report(tmp, days=1, now=now + 10)
assert '۷) سمت BTC' in txt, txt[-800:]
sec = txt[txt.index('۷) سمت BTC'):]
assert '۳ از ۳ هم‌جهت: `۲`' in sec, sec
assert 'SOL هم‌جهت ولی BTC یا ETH هم‌جهت نیست: `۱`' in sec, sec
assert 'SOL مخالف: `۲`' in sec, sec
assert 'SOL روی سطح یا نامشخص: `۱`' in sec, sec
# بدون هیچ core3 → پیام خالی، بدون خطا
tmp2 = tempfile.mkdtemp()
with open(os.path.join(tmp2, 'funnel_t.jsonl'), 'w', encoding='utf-8') as f:
    for e in ev:
        if e['kind'] != 'core3':
            f.write(json.dumps(e, ensure_ascii=False) + '\n')
assert 'هنوز برخوردی با ثبت سمت سه نماد نداریم' in FR.build_report(tmp2, days=1, now=now + 10)
print('core3_selftest OK')
