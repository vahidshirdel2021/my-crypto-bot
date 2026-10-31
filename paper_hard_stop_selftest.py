"""تست آفلاین محافظ حد ضرر PAPER (قیمت لحظه‌ای). اجرا: python3 paper_hard_stop_selftest.py"""
import sys, types, os, tempfile, time
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try:
        __import__(name)
    except Exception:
        sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
_tmp = tempfile.mkdtemp()
os.environ.update(TELEGRAM_TOKEN='123:abc', ADMIN_CHAT_IDS='111', BOT_DB_PATH=os.path.join(_tmp, 'bot.sqlite3'),
                  PRESETS_CUSTOM_PATH=os.path.join(_tmp, 'p.json'), TELEGRAM_SKIP_BACKLOG='true')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib, pandas as pd
bot = importlib.import_module('bot')
bot.init_db()
ok_all = True
def check(name, cond, info=''):
    global ok_all
    ok_all &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name, info)

closed = []
bot.close_position = lambda chat_id, pos, price=None, reason='manual': (closed.append((pos['symbol'], round(float(price), 8), reason)) or (bot.get_session(chat_id)['paper_positions'].remove(pos), True)[1])
bot.send_message = lambda *a, **k: True
px = {'ANKR': 0.003890, 'AAA': 100.0}
bot.latest_price = lambda sym: px.get(sym)

def mk(sym, side, entry, sl, tp):
    return {'symbol': sym, 'side': side, 'entry_price': entry, 'sl': sl, 'tp': tp, 'margin': 100.0, 'leverage': 5, 'amount': 1.0,
            'risk_distance': abs(entry - sl), 'opened_at': time.time() - 10*86400, 'timeframe': '15min', 'trade_id': sym}

CID = 222
s = bot.get_session(CID); s['trading_mode'] = 'PAPER'; s['paper_positions'] = []
# موردِ گزارش‌شده: فروش ANKR، SL=0.003877، قیمت 0.003890
a = mk('ANKR', 'SELL (Short)', 0.003847, 0.003877, 0.003743)
b = mk('AAA', 'BUY (Long)', 100.0, 98.0, 110.0)
s['paper_positions'] = [a, b]
bot.paper_hard_stop_scan_once()
check('فروش بالاتر از SL بسته شد', [c for c in closed if c[0] == 'ANKR'] and closed[0][2].startswith('SL'), closed)
check('خرید بالای SL دست نخورد', b in s['paper_positions'] and not [c for c in closed if c[0] == 'AAA'])
check('قیمت خروج حداقل SL است (نه بهتر)', closed[0][1] >= 0.003877)
px['AAA'] = 97.5; closed.clear()
bot.paper_hard_stop_scan_once()
check('خرید پایین‌تر از SL بسته شد', [c for c in closed if c[0] == 'AAA'] and closed[0][1] <= 98.0, closed)
# حالت REAL و پوزیشن واقعی نادیده گرفته می‌شود
s['paper_positions'] = [mk('ANKR', 'SELL (Short)', 0.003847, 0.003877, 0.003743)]
s['trading_mode'] = 'REAL'; closed.clear()
bot.paper_hard_stop_scan_once()
check('حالت REAL: دست نمی‌زند', not closed)
s['trading_mode'] = 'PAPER'; s['paper_positions'][0]['is_real'] = True
bot.paper_hard_stop_scan_once()
check('پوزیشن واقعی: دست نمی‌زند', not closed)
s['paper_positions'][0]['is_real'] = False; px['ANKR'] = None
bot.paper_hard_stop_scan_once()
check('بدون قیمت: خطا نمی‌دهد و نمی‌بندد', not closed)

# update_positions: کندل کش‌شده/ناقص (high پایین‌تر از SL) ولی قیمت لحظه‌ای بالای SL => باید ببندد
px['ANKR'] = 0.003890
def klines(sym, tf, n):
    rows = [{'timestamp': (int(time.time()) - (200 - i) * 900) * 1000, 'open': 0.00385, 'high': 0.00386, 'low': 0.00384, 'close': 0.00385, 'volume': 1.0} for i in range(120)]
    return pd.DataFrame(rows)
bot.get_klines = klines
s['paper_positions'] = [mk('ANKR', 'SELL (Short)', 0.003847, 0.003877, 0.003743)]
closed.clear()
bot.update_positions(CID)
check('update_positions: قیمت لحظه‌ای در سنجش SL حساب شد', closed and closed[0][2].startswith('SL'), closed)
print('paper_hard_stop_selftest:', 'ALL OK' if ok_all else 'FAILED')
sys.exit(0 if ok_all else 1)
