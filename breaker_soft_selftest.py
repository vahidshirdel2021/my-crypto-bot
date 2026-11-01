"""تست آفلاین V3.44.122: تایم‌اوتِ سمت کلاینت منبع را فوراً خاموش نمی‌کند، یک‌بار retry می‌شود، و فقط با ping شکست‌خورده trip می‌شود.
اجرا: python breaker_soft_selftest.py"""
import os, asyncio, time, logging, types
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
src = open('bot.py', encoding='utf-8').read()

try:
    import aiohttp
except Exception:       # بدون aiohttp هم تست می‌شود
    aiohttp = types.SimpleNamespace(ClientTimeout=lambda **k: k)

def cut(a, b):
    i = src.index(a); j = src.index(b, i); return src[i:j]

g = dict(asyncio=asyncio, time=time, pd=pd, aiohttp=aiohttp, logger=logging.getLogger('t'), os=os)
g.update(SOURCE_COOLDOWN_SECONDS=60, _SOURCE_DOWN_UNTIL={}, _SOURCE_FAILS={}, _BINANCE_SOURCES=('binance',),
         _binance_base_url=lambda s: 'https://x', _net_event=lambda *a, **k: None)
exec(cut("KLINE_REQUEST_TIMEOUT_S = max(", "BINANCE_SYMBOLS_TTL"), g)
exec(cut("def _source_available(source):", "def _status_trips_source(status):"), g)
exec(cut("def _status_trips_source(status):", "def _symbol_missing(source, base):"), g)
exec(cut("async def _fetch_kline_http(", "async def get_klines_async("), g)
g['KLINE_TIMEOUT_RETRIES'] = 1

class Resp:
    def __init__(s, status=200, payload=None): s.status = status; s._p = payload
    async def json(s, content_type=None): return s._p
    async def __aenter__(s): return s
    async def __aexit__(s, *a): return False

class Http:
    def __init__(s, plan, ping_ok=True): s.plan = list(plan); s.ping_ok = ping_ok; s.calls = 0
    def get(s, url, params=None, timeout=None):
        if url.endswith('/ping'):
            if not s.ping_ok: raise asyncio.TimeoutError()
            return Resp(200)
        s.calls += 1
        act = s.plan.pop(0) if s.plan else 'ok'
        if act == 'timeout': raise asyncio.TimeoutError()
        if isinstance(act, int): return Resp(act)
        return Resp(200, [1])

parse = lambda p: pd.DataFrame({'x': [1]})
run = asyncio.run

# 1) یک timeout و بعد موفق => retry کار می‌کند
h = Http(['timeout', 'ok']); st, pl, df = run(g['_fetch_kline_http'](h, 'https://x/k', {}, parse, 'binance', 'BTC'))
assert st == 200 and h.calls == 2 and len(df) == 1, (st, h.calls)
# 2) دو timeout پشت‌سرهم => raise
h = Http(['timeout', 'timeout'])
try: run(g['_fetch_kline_http'](h, 'https://x/k', {}, parse, 'binance', 'BTC')); raise SystemExit('should raise')
except asyncio.TimeoutError: pass
# 3) کد 429 => بدون خواندن بدنه برمی‌گردد (و trip توسط فراخواننده)
h = Http([429]); st, pl, df = run(g['_fetch_kline_http'](h, 'https://x/k', {}, parse, 'binance', 'BTC'))
assert st == 429 and pl is None
# 4) ۱۱ timeout نرم => هنوز trip نمی‌شود؛ بریکر فقط با ۱۲ تا و ping شکست‌خورده trip می‌کند
async def soft(h, n):
    for _ in range(n): await g['_source_fail_async'](h, 'binance', soft=True)
g['_SOURCE_DOWN_UNTIL'].clear(); g['_SOURCE_SOFT_FAILS'].clear()
h = Http([], ping_ok=False); run(soft(h, 11)); assert g['_source_available']('binance'), 'زودتر از موعد trip شد'
run(soft(h, 1)); assert not g['_source_available']('binance'), 'با ping خراب باید trip شود'
# 5) ۱۲ timeout نرم ولی ping سالم => trip نمی‌شود (مشکل از شلوغیِ ربات است)
g['_SOURCE_DOWN_UNTIL'].clear(); g['_SOURCE_SOFT_FAILS'].clear()
h = Http([], ping_ok=True); run(soft(h, 30)); assert g['_source_available']('binance'), 'با ping سالم نباید trip شود'
# 6) شکست سخت مثل قبل: ۳ بار => trip
g['_SOURCE_DOWN_UNTIL'].clear(); g['_SOURCE_FAILS'].clear()
async def hard(h, n):
    for _ in range(n): await g['_source_fail_async'](h, 'binance', soft=False)
run(hard(None, 2)); assert g['_source_available']('binance'); run(hard(None, 1)); assert not g['_source_available']('binance')
# 7) موفقیت شمارنده‌ی نرم را صفر می‌کند
g['_SOURCE_DOWN_UNTIL'].clear(); g['_SOURCE_SOFT_FAILS'].clear()
run(soft(Http([]), 5)); g['_source_ok']('binance'); assert not g['_SOURCE_SOFT_FAILS']['binance']
# 8) سقف هم‌زمانی اسکن
assert 'tasks.append(scan_symbol(http,cid,sym))' not in src and src.count('tasks.append(_bounded_scan(http,cid,sym))') == 2
print('breaker_soft selftest OK')
