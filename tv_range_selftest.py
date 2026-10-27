"""تست آفلاین V3.44.92: سقف/کف مدل نصف‌کردن هم‌تراز با TradingView (جدول دستی > Bybit > Binance).
اجرا: python tv_range_selftest.py"""
import os, json, time, math, asyncio, logging
import pandas as pd
import halving_levels as hv

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("def _ohlcv_df(rows):"); b = src.index("# ===================== Bitunix Futures: داده‌ی عمومی")
block = src[a:b]
a2 = src.index("HALVING_RANGE_TTL = "); b2 = src.index("def _with_halving_cfg(")
block += "\n" + src[a2:b2]

class Resp:
    def __init__(self, status, payload): self.status_code = status; self.ok = status == 200; self._p = payload
    def json(self): return self._p
calls = []; script = {}
def fake_get(url, params=None, timeout=None):
    calls.append((url, dict(params or {})))
    host = 'bybit' if 'bybit' in url else 'binance'
    h = script.get(host)
    if h is None: raise ConnectionError('no route')
    return Resp(*h)
class R: get = staticmethod(fake_get)
down = set()
g = dict(pd=pd, math=math, time=time, asyncio=asyncio, json=json, os=os, logger=logging.getLogger('t'), requests=R,
         _base_asset=lambda s: str(s).upper().replace('USDT', '').replace('/', ''),
         _binance_map_needs_refresh=lambda: False, _binance_refresh_symbol_map=lambda: None,
         _binance_symbol_from_cache=lambda base: base + 'USDT',
         _BINANCE_SOURCES=('binance',), _binance_base_url=lambda s: 'https://api.binance.com',
         _source_available=lambda s: s not in down, _source_trip=lambda s, seconds=None: down.add(s),
         _source_fail=lambda s: None, _source_ok=lambda s: None,
         _status_trips_source=lambda st: st in (403, 418, 429, 451) or st >= 500,
         Dict=dict, Any=object)
g.update(get_klines=lambda *a: None)
async def _ak(*a): return None
g.update(get_klines_async=_ak)
os.environ.pop('HALVING_RANGE_OVERRIDE', None)
exec(block, g)
sync, cache, src_map = g['get_halving_range_sync'], g['HALVING_RANGE_CACHE'], g['_HIST_RANGE_SRC']
def reset(): calls.clear(); script.clear(); down.clear(); cache.clear(); src_map.clear()

# 1) ETH: جدول داخلی → سطوح دقیقاً همان چارت TradingView (±0.02)، بدون هیچ درخواست شبکه
reset(); hi, lo = sync('ETHUSDT'); assert not calls and src_map['ETHUSDT'][0] == 'Manual'
tv = [2216.04, 2247.90, 2279.76, 2311.61, 2343.47, 2375.33, 2407.19, 2439.04]
D = hv.choose_depth(hi, lo, 7.5, 4.0, 3, 10); assert D == 7, D
got = [round(x['price'], 2) for x in hv.levels_near(hi, lo, D, 2200, 2450)]
assert len(got) == len(tv) and all(abs(x - y) <= 0.03 for x, y in zip(got, tv)), got
depths = [x['depth'] for x in hv.levels_near(hi, lo, D, 2200, 2450)]; assert depths == [6, 7, 5, 7, 6, 7, 3, 7], depths
print('1 ETH matches TradingView levels ok')

# 2) BTC: همان رنج تأییدشده‌ی قبلی (فاصله‌ی عمق ۷ = ۹۶۳.۹۳)
reset(); hi, lo = sync('BTCUSDT'); assert abs(hv.spacing_at(hi, lo, 7) - 963.93) < 0.01
print('2 BTC range ok')

# 3) env بازنویسی می‌کند و "off" نماد را از جدول برمی‌دارد
reset(); os.environ['HALVING_RANGE_OVERRIDE'] = json.dumps({'ETHUSDT': [5000, 900], 'SOLUSDT': [300, 10], 'BTC': 'off'})
assert sync('ETHUSDT') == (5000.0, 900.0) and sync('SOLUSDT') == (300.0, 10.0)
os.environ['HALVING_RANGE_BYBIT'] = '0'; script['binance'] = (200, [[0, 0, 7, 6, 0, 0]] * 9)
os.environ.pop('HALVING_RANGE_OVERRIDE'); cache.clear(); print('3 env override ok')

# 4) نماد خارج از جدول: Bybit (کندل هفتگی، جدیدترین اول) سقف/کف را می‌دهد
reset(); g['BYBIT_RANGE_ENABLED'] = True
rows = [[str(1_700_000_000_000 - i * 604800000), '1', str(100 + (i == 5) * 25), str(20 - (i == 7) * 5), '1', '1', '1'] for i in range(40)]
script['bybit'] = (200, {'retCode': 0, 'result': {'list': rows}})
assert sync('ABCUSDT') == (125.0, 15.0) and src_map['ABCUSDT'][0] == 'Bybit'
assert calls[0][0].endswith('/v5/market/kline') and calls[0][1] == {'category': 'linear', 'symbol': 'ABCUSDT', 'interval': 'W', 'limit': 1000}
print('4 bybit weekly range ok')

# 5) Bybit بلاک (403) → منبع موقتاً خاموش و بدون خطا به Binance می‌رود
reset(); script['bybit'] = (403, None); script['binance'] = (200, [[1_600_000_000_000 + i, 5, 60 if i == 3 else 40, 8 if i == 4 else 20, 30, 1] for i in range(40)])
assert sync('ABCUSDT') == (60.0, 8.0) and 'bybit' in down and src_map['ABCUSDT'][0] == 'Binance'
print('5 bybit blocked -> binance ok')
print('ALL OK')
