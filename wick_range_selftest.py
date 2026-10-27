"""تست آفلاین V3.44.100: سایه‌ی غیرواقعی (کف 0.0001) از سقف/کف تاریخی حذف می‌شود.  اجرا: python wick_range_selftest.py"""
import os, math, logging
import pandas as pd
logger = logging.getLogger('t')
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("HALVING_RANGE_WICK_RATIO = "); b = src.index("_HIST_RANGE_SRC = {}")
exec(src[a:b])

def mk(n=40):
    rows = []
    for i in range(n):
        base = 1.0 + i * 0.05
        rows.append({'open': base, 'close': base * 1.02, 'high': base * 1.05, 'low': base * 0.95})
    return pd.DataFrame(rows)

d = mk(); d.loc[10, 'low'] = 0.0001                      # کندلی با بدنه ~1.5 و کف 0.0001 (خطای داده)
hi, lo = _halving_range_from_df(d)
assert abs(lo - mk()['low'].min()) < 1e-9, lo            # کف واقعیِ بقیه‌ی کندل‌ها
d = mk(); d.loc[5, 'high'] = 9999.0                      # سقفِ غیرواقعی
hi, lo = _halving_range_from_df(d); assert abs(hi - mk()['high'].max()) < 1e-9, hi
d = mk(); d.loc[7, 'low'] = d.loc[7, 'low'] * 0.3        # سایه‌ی واقعیِ بلند (۷۰٪ زیر) باید بماند
hi, lo = _halving_range_from_df(d); assert abs(lo - d['low'].min()) < 1e-9
HALVING_RANGE_WICK_RATIO = 0.0                           # فیلتر خاموش = رفتار قبلی
d = mk(); d.loc[10, 'low'] = 0.0001
assert _halving_range_from_df(d)[1] == 0.0001
print('wick_range_selftest OK')
