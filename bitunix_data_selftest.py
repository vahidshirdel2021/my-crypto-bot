# -*- coding: utf-8 -*-
"""تست منطق داده‌ی بیتیونیکس (V3.44.56): پارس، کندل در حال تشکیل، صفحه‌بندی، نرخ‌گیر، ترتیب منابع و fallback به باینانس."""
import asyncio, logging, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import threading
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
src = open('bot.py', encoding='utf-8').read()

# ---------------------------------------------------------------- ۰) حذف Bybit/KuCoin و ترتیب پیش‌فرض
code_only = '\n'.join(l for l in src.split('\n') if not l.lstrip().startswith('#'))
hits = [l.strip() for l in code_only.split('\n') if re.search(r'bybit|kucoin', l, re.I) and '"""' not in l and '_MDS_RAW' not in l]
assert not hits, hits[:3]                                    # فقط در کامنت/توضیح و محافظ مقدار قدیمی .env (_MDS_RAW) نام می‌آید
assert "_ALL_DATA_SOURCES = ('bitunix', 'binance', 'binancevision')" in src
assert "'bitunix': 'BITUNIX', 'binance': 'BINANCE', 'binancevision': 'BINANCE'" in src

a = src.index("# ===================== Bitunix Futures: داده‌ی عمومی (V3.44.56)")
b = src.index("def _klines_usable(df, min_rows=60):")
BLOCK = src[a:b]
ai = src.index("def _ohlcv_df(rows):"); bi = src.index("def _binance_kline_df(payload):")
OHLCV = src[ai:bi]

class Resp:
    def __init__(self, status=200, body=None): self.status_code = status; self._b = body; self.ok = status == 200
    def json(self): return self._b

calls = []; sleeps = []; trips = []; fails = []; oks = []
state = {'handler': None, 'now': 1_700_000_000.0}
class FakeTime:
    def time(self): return state['now']
    def sleep(self, x): sleeps.append(x); state['now'] += x
class FakeRequests:
    def get(self, url, params=None, timeout=None):
        calls.append((url, dict(params or {}), state['now']))
        return state['handler'](url, dict(params or {}))
FT = FakeTime()
def base_ns():
    return dict(time=FT, pd=pd, requests=FakeRequests(), logger=logging.getLogger('bx'), RLock=RLock, threading=threading,
                ThreadPoolExecutor=ThreadPoolExecutor, BITUNIX_PUBLIC='https://fapi.bitunix.com', BITUNIX_MIN_GAP=0.125,
                BITUNIX_SYMBOLS_TTL=6 * 3600, BITUNIX_TICKERS_TTL=3.0,
                BITUNIX_INTERVAL_MAP={'5min': '5m', '15min': '15m', '1hour': '1h', '1day': '1d', '1month': '1M'},
                BITUNIX_TF_SECONDS={'5min': 300, '15min': 900, '1hour': 3600, '1day': 86400, '1month': 2592000},
                _status_trips_source=lambda st: st in (403, 418, 429, 451) or st >= 500,
                _source_trip=lambda s_, *a: trips.append(s_), _source_ok=lambda s_: oks.append(s_), _source_fail=lambda s_: fails.append(s_),
                _base_asset=lambda sy: str(sy).upper().replace('USDT', '').replace('/', ''))
g = base_ns(); exec(OHLCV, g); exec(BLOCK, g)

# ---------------------------------------------------------------- ۱) پارس نمادها و قیمت‌ها
pairs = {'code': 0, 'data': [
    {'symbol': 'BTCUSDT', 'base': 'BTC', 'quote': 'USDT', 'symbolStatus': 'OPEN', 'minTradeVolume': '0.0001', 'maxLeverage': 125, 'isApiSupported': True},
    {'symbol': 'ETHUSDT', 'base': 'ETH', 'quote': 'USDT', 'symbolStatus': 'OPEN'},
    {'symbol': 'OLDUSDT', 'base': 'OLD', 'quote': 'USDT', 'symbolStatus': 'STOP'},
    {'symbol': 'XYZUSDT', 'base': 'XYZ', 'quote': 'USDT', 'symbolStatus': 'CANCEL_ONLY'},
    {'symbol': '1000PEPEUSDT', 'base': '1000PEPE', 'quote': 'USDT', 'symbolStatus': 'OPEN'},
    {'symbol': 'BTCUSD', 'base': 'BTC', 'quote': 'USD', 'symbolStatus': 'OPEN'}]}
m, info = g['_parse_bitunix_pairs'](pairs)
assert m == {'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT', '1000PEPE': '1000PEPEUSDT'} and info['BTC']['api_supported'] is True, m
assert 'PEPE' not in m            # مقیاس ۱۰۰۰تایی با نماد معمولی قاطی نمی‌شود (قیمت‌ها ۱۰۰۰ برابر می‌شد)
assert g['_parse_bitunix_pairs']({'code': 1})[0] == {} and g['_parse_bitunix_pairs'](None)[0] == {}
tk = g['_parse_bitunix_tickers']({'code': 0, 'data': [{'symbol': 'BTCUSDT', 'lastPrice': '81000.5'}, {'symbol': 'ETHUSDT', 'last': '2000'}, {'symbol': 'BAD', 'lastPrice': 'x'}, {'symbol': 'ZERO', 'lastPrice': '0'}]})
assert tk == {'BTCUSDT': 81000.5, 'ETHUSDT': 2000.0}, tk

# ---------------------------------------------------------------- ۲) پارس کندل: ترتیب ورودی مهم نیست؛ خروجی صعودی
def kl(t0, n, step, base=100.0):
    return [{'open': str(base + i), 'high': str(base + i + 2), 'low': str(base + i - 1), 'close': str(base + i + 1), 'time': t0 + i * step, 'baseVol': '5', 'quoteVol': '1'} for i in range(n)]
rows = kl(1_000_000_000, 5, 300_000)
df = g['_bitunix_kline_df']({'code': 0, 'data': list(reversed(rows))})
assert list(df['timestamp']) == sorted(df['timestamp']) and len(df) == 5 and float(df['close'].iloc[-1]) == 105.0 and float(df['volume'].iloc[0]) == 5.0
assert g['_bitunix_kline_df']({'code': 2, 'data': rows}).empty and g['_bitunix_kline_df'](None).empty

# ---------------------------------------------------------------- ۳) کندل در حال تشکیل
secs = 300; now_ms = 1_700_000_000_000
t_last_closed = (now_ms // (secs * 1000)) * secs * 1000 - secs * 1000          # آخرین کندل بسته: یک دوره قبل از دوره‌ی جاری
closed = g['_ohlcv_df']([[t_last_closed - (9 - i) * secs * 1000, 100 + i, 102 + i, 99 + i, 101 + i, 1] for i in range(10)])
out = g['_bitunix_add_forming_candle'](closed, '5min', 112.5, now_ms=now_ms)
assert len(out) == 11 and int(out['timestamp'].iloc[-1]) == t_last_closed + secs * 1000
last = out.iloc[-1]
assert last['open'] == 110.0 and last['close'] == 112.5 and last['high'] == 112.5 and last['low'] == 110.0 and last['volume'] == 0.0
assert out.iloc[-2]['close'] == closed.iloc[-1]['close']                          # iloc[-2] همان آخرین کندل بسته است
dn = g['_bitunix_add_forming_candle'](closed, '5min', 105.0, now_ms=now_ms).iloc[-1]; assert dn['low'] == 105.0 and dn['high'] == 110.0 and dn['close'] == 105.0
flat = g['_bitunix_add_forming_candle'](closed, '5min', None, now_ms=now_ms).iloc[-1]; assert flat['open'] == flat['close'] == flat['high'] == flat['low'] == 110.0
# اگر API کندل در حال تشکیل را هم داده بود: دوباره اضافه نمی‌شود
forming = g['_ohlcv_df']([[t_last_closed + secs * 1000, 110, 113, 109, 112, 1]])
withf = pd.concat([closed, forming], ignore_index=True)
assert len(g['_bitunix_add_forming_candle'](withf, '5min', 112.0, now_ms=now_ms)) == 11
assert g['_bitunix_add_forming_candle'](closed, 'weird', 1.0) is closed or len(g['_bitunix_add_forming_candle'](closed, 'weird', 1.0)) == 10

# ---------------------------------------------------------------- ۴) نرخ‌گیر: فاصله‌ی حداقلی بین دو درخواست
calls.clear(); sleeps.clear(); state['now'] = 1_700_000_000.0
state['handler'] = lambda url, p: Resp(200, {'code': 0, 'data': []})
g['_bitunix_get']('/x'); g['_bitunix_get']('/x'); g['_bitunix_get']('/x')
assert len(calls) == 3 and len(sleeps) == 2 and all(abs(x - 0.125) < 1e-9 for x in sleeps), sleeps
gaps = [calls[i + 1][2] - calls[i][2] for i in range(2)]; assert all(x >= 0.125 - 1e-9 for x in gaps), gaps

# ---------------------------------------------------------------- ۵) صفحه‌بندی و نماد
g['_BITUNIX_SYMBOLS'].update(map={'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT'}, ts=state['now'])
all_rows = kl(t_last_closed - 449 * secs * 1000, 450, secs * 1000)               # ۴۵۰ کندل بسته‌ی پیوسته، آخری = t_last_closed
def kline_handler(url, p):
    if url.endswith('/kline'):
        assert p['symbol'] == 'BTCUSDT' and p['interval'] == '5m' and p['limit'] <= 200, p
        pool = [r for r in all_rows if p.get('endTime') is None or r['time'] <= p['endTime']]
        return Resp(200, {'code': 0, 'data': list(reversed(pool[-p['limit']:]))})
    if url.endswith('/tickers'):
        return Resp(200, {'code': 0, 'data': [{'symbol': 'BTCUSDT', 'lastPrice': '600.0'}]})
    raise AssertionError(url)
state['handler'] = kline_handler; calls.clear(); g['_BITUNIX_TICKERS'].update(ts=0.0, map={})
res = g['_bitunix_fetch_klines']('BTC', '5min', 450)
d5, st5, _pl = res
assert st5 == 200 and len(d5) == 451, len(d5)                                    # ۴۵۰ بسته + ۱ در حال تشکیل
kcalls = [c for c in calls if c[0].endswith('/kline')]
assert len(kcalls) == 3 and kcalls[0][1].get('endTime') is None and 'endTime' in kcalls[1][1] and 'endTime' in kcalls[2][1], kcalls
assert d5['timestamp'].is_monotonic_increasing and d5['timestamp'].is_unique
assert float(d5['close'].iloc[-1]) == 600.0 and int(d5['timestamp'].iloc[-1]) == t_last_closed + secs * 1000
# یک درخواست کافی است وقتی ≤ ۲۰۰ کندل خواسته شود
calls.clear(); g['_BITUNIX_TICKERS'].update(ts=0.0, map={})
d1, st1, _ = g['_bitunix_fetch_klines']('BTC', '5min', 160)
assert len([c for c in calls if c[0].endswith('/kline')]) == 1 and len(d1) == 161, len(d1)
# نماد ناموجود / تایم‌فریم ناشناخته => None؛ بدون فهرست نمادها حدس ساده
assert g['_bitunix_fetch_klines']('NOPE', '5min', 100) is None and g['_bitunix_fetch_klines']('BTC', '3min', 100) is None
g['_BITUNIX_SYMBOLS'].update(map={}); assert g['_bitunix_symbol_from_cache']('FOO') == 'FOOUSDT'
g['_BITUNIX_SYMBOLS'].update(map={'BTC': 'BTCUSDT'}); assert g['_bitunix_symbol_from_cache']('FOO') is None
# خطای HTTP: (خالی، کد، None)
state['handler'] = lambda url, p: Resp(429, None)
e, est, ep = g['_bitunix_fetch_klines']('BTC', '5min', 100); assert e.empty and est == 429 and ep is None

# ---------------------------------------------------------------- ۶) قیمت لحظه‌ای: یک درخواست برای همه، کش ۳ ثانیه‌ای، fallback تک‌نمادی
g['_BITUNIX_SYMBOLS'].update(map={'BTC': 'BTCUSDT', 'ETH': 'ETHUSDT'})
calls.clear(); g['_BITUNIX_TICKERS'].update(ts=0.0, map={})
state['handler'] = lambda url, p: Resp(200, {'code': 0, 'data': [{'symbol': 'BTCUSDT', 'lastPrice': '81000'}, {'symbol': 'ETHUSDT', 'lastPrice': '2000'}]})
assert g['_bitunix_price']('BTC') == 81000.0 and g['_bitunix_price']('ETH') == 2000.0 and len(calls) == 1
state['now'] += 5; assert g['_bitunix_price']('ETH') == 2000.0 and len(calls) == 2                # کش منقضی شد
assert g['_bitunix_price']('NOPE') is None
calls.clear(); g['_BITUNIX_TICKERS'].update(ts=0.0, map={})
state['handler'] = lambda url, p: Resp(200, {'code': 0, 'data': [{'symbol': 'ETHUSDT', 'lastPrice': '1999'}]}) if p.get('symbols') else Resp(200, {'code': 0, 'data': []})
assert g['_bitunix_price']('ETH') == 1999.0 and any('symbols' in c[1] for c in calls)

# ---------------------------------------------------------------- ۷) get_klines: ترتیب منابع و fallback
a2 = src.index("def get_klines(symbol, tf='5min', limit=200):"); b2 = src.index("async def get_klines_async(http, symbol, tf='5min', limit=200):")
c2 = src.index("def latest_price(symbol):"); d2 = src.index("# ===================== Binance USDⓈ-M Futures (V3.44.0)")
a3 = b2; b3 = src.index("def latest_price(symbol):", a3)
bn = {'n': 0}
def binance_df(n=120):
    return pd.DataFrame({'timestamp': range(n), 'open': [100.0 + i for i in range(n)], 'high': [102.0 + i for i in range(n)], 'low': [99.0 + i for i in range(n)], 'close': [101.0 + i for i in range(n)], 'volume': [1.0] * n})
def kenv(order, bitunix_result, binance_ok=True, avail=None):
    env = dict(time=time, pd=pd, logger=logging.getLogger('gk'), DATA_LOCK=RLock(), DATA_CACHE={}, DATA_CACHE_SECONDS=20, TIMEFRAME_MAP={'5min': '5min'},
               MARKET_DATA_SOURCES=order, _sources_now=lambda: order, _venue=lambda: 'binance', _BINANCE_SOURCES=('binance', 'binancevision'), _DATA_NOTES={}, _DATA_SOURCE_USED={}, _SYMBOL_MISS_UNTIL={}, _SOURCE_DOWN_UNTIL=dict(avail or {}),
               _base_asset=lambda sy: str(sy).upper().replace('USDT', ''), _source_available=lambda s_: time.time() >= (avail or {}).get(s_, 0), _symbol_missing=lambda s_, b_: False,
               _mark_symbol_missing=lambda s_, b_: env['_marked'].append((s_, b_)), _marked=[],
               _binance_map_needs_refresh=lambda: False, _binance_refresh_symbol_map=lambda: None,
               _bitunix_map_needs_refresh=lambda: False, _bitunix_refresh_symbol_map=lambda: None,
               _bitunix_fetch_klines=bitunix_result, _status_trips_source=lambda st: st in (403, 418, 429, 451) or st >= 500,
               _source_trip=lambda s_, *a: env['_trips'].append(s_), _trips=[], _source_ok=lambda s_: None, _source_fail=lambda s_: None,
               _klines_usable=lambda d, min_rows=60: d is not None and len(d) >= min_rows,
               _fail_note=lambda s_, st, pl: f'{s_}:fail_{st}',
               _kline_request=lambda source, symbol, tf, limit: ('http://x', {}, lambda payload: binance_df()) if source.startswith('binance') and binance_ok else None,
               requests=type('R', (), {'get': staticmethod(lambda url, params=None, timeout=None: (bn.__setitem__('n', bn['n'] + 1) or Resp(200, [])))})())
    exec(src[a2:b2], env)
    return env
ORDER = ['bitunix', 'binance', 'binancevision']
# الف) بیتیونیکس سالم => از همان می‌آید و باینانس صدا زده نمی‌شود
bn['n'] = 0; e1 = kenv(ORDER, lambda sy, tf, lim: (binance_df(130), 200, {'code': 0}))
d = e1['get_klines']('BTC', '5min', 120)
assert len(d) == 120 and e1['_DATA_SOURCE_USED']['BTC'] == 'bitunix' and bn['n'] == 0     # tail(limit)
# ب) نماد روی بیتیونیکس نیست => باینانس
e2 = kenv(ORDER, lambda sy, tf, lim: None); d = e2['get_klines']('FOO', '5min', 120)
assert len(d) == 120 and e2['_DATA_SOURCE_USED']['FOO'] == 'binance' and bn['n'] == 1
# پ) بیتیونیکس 429 => منبع موقتاً کنار می‌رود و باینانس جواب می‌دهد
e3 = kenv(ORDER, lambda sy, tf, lim: (pd.DataFrame(), 429, None)); d = e3['get_klines']('BTC', '5min', 120)
assert e3['_trips'] == ['bitunix'] and e3['_DATA_SOURCE_USED']['BTC'] == 'binance' and len(d) == 120
# ت) بیتیونیکس داده‌ی ناقص (<۶۰ کندل) => نماد برای بیتیونیکس «ناموجود» علامت می‌خورد و باینانس می‌آید
e4 = kenv(ORDER, lambda sy, tf, lim: (binance_df(30), 200, {'code': 0})); d = e4['get_klines']('NEW', '5min', 120)
assert ('bitunix', 'NEW') in e4['_marked'] and e4['_DATA_SOURCE_USED']['NEW'] == 'binance'
# ث) خطای شبکه‌ی بیتیونیکس (exception) => باینانس
def boom(sy, tf, lim): raise RuntimeError('net')
e5 = kenv(ORDER, boom); d = e5['get_klines']('BTC', '5min', 120); assert e5['_DATA_SOURCE_USED']['BTC'] == 'binance' and 'bitunix:network_error' not in e5['_DATA_NOTES']
# ج) همه ناموجود => DataFrame خالی و دلیل‌ها ثبت می‌شود
e6 = kenv(ORDER, lambda sy, tf, lim: None, binance_ok=False); d = e6['get_klines']('ZZZ', '5min', 120)
assert d.empty and e6['_DATA_NOTES']['ZZZ'][0] == 'bitunix:not_listed', e6['_DATA_NOTES']
# چ) فقط باینانس در MARKET_DATA_SOURCES => بیتیونیکس اصلاً صدا زده نمی‌شود
e7 = kenv(['binance'], boom); assert len(e7['get_klines']('BTC', '5min', 120)) == 120

# نسخه‌ی async همان ترتیب را دارد
async def run_async():
    def aenv(order, bres):
        env = kenv(order, bres)
        env.update(asyncio=asyncio, aiohttp=type('A', (), {'ClientTimeout': staticmethod(lambda total=None: None)}), ASYNC_SEMAPHORE=asyncio.Semaphore(2),
                   _BITUNIX_POOL=ThreadPoolExecutor(max_workers=2))
        exec(src[a3:b3], env); return env
    ea = aenv(ORDER, lambda sy, tf, lim: (binance_df(140), 200, {'code': 0}))
    d = await ea['get_klines_async'](None, 'BTC', '5min', 120); assert len(d) == 120 and ea['_DATA_SOURCE_USED']['BTC'] == 'bitunix'
    eb = aenv(ORDER, lambda sy, tf, lim: (pd.DataFrame(), 451, None))
    class Http:
        def get(self, url, params=None, timeout=None):
            class Ctx:
                async def __aenter__(s_): return type('Rsp', (), {'status': 200, 'json': staticmethod(lambda content_type=None: asyncio.sleep(0, result=[]))})()
                async def __aexit__(s_, *a): return False
            return Ctx()
    eb['_kline_request'] = lambda source, symbol, tf, limit: ('http://x', {}, lambda payload: binance_df(125)) if source.startswith('binance') else None
    d = await eb['get_klines_async'](Http(), 'BTC', '5min', 120)
    assert eb['_trips'] == ['bitunix'] and eb['_DATA_SOURCE_USED']['BTC'] == 'binance' and len(d) == 120, (eb['_trips'], eb['_DATA_SOURCE_USED'])
asyncio.run(run_async())

# ---------------------------------------------------------------- ۸) latest_price
a4 = src.index("def latest_price(symbol):"); b4 = src.index("# ===================== Binance USDⓈ-M Futures (V3.44.0)")
def penv(order, bprice, binance_price=None):
    env = dict(time=time, logger=logging.getLogger('lp'), DATA_LOCK=RLock(), PRICE_CACHE={}, MARKET_DATA_SOURCES=order, _sources_now=lambda: order, _venue=lambda: 'binance', _BINANCE_SOURCES=('binance', 'binancevision'),
               _base_asset=lambda sy: str(sy).upper().replace('USDT', ''), _source_available=lambda s_: True, _symbol_missing=lambda s_, b_: False,
               _binance_map_needs_refresh=lambda: False, _binance_refresh_symbol_map=lambda: None, _bitunix_map_needs_refresh=lambda: False, _bitunix_refresh_symbol_map=lambda: None,
               _bitunix_price=bprice, _status_trips_source=lambda st: False, _source_trip=lambda *a: None, _source_ok=lambda s_: None, _source_fail=lambda s_: None,
               _mark_symbol_missing=lambda *a: None, _price_request=lambda source, symbol: ('http://x', {}), _price_from_payload=lambda source, payload: binance_price,
               requests=type('R', (), {'get': staticmethod(lambda url, params=None, timeout=None: Resp(200, {}))})())
    exec(src[a4:b4], env); return env
assert penv(ORDER, lambda b_: 81000.0, 80990.0)['latest_price']('BTC') == 81000.0                    # بیتیونیکس اول
assert penv(ORDER, lambda b_: None, 80990.0)['latest_price']('BTC') == 80990.0                       # نبود قیمت => باینانس
def boomp(b_): raise RuntimeError('x')
assert penv(ORDER, boomp, 80990.0)['latest_price']('BTC') == 80990.0
assert penv(['binance'], boomp, 80990.0)['latest_price']('BTC') == 80990.0

# ---------------------------------------------------------------- ۹) لینک TradingView (V3.44.98: بر اساس صرافیِ حالت، نه آخرین منبع داده)
a5 = src.index("def tradingview_symbol(symbol, chat_id=None):"); b5 = src.index("def tradingview_chart_url(symbol, timeframe='5min', chat_id=None):")
ctx = {'v': 'binance'}; by_chat = {1: 'binance', 2: 'bitunix'}
tv = dict(_base_asset=lambda sy: str(sy).upper().replace('USDT', ''), TRADINGVIEW_EXCHANGE='', _venue=lambda: ctx['v'], data_venue_for=lambda c: by_chat.get(c, 'binance'),
          TV_EXCHANGE_MAP={'bitunix': 'BITUNIX', 'binance': 'BINANCE', 'binancevision': 'BINANCE'}, _bitunix_scale=lambda b: 1)
exec(src[a5:b5], tv)
assert tv['tradingview_symbol']('BTC') == 'BINANCE:BTCUSDT' and tv['tradingview_symbol']('BTC', 1) == 'BINANCE:BTCUSDT' and tv['tradingview_symbol']('BTC', 2) == 'BITUNIX:BTCUSDT.P'
ctx['v'] = 'bitunix'; assert tv['tradingview_symbol']('ETH') == 'BITUNIX:ETHUSDT.P'
tv['TRADINGVIEW_EXCHANGE'] = 'OKX'; assert tv['tradingview_symbol']('BTC') == 'OKX:BTCUSDT'

# ---------------------------------------------------------------- ۱۰) watchlist_tools
import watchlist_tools as wt
src_wt = open('watchlist_tools.py', encoding='utf-8').read()
assert not re.search(r'bybit|kucoin', src_wt, re.I) and 'fetch_bitunix_futures' in src_wt
wt._get = lambda url, params=None, timeout=12: {'code': 0, 'data': pairs['data'] + [{'symbol': 'SOLUSDT', 'base': 'SOL', 'quote': 'USDT', 'symbolStatus': 'OPEN'}]}
assert wt.fetch_bitunix_futures() == {'BTC', 'ETH', '1000PEPE', 'SOL'}
wt._get = lambda url, params=None, timeout=12: {'code': 7}
try: wt.fetch_bitunix_futures(); raise SystemExit('should fail')
except RuntimeError as exc: assert 'bitunix futures: code=7' in str(exc)
wt.fetch_bitunix_futures = lambda timeout=12: {'BTC', 'ETH'}; wt.fetch_binance_spot = lambda timeout=12: {'BTC', 'ETH', 'FOO'}
union, per, errors = wt.fetch_available(); assert list(per) == ['bitunix', 'binance'] and union == {'BTC', 'ETH', 'FOO'} and not errors
wt.fetch_bitunix_futures = lambda timeout=12: (_ for _ in ()).throw(RuntimeError('down'))
union, per, errors = wt.fetch_available(); assert list(per) == ['binance'] and 'bitunix' in errors and union == {'BTC', 'ETH', 'FOO'}
# ربات: گزارش نمادهای غایب روی بیتیونیکس
assert "report['not_on_bitunix']" in src and 'Watchlist vs Bitunix' in src

# ---------------------------------------------------------------- ۱۱) V3.44.98: MARKET_DATA_SOURCES با env محدود/مرتب نمی‌شود (صرافی را حالت تعیین می‌کند)
i0 = src.index("_ALL_DATA_SOURCES = ("); j0 = src.index('\n', src.index("MARKET_DATA_SOURCES = list(_ALL_DATA_SOURCES)"))
seg = src[i0:j0]
for env in ("binance,binancevision,bybit,kucoin", "binance", "", None):
    if env is None: os.environ.pop('MARKET_DATA_SOURCES', None)
    else: os.environ['MARKET_DATA_SOURCES'] = env
    ns = {'os': os}; exec(seg, ns); assert ns['MARKET_DATA_SOURCES'] == ['bitunix', 'binance', 'binancevision'], (env, ns['MARKET_DATA_SOURCES'])
os.environ.pop('MARKET_DATA_SOURCES', None)
env_ex = open('.env.example', encoding='utf-8').read()
assert not re.search(r'bybit|kucoin', env_ex.replace('Bybit و KuCoin حذف شدند', ''), re.I)
print('bitunix_data_selftest: ALL OK')
