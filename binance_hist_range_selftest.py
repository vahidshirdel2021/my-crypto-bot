"""تست آفلاین: سقف/کف تاریخی (مدل نصف‌کردن) اول از Binance گرفته می‌شود و فقط در نبودش به منبع قبلی برمی‌گردد.
اجرا:  python binance_hist_range_selftest.py"""
import os, re, json, time, math, asyncio, logging
os.environ['HALVING_RANGE_BYBIT'] = '0'; os.environ['HALVING_RANGE_OVERRIDE'] = '{"BTC":"off","ETH":"off"}'   # V3.44.92: این تست فقط زنجیره‌ی Binance را می‌سنجد
import pandas as pd

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("def _ohlcv_df(rows):"); b = src.index("# ===================== Bitunix Futures: داده‌ی عمومی")
block = src[a:b]
a2 = src.index("HALVING_RANGE_TTL = "); b2 = src.index("def _with_halving_cfg(")
block += "\n" + src[a2:b2]

class Resp:
    def __init__(self, status, payload): self.status_code = status; self.ok = status == 200; self._p = payload
    def json(self): return self._p

def kl(n, hi0=100.0, lo0=50.0):
    # n کندل [t, o, h, l, c, v]؛ سقف واقعی hi0 و کف واقعی lo0 فقط در «سایه» هستند
    rows = []
    for i in range(n):
        span = hi0 - lo0
        h = hi0 if i == n // 2 else lo0 + span * 0.8
        l = lo0 if i == n // 3 else lo0 + span * 0.2
        rows.append([1_600_000_000_000 + i * 604800000, lo0 + span * 0.5, h, l, lo0 + span * 0.55, 10.0])
    return rows

class Fake:
    def __init__(self): self.calls = []; self.script = {}; self.fallback_calls = []
FK = Fake()
state = {'down': set(), 'fails': {}, 'map': {'BTC': 'BTCUSDT', 'ABC': 'ABCUSDT'}}

def fake_get(url, params=None, timeout=None):
    FK.calls.append((url, dict(params or {})))
    host = 'vision' if 'binance.vision' in url else 'api'
    h = FK.script.get((host, params['interval']))
    if h is None: raise ConnectionError('no route')
    if isinstance(h, Exception): raise h
    return Resp(*h)

class R: get = staticmethod(fake_get)
def trip(src_): state['down'].add(src_)
g = dict(pd=pd, math=math, time=time, asyncio=asyncio, logger=logging.getLogger('t'), requests=R,
         _base_asset=lambda s: str(s).upper().replace('USDT', '').replace('/', ''),
         _binance_map_needs_refresh=lambda: False, _binance_refresh_symbol_map=lambda: None,
         _binance_symbol_from_cache=lambda base: state['map'].get(base),
         _BINANCE_SOURCES=('binance', 'binancevision'),
         _binance_base_url=lambda s: 'https://data-api.binance.vision' if s == 'binancevision' else 'https://api.binance.com',
         _source_available=lambda s: s not in state['down'], _source_trip=trip, _source_fail=lambda s: None, _source_ok=lambda s: None,
         _status_trips_source=lambda st: st in (403, 418, 429, 451) or st >= 500,
         os=os, json=json, Dict=dict, Any=object)
def old_klines(sym, tf, lim):
    FK.fallback_calls.append((sym, tf, lim)); return kl(30, 999.0, 1.0) and _df(kl(30, 999.0, 1.0))
def _df(rows):
    return pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
async def old_klines_async(http, sym, tf, lim): return old_klines(sym, tf, lim)
g.update(get_klines=old_klines, get_klines_async=old_klines_async)
exec(block, g)
sync, asyn, cache = g['get_halving_range_sync'], g['get_halving_range'], g['HALVING_RANGE_CACHE']

def reset():
    FK.calls.clear(); FK.fallback_calls.clear(); FK.script.clear(); state['down'].clear(); cache.clear()

# 1) Binance جواب بدهد: سقف/کف از سایه‌ها، بدون تماس با منبع قبلی
reset(); FK.script[('api', '1w')] = (200, kl(40, 123.5, 7.25))
assert sync('ABCUSDT') == (123.5, 7.25), sync('ABCUSDT')
assert not FK.fallback_calls and FK.calls[0][0].endswith('/api/v3/klines')
assert FK.calls[0][1] == {'symbol': 'ABCUSDT', 'interval': '1w', 'limit': 1000}
print('1 binance primary ok')

# 2) کش: بار دوم درخواستی نمی‌رود
n = len(FK.calls); assert sync('ABCUSDT') == (123.5, 7.25) and len(FK.calls) == n
print('2 cache ok')

# 3) نماد روی اسپات Binance نیست → برگشت به منبع قبلی (مقیاس قیمت منبع معاملاتی حفظ می‌شود)
reset(); r = sync('1000SHIBUSDT'); assert r == (999.0, 1.0) and FK.fallback_calls and not FK.calls
print('3 not-listed fallback ok')

# 4) ۴۵۱ روی api.binance.com → آینه‌ی vision جواب بدهد
reset(); FK.script[('api', '1w')] = (451, None); FK.script[('vision', '1w')] = (200, kl(40, 55.0, 5.0))
assert sync('ABCUSDT') == (55.0, 5.0) and 'binance' in state['down'] and not FK.fallback_calls
print('4 vision mirror ok')

# 5) هر دو شبکه‌خطا → برگشت به منبع قبلی
reset(); assert sync('ABCUSDT') == (999.0, 1.0) and FK.fallback_calls
print('5 network-fail fallback ok')

# 6) نماد خیلی تازه: هفتگی <۸ کندل → روزانه
reset(); FK.script[('api', '1w')] = (200, kl(5, 9.0, 1.0)); FK.script[('api', '1d')] = (200, kl(30, 8.0, 2.0))
assert sync('ABCUSDT') == (8.0, 2.0) and not FK.fallback_calls
print('6 new-listing daily ok')

# 7) نسخه‌ی async هم همین مسیر را دارد و کش می‌کند
reset(); FK.script[('api', '1w')] = (200, kl(40, 321.0, 3.0))
assert asyncio.run(asyn(None, 'BTCUSDT')) == (321.0, 3.0) and cache['BTCUSDT']['range'] == (321.0, 3.0) and not FK.fallback_calls
print('7 async ok')

# 8) داده‌ی خراب (کف ≤ ۰) رد می‌شود → برگشت به منبع قبلی
reset(); FK.script[('api', '1w')] = (200, kl(40, 10.0, 0.0)); FK.script[('vision', '1w')] = (200, kl(40, 10.0, 0.0))
assert sync('ABCUSDT') == (999.0, 1.0)
print('8 bad-data fallback ok')
print('ALL OK')
