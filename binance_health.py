# -*- coding: utf-8 -*-
"""V3.44.121: سلامت‌سنجی مسیر داده‌ی Binance Futures از داخل خود ربات (فقط ادمین: /binance_health).

خروجی یک dict قابل‌ذخیره به‌صورت JSON است و همان مسیرهایی را می‌آزماید که ربات واقعاً استفاده می‌کند:
  - محیط (نسخه‌ی کتابخانه‌ها، پروکسی، env های مرتبط)
  - DNS و زمان اتصال TCP به تفکیک IPv4/IPv6
  - requests هم‌زمان (مثل مسیر sync ربات: timeout=7)
  - aiohttp دقیقاً مثل اسکنر (TCPConnector(limit=MAX_ASYNC_REQUESTS)، ClientTimeout(total=10)، هر درخواست total=7)
    با تفکیک مرحله‌ی شکست: connect/read/json/parse
  - صدا زدن get_klines واقعی ربات (با limit یکتا تا کش دخالت نکند) و دلیل شکست آن
  - وضعیت درونیِ منبع (down_until، شمارنده‌ی شکست، نقشه‌ی نمادها) و حلقه‌ی آخرین exception های واقعیِ ربات

این ماژول عمداً از bot.py import نمی‌کند؛ هرچه از ربات لازم دارد در ctx داده می‌شود (قابل تست آفلاین).
هیچ‌چیز از این ماژول نباید جلوی کار ربات را بگیرد: همه‌ی خطاها داخل خروجی ثبت می‌شوند.
"""
import asyncio
import json
import os
import platform
import socket
import sys
import threading
import time
import traceback

_SYMS = ('BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'DOGEUSDT', 'LINKUSDT', 'AAVEUSDT', 'SUIUSDT', 'XRPUSDT')


def _r(x, n=3):
    try:
        return round(float(x), n)
    except Exception:
        return None


def _exc(e):
    return {'type': type(e).__name__, 'msg': str(e)[:300]}


def _versions():
    out = {'python': sys.version.split()[0], 'platform': platform.platform()}
    for name in ('requests', 'urllib3', 'aiohttp', 'pandas', 'ccxt', 'certifi'):
        try:
            m = __import__(name)
            out[name] = getattr(m, '__version__', '?')
        except Exception as e:
            out[name] = f'import_error:{type(e).__name__}'
    try:
        import ssl
        out['openssl'] = ssl.OPENSSL_VERSION
    except Exception:
        pass
    return out


def _env():
    keys = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY', 'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy',
            'BINANCE_FUTURES_URL', 'MAX_ASYNC_REQUESTS', 'DATA_CACHE_SECONDS', 'MARKET_DATA_SOURCE_COOLDOWN_SECONDS',
            'MARKET_DATA_SYMBOL_MISS_TTL_SECONDS')
    return {k: os.environ.get(k) for k in keys if os.environ.get(k)}


def _host_port(url):
    from urllib.parse import urlparse
    u = urlparse(url)
    return u.hostname or url, (u.port or (443 if u.scheme == 'https' else 80))


def probe_dns_tcp(host, port=443, timeout=5):
    """DNS + زمان اتصال TCP به هر آدرس (IPv4 و IPv6 جدا)."""
    res = {'host': host, 'port': port, 'addresses': [], 'dns_ms': None}
    try:
        t = time.time()
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        res['dns_ms'] = _r((time.time() - t) * 1000, 1)
    except Exception as e:
        res['dns_error'] = _exc(e)
        return res
    seen = set()
    for fam, _, _, _, sa in infos:
        ip = sa[0]
        if ip in seen:
            continue
        seen.add(ip)
        item = {'family': 'IPv6' if fam == socket.AF_INET6 else 'IPv4', 'ip': ip}
        t = time.time()
        try:
            s = socket.socket(fam, socket.SOCK_STREAM); s.settimeout(timeout)
            s.connect(sa); s.close()
            item['connect_ms'] = _r((time.time() - t) * 1000, 1)
        except Exception as e:
            item['connect_error'] = _exc(e); item['elapsed_ms'] = _r((time.time() - t) * 1000, 1)
        res['addresses'].append(item)
        if len(res['addresses']) >= 6:
            break
    return res


def probe_sync_basic(requests, base_url):
    out = {}
    for name, path, params in (('ping', '/fapi/v1/ping', None), ('time', '/fapi/v1/time', None)):
        t = time.time()
        try:
            r = requests.get(base_url + path, params=params, timeout=7)
            out[name] = {'status': r.status_code, 'ms': _r((time.time() - t) * 1000, 1)}
        except Exception as e:
            out[name] = {'error': _exc(e), 'ms': _r((time.time() - t) * 1000, 1)}
    return out


def probe_exchange_info(requests, base_url, parse_fn):
    t = time.time()
    try:
        r = requests.get(base_url + '/fapi/v1/exchangeInfo', timeout=12)
        res = {'status': r.status_code, 'ms': _r((time.time() - t) * 1000, 1), 'bytes': len(r.content or b'')}
        if r.ok:
            mp = parse_fn(r.json())
            res['accepted_symbols'] = len(mp)
        return res
    except Exception as e:
        return {'error': _exc(e), 'ms': _r((time.time() - t) * 1000, 1), 'trace': traceback.format_exc()[-600:]}


def probe_sync_concurrent(requests, kline_request, threads=5, per_thread=4):
    """مثل مسیر sync ربات (requests، timeout=7) ولی هم‌زمان؛ مرحله‌ی شکست جدا ثبت می‌شود."""
    rows = []; lock = threading.Lock()

    def worker(n):
        for i in range(per_thread):
            sym = _SYMS[(n + i) % len(_SYMS)]
            t = time.time(); stage = 'build'
            try:
                req = kline_request('binance', sym, '15min', 300)
                if not req:
                    raise RuntimeError('kline_request=None (نماد در نقشه نیست)')
                url, params, parse = req
                stage = 'request'
                r = requests.get(url, params=params, timeout=7)
                row = {'sym': sym, 'status': r.status_code, 'ms': _r((time.time() - t) * 1000, 1)}
                if r.ok:
                    stage = 'json'; payload = r.json()
                    stage = 'parse'; df = parse(payload)
                    row['rows'] = int(len(df))
                row['ok'] = bool(r.ok)
            except Exception as e:
                row = {'sym': sym, 'ok': False, 'stage': stage, 'ms': _r((time.time() - t) * 1000, 1), 'error': _exc(e)}
            with lock:
                rows.append(row)

    ths = [threading.Thread(target=worker, args=(n,), daemon=True) for n in range(threads)]
    t0 = time.time()
    for th in ths: th.start()
    for th in ths: th.join(timeout=60)
    return {'total_s': _r(time.time() - t0, 2), 'ok': sum(1 for r in rows if r.get('ok')), 'n': len(rows), 'rows': rows[:40]}


async def _aio_one(aiohttp, http, sem, kline_request, sym, tf, limit):
    t = time.time(); stage = 'build'
    try:
        req = kline_request('binance', sym, tf, limit)
        if not req:
            raise RuntimeError('kline_request=None')
        url, params, parse = req
        async with sem:
            stage = 'request'
            async with http.get(url, params=params, timeout=aiohttp.ClientTimeout(total=7)) as r:
                status = r.status
                row = {'sym': sym, 'status': status}
                if status == 200:
                    stage = 'json'; payload = await r.json(content_type=None)
                    stage = 'parse'; df = parse(payload)
                    row['rows'] = int(len(df))
        row['ok'] = status == 200; row['ms'] = _r((time.time() - t) * 1000, 1)
        return row
    except BaseException as e:      # شامل asyncio.TimeoutError / CancelledError
        return {'sym': sym, 'ok': False, 'stage': stage, 'ms': _r((time.time() - t) * 1000, 1), 'error': _exc(e)}


async def _aio_run(aiohttp, kline_request, max_async, n_req):
    timeout = aiohttp.ClientTimeout(total=10)
    conn = aiohttp.TCPConnector(limit=max_async, ttl_dns_cache=300)
    sem = asyncio.Semaphore(max_async)
    async with aiohttp.ClientSession(timeout=timeout, connector=conn) as http:
        jobs = [_aio_one(aiohttp, http, sem, kline_request, _SYMS[i % len(_SYMS)], '15min', 300) for i in range(n_req)]
        return await asyncio.gather(*jobs)


def probe_aiohttp_scan_path(kline_request, max_async, n_req=20):
    """دقیقاً مثل scan_loop: ClientSession(timeout=10، TCPConnector(limit=MAX_ASYNC_REQUESTS))، هر درخواست total=7."""
    try:
        import aiohttp
    except Exception as e:
        return {'error': _exc(e)}
    t0 = time.time()
    try:
        rows = asyncio.run(_aio_run(aiohttp, kline_request, max_async, n_req))
    except Exception as e:
        return {'error': _exc(e), 'trace': traceback.format_exc()[-800:]}
    return {'total_s': _r(time.time() - t0, 2), 'ok': sum(1 for r in rows if r.get('ok')), 'n': len(rows), 'rows': rows[:40]}


def probe_real_get_klines(get_klines, failure_notes, state_fn, symbols=('BTCUSDT', 'ETHUSDT', 'SOLUSDT')):
    """تابع واقعی ربات؛ limit یکتا تا کش دخالت نکند (ممکن است منبع را trip کند؛ وضعیت قبل/بعد ثبت می‌شود)."""
    out = {'before': state_fn(), 'calls': []}
    for i, sym in enumerate(symbols):
        t = time.time()
        try:
            df = get_klines(sym, '15min', 233 + i)
            out['calls'].append({'sym': sym, 'rows': int(len(df)), 'ms': _r((time.time() - t) * 1000, 1),
                                 'notes': failure_notes(sym)})
        except Exception as e:
            out['calls'].append({'sym': sym, 'error': _exc(e), 'ms': _r((time.time() - t) * 1000, 1),
                                 'trace': traceback.format_exc()[-500:]})
    out['after'] = state_fn()
    return out


def probe_hist_range(requests, base_url, symbols=('BTCUSDT', 'DOGEUSDT')):
    out = []
    for sym in symbols:
        t = time.time()
        try:
            r = requests.get(base_url + '/fapi/v1/klines', params={'symbol': sym, 'interval': '1w', 'limit': 1000}, timeout=10)
            item = {'sym': sym, 'status': r.status_code, 'ms': _r((time.time() - t) * 1000, 1)}
            if r.ok:
                item['rows'] = len(r.json())
            out.append(item)
        except Exception as e:
            out.append({'sym': sym, 'error': _exc(e), 'ms': _r((time.time() - t) * 1000, 1)})
    return out


def verdict(rep):
    """جمع‌بندی ماشینی کوتاه برای خواندن سریع (دلیل‌های محتمل)."""
    f = []
    dns = rep.get('dns_tcp') or {}
    if dns.get('dns_error'):
        f.append('DNS: ' + dns['dns_error']['type'] + ' ' + dns['dns_error']['msg'])
    v4 = [a for a in dns.get('addresses', []) if a.get('family') == 'IPv4']
    v6 = [a for a in dns.get('addresses', []) if a.get('family') == 'IPv6']
    if v6 and all('connect_error' in a for a in v6) and any('connect_ms' in a for a in v4):
        f.append('IPv6 قابل اتصال نیست ولی IPv4 هست: کتابخانه‌ها ممکن است اول IPv6 را امتحان کنند و timeout بخورند')
    if any('connect_error' in a for a in dns.get('addresses', [])) and not any('connect_ms' in a for a in dns.get('addresses', [])):
        f.append('هیچ آدرسی قابل اتصال نیست (فایروال/بلاک شبکه)')
    sc = rep.get('sync_concurrent') or {}
    ac = rep.get('aiohttp_scan_path') or {}
    if sc.get('n'):
        f.append(f"requests هم‌زمان: {sc['ok']}/{sc['n']} موفق")
    if ac.get('n'):
        f.append(f"aiohttp مثل اسکنر: {ac['ok']}/{ac['n']} موفق")
    if sc.get('n') and sc.get('ok') == sc['n'] and ac.get('n') and ac.get('ok', 0) < ac['n']:
        f.append('requests سالم ولی aiohttp اسکنر خطا دارد: مشکل مسیر aiohttp (تنظیم session/connector/timeout)')
    stages = {}
    for r in (sc.get('rows') or []) + (ac.get('rows') or []):
        if not r.get('ok') and r.get('error'):
            k = f"{r.get('stage')}:{r['error']['type']}"
            stages[k] = stages.get(k, 0) + 1
    if stages:
        f.append('شکست‌ها به تفکیک مرحله:نوع -> ' + json.dumps(stages, ensure_ascii=False))
    st = rep.get('state') or {}
    b = (st.get('sources') or {}).get('binance') or {}
    if b.get('down_remaining_s', 0) > 0:
        f.append(f"الان منبع binance در ربات غیرفعال است (باقی‌مانده {b['down_remaining_s']}s، شکست‌های پیاپی={b.get('fails')})")
    ev = st.get('net_events') or []
    kinds = {}
    for e in ev:
        k = f"{e.get('kind')}:{e.get('exc') or e.get('status')}"
        kinds[k] = kinds.get(k, 0) + 1
    if kinds:
        f.append('رویدادهای واقعی اخیر ربات: ' + json.dumps(kinds, ensure_ascii=False))
    if not f:
        f.append('مورد مشکوکی پیدا نشد')
    return f


def run(ctx):
    """ctx: requests, base_url, kline_request, parse_exchange_info, get_klines, failure_notes, state_fn, max_async."""
    rep = {'ts': int(time.time()), 'bot_version': ctx.get('bot_version'), 'base_url': ctx['base_url']}
    steps = (
        ('versions', lambda: _versions()),
        ('env', lambda: _env()),
        ('dns_tcp', lambda: probe_dns_tcp(*_host_port(ctx['base_url']))),
        ('sync_basic', lambda: probe_sync_basic(ctx['requests'], ctx['base_url'])),
        ('exchange_info', lambda: probe_exchange_info(ctx['requests'], ctx['base_url'], ctx['parse_exchange_info'])),
        ('sync_concurrent', lambda: probe_sync_concurrent(ctx['requests'], ctx['kline_request'])),
        ('aiohttp_scan_path', lambda: probe_aiohttp_scan_path(ctx['kline_request'], ctx.get('max_async') or 10)),
        ('hist_range', lambda: probe_hist_range(ctx['requests'], ctx['base_url'])),
        ('real_get_klines', lambda: probe_real_get_klines(ctx['get_klines'], ctx['failure_notes'], ctx['state_fn'])),
        ('state', lambda: ctx['state_fn']()),
    )
    for name, fn in steps:
        t = time.time()
        try:
            rep[name] = fn()
        except Exception as e:
            rep[name] = {'probe_error': _exc(e), 'trace': traceback.format_exc()[-600:]}
        rep.setdefault('timings_s', {})[name] = _r(time.time() - t, 2)
    rep['verdict'] = verdict(rep)
    return rep


def to_json_bytes(rep):
    return json.dumps(rep, ensure_ascii=False, indent=1, default=str).encode('utf-8')
