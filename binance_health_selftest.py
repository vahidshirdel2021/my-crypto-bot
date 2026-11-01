"""تست آفلاین V3.44.121: سلامت‌سنجی مسیر Binance Futures (/binance_health) و حلقه‌ی رویدادهای شبکه.
اجرا: python binance_health_selftest.py"""
import asyncio, json, os, sys, threading, types, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import deque

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
import binance_health as bh

src = open('bot.py', encoding='utf-8').read()
code = '\n'.join(l for l in src.split('\n') if not l.lstrip().startswith('#'))

# ---------------------------------------------------------------- ۰) سیم‌کشی در bot.py
assert "BOT_VERSION = '3.44.123'" in src
assert "cl == '/binance_health'" in src
i = src.index("cl == '/binance_health'"); blk = src[i:i + 700]
assert 'is_admin(chat_id)' in blk and 'فقط برای ادمین' in blk and 'Thread(target=_run_binance_health_and_send' in blk, 'دستور باید ادمین‌محور و غیرمسدودکننده باشد'
assert '/binance_health' not in open('access_policy.py', encoding='utf-8').read(), 'نباید برای کاربر عادی باز شود'
assert code.count("_net_event('fail'") >= 4 and code.count("_net_event('http'") >= 4 and "_net_event('trip'" in code
assert 'sendDocument' in src[src.index('def _run_binance_health_and_send'):src.index('def _run_binance_health_and_send') + 1500]

# ---------------------------------------------------------------- ۱) _net_event واقعی از کد bot.py
a = src.index('_NET_EVENTS = _deque(maxlen=120)'); b = src.index('def _net_event(')
c = src.index("        _NET_EVENTS.append(ev)\n    except Exception:\n        pass\n", b) + len("        _NET_EVENTS.append(ev)\n    except Exception:\n        pass\n")
g = dict(time=time, threading=threading, _deque=deque)
exec(src[a:c], g)
g['_net_event']('fail', 'binance', 'get_klines', 'BTCUSDT', exc=asyncio.TimeoutError('t'))
g['_net_event']('http', 'binance', 'get_klines', 'ETHUSDT', status=429)
g['_net_event']('trip', 'binance', seconds=60)
evs = list(g['_NET_EVENTS'])
assert len(evs) == 3 and evs[0]['exc'] == 'TimeoutError' and evs[1]['status'] == 429 and evs[2]['seconds'] == 60
for _ in range(300): g['_net_event']('fail', 'binance')
assert len(g['_NET_EVENTS']) == 120
g['_net_event']('fail', 'x', exc=None)       # هیچ‌وقت نباید exception بدهد

# ---------------------------------------------------------------- ۲) سرور محلی شبیه fapi
MODE = {'klines': 200}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code); self.send_header('Content-Type', 'application/json'); self.send_header('Content-Length', str(len(raw)))
        self.end_headers(); self.wfile.write(raw)

    def do_GET(self):
        p = self.path.split('?')[0]
        if p == '/fapi/v1/ping': return self._send(200, {})
        if p == '/fapi/v1/time': return self._send(200, {'serverTime': int(time.time() * 1000)})
        if p == '/fapi/v1/exchangeInfo':
            return self._send(200, {'symbols': [{'baseAsset': 'BTC', 'symbol': 'BTCUSDT', 'contractType': 'PERPETUAL', 'status': 'TRADING', 'quoteAsset': 'USDT'}]})
        if p == '/fapi/v1/klines':
            if MODE['klines'] != 200: return self._send(MODE['klines'], {'msg': 'x'})
            t0 = int(time.time() * 1000) - 300 * 900000
            return self._send(200, [[t0 + i * 900000, '100', '101', '99', '100.5', '10', 0, '0', 0, '0', '0', '0'] for i in range(300)])
        self._send(404, {})


srv = HTTPServer(('127.0.0.1', 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f'http://127.0.0.1:{port}'


def kline_request(source, sym, tf, limit):
    def parse(payload):
        df = pd.DataFrame([r[:6] for r in payload], columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        return df.astype(float)
    return (BASE + '/fapi/v1/klines', {'symbol': sym, 'interval': '15m', 'limit': limit}, parse)


def get_klines(sym, tf, limit):
    r = requests.get(BASE + '/fapi/v1/klines', timeout=5)
    return pd.DataFrame(r.json()) if r.ok else pd.DataFrame()


def state_fn():
    return {'now': int(time.time()), 'sources': {'binance': {'down_remaining_s': 0, 'fails': 0}}, 'net_events': list(g['_NET_EVENTS'])[-5:]}


def ctx():
    return {'requests': requests, 'base_url': BASE, 'bot_version': '3.44.121', 'kline_request': kline_request,
            'parse_exchange_info': lambda p: {s['baseAsset']: s['symbol'] for s in p['symbols']},
            'get_klines': get_klines, 'failure_notes': lambda s: '', 'state_fn': state_fn, 'max_async': 4}


# ---------------------------------------------------------------- ۳) aiohttp جعلی (در این محیط نصب نیست) با همان API لازم
class _Resp:
    def __init__(self, r): self.r = r; self.status = r.status_code
    async def json(self, content_type=None): return self.r.json()


class _Ctx:
    def __init__(self, url, params): self.url, self.params = url, params
    async def __aenter__(self):
        loop = asyncio.get_running_loop()
        return _Resp(await loop.run_in_executor(None, lambda: requests.get(self.url, params=self.params, timeout=5)))
    async def __aexit__(self, *a): return False


class _Session:
    def __init__(self, **kw): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *a): return False
    def get(self, url, params=None, timeout=None): return _Ctx(url, params)


fake = types.ModuleType('aiohttp')
fake.ClientTimeout = lambda total=None: ('timeout', total)
fake.TCPConnector = lambda **kw: ('conn', kw)
fake.ClientSession = _Session
fake.__version__ = 'fake'
sys.modules['aiohttp'] = fake

# ---------------------------------------------------------------- ۴) حالت سالم
rep = bh.run(ctx())
for k in ('versions', 'env', 'dns_tcp', 'sync_basic', 'exchange_info', 'sync_concurrent', 'aiohttp_scan_path', 'hist_range', 'real_get_klines', 'state', 'verdict', 'timings_s'):
    assert k in rep, k
assert rep['sync_basic']['ping']['status'] == 200
assert rep['exchange_info']['accepted_symbols'] == 1
assert rep['sync_concurrent']['ok'] == rep['sync_concurrent']['n'] == 20, rep['sync_concurrent']
assert rep['aiohttp_scan_path']['ok'] == rep['aiohttp_scan_path']['n'] == 20, rep['aiohttp_scan_path']
assert all(r.get('rows') == 300 for r in rep['aiohttp_scan_path']['rows'])
assert rep['real_get_klines']['calls'][0]['rows'] == 300 and 'before' in rep['real_get_klines'] and 'after' in rep['real_get_klines']
assert rep['dns_tcp']['addresses'] and 'connect_ms' in rep['dns_tcp']['addresses'][0]
data = bh.to_json_bytes(rep); json.loads(data.decode('utf-8'))
assert any('20/20' in v for v in rep['verdict']), rep['verdict']

# ---------------------------------------------------------------- ۵) خطای سرور (HTTP 500): شکست باید به‌صورت ok=false ثبت شود، نه exception
MODE['klines'] = 500
rep2 = bh.run(ctx())
assert rep2['sync_concurrent']['ok'] == 0 and rep2['aiohttp_scan_path']['ok'] == 0
assert all(r.get('status') == 500 for r in rep2['sync_concurrent']['rows'])
MODE['klines'] = 200

# ---------------------------------------------------------------- ۶) اتصال ممکن نیست (پورت بسته): هیچ مرحله‌ای نباید کل گزارش را بشکند
c3 = ctx(); c3['base_url'] = 'http://127.0.0.1:9'
c3['kline_request'] = lambda s, sym, tf, lim: ('http://127.0.0.1:9/fapi/v1/klines', {}, lambda p: pd.DataFrame())
rep3 = bh.run(c3)
assert rep3['sync_concurrent']['ok'] == 0 and rep3['sync_concurrent']['rows'][0]['stage'] == 'request'
assert rep3['sync_concurrent']['rows'][0]['error']['type']
assert rep3['sync_basic']['ping'].get('error')
assert rep3['verdict'], 'verdict خالی'
json.loads(bh.to_json_bytes(rep3).decode('utf-8'))

# ---------------------------------------------------------------- ۷) نبودن aiohttp: فقط همان مرحله خطا می‌دهد
del sys.modules['aiohttp']; sys.modules['aiohttp'] = None       # import را ImportError می‌کند
rep4 = bh.run(ctx())
assert 'error' in rep4['aiohttp_scan_path'] and rep4['sync_concurrent']['ok'] == 20

# ---------------------------------------------------------------- ۸) verdict: تشخیص «requests سالم، aiohttp خراب» و منبع غیرفعال
v = bh.verdict({'sync_concurrent': {'n': 20, 'ok': 20, 'rows': []},
                'aiohttp_scan_path': {'n': 20, 'ok': 3, 'rows': [{'ok': False, 'stage': 'request', 'error': {'type': 'TimeoutError', 'msg': ''}}]},
                'state': {'sources': {'binance': {'down_remaining_s': 42, 'fails': 2}}, 'net_events': [{'kind': 'fail', 'exc': 'TimeoutError'}]}})
txt = ' | '.join(v)
assert 'مشکل مسیر aiohttp' in txt and '42' in txt and 'TimeoutError' in txt, txt
v6 = bh.verdict({'dns_tcp': {'addresses': [{'family': 'IPv6', 'ip': '::1', 'connect_error': {'type': 'TimeoutError', 'msg': ''}},
                                           {'family': 'IPv4', 'ip': '1.1.1.1', 'connect_ms': 5}]}})
assert any('IPv6' in x for x in v6)

print('binance_health selftest OK')
