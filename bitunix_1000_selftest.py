# -*- coding: utf-8 -*-
"""V3.44.112: نمادهای ۱۰۰۰تایی بیتیونیکس (1000PEPE, 1000SHIB, ...) برای نام‌های اسپات‌گونه‌ی ربات (PEPE, SHIB, ...):
نگاشت نماد، تقسیم قیمت/کندل بر ۱۰۰۰، سقف/کف تاریخی هم‌مقیاس، چارت TradingView از اسپات و گزارش واچ‌لیست."""
import logging, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from threading import RLock
import threading
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
src = open('bot.py', encoding='utf-8').read()
a = src.index("# ===================== Bitunix Futures: داده‌ی عمومی (V3.44.56)"); b = src.index("def _klines_usable(df, min_rows=60):")
BLOCK = src[a:b]
OHLCV = src[src.index("def _ohlcv_df(rows):"):src.index("def _binance_kline_df(payload):")]

class Resp:
    def __init__(self, status=200, body=None): self.status_code = status; self._b = body; self.ok = status == 200
    def json(self): return self._b
now = {'t': 1_700_000_000.0}
class FT:
    def time(self): return now['t']
    def sleep(self, x): now['t'] += x
def handler(url, params):
    if url.endswith('/kline'):
        rows = [{'time': 1_699_000_000_000 + i * 300_000, 'open': 0.01, 'high': 0.012, 'low': 0.009, 'close': 0.011, 'baseVol': 5} for i in range(80)]   # قیمتِ فیوچرز (۱۰۰۰PEPE ≈ ۰٫۰۱۱)
        return Resp(200, {'code': 0, 'data': rows})
    if url.endswith('/tickers'):
        return Resp(200, {'code': 0, 'data': [{'symbol': '1000PEPEUSDT', 'lastPrice': '0.0123'}, {'symbol': 'BTCUSDT', 'lastPrice': '81000'},
                                              {'symbol': '1INCHUSDT', 'lastPrice': '0.3'}]})
    return Resp(404, None)
class FR:
    def get(self, url, params=None, timeout=None): return handler(url, dict(params or {}))
g = dict(time=FT(), pd=pd, requests=FR(), logger=logging.getLogger('b1000'), RLock=RLock, threading=threading, ThreadPoolExecutor=ThreadPoolExecutor,
         BITUNIX_PUBLIC='https://fapi.bitunix.com', BITUNIX_MIN_GAP=0.0, BITUNIX_SYMBOLS_TTL=6 * 3600, BITUNIX_TICKERS_TTL=3.0,
         BITUNIX_INTERVAL_MAP={'5min': '5m', '1day': '1d', '1week': '1w'}, BITUNIX_TF_SECONDS={'5min': 300},
         _status_trips_source=lambda st: False, _source_trip=lambda *a, **k: None, _source_ok=lambda s: None, _source_fail=lambda s: None,
         _base_asset=lambda sy: str(sy).upper().replace('USDT', '').replace('/', ''))
exec(OHLCV, g); exec(BLOCK, g)
g['_BITUNIX_SYMBOLS'].update(map={'BTC': 'BTCUSDT', '1000PEPE': '1000PEPEUSDT', '1000SHIB': '1000SHIBUSDT', '10000SATS': '10000SATSUSDT',
                                  '1INCH': '1INCHUSDT', '1000BONK': '1000BONKUSDT', 'SHIB': 'SHIBUSDT'}, ts=now['t'])
R = g['_bitunix_resolve']
# ۱) نگاشت: نام عادی عیناً، بعد پیشوندها؛ ناموجود None
assert R('BTC') == ('BTCUSDT', 1) and R('pepe') == ('1000PEPEUSDT', 1000) and R('BONK') == ('1000BONKUSDT', 1000)
assert R('SATS') == ('10000SATSUSDT', 10000) and R('1INCH') == ('1INCHUSDT', 1)          # 1INCH واقعاً نام خودش است، پیشوند نیست
assert R('SHIB') == ('SHIBUSDT', 1)                                                      # اگر نام عیناً هست، همان (اولویت با نام دقیق)
assert R('NOPE') == (None, 1) and g['_bitunix_symbol_from_cache']('PEPE') == '1000PEPEUSDT' and g['_bitunix_scale']('PEPE') == 1000
assert R('1000PEPE') == ('1000PEPEUSDT', 1)                                              # اگر کسی خودش 1000PEPE نوشت: بدون تغییر مقیاس
g['_BITUNIX_SYMBOLS'].update(map={}); assert R('FOO') == ('FOOUSDT', 1)                  # لیست نمادها نیامده: حدس ساده مثل قبل
g['_BITUNIX_SYMBOLS'].update(map={'BTC': 'BTCUSDT', '1000PEPE': '1000PEPEUSDT', '1INCH': '1INCHUSDT'}, ts=now['t'])
# ۲) قیمت لحظه‌ای ÷۱۰۰۰
assert abs(g['_bitunix_price']('PEPE') - 0.0000123) < 1e-12 and g['_bitunix_price']('BTC') == 81000.0 and g['_bitunix_price']('NOPE') is None
# ۳) کندل‌ها ÷۱۰۰۰ (قیمت) و ×۱۰۰۰ (حجم)، کندل در حال تشکیل هم‌مقیاس
df, st, _ = g['_bitunix_fetch_klines']('PEPE', '5min', 60)
assert st == 200 and abs(df['close'].iloc[0] - 0.000011) < 1e-12 and abs(df['high'].iloc[0] - 0.000012) < 1e-12 and df['volume'].iloc[0] == 5000
assert df['close'].iloc[-1] == g['_bitunix_price']('PEPE') and df['high'].max() < 0.0001                       # آخرین ردیف = قیمتِ لحظه‌ایِ ÷۱۰۰۰
dfb, _, _ = g['_bitunix_fetch_klines']('BTC', '5min', 60); assert abs(dfb['close'].iloc[0] - 0.011) < 1e-12 and dfb['volume'].iloc[0] == 5   # نماد عادی دست‌نخورده
assert g['_bitunix_fetch_klines']('NOPE', '5min', 60) is None
# ۴) unscale دست‌نخورده برای scale=1 / df خالی
x = pd.DataFrame({'open': [2.0], 'high': [3.0], 'low': [1.0], 'close': [2.0], 'volume': [7.0]})
assert g['_bitunix_unscale_df'](x, 1) is x and g['_bitunix_unscale_df'](pd.DataFrame(), 1000).empty
y = g['_bitunix_unscale_df'](x, 1000); assert y['close'].iloc[0] == 0.002 and y['volume'].iloc[0] == 7000.0 and x['close'].iloc[0] == 2.0   # df اصلی تغییر نمی‌کند
# ۵) TradingView: ۱۰۰۰تایی => اسپات (بدون .P)، بقیه فیوچرز
a5 = src.index("def tradingview_symbol(symbol, chat_id=None):"); b5 = src.index("def tradingview_chart_url(symbol, timeframe='5min', chat_id=None):")
ctx = {'v': 'bitunix'}
tv = dict(_base_asset=lambda sy: str(sy).upper().replace('USDT', ''), TRADINGVIEW_EXCHANGE='', _venue=lambda: ctx['v'], data_venue_for=lambda c: ctx['v'],
          TV_EXCHANGE_MAP={'bitunix': 'BITUNIX', 'binance': 'BINANCE', 'binancevision': 'BINANCE'}, _bitunix_scale=g['_bitunix_scale'])
exec(src[a5:b5], tv)
assert tv['tradingview_symbol']('PEPE') == 'BITUNIX:PEPEUSDT' and tv['tradingview_symbol']('BTC') == 'BITUNIX:BTCUSDT.P' and tv['tradingview_symbol']('1INCH') == 'BITUNIX:1INCHUSDT.P'
ctx['v'] = 'binance'; assert tv['tradingview_symbol']('PEPE') == 'BINANCE:PEPEUSDT'
ctx['v'] = 'bitunix'; tv['TRADINGVIEW_EXCHANGE'] = 'OKX'; assert tv['tradingview_symbol']('PEPE') == 'OKX:PEPEUSDT'
# ۶) سقف/کف تاریخی ÷۱۰۰۰ (کد منبع)
assert re.search(r"_halving_range_from_df\(_bitunix_unscale_df\(", src) and "sym, scale = _bitunix_resolve(base)" in src
# ۷) واچ‌لیست
import watchlist_tools as wt
av = {'BTC', '1000PEPE', '10000SATS', '1INCH'}
assert wt.on_bitunix('PEPE', av) and wt.on_bitunix('SATS', av) and wt.on_bitunix('BTC', av) and wt.on_bitunix('1INCH', av) and not wt.on_bitunix('NOPE', av)
assert "watchlist_tools.on_bitunix(x, per['bitunix'])" in src
print('bitunix_1000_selftest: ALL OK')
