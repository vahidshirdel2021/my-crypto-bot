"""تست آفلاین V3.44.98 (+V3.44.108): صرافیِ داده = صرافیِ انتخابیِ کاربر.
PAPER → paper_exchange (پیش‌فرض Binance)؛ REAL → real_exchange؛ همه‌چیز (کندل، قیمت، سطوح تاریخی، لینک TradingView) از همان صرافی و بدون fallback به صرافی دیگر.
اجرا: python venue_mode_selftest.py"""
import os, json, time, math, asyncio, logging, functools, inspect, contextvars
from threading import RLock
import pandas as pd

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
os.environ.pop('HALVING_RANGE_OVERRIDE', None)

# ---------------------------------------------------------------- ۱) تعیین صرافی از روی حالت
a = src.index("VENUE_SOURCES = {"); b = src.index("def _with_data_venue(fn, kind, idx):")
SESS = {1: {'trading_mode': 'PAPER', 'real_exchange': 'bitunix'},      # PAPER حتی با انتخاب Bitunix → Binance
        2: {'trading_mode': 'REAL', 'real_exchange': 'bitunix'},
        3: {'trading_mode': 'REAL', 'real_exchange': 'binance'},
        4: {'trading_mode': 'REAL'},                                   # انتخاب نشده → پیش‌فرض Binance
        5: {'trading_mode': 'REAL', 'real_exchange': 'okx'},           # مقدار نامعتبر → Binance
        6: {'trading_mode': 'PAPER', 'paper_exchange': 'bitunix'},     # V3.44.108: کاغذی با Bitunix → Bitunix
        7: {'trading_mode': 'PAPER', 'paper_exchange': 'binance', 'real_exchange': 'bitunix'},
        8: {'trading_mode': 'PAPER', 'paper_exchange': 'okx'}}         # نامعتبر → Binance
env = dict(contextvars=contextvars, USER_SESSIONS=SESS, inspect=inspect, functools=functools)
exec(src[a:b], env)
dv = env['data_venue_for']
assert [dv(c) for c in (1, 2, 3, 4, 5, 999, None, 6, 7, 8)] == ['binance', 'bitunix', 'binance', 'binance', 'binance', 'binance', 'binance', 'bitunix', 'binance', 'binance']
assert env['VENUE_SOURCES']['bitunix'] == ('bitunix',) and 'bitunix' not in env['VENUE_SOURCES']['binance'] and 'binance' not in env['VENUE_SOURCES']['bitunix']
print('1 venue by mode ok')

# ---------------------------------------------------------------- ۲) دکوراتور: chat_id / session / رکورد
a2 = b; _i = src.index("def _install_data_venue_wrappers():"); b2 = src.index("    return n\n", _i) + len("    return n\n")
env['__name__'] = 'vtest'
exec(src[a2:b2], env)
exec('''
def f_chat(x, chat_id): return _venue()
def f_sess(s): return _venue()
def f_rec(rec, now=None): return _venue()
def f_none(a): return _venue()
async def f_async(http, chat_id): return _venue()
def f_nested(chat_id): return f_none(1)
def f_gen(chat_id):
    yield 1
''', env)
n = env['_install_data_venue_wrappers']()
assert n == 5, n   # f_chat, f_sess, f_rec, f_async, f_nested
for name in ('f_chat', 'f_sess', 'f_rec', 'f_async', 'f_nested'): assert getattr(env[name], '_venue_wrapped', False), name
assert not getattr(env['f_none'], '_venue_wrapped', False) and not getattr(env['f_gen'], '_venue_wrapped', False)
assert env['f_chat'](0, 2) == 'bitunix' and env['f_chat'](0, chat_id=3) == 'binance' and env['f_chat'](0, 1) == 'binance'
assert env['f_sess'](SESS[2]) == 'bitunix' and env['f_sess'](SESS[1]) == 'binance' and env['f_sess']('not-a-dict') == 'binance'
assert env['f_rec']({'chat_id': 2}) == 'bitunix' and env['f_rec']({'chat_id': 1}) == 'binance' and env['f_rec']({'x': 1}) == 'binance'
assert asyncio.run(env['f_async'](None, 2)) == 'bitunix' and asyncio.run(env['f_async'](None, 3)) == 'binance'
assert env['f_nested'](2) == 'bitunix'                      # فراخوانی‌های داخلی همان صرافی را به ارث می‌برند
assert env['f_none'](0) == 'binance'                        # بیرون از هر زمینه → Binance
# بعد از خروج زمینه برمی‌گردد
env['f_chat'](0, 2); assert env['_venue']() == 'binance'
print('2 wrappers ok')

# ---------------------------------------------------------------- ۳) get_klines / latest_price: هیچ نشتی بین دو صرافی
ga = src.index("def get_klines(symbol, tf='5min', limit=200):"); gb = src.index("async def get_klines_async(http, symbol, tf='5min', limit=200):")
la = src.index("def latest_price(symbol):"); lb = src.index("# ===================== Binance USDⓈ-M Futures (V3.44.0)")
def mkdf(n=120, base=100.0):
    return pd.DataFrame({'timestamp': range(n), 'open': [base + i for i in range(n)], 'high': [base + 2 + i for i in range(n)], 'low': [base - 1 + i for i in range(n)], 'close': [base + 1 + i for i in range(n)], 'volume': [1.0] * n})
hits = {'bitunix': 0, 'binance': 0, 'price_bitunix': 0, 'price_binance': 0}
def fake_bitunix_klines(sy, tf, lim): hits['bitunix'] += 1; return (mkdf(130, 1000.0), 200, {'code': 0})
class Resp:
    def __init__(s_, st, p): s_.status_code = st; s_.ok = st == 200; s_._p = p
    def json(s_): return s_._p
def fake_get(url, params=None, timeout=None): hits['binance'] += 1; return Resp(200, [])
def _bpx(base): hits['price_bitunix'] += 1; return 1234.0
genv = dict(env)
genv.update(time=time, pd=pd, logger=logging.getLogger('v'), DATA_LOCK=RLock(), DATA_CACHE={}, PRICE_CACHE={}, DATA_CACHE_SECONDS=20, TIMEFRAME_MAP={'5min': '5min'},
            _BINANCE_SOURCES=('binance', 'binancevision'), _DATA_NOTES={}, _DATA_SOURCE_USED={}, _base_asset=lambda sy: str(sy).upper().replace('USDT', ''),
            _source_available=lambda s_: True, _symbol_missing=lambda s_, b_: False, _mark_symbol_missing=lambda *a: None,
            _binance_map_needs_refresh=lambda: False, _binance_refresh_symbol_map=lambda: None, _bitunix_map_needs_refresh=lambda: False, _bitunix_refresh_symbol_map=lambda: None,
            _bitunix_fetch_klines=fake_bitunix_klines, _bitunix_price=_bpx, _status_trips_source=lambda st: False, _source_trip=lambda *a: None, _source_ok=lambda s_: None, _source_fail=lambda s_: None,
            _klines_usable=lambda d, min_rows=60: d is not None and len(d) >= min_rows, _fail_note=lambda s_, st, pl: f'{s_}:fail_{st}',
            _kline_request=lambda source, symbol, tf, limit: ('http://x', {}, lambda payload: mkdf(125, 50.0)) if source.startswith('binance') else None,
            _price_request=lambda source, symbol: ('http://x', {}), _price_from_payload=lambda source, payload: 77.0,
            requests=type('R', (), {'get': staticmethod(fake_get)})())
exec(src[ga:gb], genv); exec(src[la:lb], genv)
gk, lp, setv = genv['get_klines'], genv['latest_price'], genv['_DATA_VENUE_CTX']

tok = setv.set('bitunix'); d = gk('BTC', '5min', 120); lpb = lp('BTC'); setv.reset(tok)
assert len(d) == 120 and float(d['close'].iloc[-1]) > 1000 and hits['bitunix'] == 1 and hits['binance'] == 0 and lpb == 1234.0 and hits['price_binance'] == 0
# Bitunix نماد را ندارد → هیچ fallback‌ای به Binance نیست (داده‌ی خالی)
genv['_bitunix_fetch_klines'] = lambda sy, tf, lim: None
tok = setv.set('bitunix'); d = gk('NOPE', '5min', 120); setv.reset(tok)
assert d.empty and hits['binance'] == 0, hits
# Binance venue (PAPER یا REAL+Binance): هیچ‌وقت به Bitunix دست نمی‌زند، حتی اگر Bitunix سالم و اولین منبع پیش‌فرض قدیمی بود
genv['_bitunix_fetch_klines'] = fake_bitunix_klines; hits.update(bitunix=0, binance=0, price_bitunix=0, price_binance=0)
tok = setv.set('binance'); d = gk('BTC', '5min', 120); p = lp('BTC'); setv.reset(tok)
assert len(d) == 120 and float(d['close'].iloc[-1]) < 1000 and hits['bitunix'] == 0 and p == 77.0 and hits['price_bitunix'] == 0, hits
# کش برای هر صرافی جدا است (همان نماد/تایم‌فریم، قیمت‌های متفاوت)
tok = setv.set('bitunix'); d1 = gk('BTC', '5min', 120); setv.reset(tok)
tok = setv.set('binance'); d2 = gk('BTC', '5min', 120); setv.reset(tok)
assert float(d1['close'].iloc[-1]) != float(d2['close'].iloc[-1])
print('3 data isolation ok')

# ---------------------------------------------------------------- ۴) سقف/کف تاریخی از صرافیِ حالت
ha = src.index("HALVING_RANGE_TTL = "); hb = src.index("def _with_halving_cfg(")
ba = src.index("def _bitunix_kline_df(payload):"); bb = src.index("def _bitunix_add_forming_candle(")
calls = []
def fake_req_get(url, params=None, timeout=None): calls.append(('binance', url, dict(params or {}))); return Resp(200, [[i * 1000, 5, 9, 4, 6, 1, 0] for i in range(40)] + [[99999, 5, 123.0, 2.0, 6, 1, 0]])
def fake_bx_get(path, params=None, timeout=7):
    calls.append(('bitunix', path, dict(params or {})))
    rows = [{'time': 1000 + i, 'open': 5, 'high': 9, 'low': 4, 'close': 6, 'baseVol': 1} for i in range(30)] + [{'time': 5000, 'open': 5, 'high': 55.5, 'low': 3.25, 'close': 6, 'baseVol': 1}]
    return Resp(200, {'code': 0, 'data': rows})
henv = dict(pd=pd, math=math, time=time, asyncio=asyncio, json=json, os=os, logger=logging.getLogger('h'), requests=type('R', (), {'get': staticmethod(fake_req_get)}),
            _base_asset=lambda s_: str(s_).upper().replace('USDT', '').replace('/', ''), _binance_map_needs_refresh=lambda: False, _binance_refresh_symbol_map=lambda: None,
            _binance_symbol_from_cache=lambda base: base + 'USDT', _BINANCE_SOURCES=('binance',), _binance_base_url=lambda s_: 'https://api.binance.com',
            _source_available=lambda s_: True, _source_trip=lambda *a, **k: None, _source_fail=lambda s_: None, _source_ok=lambda s_: None,
            _status_trips_source=lambda st: False, Dict=dict, Any=object, _venue=lambda: henv['_v'], _v='binance',
            _bitunix_map_needs_refresh=lambda: False, _bitunix_refresh_symbol_map=lambda: None, _bitunix_symbol_from_cache=lambda base: base + 'USDT', _bitunix_resolve=lambda base: (base + 'USDT', 1), _bitunix_unscale_df=lambda df, sc: df, _bitunix_get=fake_bx_get,
            get_klines=lambda *a: None)
async def _ak(*a): return None
henv['get_klines_async'] = _ak
exec(src[ba:bb], henv)                          # _bitunix_kline_df
exec("from _ohlc_helper import *", {}) if False else None
exec(src[src.index("def _ohlcv_df(rows):"):src.index("def _binance_kline_df(payload):")], henv)
exec(src[src.index("def _binance_kline_df(payload):"):src.index("# ===================== Bitunix Futures: داده‌ی عمومی")], henv)
exec(src[ha:hb], henv)
sync, cache, srcmap = henv['get_halving_range_sync'], henv['HALVING_RANGE_CACHE'], henv['_HIST_RANGE_SRC']
def reset(v): calls.clear(); cache.clear(); srcmap.clear(); henv['_v'] = v

# Binance: BTC از جدول داخلی (بدون درخواست)؛ نماد دیگر از Binance
reset('binance'); hi, lo = sync('BTCUSDT'); assert (hi, lo) == (123.0, 2.0) and {c[0] for c in calls} == {'binance'} and srcmap['BTCUSDT'][0] == 'Binance'  # V3.44.99: جدول داخلی حذف شد
reset('binance'); hi, lo = sync('FOOUSDT'); assert (hi, lo) == (123.0, 2.0) and {c[0] for c in calls} == {'binance'} and srcmap['FOOUSDT'][0] == 'Binance'
# Bitunix: جدول داخلی BTC اعمال نمی‌شود، فقط Bitunix صدا زده می‌شود و Binance هرگز
reset('bitunix'); hi, lo = sync('BTCUSDT'); assert (hi, lo) == (55.5, 3.25) and {c[0] for c in calls} == {'bitunix'} and srcmap['BTCUSDT'][0] == 'Bitunix', (hi, lo, calls)
assert calls[0][2]['interval'] == '1w' and calls[0][2]['limit'] == 200
# کش جدا برای هر صرافی
reset('binance'); sync('FOOUSDT'); henv['_v'] = 'bitunix'; calls.clear(); sync('FOOUSDT'); assert {c[0] for c in calls} == {'bitunix'}
# override صریح کاربر (env) برای هر دو صرافی معتبر است
os.environ['HALVING_RANGE_OVERRIDE'] = json.dumps({'BTCUSDT': [200000, 1000]})
for v in ('binance', 'bitunix'):
    reset(v); assert sync('BTCUSDT') == (200000.0, 1000.0) and not calls
os.environ.pop('HALVING_RANGE_OVERRIDE')
print('4 historical range per venue ok')

# ---------------------------------------------------------------- ۵) لینک TradingView
ta = src.index("def tradingview_symbol(symbol, chat_id=None):"); tb = src.index("def tradingview_chart_url(symbol, timeframe='5min', chat_id=None):")
tv = dict(env); tv.update(_base_asset=lambda sy: str(sy).upper().replace('USDT', ''), _bitunix_scale=lambda b: 1, TRADINGVIEW_EXCHANGE='', TV_EXCHANGE_MAP={'bitunix': 'BITUNIX', 'binance': 'BINANCE', 'binancevision': 'BINANCE'})
exec(src[ta:tb], tv)
assert tv['tradingview_symbol']('SOL', 1) == 'BINANCE:SOLUSDT'            # PAPER
assert tv['tradingview_symbol']('SOL', 3) == 'BINANCE:SOLUSDT'            # REAL + Binance
assert tv['tradingview_symbol']('SOL', 2) == 'BITUNIX:SOLUSDT.P'          # REAL + Bitunix
tok = env['_DATA_VENUE_CTX'].set('bitunix'); assert tv['tradingview_symbol']('SOL') == 'BITUNIX:SOLUSDT.P'; env['_DATA_VENUE_CTX'].reset(tok)
print('5 tradingview symbol ok')

# ---------------------------------------------------------------- ۶) ساختار: هیچ مسیری به Bybit/KuCoin یا مخلوط‌کردن دو صرافی نمانده
assert "for source in MARKET_DATA_SOURCES:" not in src, 'حلقه‌ی قدیمیِ منابع (ترتیب سراسری) باقی مانده'
assert src.count("for source in _sources_now():") == 2 and "for source in _srcs:" in src
assert "_DATA_SOURCE_USED.get(base" not in src.split("def tradingview_symbol")[1].split("def tradingview_chart_url")[0]
print('venue_mode_selftest: ALL OK')
