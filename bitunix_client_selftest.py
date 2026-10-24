# -*- coding: utf-8 -*-
"""تست کلاینت و لایه‌ی ccxt‌مانند بیتیونیکس + ذخیره‌ی رمزشده‌ی کلیدها (بدون اینترنت)."""
import hashlib, json, os, sqlite3, stat, tempfile
import bitunix_client as bx
from credentials_store import CredentialsStore, CredentialsError

# ---------------------------------------------------------------- امضا
assert bx.query_signature_string({'uid': '200', 'id': '1'}) == 'id1uid200'                        # نمونه‌ی مستندات
body = {"uid": "2899", "arr": [{"id": 1, "name": "maple"}, {"id": 2, "name": "lily"}]}
assert bx.body_string(body) == '{"uid":"2899","arr":[{"id":1,"name":"maple"},{"id":2,"name":"lily"}]}'      # بدون فاصله
assert bx.body_string(None) == '' and bx.body_string({}) == ''
d1 = hashlib.sha256(('123456' + '20241120123045' + 'yourApiKey' + 'id1uid200' + bx.body_string(body)).encode()).hexdigest()
assert bx.sign_request('123456', '20241120123045', 'yourApiKey', 'yourSecretKey', 'id1uid200', bx.body_string(body)) == hashlib.sha256((d1 + 'yourSecretKey').encode()).hexdigest()

# ---------------------------------------------------------------- HTTP جعلی
class Resp:
    def __init__(self, payload, status=200): self._p = payload; self.status_code = status
    def json(self):
        if self._p is None: raise ValueError('no json')
        return self._p
class Http:
    def __init__(self): self.routes = {}; self.calls = []
    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        path = url.split('fapi.bitunix.com')[1]
        body = json.loads(data.decode()) if data else None
        self.calls.append({'method': method, 'path': path, 'params': params or {}, 'body': body, 'headers': headers or {}, 'raw': data})
        h = self.routes.get((method, path))
        if h is None: raise AssertionError(f'unexpected {method} {path}')
        r = h(params or {}, body)
        return r if isinstance(r, Resp) else Resp({'code': 0, 'msg': 'Success', 'data': r})
clock = {'t': 1_700_000_000.0}; sleeps = []
def sleep(x): sleeps.append(x); clock['t'] += x
http = Http()
cl = bx.BitunixClient('KEY123456789', 'SECRET', http=http, time_fn=lambda: clock['t'], sleep_fn=sleep, nonce_fn=lambda: 'n' * 32, min_gap=0.11)

# ---------------------------------------------------------------- درخواست امضاشده
http.routes[('GET', '/api/v1/futures/account')] = lambda p, b: [{'marginCoin': 'USDT', 'available': '100', 'frozen': '1', 'margin': '9', 'crossUnrealizedPNL': '2', 'isolationUnrealizedPNL': '-1', 'positionMode': 'ONE_WAY'}]
acc = cl.account()
c = http.calls[-1]; h = c['headers']
assert acc['available'] == '100' and c['params'] == {'marginCoin': 'USDT'} and c['body'] is None and c['raw'] is None
assert h['api-key'] == 'KEY123456789' and h['nonce'] == 'n' * 32 and h['timestamp'] == str(1_700_000_000_000) and h['Content-Type'] == 'application/json'
assert h['sign'] == bx.sign_request('n' * 32, h['timestamp'], 'KEY123456789', 'SECRET', 'marginCoinUSDT', '')
assert 'SECRET' not in json.dumps(c)                                                                 # secret هرگز ارسال نمی‌شود
# POST: همان بایت‌هایی که امضا شده‌اند ارسال می‌شود
http.routes[('POST', '/api/v1/futures/account/change_leverage')] = lambda p, b: [{'leverage': 5}]
cl.change_leverage('BTCUSDT', 5)
c = http.calls[-1]; assert c['raw'].decode() == '{"symbol":"BTCUSDT","leverage":5,"marginCoin":"USDT"}'
assert c['headers']['sign'] == bx.sign_request('n' * 32, c['headers']['timestamp'], 'KEY123456789', 'SECRET', '', c['raw'].decode())
# نرخ‌گیر: فاصله‌ی حداقلی
sleeps.clear(); cl.account(); cl.account(); assert len(sleeps) >= 1 and all(abs(x - 0.11) < 0.02 or x > 0 for x in sleeps)
# عمومی: بدون هدر امضا
http.routes[('GET', '/api/v1/futures/market/tickers')] = lambda p, b: [{'symbol': 'BTCUSDT', 'lastPrice': '81000', 'markPrice': '81001'}]
cl.tickers('BTCUSDT'); assert 'sign' not in http.calls[-1]['headers'] and http.calls[-1]['params'] == {'symbols': 'BTCUSDT'}
# خطاها
http.routes[('GET', '/api/v1/futures/account')] = lambda p, b: Resp({'code': 10003, 'msg': 'Invalid api key'})
try: cl.account(); raise SystemExit('should raise')
except bx.BitunixError as e: assert e.code == 10003 and 'Invalid api key' in str(e)
http.routes[('GET', '/api/v1/futures/account')] = lambda p, b: Resp(None, 502)
try: cl.account(); raise SystemExit('should raise')
except bx.BitunixError as e: assert e.status == 502
try: bx.BitunixClient('', '', http=http).account(); raise SystemExit('should raise')
except bx.BitunixError as e: assert e.code == -1
http.routes[('GET', '/api/v1/futures/account')] = lambda p, b: {'marginCoin': 'USDT', 'available': '5'}            # دیکشنری هم پذیرفته می‌شود
assert cl.account()['available'] == '5'

# ---------------------------------------------------------------- BitunixExchange
pairs = [{'symbol': 'BTCUSDT', 'base': 'BTC', 'quote': 'USDT', 'symbolStatus': 'OPEN', 'minTradeVolume': '0.0001', 'basePrecision': 4, 'quotePrecision': 1, 'maxLeverage': 125, 'isApiSupported': True},
         {'symbol': '1000PEPEUSDT', 'base': '1000PEPE', 'quote': 'USDT', 'symbolStatus': 'OPEN', 'minTradeVolume': '1', 'basePrecision': 0, 'quotePrecision': 6, 'maxLeverage': 50},
         {'symbol': 'OLDUSDT', 'base': 'OLD', 'quote': 'USDT', 'symbolStatus': 'STOP', 'basePrecision': 2, 'quotePrecision': 2},
         {'symbol': 'NOAPIUSDT', 'base': 'NOAPI', 'quote': 'USDT', 'symbolStatus': 'OPEN', 'basePrecision': 2, 'quotePrecision': 2, 'isApiSupported': False},
         {'symbol': 'BTCUSD', 'base': 'BTC', 'quote': 'USD', 'symbolStatus': 'OPEN'}]
http = Http(); cl = bx.BitunixClient('K', 'S', http=http, time_fn=lambda: clock['t'], sleep_fn=sleep, min_gap=0)
http.routes[('GET', '/api/v1/futures/market/trading_pairs')] = lambda p, b: pairs
ex = bx.BitunixExchange(client=cl, margin_mode='isolated', stop_type='MARK_PRICE'); ex.load_markets()
assert set(ex.markets) == {'BTC/USDT:USDT', '1000PEPE/USDT:USDT', 'OLD/USDT:USDT', 'NOAPI/USDT:USDT'}
m = ex.markets['BTC/USDT:USDT']
assert m['id'] == 'BTCUSDT' and m['active'] is True and m['limits']['amount']['min'] == 0.0001 and m['limits']['cost']['min'] is None
assert ex.markets['OLD/USDT:USDT']['active'] is False and ex.markets['NOAPI/USDT:USDT']['active'] is False        # STOP / API پشتیبانی نمی‌شود
assert ex.amount_to_precision('BTC/USDT:USDT', 0.123456) == '0.1234' and ex.amount_to_precision('BTC/USDT:USDT', 0.00009) == '0'
assert ex.amount_to_precision('1000PEPE/USDT:USDT', 12.9) == '12' and ex.price_to_precision('BTC/USDT:USDT', 81000.26) == '81000.3'
assert ex.price_to_precision('1000PEPE/USDT:USDT', 0.0000123456) == '0.000012'                                      # بدون نماد علمی
http.routes[('GET', '/api/v1/futures/market/trading_pairs')] = lambda p, b: []
try: bx.BitunixExchange(client=cl).load_markets(); raise SystemExit('should raise')
except bx.BitunixError: pass

http.routes[('GET', '/api/v1/futures/market/tickers')] = lambda p, b: [{'symbol': 'BTCUSDT', 'lastPrice': '81000.5', 'markPrice': '81001'}]
t = ex.fetch_ticker('BTC/USDT:USDT'); assert t['last'] == 81000.5 and t['mark'] == 81001.0
http.routes[('GET', '/api/v1/futures/account')] = lambda p, b: [{'marginCoin': 'USDT', 'available': '100', 'frozen': '1', 'margin': '9', 'crossUnrealizedPNL': '2', 'isolationUnrealizedPNL': '-1', 'positionMode': 'ONE_WAY'}]
b = ex.fetch_balance(); assert b['total']['USDT'] == 111.0 and b['free']['USDT'] == 100.0 and b['used']['USDT'] == 10.0

# پوزیشن‌ها
rows = [{'positionId': '77', 'symbol': 'BTCUSDT', 'qty': '0.5', 'side': 'LONG', 'leverage': 10, 'avgOpenPrice': '80000', 'unrealizedPNL': '3.5', 'marginMode': 'ISOLATION'},
        {'positionId': '78', 'symbol': 'ETHUSDT', 'qty': '2', 'side': 'SHORT', 'leverage': 5, 'avgOpenPrice': '2000', 'unrealizedPNL': '-1'}]
http.routes[('GET', '/api/v1/futures/position/get_pending_positions')] = lambda p, b: [r for r in rows if not p.get('symbol') or r['symbol'] == p['symbol']]
ps = ex.fetch_positions()
assert len(ps) == 2 and ps[0] == {**ps[0], 'id': '77', 'symbol': 'BTC/USDT:USDT', 'side': 'long', 'contracts': 0.5, 'entryPrice': 80000.0, 'leverage': 10, 'unrealizedPnl': 3.5}
assert ps[1]['side'] == 'short' and ps[1]['symbol'] == 'ETH/USDT:USDT'
only = ex.fetch_positions(['BTC/USDT:USDT']); assert len(only) == 1 and only[0]['id'] == '77' and http.calls[-1]['params'] == {'symbol': 'BTCUSDT'}

# حالت One-way / مارجین / اهرم
http.routes[('GET', '/api/v1/futures/account')] = lambda p, b: [{'marginCoin': 'USDT', 'available': '1', 'positionMode': 'HEDGE'}]
http.routes[('POST', '/api/v1/futures/account/change_position_mode')] = lambda p, b: [{'positionMode': b['positionMode']}]
ex._one_way_ok = False; ex.ensure_one_way()
assert http.calls[-1]['path'].endswith('change_position_mode') and http.calls[-1]['body'] == {'positionMode': 'ONE_WAY'} and ex._one_way_ok
n = len(http.calls); ex.ensure_one_way(); assert len(http.calls) == n              # دوباره پرس‌وجو نمی‌شود
http.routes[('GET', '/api/v1/futures/account/get_leverage_margin_mode')] = lambda p, b: {'symbol': p['symbol'], 'leverage': 10, 'marginMode': 'ISOLATION'}
http.routes[('POST', '/api/v1/futures/account/change_margin_mode')] = lambda p, b: [{'positionMode': b['marginMode']}]
ex.set_margin_mode('isolated', 'BTC/USDT:USDT'); assert not http.calls[-1]['path'].endswith('change_margin_mode')    # همان مود: تغییری لازم نیست
ex.set_margin_mode('cross', 'BTC/USDT:USDT'); assert http.calls[-1]['body'] == {'marginMode': 'CROSS', 'symbol': 'BTCUSDT', 'marginCoin': 'USDT'}
http.routes[('POST', '/api/v1/futures/account/change_leverage')] = lambda p, b: [{'leverage': b['leverage']}]
ex.set_leverage(10, 'BTC/USDT:USDT'); assert http.calls[-1]['path'].endswith('get_leverage_margin_mode')            # همان اهرم: تغییری نیست
ex.set_leverage(5, 'BTC/USDT:USDT'); assert http.calls[-1]['body']['leverage'] == 5
assert ex.fetch_market_leverage_tiers('BTC/USDT:USDT') == [{'maxLeverage': 125.0}]

# سفارش
orders = {}
def place(p, body):
    if body['qty'] == '0.0001' and body['side'] == 'BUY' and body['symbol'] == 'BTCUSDT' and body.get('price') == '1':
        return Resp({'code': 10012, 'msg': 'Insufficient balance'})
    orders['last'] = body; return {'orderId': '9001', 'clientId': ''}
http.routes[('POST', '/api/v1/futures/trade/place_order')] = place
o = ex.create_order('BTC/USDT:USDT', 'market', 'buy', 0.1234, None, {'newOrderRespType': 'RESULT'})
assert o['id'] == '9001' and orders['last'] == {'symbol': 'BTCUSDT', 'side': 'BUY', 'qty': '0.1234', 'orderType': 'MARKET'}      # reduceOnly نیست
ex.create_order('BTC/USDT:USDT', 'market', 'sell', 0.1234, None, {'reduceOnly': True, 'newOrderRespType': 'RESULT'})
assert orders['last']['reduceOnly'] is True and orders['last']['side'] == 'SELL'
ex.create_order('BTC/USDT:USDT', 'limit', 'buy', 0.5, 80000.0)
assert orders['last']['orderType'] == 'LIMIT' and orders['last']['price'] == '80000' and orders['last']['effect'] == 'GTC'
ex.create_order('1000PEPE/USDT:USDT', 'market', 'buy', 1000000000.0)
assert orders['last']['qty'] == '1000000000'                                                         # بدون نماد علمی
try:
    ex.create_order('BTC/USDT:USDT', 'limit', 'buy', 0.0001, 1.0); raise SystemExit('should raise')
except bx.BitunixOrderRejected as e: assert e.code == 10012
class Boom(Http):
    def request(self, *a, **k): raise ConnectionError('timeout')
exb = bx.BitunixExchange(client=bx.BitunixClient('K', 'S', http=Boom(), sleep_fn=sleep, min_gap=0)); exb.markets = ex.markets; exb._by_id = ex._by_id
try: exb.create_order('BTC/USDT:USDT', 'market', 'buy', 0.1); raise SystemExit('should raise')
except ConnectionError: pass                                                                         # خطای شبکه: ابهام ⇒ rejected نیست (ربات متوقف می‌شود)
http.routes[('POST', '/api/v1/futures/trade/place_order')] = lambda p, b: Resp({'code': 0, 'data': None}, 500)
try: ex.create_order('BTC/USDT:USDT', 'market', 'buy', 0.1); raise SystemExit('should raise')
except bx.BitunixError as e: assert not isinstance(e, bx.BitunixOrderRejected)

# fetch_order: وضعیت‌ها، میانگین از معاملات، fallback به میانگین پوزیشن
detail = {'orderId': '9001', 'status': 'FILLED', 'tradeQty': '0.1234', 'qty': '0.1234', 'price': '0', 'symbol': 'BTCUSDT', 'orderType': 'MARKET', 'reduceOnly': False}
http.routes[('GET', '/api/v1/futures/trade/get_order_detail')] = lambda p, b: dict(detail)
http.routes[('GET', '/api/v1/futures/trade/get_history_trades')] = lambda p, b: {'tradeList': [{'orderId': '9001', 'qty': '0.1', 'price': '80000'}, {'orderId': '9001', 'qty': '0.0234', 'price': '80100'}], 'total': 2}
fo = ex.fetch_order('9001', 'BTC/USDT:USDT')
assert fo['status'] == 'closed' and fo['filled'] == 0.1234 and abs(fo['average'] - (0.1 * 80000 + 0.0234 * 80100) / 0.1234) < 1e-6 and fo['price'] is None
http.routes[('GET', '/api/v1/futures/trade/get_history_trades')] = lambda p, b: {'tradeList': [], 'total': 0}
fo = ex.fetch_order('9001', 'BTC/USDT:USDT'); assert fo['average'] == 80000.0                          # میانگین ورود پوزیشن
detail.update(status='NEW', tradeQty='0'); fo = ex.fetch_order('9001'); assert fo['status'] == 'open' and fo['filled'] == 0.0 and fo['average'] is None
detail.update(status='PART_FILLED', tradeQty='0.05'); assert ex.fetch_order('9001')['status'] == 'partially_filled'
detail.update(status='CANCELED'); assert ex.fetch_order('9001')['status'] == 'canceled'
http.routes[('POST', '/api/v1/futures/trade/cancel_orders')] = lambda p, b: {'successList': [{'orderId': '9001'}], 'failureList': []}
ex.cancel_order('9001', 'BTC/USDT:USDT'); assert http.calls[-1]['body'] == {'symbol': 'BTCUSDT', 'orderList': [{'orderId': '9001'}]}

# تاریخچه‌ی معاملات برای PnL
page = [{'tradeId': str(i), 'orderId': '1', 'qty': '0.1', 'price': '80000', 'fee': '0.05', 'realizedPNL': '1.5', 'ctime': 1_700_000_000_000 + i} for i in range(100)]
calls_h = []
def hist(p, b):
    calls_h.append(dict(p)); return {'tradeList': page if int(p.get('skip', 0)) == 0 else page[:20], 'total': 120}
http.routes[('GET', '/api/v1/futures/trade/get_history_trades')] = hist
tr = ex.fetch_my_trades('BTC/USDT:USDT', 1_700_000_000_000, 200)
assert len(tr) == 120 and calls_h[0]['symbol'] == 'BTCUSDT' and calls_h[0]['startTime'] == '1700000000000' and calls_h[1]['skip'] == '100'
assert tr[0]['info']['realizedPnl'] == 1.5 and tr[0]['fee'] == {'cost': 0.05, 'currency': 'USDT'} and tr[0]['price'] == 80000.0

# TP/SL پوزیشن: ثبت اولیه، ویرایش، حفظ TP هنگام جابه‌جایی SL، لغو
pend = {'rows': []}
http.routes[('GET', '/api/v1/futures/tpsl/get_pending_orders')] = lambda p, b: list(pend['rows'])
http.routes[('POST', '/api/v1/futures/tpsl/position/place_order')] = lambda p, b: (pend['rows'].append({'id': 'T1', 'positionId': b['positionId'], 'slPrice': b.get('slPrice'), 'tpPrice': b.get('tpPrice')}) or {'orderId': 'T1'})
def modify(p, b):
    r = pend['rows'][0]; r['slPrice'] = b.get('slPrice', r['slPrice']); r['tpPrice'] = b.get('tpPrice', r['tpPrice']); return {'orderId': 'T1'}
http.routes[('POST', '/api/v1/futures/tpsl/position/modify_order')] = modify
ex.set_position_tpsl('BTC/USDT:USDT', '77', sl='79000', tp='83000')
assert http.calls[-1]['path'].endswith('/position/place_order') and http.calls[-1]['body'] == {'symbol': 'BTCUSDT', 'positionId': '77', 'tpPrice': '83000', 'tpStopType': 'MARK_PRICE', 'slPrice': '79000', 'slStopType': 'MARK_PRICE'}
assert ex.get_position_tpsl('BTCUSDT', '77') == {'sl': 79000.0, 'tp': 83000.0, 'order_id': 'T1'}
ex.set_position_tpsl('BTC/USDT:USDT', '77', sl='79500', keep_existing=True)
assert http.calls[-1]['path'].endswith('/position/modify_order') and http.calls[-1]['body']['tpPrice'] == '83000' and http.calls[-1]['body']['slPrice'] == '79500'      # TP حفظ شد
http.routes[('POST', '/api/v1/futures/tpsl/cancel_order')] = lambda p, b: ({'orderId': b['orderId']} if (pend['rows'].clear() or True) else None)
assert ex.cancel_position_tpsl('BTC/USDT:USDT') == 1 and pend['rows'] == []
try: ex.set_position_tpsl('BTC/USDT:USDT', '77'); raise SystemExit('should raise')
except bx.BitunixError: pass
exl = bx.BitunixExchange(client=cl, stop_type='LAST_PRICE'); exl.markets = ex.markets; exl._by_id = ex._by_id
exl.set_position_tpsl('BTC/USDT:USDT', '77', sl='1'); assert http.calls[-1]['body']['slStopType'] == 'LAST_PRICE'

# ---------------------------------------------------------------- ذخیره‌ی رمزشده
from cryptography.fernet import Fernet
with tempfile.TemporaryDirectory() as td:
    dbp = os.path.join(td, 'x.sqlite3'); kp = os.path.join(td, 'credentials.key')
    st = CredentialsStore(dbp, key_path=kp, env_key=''); st.init_table()
    assert st.load(1, 'bitunix') is None and not st.has(1, 'bitunix')
    st.save(1, 'bitunix', 'AAAABBBBCCCC1234', 'SUPERSECRETVALUE'); st.save(1, 'binance', 'BKEY0001', 'BSECRET0001'); st.save(2, 'bitunix', 'OTHERKEY9999', 'OTHERSECRET')
    assert st.load(1, 'bitunix') == ('AAAABBBBCCCC1234', 'SUPERSECRETVALUE') and st.load(1, 'binance') == ('BKEY0001', 'BSECRET0001') and st.hint(1, 'bitunix') == '1234'
    raw = open(dbp, 'rb').read(); assert b'SUPERSECRETVALUE' not in raw and b'AAAABBBBCCCC1234' not in raw                 # در دیتابیس متن ساده نیست
    assert os.path.exists(kp) and stat.S_IMODE(os.stat(kp).st_mode) == 0o600
    st.save(1, 'bitunix', 'NEWKEY5678', 'NEWSECRET'); assert st.load(1, 'bitunix') == ('NEWKEY5678', 'NEWSECRET')           # جایگزینی
    st2 = CredentialsStore(dbp, key_path=kp, env_key=''); assert st2.load(2, 'bitunix') == ('OTHERKEY9999', 'OTHERSECRET')   # با همان فایل کلید دوباره خوانده می‌شود
    st3 = CredentialsStore(dbp, key_path=os.path.join(td, 'other.key'), env_key=Fernet.generate_key().decode())
    try: st3.load(1, 'bitunix'); raise SystemExit('should raise')
    except CredentialsError: pass                                                                                          # کلید رمزنگاری عوض شود: خطای واضح
    assert st.delete(1, 'bitunix') == 1 and st.load(1, 'bitunix') is None and st.load(1, 'binance') is not None
    assert st.delete(1) == 1 and not st.has(1, 'binance') and st.has(2, 'bitunix')
    try: st.save(3, 'bitunix', '', 'x'); raise SystemExit('should raise')
    except CredentialsError: pass
    try: CredentialsStore(dbp, key_path=kp, env_key='not-a-key')._fernet(); raise SystemExit('should raise')
    except CredentialsError: pass
print('bitunix_client_selftest: ALL OK')
