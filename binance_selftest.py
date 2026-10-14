"""تست آفلاین (بدون اینترنت) لایه‌ی Binance با یک صرافی ساختگی. اجرا:  python binance_selftest.py"""
import os, re, time, math, logging, threading
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("# ===================== Binance USDⓈ-M Futures (V3.44.0)")
b = src.index("def side_long(side)")
block = src[a:b]
a2 = src.index("def market_meta(chat_id,symbol):"); b2 = src.index("def safe_size(")
block += "\n" + src[a2:b2]

class ExchangeStateError(RuntimeError): pass

class FakeEx:
    def __init__(self):
        self.calls = []; self.algo = []; self.next_id = 1000; self.dual = False
        mk = lambda base, prec=3: {'symbol': f'{base}/USDT:USDT', 'id': f'{base}USDT', 'active': True,
                                    'limits': {'amount': {'min': 0.001}, 'cost': {'min': 5}}}
        self.markets = {f'{b}/USDT:USDT': mk(b) for b in ('BTC', 'ETH', '1000SHIB', '1000PEPE', 'LUNA2', '1INCH')}
        self.positions = []; self.trades = []
    # ccxt-like
    def price_to_precision(self, sym, p): return f'{float(p):.6f}'.rstrip('0').rstrip('.')
    def amount_to_precision(self, sym, a): return f'{math.floor(float(a)*1000)/1000:.3f}'
    def fetch_positions(self, syms=None): return list(self.positions)
    def fetch_my_trades(self, sym, since=None, limit=None): return list(self.trades)
    def fetch_ticker(self, sym): return {'last': 0.0085 if 'SHIB' in sym else 100.0}
    def create_order(self, sym, typ, side, amt, price=None, params=None):
        self.calls.append(('create_order', sym, typ, side, amt, price, params)); return {'id': '1', 'average': 100.0}
    def fetch_order(self, oid, sym): return {'average': 100.0, 'filled': 1}
    def request(self, path, api, method, params=None):
        self.calls.append((method, path, dict(params or {})))
        if path == 'positionSide/dual' and method == 'GET': return {'dualSidePosition': self.dual}
        if path == 'positionSide/dual' and method == 'POST': self.dual = False; return {'code': 200}
        if path == 'algoOrder' and method == 'POST':
            self.next_id += 1
            self.algo.append({'algoId': self.next_id, 'orderType': params['type'], 'triggerPrice': params['triggerPrice'], 'symbol': params['symbol'], 'side': params['side'], 'closePosition': params['closePosition']})
            return {'algoId': self.next_id}
        if path == 'algoOrder' and method == 'DELETE':
            self.algo = [o for o in self.algo if o['algoId'] != params['algoId']]; return {'code': 200}
        if path == 'openAlgoOrders': return list(self.algo)
        raise RuntimeError('unexpected ' + path)

EX = FakeEx()
sent = []
g = dict(re=re, time=time, math=math, logger=logging.getLogger('t'), TAKER_FEE_PCT=0.05, PROTECTION_TRIGGER='mark_price',
         ExchangeStateError=ExchangeStateError, DATA_LOCK=threading.Lock(), REAL_PRICE_CACHE={},
         get_exchange=lambda cid: EX, side_long=lambda s: 'BUY' in str(s).upper() or 'LONG' in str(s).upper(),
         send_message=lambda *a, **k: sent.append(a), MARGIN_MODE='isolated')
exec(block, g)

# 1) mapping
assert g['futures_market'](EX, 'BTC')[1] == 1
m, sc = g['futures_market'](EX, 'SHIB'); assert m['symbol'] == '1000SHIB/USDT:USDT' and sc == 1000
m, sc = g['futures_market'](EX, 'LUNA'); assert m['symbol'] == 'LUNA2/USDT:USDT' and sc == 1
m, sc = g['futures_market'](EX, '1INCH'); assert m['symbol'] == '1INCH/USDT:USDT' and sc == 1
assert g['futures_market'](EX, 'NOPE')[0] is None
assert g['_split_futures_base']('1000SHIB') == (1000, 'SHIB') and g['_split_futures_base']('LUNA2') == (1, 'LUNA') and g['_split_futures_base']('1INCH') == (1, '1INCH')
print('mapping ok')

# 2) price/amount scaling
print('norm price SHIB:', g['normalize_price'](1, 'SHIB', 0.00000851234), ' amount:', g['normalize_amount'](1, 'SHIB', 1234567.0))
assert g['exchange_latest_price'](1, 'SHIB') == 0.0085/1000

# 3) position normalize
n = g['normalize_real_position']({'symbol': '1000SHIB/USDT:USDT', 'side': 'short', 'contracts': 500.0, 'entryPrice': 0.0085, 'leverage': 10, 'unrealizedPnl': 1.2})
assert n['symbol'] == 'SHIB' and n['amount'] == 500000.0 and abs(n['entry_price'] - 0.0000085) < 1e-12 and n['side'].startswith('SELL'), n
print('normalize ok', n)

# 4) protection (long BTC)
EX.positions = [{'symbol': 'BTC/USDT:USDT', 'side': 'long', 'contracts': 0.01, 'entryPrice': 100.0, 'leverage': 10, 'unrealizedPnl': 0}]
ok, err = g['set_protection'](1, 'BTC', 95.0, 110.0); assert ok, err
types = sorted((o['orderType'], o['triggerPrice'], o['side']) for o in EX.algo)
assert types == [('STOP_MARKET', '95', 'SELL'), ('TAKE_PROFIT_MARKET', '110', 'SELL')], types
posts = [c for c in EX.calls if c[0] == 'POST' and c[1] == 'algoOrder']
assert all(c[2]['closePosition'] == 'true' and c[2]['algoType'] == 'CONDITIONAL' and c[2]['workingType'] == 'MARK_PRICE' for c in posts)
print('set_protection ok')
ok, err = g['move_stop_loss'](1, 'BTC', 97.0); assert ok, err
sls = [o for o in EX.algo if o['orderType'] == 'STOP_MARKET']; assert len(sls) == 1 and sls[0]['triggerPrice'] == '97'
assert len([o for o in EX.algo if o['orderType'] == 'TAKE_PROFIT_MARKET']) == 1
print('move_stop_loss ok')
# re-set protection should not duplicate
ok, err = g['set_protection'](1, 'BTC', 96.0, 111.0); assert ok and len(EX.algo) == 2
# SHIB short protection scaled x1000 and BUY side
EX.algo.clear()
EX.positions = [{'symbol': '1000SHIB/USDT:USDT', 'side': 'short', 'contracts': 500.0, 'entryPrice': 0.0085, 'leverage': 10}]
ok, err = g['set_protection'](1, 'SHIB', 0.0000090, 0.0000080); assert ok, err
assert sorted((o['orderType'], o['triggerPrice'], o['side']) for o in EX.algo) == [('STOP_MARKET', '0.009', 'BUY'), ('TAKE_PROFIT_MARKET', '0.008', 'BUY')], EX.algo
print('scaled protection ok')
# failed new SL -> old restored
EX.algo.clear(); EX.positions = [{'symbol': 'BTC/USDT:USDT', 'side': 'long', 'contracts': 0.01, 'entryPrice': 100.0}]
g['set_protection'](1, 'BTC', 95.0, 110.0)
orig = EX.request
def flaky(path, api, method, params=None):
    if path == 'algoOrder' and method == 'POST' and params.get('triggerPrice') == '99': raise RuntimeError('-2021 Order would immediately trigger')
    return orig(path, api, method, params)
EX.request = flaky
ok, err = g['move_stop_loss'](1, 'BTC', 99.0); assert not ok
EX.request = orig
assert any(o['orderType'] == 'STOP_MARKET' and o['triggerPrice'] == '95' for o in EX.algo), EX.algo
print('SL restore ok')
# cancel_all_protection
g['cancel_all_protection'](1, 'BTC'); assert EX.algo == []

# 5) close + history
EX.calls.clear(); o = g['_close_market'](EX, '1000SHIB/USDT:USDT', False, 500.0)
c = EX.calls[-1]; assert c[3] == 'buy' and c[6]['reduceOnly'] is True and c[1] == '1000SHIB/USDT:USDT'
EX.trades = [{'timestamp': 1000, 'price': 100.0, 'cost': 100.0, 'fee': {'cost': 0.05, 'currency': 'USDT'}, 'info': {'realizedPnl': '0'}},
             {'timestamp': 2000, 'price': 104.0, 'cost': 104.0, 'fee': {'cost': 0.00008, 'currency': 'BNB'}, 'info': {'realizedPnl': '4.0'}}]
h = g['position_history_for'](1, 'BTC', 0)
assert len(h) == 1 and abs(h[0]['realizedPnl'] - (4.0 - 0.05 - 104.0*0.0005)) < 1e-9 and h[0]['close_price'] == 104.0, h
print('history ok', h[0]['realizedPnl'])

# 6) one-way mode auto-switch
EX2 = FakeEx(); EX2.dual = True
g['_ensure_one_way_mode'](EX2); assert EX2.dual is False
print('ALL OK')
