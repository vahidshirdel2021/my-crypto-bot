"""تست آفلاین V3.44.120: داده‌ی بازارِ صرافی Binance فقط از «فیوچرز USDⓈ-M» (fapi) می‌آید، نه اسپات.
اجرا: python binance_futures_data_selftest.py"""
import os, re, logging, time
import pandas as pd
from threading import RLock

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
src = open('bot.py', encoding='utf-8').read()

# ---------------------------------------------------------------- ۰) هیچ مسیر اسپات در داده‌ی بازار نمانده
code = '\n'.join(l for l in src.split('\n') if not l.lstrip().startswith('#'))
assert '/api/v3/' not in code, 'endpoint اسپات باقی مانده'
assert "_BINANCE_SOURCES = ('binance',)" in src and "'binance': ('binance',)" in src, 'آینه‌ی اسپات هنوز در منابع هست'
assert "BINANCE_FUTURES = os.environ.get('BINANCE_FUTURES_URL', 'https://fapi.binance.com')" in src
wt_src = open('watchlist_tools.py', encoding='utf-8').read()
assert '/api/v3/' not in wt_src and '/fapi/v1/exchangeInfo' in wt_src
assert '/api/v3/' not in open('check_market_data.py', encoding='utf-8').read()

# ---------------------------------------------------------------- ۱) پارس exchangeInfo فیوچرز
a = src.index("_BINANCE_SYMBOL_ALIASES = {"); b = src.index("_BINANCE_WORKING_TYPE =")
c = src.index("def _split_futures_base(raw_base):"); d = src.index("def _binance_call(ex, method, path, params=None):")
e = src.index("def _binance_futures_entries(payload):"); f = src.index("def _binance_map_needs_refresh():")
g = dict(re=re)
exec(src[a:b] + "\n" + src[c:d] + "\n" + src[e:f], g)

def sym(base, symbol, ctype='PERPETUAL', status='TRADING', quote='USDT'):
    return {'baseAsset': base, 'symbol': symbol, 'contractType': ctype, 'status': status, 'quoteAsset': quote}
info = {'symbols': [
    sym('BTC', 'BTCUSDT'), sym('ETH', 'ETHUSDT'),
    sym('BTC', 'BTCUSDT_261225', ctype='CURRENT_QUARTER'),     # قرارداد سررسیددار: نباید بیاید
    sym('1000PEPE', '1000PEPEUSDT'), sym('1000SHIB', '1000SHIBUSDT'), sym('1000000MOG', '1000000MOGUSDT'),
    sym('LUNA2', 'LUNA2USDT'), sym('XRP', 'XRPUSDC', quote='USDC'), sym('OLD', 'OLDUSDT', status='SETTLING'),
    sym('SHIB', 'SHIBUSDT'),                                    # اگر هم SHIB و هم 1000SHIB بود: بدون پیشوند می‌ماند
    sym('1INCH', '1INCHUSDT'),
]}
m = g['_parse_binance_exchange_info'](info); sc = g['_parse_binance_scales'](info)
assert m['BTC'] == 'BTCUSDT' and m['PEPE'] == '1000PEPEUSDT' and sc['PEPE'] == 1000 and sc['BTC'] == 1
assert m['LUNA'] == 'LUNA2USDT' and m['MOG'] == '1000000MOGUSDT' and sc['MOG'] == 1000000
assert m['SHIB'] == 'SHIBUSDT' and sc['SHIB'] == 1, (m['SHIB'], sc['SHIB'])
assert '1INCH' in m and m['1INCH'] == '1INCHUSDT' and sc['1INCH'] == 1      # «1INCH» پیشوند ۱۰۰۰ نیست
assert 'OLD' not in m and 'XRP' not in m and list(m).count('BTC') == 1
print('1 exchangeInfo futures parse ok')

# ---------------------------------------------------------------- ۲) کش نماد/scale و درخواست کندل/قیمت
h = dict(g)
h.update(pd=pd, _BINANCE_SYMBOLS={'map': m, 'scale': sc, 'ts': 0.0, 'next_try': 0.0}, BINANCE_FUTURES='https://fapi.binance.com',
         _BINANCE_SOURCES=('binance',), BINANCE_INTERVAL_MAP={'5min': '5m', '1hour': '1h'},
         _base_asset=lambda s_: str(s_).upper().replace('USDT', '').replace('/', ''))
exec(src[src.index("def _binance_base_url(source):"):src.index("def _source_available(source):")], h)
exec(src[src.index("def _binance_symbol_from_cache(base):"):src.index("def _bitunix_get(path") if False else src.index("# ===================== Bitunix Futures: داده‌ی عمومی")], h)
exec(src[src.index("def _bitunix_unscale_df(df, scale):"):src.index("def _parse_bitunix_tickers(payload):")], h)
exec(src[src.index("def _kline_request(source, symbol, tf, limit):"):src.index("def get_klines(symbol, tf='5min', limit=200):")], h)
assert h['_binance_base_url']('binance') == 'https://fapi.binance.com'
assert h['_binance_symbol_from_cache']('PEPE') == '1000PEPEUSDT' and h['_binance_scale_from_cache']('PEPE') == 1000
assert h['_binance_symbol_from_cache']('NOPE') is None and h['_binance_scale_from_cache']('NOPE') == 1
url, params, parse = h['_kline_request']('binance', 'PEPEUSDT', '5min', 200)
assert url == 'https://fapi.binance.com/fapi/v1/klines' and params['symbol'] == '1000PEPEUSDT' and params['interval'] == '5m'
rows = [[1000 * i, '12.0', '14.0', '11.0', '13.0', '5'] + [0] * 6 for i in range(3)]
df = parse(rows)
assert abs(df['close'].iloc[-1] - 0.013) < 1e-12 and abs(df['high'].iloc[0] - 0.014) < 1e-12 and df['volume'].iloc[0] == 5000.0
url, params, parse = h['_kline_request']('binance', 'BTCUSDT', '5min', 200)
assert params['symbol'] == 'BTCUSDT' and parse(rows)['close'].iloc[-1] == 13.0       # نماد عادی دست‌نخورده
assert h['_kline_request']('binance', 'NOPEUSDT', '5min', 200) is None
url, params = h['_price_request']('binance', 'PEPEUSDT')
assert url == 'https://fapi.binance.com/fapi/v1/ticker/price' and params == {'symbol': '1000PEPEUSDT'}
print('2 futures kline/price request + 1000x scaling ok')

# ---------------------------------------------------------------- ۳) latest_price: قیمت فیوچرز ÷ scale
class Resp:
    def __init__(s_, st, p): s_.status_code = st; s_.ok = st == 200; s_._p = p
    def json(s_): return s_._p
la = src.index("def latest_price(symbol):"); lb = src.index("# ===================== Binance USDⓈ-M Futures (V3.44.0)")
seen = []
def fake_get(url, params=None, timeout=None):
    seen.append((url, dict(params or {})))
    return Resp(200, {'symbol': params['symbol'], 'price': '0.0125' if params['symbol'].startswith('1000') else '81000.5'})
pe = dict(time=time, logger=logging.getLogger('p'), DATA_LOCK=RLock(), PRICE_CACHE={}, _sources_now=lambda: ['binance'], _venue=lambda: 'binance',
          _BINANCE_SOURCES=('binance',), _base_asset=h['_base_asset'], _source_available=lambda s_: True, _symbol_missing=lambda s_, b_: False,
          _binance_map_needs_refresh=lambda: False, _binance_refresh_symbol_map=lambda: None, _bitunix_map_needs_refresh=lambda: False,
          _bitunix_refresh_symbol_map=lambda: None, _status_trips_source=lambda st: False, _source_trip=lambda *a: None, _source_ok=lambda s_: None,
          _source_fail=lambda s_: None, _mark_symbol_missing=lambda *a: None, _price_request=h['_price_request'],
          _price_from_payload=h['_price_from_payload'], _binance_scale_from_cache=h['_binance_scale_from_cache'],
          requests=type('R', (), {'get': staticmethod(fake_get)})())
exec(src[la:lb], pe)
assert abs(pe['latest_price']('PEPE') - 0.0000125) < 1e-15, pe['latest_price']('PEPE')     # ۰٫۰۱۲۵ ÷ ۱۰۰۰
assert pe['latest_price']('BTC') == 81000.5
assert all('/fapi/v1/ticker/price' in u for u, _ in seen), seen
print('3 latest_price futures + scale ok')

# ---------------------------------------------------------------- ۴) watchlist_tools: فهرست Binance = فیوچرز (نام‌های ×۱۰۰۰ به نام ربات)
import watchlist_tools as wt
calls = []
def fake_wt_get(url, params=None, timeout=12):
    calls.append((url, params)); return info
wt._get = fake_wt_get
av = wt.fetch_binance_futures()
assert calls == [('https://fapi.binance.com/fapi/v1/exchangeInfo', None)], calls
assert {'BTC', 'ETH', 'PEPE', '1000PEPE', 'SHIB', 'LUNA', '1INCH', 'MOG'} <= av and 'XRP' not in av and 'OLD' not in av, av
assert wt.fetch_binance_spot is wt.fetch_binance_futures       # نام قدیمی (سازگاری)
print('4 watchlist futures list ok')
print('binance_futures_data_selftest: ALL OK')
