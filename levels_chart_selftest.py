"""تست آفلاین V3.44.93: چارت PNG «سطوح ربات» (۳ بالا / ۳ پایین) + قفل نقش.  اجرا: python levels_chart_selftest.py"""
import os, io, logging
import numpy as np, pandas as pd
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
import halving_levels as hv
import access_policy as ap

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("def render_levels_chart_png("); b = src.index("def symbol_levels_chart(")
block = src[a:b]
def fmt(v): return f'{float(v):,.2f}'
def _pct_from(p, l): return f"{(float(l)/float(p)-1)*100:+.1f}%"
def _hv_level_label(dp): return f'HV d{int(dp)}'
g = dict(plt=plt, io=io, fmt=fmt, _pct_from=_pct_from, _hv_level_label=_hv_level_label, logger=logging.getLogger('t'))
exec(block, g)

# داده‌ی مصنوعی شبیه ETH 15m با رنج TradingView
H, L = 4955.87, 878.0
rng = np.random.default_rng(1)
close = 2311 + np.cumsum(rng.normal(0, 4, 300))
d = pd.DataFrame({'open': close + rng.normal(0, 2, 300), 'close': close})
d['high'] = d[['open', 'close']].max(axis=1) + abs(rng.normal(0, 3, 300))
d['low'] = d[['open', 'close']].min(axis=1) - abs(rng.normal(0, 3, 300))
price = float(d['close'].iloc[-1])
lv = hv.levels_near(H, L, 7, price - 400, price + 400)
up = [x for x in lv if x['price'] > price][:3]; dn = list(reversed([x for x in lv if x['price'] <= price]))[:3]
assert len(up) == 3 and len(dn) == 3
png = g['render_levels_chart_png']('ETHUSDT', d, price, up, dn, '15م', 7, hv.spacing_at(H, L, 7), 'Range: manual/TV')
assert png is not None and png.read(8) == b'\x89PNG\r\n\x1a\n'
png.seek(0); open('/tmp/levels_chart_test.png', 'wb').write(png.read())
assert g['render_levels_chart_png']('X', d.head(2), price, up, dn, '15م', 7, 1.0) is None     # داده‌ی کم → None، بدون خطا
print('1 render ok')

# قفل نقش: /lvc_ و /lv_ برای کاربر عادی بسته، برای ادمین (غیرمحدود) باز
assert not ap.user_command_allowed('/lvc_ETHUSDT') and not ap.user_command_allowed('/lv_ETHUSDT')
assert 'if is_restricted_user(chat_id):' in src[src.index("startswith('/lvc_')"):src.index("startswith('/lvc_')") + 200]
assert "'/lv_', '/lvc_'" in src
print('2 role lock ok')
print('ALL OK')
