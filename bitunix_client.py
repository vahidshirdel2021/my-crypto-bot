# -*- coding: utf-8 -*-
"""Bitunix Futures: کلاینت REST امضاشده + یک لایه‌ی «شبیه ccxt» برای مسیر REAL ربات (V3.44.57).

مستندات: https://openapidoc.bitunix.com  (امضا: دو بار SHA256؛ سقف ۱۰ درخواست در ثانیه برای هر uid).
نکته‌ی مهم TP/SL: «Position TP/SL» بیتیونیکس هنگام فعال شدن کل حجمِ «همان لحظه»‌ی پوزیشن را با مارکت می‌بندد و هر پوزیشن فقط
یکی دارد؛ یعنی معادل closePosition باینانس است و بعد از بستن بخشی از پوزیشن هم برای بقیه معتبر می‌ماند.

این فایل به bot.py وابسته نیست تا بدون اینترنت و بدون aiohttp قابل تست باشد."""
import hashlib
import json
import logging
import threading
import time
import uuid
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, InvalidOperation

import requests

logger = logging.getLogger(__name__)

BASE_URL = 'https://fapi.bitunix.com'
MARGIN_COIN = 'USDT'


class BitunixError(Exception):
    """پاسخ خطای API (code != 0) یا HTTP غیر ۲۰۰."""
    def __init__(self, code, msg, status=None, path=None):
        super().__init__(f'Bitunix {path or ""} code={code} msg={msg} http={status}')
        self.code = code; self.msg = msg; self.status = status; self.path = path


class BitunixOrderRejected(BitunixError):
    """ثبت سفارش قطعاً رد شده (سفارشی ساخته نشده)؛ ربات برای این حالت متوقف نمی‌شود."""


def sha256_hex(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def sign_request(nonce, timestamp, api_key, secret, query_params='', body=''):
    """digest = SHA256(nonce + timestamp + api-key + queryParams + body) ؛ sign = SHA256(digest + secretKey)"""
    return sha256_hex(sha256_hex(f'{nonce}{timestamp}{api_key}{query_params}{body}') + secret)


def query_signature_string(params):
    """همه‌ی queryParams بر اساس کلید (ASCII صعودی) مرتب و به‌صورت key+value پشت هم می‌آیند؛ مثلاً id1uid200."""
    return ''.join(f'{k}{params[k]}' for k in sorted(params))


def body_string(body):
    """بدنه‌ی فشرده بدون هیچ فاصله؛ عیناً همین رشته هم امضا می‌شود و هم ارسال."""
    return json.dumps(body, separators=(',', ':'), ensure_ascii=False) if body else ''


def _dec(x):
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _fnum(x, default=0.0):
    try:
        v = float(x)
        return v if v == v else default
    except (TypeError, ValueError):
        return default


def fmt_decimal(d):
    """Decimal را بدون نماد علمی (e-05) به رشته می‌دهد."""
    s = format(d, 'f')
    if '.' in s:
        s = s.rstrip('0').rstrip('.')
    return s or '0'


class BitunixClient:
    def __init__(self, api_key='', secret='', base_url=BASE_URL, http=None, timeout=10, min_gap=0.11,
                 time_fn=time.time, sleep_fn=time.sleep, nonce_fn=None):
        self.api_key = (api_key or '').strip(); self.secret = (secret or '').strip()
        self.base_url = base_url.rstrip('/'); self.http = http or requests; self.timeout = timeout
        self.min_gap = min_gap; self._time = time_fn; self._sleep = sleep_fn
        self._nonce = nonce_fn or (lambda: uuid.uuid4().hex)
        self._lock = threading.Lock(); self._last = 0.0

    # ---- پایه ----
    def _throttle(self):
        with self._lock:
            wait = self._last + self.min_gap - self._time()
            if wait > 0:
                self._sleep(wait)
            self._last = self._time()

    def request(self, method, path, params=None, body=None, auth=True):
        method = method.upper(); params = {k: v for k, v in (params or {}).items() if v is not None}
        params = {k: (str(v).lower() if isinstance(v, bool) else str(v)) for k, v in params.items()}
        headers = {'Content-Type': 'application/json', 'language': 'en-US'}
        data = None
        if auth:
            if not self.api_key or not self.secret:
                raise BitunixError(-1, 'API key/secret missing', None, path)
            nonce = self._nonce(); ts = str(int(self._time() * 1000))
            bstr = body_string(body)
            headers.update({'api-key': self.api_key, 'nonce': nonce, 'timestamp': ts,
                            'sign': sign_request(nonce, ts, self.api_key, self.secret, query_signature_string(params), bstr)})
            data = bstr.encode('utf-8') if bstr else None
        elif body:
            data = body_string(body).encode('utf-8')
        self._throttle()
        r = self.http.request(method, f'{self.base_url}{path}', params=params or None, data=data, headers=headers, timeout=self.timeout)
        try:
            payload = r.json()
        except Exception:
            payload = None
        status = getattr(r, 'status_code', 200)
        if not isinstance(payload, dict):
            raise BitunixError(-2, 'invalid response', status, path)
        code = payload.get('code')
        if status != 200 or code != 0:
            raise BitunixError(code, payload.get('msg') or payload.get('message'), status, path)
        return payload.get('data')

    # ---- عمومی ----
    def trading_pairs(self, symbols=None):
        return self.request('GET', '/api/v1/futures/market/trading_pairs', {'symbols': symbols} if symbols else None, auth=False) or []

    def tickers(self, symbols=None):
        return self.request('GET', '/api/v1/futures/market/tickers', {'symbols': symbols} if symbols else None, auth=False) or []

    # ---- حساب ----
    def account(self):
        d = self.request('GET', '/api/v1/futures/account', {'marginCoin': MARGIN_COIN})
        if isinstance(d, list):
            for row in d:
                if str(row.get('marginCoin', MARGIN_COIN)).upper() == MARGIN_COIN:
                    return row
            return {}
        return d or {}

    def change_position_mode(self, mode):
        return self.request('POST', '/api/v1/futures/account/change_position_mode', body={'positionMode': mode})

    def leverage_margin_mode(self, symbol):
        return self.request('GET', '/api/v1/futures/account/get_leverage_margin_mode', {'symbol': symbol, 'marginCoin': MARGIN_COIN}) or {}

    def change_margin_mode(self, symbol, mode):
        return self.request('POST', '/api/v1/futures/account/change_margin_mode', body={'marginMode': mode, 'symbol': symbol, 'marginCoin': MARGIN_COIN})

    def change_leverage(self, symbol, leverage):
        return self.request('POST', '/api/v1/futures/account/change_leverage', body={'symbol': symbol, 'leverage': int(leverage), 'marginCoin': MARGIN_COIN})

    # ---- پوزیشن‌ها ----
    def pending_positions(self, symbol=None, position_id=None):
        return self.request('GET', '/api/v1/futures/position/get_pending_positions', {'symbol': symbol, 'positionId': position_id}) or []

    def history_positions(self, symbol=None, position_id=None, start=None, end=None, skip=0, limit=100):
        d = self.request('GET', '/api/v1/futures/position/get_history_positions',
                         {'symbol': symbol, 'positionId': position_id, 'startTime': start, 'endTime': end, 'skip': skip, 'limit': limit}) or {}
        return d.get('positionList') or []

    # ---- سفارش‌ها ----
    def place_order(self, symbol, side, qty, order_type='MARKET', price=None, reduce_only=False, trade_side=None, position_id=None, client_id=None):
        body = {'symbol': symbol, 'side': side, 'qty': qty, 'orderType': order_type}
        if order_type == 'LIMIT':
            body['price'] = price; body['effect'] = 'GTC'
        if reduce_only:
            body['reduceOnly'] = True
        if trade_side:
            body['tradeSide'] = trade_side
        if position_id:
            body['positionId'] = str(position_id)
        if client_id:
            body['clientId'] = client_id
        return self.request('POST', '/api/v1/futures/trade/place_order', body=body) or {}

    def order_detail(self, order_id):
        return self.request('GET', '/api/v1/futures/trade/get_order_detail', {'orderId': order_id}) or {}

    def cancel_orders(self, symbol, order_ids):
        return self.request('POST', '/api/v1/futures/trade/cancel_orders', body={'symbol': symbol, 'orderList': [{'orderId': str(o)} for o in order_ids]}) or {}

    def history_trades(self, symbol=None, order_id=None, position_id=None, start=None, end=None, skip=0, limit=100):
        d = self.request('GET', '/api/v1/futures/trade/get_history_trades',
                         {'symbol': symbol, 'orderId': order_id, 'positionId': position_id, 'startTime': start, 'endTime': end, 'skip': skip, 'limit': limit}) or {}
        return d.get('tradeList') or []

    def flash_close(self, position_id):
        return self.request('POST', '/api/v1/futures/trade/flash_close_position', body={'positionId': str(position_id)})

    # ---- TP/SL پوزیشن ----
    def tpsl_pending(self, symbol=None, position_id=None):
        return self.request('GET', '/api/v1/futures/tpsl/get_pending_orders', {'symbol': symbol, 'positionId': position_id, 'limit': 100}) or []

    def tpsl_place_position(self, symbol, position_id, sl=None, tp=None, stop_type='MARK_PRICE'):
        body = {'symbol': symbol, 'positionId': str(position_id)}
        if tp is not None: body.update(tpPrice=tp, tpStopType=stop_type)
        if sl is not None: body.update(slPrice=sl, slStopType=stop_type)
        return self.request('POST', '/api/v1/futures/tpsl/position/place_order', body=body)

    def tpsl_modify_position(self, symbol, position_id, sl=None, tp=None, stop_type='MARK_PRICE'):
        body = {'symbol': symbol, 'positionId': str(position_id)}
        if tp is not None: body.update(tpPrice=tp, tpStopType=stop_type)
        if sl is not None: body.update(slPrice=sl, slStopType=stop_type)
        return self.request('POST', '/api/v1/futures/tpsl/position/modify_order', body=body)

    def tpsl_cancel(self, symbol, order_id):
        return self.request('POST', '/api/v1/futures/tpsl/cancel_order', body={'symbol': symbol, 'orderId': str(order_id)})


class BitunixExchange:
    """ظاهر ccxt برای همان متدهایی که مسیر REAL ربات صدا می‌زند (markets، fetch_balance، fetch_positions، create_order، ...)."""
    is_bitunix = True
    name = 'Bitunix'

    def __init__(self, api_key='', secret='', client=None, margin_mode='isolated', stop_type='MARK_PRICE', sleep_fn=time.sleep):
        self.client = client or BitunixClient(api_key, secret)
        self.markets = {}; self._by_id = {}
        self.margin_mode = 'CROSS' if str(margin_mode).lower() == 'cross' else 'ISOLATION'
        self.stop_type = 'LAST_PRICE' if str(stop_type).upper().startswith('LAST') else 'MARK_PRICE'
        self._one_way_ok = False; self._sleep = sleep_fn

    # ---- بازارها ----
    def load_markets(self):
        markets = {}; by_id = {}
        for p in self.client.trading_pairs():
            if str(p.get('quote', '')).upper() != MARGIN_COIN:
                continue
            base = str(p.get('base', '')).upper(); sid = str(p.get('symbol') or f'{base}{MARGIN_COIN}')
            if not base:
                continue
            active = str(p.get('symbolStatus', 'OPEN')).upper() == 'OPEN' and p.get('isApiSupported') is not False
            m = {'id': sid, 'symbol': f'{base}/{MARGIN_COIN}:{MARGIN_COIN}', 'base': base, 'quote': MARGIN_COIN, 'active': active, 'contract': True,
                 'limits': {'amount': {'min': _fnum(p.get('minTradeVolume')) or None}, 'cost': {'min': None}},
                 'precision': {'amount': int(_fnum(p.get('basePrecision'), 0)), 'price': int(_fnum(p.get('quotePrecision'), 0))},
                 'maxLeverage': _fnum(p.get('maxLeverage')) or None, 'info': p}
            markets[m['symbol']] = m; by_id[sid] = m
        if not markets:
            raise BitunixError(-3, 'empty trading pairs list', None, 'trading_pairs')
        self.markets = markets; self._by_id = by_id
        return markets

    def _market(self, symbol):
        m = self.markets.get(symbol) or self._by_id.get(str(symbol).replace('/', '').replace(':USDT', ''))
        if not m:
            raise BitunixError(-4, f'unknown symbol {symbol}', None, 'market')
        return m

    def _sid(self, symbol):
        return self._market(symbol)['id']

    def amount_to_precision(self, symbol, amount):
        m = self._market(symbol); step = Decimal(1).scaleb(-m['precision']['amount'])
        return fmt_decimal(_dec(amount).quantize(step, rounding=ROUND_DOWN))

    def price_to_precision(self, symbol, price):
        m = self._market(symbol); step = Decimal(1).scaleb(-m['precision']['price'])
        return fmt_decimal(_dec(price).quantize(step, rounding=ROUND_HALF_UP))

    # ---- قیمت و موجودی ----
    def fetch_ticker(self, symbol):
        sid = self._sid(symbol)
        for t in self.client.tickers(sid):
            if str(t.get('symbol')) == sid:
                last = _fnum(t.get('lastPrice') or t.get('last'))
                return {'last': last, 'mark': _fnum(t.get('markPrice')) or last, 'close': last, 'info': t}
        raise BitunixError(-5, f'no ticker for {sid}', None, 'tickers')

    def fetch_balance(self):
        a = self.client.account()
        avail = _fnum(a.get('available')); frozen = _fnum(a.get('frozen')); margin = _fnum(a.get('margin'))
        upnl = _fnum(a.get('crossUnrealizedPNL')) + _fnum(a.get('isolationUnrealizedPNL'))
        total = avail + frozen + margin + upnl
        return {'total': {MARGIN_COIN: total}, 'free': {MARGIN_COIN: avail}, 'used': {MARGIN_COIN: frozen + margin}, 'info': a}

    # ---- پوزیشن‌ها ----
    def fetch_positions(self, symbols=None):
        sid = None
        if symbols:
            sid = self._sid(symbols[0]) if len(symbols) == 1 else None
        rows = self.client.pending_positions(sid)
        wanted = {self._sid(s) for s in symbols} if symbols else None
        out = []
        for r in rows:
            psid = str(r.get('symbol') or '')
            if wanted is not None and psid not in wanted:
                continue
            m = self._by_id.get(psid)
            sym = m['symbol'] if m else f"{psid.replace(MARGIN_COIN, '')}/{MARGIN_COIN}:{MARGIN_COIN}"
            out.append({'id': str(r.get('positionId')), 'symbol': sym, 'side': 'long' if str(r.get('side')).upper() == 'LONG' else 'short',
                        'contracts': _fnum(r.get('qty')), 'contractSize': 1.0, 'entryPrice': _fnum(r.get('avgOpenPrice')),
                        'leverage': int(_fnum(r.get('leverage'), 1)), 'unrealizedPnl': _fnum(r.get('unrealizedPNL')),
                        'marginMode': str(r.get('marginMode', '')).lower(), 'info': r})
        return out

    # ---- حالت پوزیشن / مارجین / اهرم ----
    def ensure_one_way(self):
        if self._one_way_ok:
            return
        mode = str(self.client.account().get('positionMode') or '').upper()
        if mode == 'HEDGE':
            self.client.change_position_mode('ONE_WAY')      # با پوزیشن/سفارش باز رد می‌شود و خطا بالا می‌آید
        self._one_way_ok = True

    def set_margin_mode(self, mode, symbol):
        sid = self._sid(symbol); want = 'CROSS' if str(mode).lower() == 'cross' else 'ISOLATION'
        try:
            if str(self.client.leverage_margin_mode(sid).get('marginMode') or '').upper() == want:
                return
        except BitunixError:
            pass
        self.client.change_margin_mode(sid, want)

    def fetch_market_leverage_tiers(self, symbol):
        mx = self._market(symbol).get('maxLeverage')
        return [{'maxLeverage': mx}] if mx else []

    def set_leverage(self, leverage, symbol):
        sid = self._sid(symbol)
        try:
            if int(_fnum(self.client.leverage_margin_mode(sid).get('leverage'))) == int(leverage):
                return
        except BitunixError:
            pass
        self.client.change_leverage(sid, int(leverage))

    # ---- سفارش‌ها ----
    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        params = params or {}; sid = self._sid(symbol)
        otype = 'LIMIT' if str(order_type).lower() == 'limit' else 'MARKET'
        qty = fmt_decimal(_dec(amount))
        px = fmt_decimal(_dec(price)) if (otype == 'LIMIT' and price is not None) else None
        try:
            d = self.client.place_order(sid, 'BUY' if str(side).lower() == 'buy' else 'SELL', qty, otype, px,
                                       reduce_only=bool(params.get('reduceOnly')))
        except BitunixError as exc:
            if exc.status == 200 and exc.code not in (None, 0, -1, -2):
                raise BitunixOrderRejected(exc.code, exc.msg, exc.status, exc.path) from exc    # قطعاً رد شده
            raise
        return {'id': str(d.get('orderId') or ''), 'clientOrderId': d.get('clientId'), 'status': None, 'filled': None, 'average': None, 'info': d}

    _STATUS = {'FILLED': 'closed', 'NEW': 'open', 'INIT': 'open', 'PART_FILLED': 'partially_filled', 'CANCELED': 'canceled'}

    def fetch_order(self, order_id, symbol=None):
        d = self.client.order_detail(order_id)
        status = self._STATUS.get(str(d.get('status') or '').upper(), 'open')
        filled = _fnum(d.get('tradeQty'))
        avg = self._avg_fill_price(order_id, d) if filled > 0 else None
        return {'id': str(d.get('orderId') or order_id), 'status': status, 'filled': filled, 'average': avg,
                'price': _fnum(d.get('price')) or None, 'amount': _fnum(d.get('qty')), 'info': d}

    def _avg_fill_price(self, order_id, detail):
        try:
            tr = self.client.history_trades(order_id=order_id, limit=100)
            qty = sum(_fnum(t.get('qty') or t.get('tradeQty')) for t in tr)
            val = sum(_fnum(t.get('qty') or t.get('tradeQty')) * _fnum(t.get('price') or t.get('tradePrice')) for t in tr)
            if qty > 0 and val > 0:
                return val / qty
        except Exception as exc:
            logger.debug('bitunix avg price via trades failed: %s', exc)
        if not detail.get('reduceOnly') and str(detail.get('orderType') or detail.get('type') or '').upper() == 'MARKET':
            try:                                      # سفارش بازکننده‌ی مارکت: میانگین ورود پوزیشن همان قیمت پر شدن است
                for p in self.client.pending_positions(detail.get('symbol')):
                    if _fnum(p.get('avgOpenPrice')) > 0:
                        return _fnum(p.get('avgOpenPrice'))
            except Exception:
                pass
        return None

    def cancel_order(self, order_id, symbol=None):
        sid = self._sid(symbol) if symbol else None
        return self.client.cancel_orders(sid, [order_id])

    def fetch_my_trades(self, symbol, since=None, limit=200):
        sid = self._sid(symbol); out = []; skip = 0
        while len(out) < int(limit or 200):
            rows = self.client.history_trades(symbol=sid, start=int(since) if since else None, skip=skip, limit=100)
            for t in rows:
                q = _fnum(t.get('qty') or t.get('tradeQty')); px = _fnum(t.get('price') or t.get('tradePrice'))
                fee = abs(_fnum(t.get('fee')))
                out.append({'timestamp': _fnum(t.get('ctime')), 'price': px, 'amount': q, 'cost': q * px, 'fee': {'cost': fee, 'currency': MARGIN_COIN},
                            'info': {'realizedPnl': _fnum(t.get('realizedPNL')), 'commission': fee, 'commissionAsset': MARGIN_COIN, **t}})
            if len(rows) < 100:
                break
            skip += 100
        return out[: int(limit or 200)]

    # ---- TP/SL پوزیشن ----
    @staticmethod
    def _pos_orders(rows, position_id):
        return [r for r in rows if str(r.get('positionId')) == str(position_id)]

    def get_position_tpsl(self, symbol_id, position_id):
        """{'sl': float|None, 'tp': float|None, 'order_id': ...} برای TP/SL پوزیشن (فقط یک مورد برای هر پوزیشن)."""
        rows = self._pos_orders(self.client.tpsl_pending(symbol_id, position_id), position_id)
        if not rows:
            return {'sl': None, 'tp': None, 'order_id': None}
        r = rows[0]
        return {'sl': _fnum(r.get('slPrice')) or None, 'tp': _fnum(r.get('tpPrice')) or None, 'order_id': r.get('id')}

    def set_position_tpsl(self, symbol, position_id, sl=None, tp=None, keep_existing=False):
        """sl/tp: قیمت‌های گردشده (رشته/عدد). keep_existing=True: مقدار ندادن یک طرف یعنی «همان قبلی بماند»."""
        sid = self._market(symbol)['id'] if symbol in self.markets or symbol in self._by_id else str(symbol)
        cur = self.get_position_tpsl(sid, position_id)
        if keep_existing:
            sl = sl if sl is not None else cur['sl']; tp = tp if tp is not None else cur['tp']
        if sl is None and tp is None:
            raise BitunixError(-6, 'nothing to set', None, 'tpsl')
        sl_s = fmt_decimal(_dec(sl)) if sl is not None else None; tp_s = fmt_decimal(_dec(tp)) if tp is not None else None
        if cur['order_id'] is not None:
            self.client.tpsl_modify_position(sid, position_id, sl=sl_s, tp=tp_s, stop_type=self.stop_type)
        else:
            self.client.tpsl_place_position(sid, position_id, sl=sl_s, tp=tp_s, stop_type=self.stop_type)
        return {'sl': float(sl_s) if sl_s else None, 'tp': float(tp_s) if tp_s else None}

    def cancel_position_tpsl(self, symbol):
        sid = self._market(symbol)['id'] if symbol in self.markets or symbol in self._by_id else str(symbol)
        n = 0
        for r in self.client.tpsl_pending(sid):
            if r.get('id') is not None:
                try:
                    self.client.tpsl_cancel(sid, r['id']); n += 1
                except BitunixError as exc:
                    logger.debug('cancel tpsl %s: %s', r.get('id'), exc)
        return n

    def flash_close(self, position_id):
        return self.client.flash_close(position_id)
