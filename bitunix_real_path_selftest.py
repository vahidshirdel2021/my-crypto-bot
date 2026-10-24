# -*- coding: utf-8 -*-
"""شبیه‌سازی مسیر REAL ربات روی «بیتیونیکس جعلی» (بدون اینترنت): همان توابع واقعی bot.py با BitunixExchange.
باز کردن پوزیشن، ثبت SL/TP، جابه‌جایی SL با حفظ TP، بستن بخشی، بستن کامل، PnL از تاریخچه، موجودی و قیمت."""
import json, logging, math, os, re, time
from threading import RLock
import bitunix_client as bx

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
src = open('bot.py', encoding='utf-8').read()
a = src.index("# ===================== Binance USDⓈ-M Futures (V3.44.0)"); b = src.index("def reserved_margin(")
BLOCK = src[a:b]
a2 = src.index("def partial_close_real_position("); b2 = src.index("\n\n# ===================== V3.43.27")
PARTIAL = src[a2:b2]

class Resp:
    def __init__(self, payload, status=200): self._p = payload; self.status_code = status
    def json(self): return self._p

class Sim:
    """حساب جعلیِ بیتیونیکس: موجودی، پوزیشن‌ها (one-way)، TP/SL پوزیشن و تاریخچه‌ی معاملات."""
    def __init__(self):
        self.price = 80000.0; self.pos = {}; self.tpsl = {}; self.trades = []; self.oid = 1000; self.tid = 0; self.next_pid = 500
        self.orders = {}; self.avail = 100.0; self.mm = 'ISOLATION'; self.lev = 5; self.pm = 'ONE_WAY'; self.log = []; self.fee_rate = 0.0006
    def request(self, method, url, params=None, data=None, headers=None, timeout=None):
        path = url.split('fapi.bitunix.com')[1]; body = json.loads(data.decode()) if data else {}; p = params or {}
        self.log.append((method, path, p, body))
        if path != '/api/v1/futures/market/trading_pairs' and path != '/api/v1/futures/market/tickers':
            assert headers.get('sign') and headers.get('api-key') == 'K', path                                      # همه‌ی درخواست‌های خصوصی امضا دارند
        parts = path.split('/'); name = parts[-1]
        if parts[-2] == 'position' and parts[-3] == 'tpsl': name = 'position_' + name              # /tpsl/position/place_order
        h = getattr(self, 'h_' + name, None)
        assert h is not None, f'no handler for {path}'
        data_out = h(p, body)
        return Resp({'code': 0, 'msg': 'Success', 'data': data_out})
    # عمومی
    def h_trading_pairs(self, p, b): return [{'symbol': 'BTCUSDT', 'base': 'BTC', 'quote': 'USDT', 'symbolStatus': 'OPEN', 'minTradeVolume': '0.0001', 'basePrecision': 4, 'quotePrecision': 1, 'maxLeverage': 125}]
    def h_tickers(self, p, b): return [{'symbol': 'BTCUSDT', 'lastPrice': str(self.price), 'markPrice': str(self.price)}]
    # حساب
    def h_account(self, p, b): return [{'marginCoin': 'USDT', 'available': str(self.avail), 'frozen': '0', 'margin': str(sum(float(x['margin']) for x in self.pos.values())), 'crossUnrealizedPNL': '0', 'isolationUnrealizedPNL': str(sum(self.upnl(x) for x in self.pos.values())), 'positionMode': self.pm}]
    def h_change_position_mode(self, p, b): self.pm = b['positionMode']; return [{'positionMode': self.pm}]
    def h_get_leverage_margin_mode(self, p, b): return {'symbol': p['symbol'], 'marginCoin': 'USDT', 'leverage': self.lev, 'marginMode': self.mm}
    def h_change_margin_mode(self, p, b): self.mm = b['marginMode']; return [{}]
    def h_change_leverage(self, p, b): self.lev = b['leverage']; return [{}]
    def upnl(self, x): return (self.price - float(x['avgOpenPrice'])) * float(x['qty']) * (1 if x['side'] == 'LONG' else -1)
    # پوزیشن‌ها / سفارش‌ها
    def h_get_pending_positions(self, p, b):
        return [dict(x, unrealizedPNL=str(self.upnl(x))) for x in self.pos.values() if not p.get('symbol') or x['symbol'] == p['symbol']]
    def h_place_order(self, p, b):
        assert self.pm == 'ONE_WAY' and b['orderType'] == 'MARKET'
        self.oid += 1; qty = float(b['qty']); sym = b['symbol']; side = b['side']; px = self.price; realized = 0.0
        cur = self.pos.get(sym)
        if b.get('reduceOnly'):
            assert cur and ((side == 'SELL') == (cur['side'] == 'LONG')), 'reduceOnly must oppose position'
            q = min(qty, float(cur['qty'])); realized = (px - float(cur['avgOpenPrice'])) * q * (1 if cur['side'] == 'LONG' else -1)
            cur['qty'] = str(round(float(cur['qty']) - q, 8)); qty = q
            if float(cur['qty']) <= 0: self.pos.pop(sym); self.tpsl = {k: v for k, v in self.tpsl.items() if v['positionId'] != cur['positionId']}
        else:
            assert cur is None, 'one-way only: no add in test'
            self.next_pid += 1
            self.pos[sym] = {'positionId': str(self.next_pid), 'symbol': sym, 'qty': str(qty), 'side': 'LONG' if side == 'BUY' else 'SHORT', 'leverage': self.lev, 'avgOpenPrice': str(px), 'margin': str(qty * px / self.lev), 'marginMode': self.mm}
            self.avail -= qty * px / self.lev
        fee = qty * px * self.fee_rate; self.tid += 1
        self.trades.append({'tradeId': str(self.tid), 'orderId': str(self.oid), 'symbol': sym, 'qty': str(qty), 'price': str(px), 'fee': str(fee), 'realizedPNL': str(realized), 'ctime': int(time.time() * 1000) + self.tid, 'reduceOnly': bool(b.get('reduceOnly'))})
        self.orders[str(self.oid)] = {'orderId': str(self.oid), 'status': 'FILLED', 'tradeQty': str(qty), 'qty': str(qty), 'price': '0', 'symbol': sym, 'orderType': 'MARKET', 'reduceOnly': bool(b.get('reduceOnly'))}
        return {'orderId': str(self.oid), 'clientId': ''}
    def h_get_order_detail(self, p, b): return self.orders[p['orderId']]
    def h_get_history_trades(self, p, b):
        rows = [t for t in self.trades if (not p.get('symbol') or t['symbol'] == p['symbol']) and (not p.get('orderId') or t['orderId'] == p['orderId']) and (not p.get('startTime') or t['ctime'] >= int(p['startTime']))]
        return {'tradeList': rows[int(p.get('skip', 0)): int(p.get('skip', 0)) + int(p.get('limit', 100))], 'total': len(rows)}
    # TP/SL پوزیشن
    def h_position_place_order(self, p, b):
        assert not [1 for v in self.tpsl.values() if v['positionId'] == b['positionId']], 'only one position TP/SL per position'
        self.oid += 1; self.tpsl[str(self.oid)] = {'id': str(self.oid), 'positionId': b['positionId'], 'symbol': b['symbol'], 'slPrice': b.get('slPrice'), 'tpPrice': b.get('tpPrice')}; return {'orderId': str(self.oid)}
    def h_position_modify_order(self, p, b):
        r = [v for v in self.tpsl.values() if v['positionId'] == b['positionId']][0]
        if 'slPrice' in b: r['slPrice'] = b['slPrice']
        if 'tpPrice' in b: r['tpPrice'] = b['tpPrice']
        return {'orderId': r['id']}
    def h_get_pending_orders(self, p, b): return [v for v in self.tpsl.values() if (not p.get('positionId') or v['positionId'] == p['positionId'])]
    def h_cancel_order(self, p, b): self.tpsl.pop(b['orderId'], None); return {'orderId': b['orderId']}

sim = Sim()
ex = bx.BitunixExchange(client=bx.BitunixClient('K', 'S', http=sim, min_gap=0), margin_mode='isolated'); ex.load_markets()

class ExchangeStateError(RuntimeError): pass
SENT = []
g = dict(os=os, re=re, json=json, math=math, time=time, logger=logging.getLogger('sim'), ExchangeStateError=ExchangeStateError, RLock=RLock,
         PROTECTION_TRIGGER='mark_price', MARGIN_MODE='isolated', TAKER_FEE_PCT=0.05, DATA_LOCK=RLock(), REAL_PRICE_CACHE={},
         get_exchange=lambda chat_id: ex, send_message=lambda *a, **k: SENT.append(a), real_venue_name=lambda chat_id=None, venue=None: 'Bitunix Futures',
         _BINANCE_SOURCES=(), tradingview_symbol=lambda s: s, BitunixOrderRejected=bx.BitunixOrderRejected,
         get_entry_lock=lambda c: RLock(), get_session=lambda c: SESS, save_session=lambda c: None, audit_event=lambda *a, **k: None, new_trade_id=lambda c, s: 't1')
SESS = {'paper_positions': []}
exec(BLOCK, g); exec(PARTIAL, g)
CHAT = 1

# ---- موجودی و قیمت
assert abs(g['exchange_balance'](CHAT) - 100.0) < 1e-9
assert g['exchange_latest_price'](CHAT, 'BTC') == 80000.0
fsym, scale, m = g['_fsym'](ex, 'BTC'); assert fsym == 'BTC/USDT:USDT' and scale == 1 and m['id'] == 'BTCUSDT'
try: g['_fsym'](ex, 'NOPE'); raise SystemExit('should raise')
except ExchangeStateError as e: assert 'Bitunix' in str(e)

# ---- آماده‌سازی نماد: one-way، مارجین، اهرم (اهرم بیش از سقف نماد کم می‌شود)
sim.pm = 'HEDGE'; sim.mm = 'CROSS'
lev = g['_binance_prepare_symbol'](ex, fsym, 10)
assert lev == 10 and sim.pm == 'ONE_WAY' and sim.mm == 'ISOLATION' and sim.lev == 10
assert g['_binance_prepare_symbol'](ex, fsym, 500) == 125                                         # سقف maxLeverage نماد

# ---- باز کردن: همان دنباله‌ی _execute_trade_unlocked
sim.lev = 5; amount = float(ex.amount_to_precision(fsym, 0.0625))
order = ex.create_order(fsym, 'market', 'buy', amount, None, {'newOrderRespType': 'RESULT'})
conf = ex.fetch_order(order['id'], fsym)
assert conf['status'] == 'closed' and conf['filled'] == 0.0625 and conf['average'] == 80000.0 and conf['price'] is None
live = g['find_position'](CHAT, 'BTC')
assert live['side'] == 'BUY (Long)' and live['amount'] == 0.0625 and live['entry_price'] == 80000.0 and live['leverage'] == 5 and live['position_id'] == '501'
ok, msg = g['set_protection'](CHAT, 'BTC', 79000.04, 83000.0)
assert ok and msg == 'OK', msg
rec = list(sim.tpsl.values())[0]; assert rec['slPrice'] == '79000' and rec['tpPrice'] == '83000' and rec['positionId'] == '501'
# ثبت دوباره (مثلاً بعد از ریکانسایل) خطای «یکی برای هر پوزیشن» نمی‌دهد: ویرایش می‌شود
ok, msg = g['set_protection'](CHAT, 'BTC', 79100, 83100); assert ok and len(sim.tpsl) == 1 and list(sim.tpsl.values())[0]['slPrice'] == '79100'

# ---- جابه‌جایی SL (BE/تریلینگ): TP دست‌نخورده
ok, msg = g['move_stop_loss'](CHAT, 'BTC', 80050.0)
assert ok and list(sim.tpsl.values())[0]['slPrice'] == '80050' and list(sim.tpsl.values())[0]['tpPrice'] == '83100', (ok, msg, sim.tpsl)
sim.tpsl = {}; ok, msg = g['move_stop_loss'](CHAT, 'BTC', 80100.0)                                  # TP/SL خالی: فقط SL ثبت می‌شود
assert ok and list(sim.tpsl.values())[0]['slPrice'] == '80100' and list(sim.tpsl.values())[0]['tpPrice'] is None

# ---- بستن بخشی (محافظ BTC): ۵۰٪ از حجم اولیه، SL/TP برای بقیه می‌ماند
SESS['paper_positions'] = [{'symbol': 'BTC', 'is_real': True, 'side': 'BUY (Long)', 'entry_price': 80000.0, 'margin': 1000.0, 'amount': 0.0625, 'leverage': 5, 'trade_id': 't1'}]
pos = SESS['paper_positions'][0]; sim.price = 80500.0
assert g['partial_close_real_position'](CHAT, pos, 80500.0, 0.5, 'محافظ BTC') is True
assert float(sim.pos['BTCUSDT']['qty']) == 0.0313 - 0.0 or abs(float(sim.pos['BTCUSDT']['qty']) - 0.0312) < 0.0002, sim.pos
assert pos['amount'] == float(sim.pos['BTCUSDT']['qty']) and pos['orig_amount'] == 0.0625 and len(sim.tpsl) == 1                # TP/SL هنوز هست
assert sim.log[-1][1] != '/api/v1/futures/tpsl/cancel_order'
reduce_calls = [x for x in sim.log if x[1].endswith('place_order') and x[3].get('reduceOnly')]; assert reduce_calls and reduce_calls[-1][3]['side'] == 'SELL'

# ---- بستن کامل + PnL از تاریخچه‌ی صرافی (کارمزد کم می‌شود)
t_open = time.time() - 60
rem = g['find_position'](CHAT, 'BTC'); sim.price = 81000.0
close = g['_close_market'](ex, fsym, True, rem['amount'])
assert 'BTCUSDT' not in sim.pos and sim.tpsl == {} and g['find_position'](CHAT, 'BTC') is None                # بعد از بسته شدن TP/SL هم پاک است
g['cancel_all_protection'](CHAT, 'BTC')                                                            # روی پوزیشن بسته‌شده بی‌خطر است
hist = g['position_history_for'](CHAT, 'BTC', int((t_open) * 1000))
gross = (80500 - 80000) * 0.0312 + (81000 - 80000) * (0.0625 - 0.0312); fees = sum(float(t['fee']) for t in sim.trades)
assert len(hist) == 1 and abs(hist[0]['info']['gross_realized'] - gross) < 1e-6 and abs(hist[0]['info']['fees'] - fees) < 1e-9 and abs(hist[0]['realizedPnl'] - (gross - fees)) < 1e-6, (hist, gross, fees)
assert hist[0]['close_price'] == 81000.0

# ---- شورت + cancel_all_protection روی TP/SL باز
sim.price = 80000.0; sim.avail = 100.0
o = ex.create_order(fsym, 'market', 'sell', 0.0125, None, {}); sp = g['find_position'](CHAT, 'BTC')
assert sp['side'] == 'SELL (Short)' and g['set_protection'](CHAT, 'BTC', 81000, 78000)[0] and len(sim.tpsl) == 1
g['cancel_all_protection'](CHAT, 'BTC'); assert sim.tpsl == {}
g['_close_market'](ex, fsym, False, 0.0125); assert g['find_position'](CHAT, 'BTC') is None

# ---- سفارش ردشده و حداقل حجم
class RejectSim(Sim):
    def h_place_order(self, p, b): return None
sim.price = 80000.0
bad = bx.BitunixExchange(client=bx.BitunixClient('K', 'S', http=type('H', (), {'request': lambda s_, method, url, params=None, data=None, headers=None, timeout=None: Resp({'code': 10012, 'msg': 'Insufficient balance'})})(), min_gap=0)); bad.markets = ex.markets; bad._by_id = ex._by_id
try: bad.create_order(fsym, 'market', 'buy', 1.0); raise SystemExit('should raise')
except bx.BitunixOrderRejected as e: assert e.code == 10012
print('bitunix_real_path_selftest: ALL OK')
