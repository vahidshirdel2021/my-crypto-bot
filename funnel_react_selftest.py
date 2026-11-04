"""V3.44.139: برچسب «واکنش قیمت به سطح» (held/broke/chop) در funnel_log. اجرا: python3 funnel_react_selftest.py"""
import sys, os, time, tempfile
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import funnel_log as fl
fl.configure(tempfile.mkdtemp())

TF = 900
T0 = 1_800_000_000 // TF * TF          # شروعِ کندل برخورد
def df_from(candles):
    rows = []
    for i, (o, h, l, c) in enumerate(candles):
        rows.append({'timestamp': (T0 + (i - 2) * TF) * 1000.0, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': 100.0})
    return pd.DataFrame(rows)

def run(side, candles, level=100.0, sl=99.0, entry=100.2):
    d = df_from(candles)
    ts = d['timestamp'].astype('float64') / 1000.0
    x = {'side': side, 'level': level, 'entry': entry, 'sl': sl, 'start_ts': T0 + 120, 'tfs': TF}
    return fl._evaluate_reaction(x, d, ts)

pad = [(100, 100.1, 99.9, 100)] * 2                 # دو کندل قبل از برخورد
flat = (100.3, 100.5, 100.1, 100.3)

# BUY: نگه داشت. کندل برخورد با دُم پایین، بعد صعود تا +۱R (risk=1.2)
r = run('BUY', pad + [(100.3, 100.4, 99.7, 100.35), (100.35, 100.8, 100.3, 100.7), (100.7, 101.6, 100.6, 101.5)] + [flat] * 8)
assert r['label'] == 'held' and r['k_res'] == 2 and r['ok3'] >= 2 and r['c0']['rej_wick'] > 0.5 and r['c0']['pen_r'] > 0, r
# BUY: شکست. کلوز پشت سطح، سپس ادامه‌ی سقوط (حیوان درنده)
r = run('BUY', pad + [(100.3, 100.4, 99.9, 100.2), (100.2, 100.25, 99.5, 99.7), (99.7, 99.8, 98.4, 98.5)] + [(98.5, 98.6, 98.3, 98.4)] * 8)
assert r['label'] == 'broke' and r['k_res'] == 1 and r['run_r'] >= 1.0 and r['c'][0] < 0, r
# SELL: متقارن. سطح ۱۰۰، مقاومت؛ قیمت پایین می‌آید
r = run('SELL', pad + [(99.8, 100.3, 99.6, 99.7), (99.7, 99.75, 99.3, 99.4), (99.4, 99.5, 98.5, 98.6)] + [(98.6, 98.7, 98.4, 98.5)] * 8, entry=99.8, sl=101.0)
assert r['label'] == 'held' and r['ok3'] >= 2, r
r = run('SELL', pad + [(99.8, 100.3, 99.6, 99.9), (99.9, 100.6, 99.9, 100.5), (100.5, 101.7, 100.4, 101.6)] + [(101.6, 101.7, 101.5, 101.6)] * 8, entry=99.8, sl=101.0)
assert r['label'] == 'broke' and r['run_r'] >= 1.0, r
# چاپ: نه نگه داشت نه شکست
r = run('BUY', pad + [(100.3, 100.5, 100.0, 100.3)] * 10)
assert r['label'] == 'chop' and r['k_res'] is None and not r['partial'], r
# ناقص (کندل‌های بعد کم است)
r = run('BUY', pad + [(100.3, 100.5, 100.0, 100.3)] * 3)
assert r['partial'] is True and r['n_after'] == 2, r
# بدون سطح / بدون کندل
assert fl._evaluate_reaction({'side': 'BUY', 'level': None, 'entry': 1, 'sl': 0.9, 'start_ts': T0, 'tfs': TF}, df_from(pad), df_from(pad)['timestamp'] / 1000.0)['label'] == 'void'

# مسیر کامل ثبت ← شبیه‌ساز ← رویداد react (نه shadow)
events = []
fl.emit = lambda kind, **kw: events.append((kind, kw))
fl.ENABLED = True
fl._SHADOW[:] = []; fl._SHADOW_LOADED = True
fl._save_pending = lambda: None; fl._load_pending = lambda: None
assert fl.shadow_register('t1', 'react', {'chat': 1, 'preset': '3'}, 'ABC', 'BUY', 100.2, 99.0, 102.0, '15min', TF, start_ts=T0 + 120, level=100.0, due_s=11 * TF)
assert not fl.shadow_register('t1', 'react', {}, 'ABC', 'BUY', 100.2, 99.0, 102.0, '15min', TF, start_ts=T0 + 120, level=100.0)   # تکراری
item = fl._SHADOW[0]; assert abs(item['due'] - (T0 + 120 + 11 * TF)) < 1 and item['level'] == 100.0
item['due'] = 0
d = df_from(pad + [(100.3, 100.4, 99.7, 100.35), (100.35, 100.8, 100.3, 100.7), (100.7, 101.6, 100.6, 101.5)] + [flat] * 8)
fl._start_threads = lambda: None
n = fl.shadow_run_once(lambda sym, tf, k: d)
assert n == 1 and events and events[-1][0] == 'react' and events[-1][1]['label'] == 'held' and events[-1][1]['tid'] == 't1' and events[-1][1]['chat'] == 1, events
# shadow عادی همچنان کار می‌کند و با react قاطی نمی‌شود
events.clear()
assert fl.shadow_register('t2', 'touch', {'chat': 1}, 'ABC', 'BUY', 100.2, 99.0, 102.0, '15min', TF, start_ts=T0 + 120)
fl._SHADOW[-1]['due'] = 0
fl.shadow_run_once(lambda sym, tf, k: d)
assert events and events[-1][0] == 'shadow' and events[-1][1]['sk'] == 'touch', events
print('funnel_react_selftest ALL OK')
