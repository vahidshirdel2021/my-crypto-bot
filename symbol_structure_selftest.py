"""V3.44.105: مانع ثبت وقتی ساختار سقف/کف نماد خلاف جهت سیگنال است (روی خودِ bot.py، دیتابیس موقت). اجرا: python3 symbol_structure_selftest.py"""
import sys, types, os, tempfile
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try:
        __import__(name)
    except Exception:
        sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ['TELEGRAM_TOKEN'] = '123:abc'
os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import pandas as pd
bot = importlib.import_module('bot')
bot.init_db()

def make_df(waypoints, tail_close=None):
    """کندل‌ها از درون‌یابی خطی بین نقاط؛ پیوت‌ها دقیقاً روی نقاط می‌افتند. آخرین ردیف = کندل در حال تشکیل."""
    closes = []
    for a, b in zip(waypoints, waypoints[1:]):
        for k in range(8):
            closes.append(a + (b - a) * k / 8.0)
    closes.append(waypoints[-1])
    if tail_close is not None:
        closes.append(tail_close)
    closes.append(closes[-1])                      # کندل در حال تشکیل
    return pd.DataFrame({'open': closes, 'close': closes, 'high': [c + 0.05 for c in closes], 'low': [c - 0.05 for c in closes]})

S = bot._swing_structure
UP = [100, 110, 104, 115, 108, 120, 113, 124, 117]           # سقف‌ها: 110<115<120<124 ، کف‌ها: 104<108<113<117 (نهایی 117 → آخرین کف 113)
DOWN = [124, 114, 120, 108, 114, 100, 107, 92, 99]            # سقف‌ها و کف‌ها پایین‌تر
MIX = [100, 110, 104, 108, 102, 112, 106, 111, 105]           # سقف‌ها بالا/پایین قاطی
assert S(make_df(UP))[0] == 'UP', S(make_df(UP))
assert S(make_df(DOWN))[0] == 'DOWN', S(make_df(DOWN))
assert S(make_df(MIX))[0] is None, S(make_df(MIX))
assert S(make_df([100, 101, 100.5, 101.2]))[0] is None              # داده‌ی ناکافی
assert S(None)[0] is None
# شکست ساختار: کلوز آخر زیر آخرین کفِ بالاتر (113) → دیگر UP نیست ؛ و برعکس در DOWN
st_break, info = S(make_df(UP, tail_close=100.0)); assert st_break is None, (st_break, info)
st_break, info = S(make_df(DOWN, tail_close=130.0)); assert st_break is None, (st_break, info)
# علّی بودن: کندل در حال تشکیل نتیجه را عوض نمی‌کند
d = make_df(UP); d2 = d.copy(); d2.loc[d2.index[-1], ['high', 'low', 'close']] = [999, 1, 50]
assert S(d)[0] == S(d2)[0] == 'UP'

# ---- verdict ----
state = {'df': make_df(UP)}
bot.get_klines = lambda symbol, tf, limit=200: state['df']
V = bot._symbol_structure_verdict
ok, txt = V('XYZ', '15min', 'SELL'); assert not ok and 'صعودی' in txt and 'فروش' in txt and '15' in txt, txt
assert V('XYZ', '15min', 'BUY')[0] is True
state['df'] = make_df(DOWN)
ok, txt = V('XYZ', '1hour', 'BUY'); assert not ok and 'نزولی' in txt and 'خرید' in txt, txt
assert V('XYZ', '1hour', 'SELL')[0] is True
state['df'] = make_df(MIX); assert V('XYZ', '15min', 'SELL')[0] and V('XYZ', '15min', 'BUY')[0]
bot.get_klines = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('x'))
assert V('XYZ', '15min', 'SELL')[0] is True                       # خطا/نبود داده = مجاز
# معاملات معکوس: جهت واقعی برعکس سنجیده می‌شود
bot.get_klines = lambda symbol, tf, limit=200: state['df']; state['df'] = make_df(UP)
S_inv = {'strategy_config': {'gate_inverse_trading_enabled': True}}
assert V('XYZ', '15min', 'BUY', S_inv)[0] is False and V('XYZ', '15min', 'SELL', S_inv)[0] is True

# ---- ثبت واقعی در لیست انتظار ----
CID = 222
s = bot.get_session(CID)
bot.latest_price = lambda sym: 100.0
bot._touch_eval_one = lambda chat_id, rec: None
bot._fn_touch_created = lambda *a, **k: None
bot.save_session = lambda *a, **k: None
reason = 'سناریو ۱ | HVL=100.0'
cfg = s.setdefault('strategy_config', {})
# کلید خاموش: ثبت می‌شود (رفتار قبلی دست‌نخورده)
cfg['gate_symbol_structure_block_enabled'] = False; s['touch_wait'] = {}; s['touch_wait_seen'] = {}
st, txt = bot._touch_register(CID, 'XYZ', 'SELL', reason, '15min'); assert st == 'touch_wait' and len(s['touch_wait']) == 1, (st, txt)
# کلید روشن + ساختار صعودی: فروش اصلاً ثبت نمی‌شود، خرید ثبت می‌شود
cfg['gate_symbol_structure_block_enabled'] = True; s['touch_wait'] = {}; s['touch_wait_seen'] = {}
state['df'] = make_df(UP)
st, txt = bot._touch_register(CID, 'XYZ', 'SELL', reason, '15min')
assert st == 'blocked' and 'صعودی' in txt and not s['touch_wait'] and not s['touch_wait_seen'], (st, txt, s['touch_wait'])
assert 'مانع ثبت' in txt                                         # نام دقیق کلید در پیام (برای ادمین)
st, txt = bot._touch_register(CID, 'XYZ', 'BUY', reason, '15min'); assert st == 'touch_wait' and len(s['touch_wait']) == 1, (st, txt)
# ساختار نزولی: خرید رد، فروش ثبت (نماد دیگر چون XYZ الان در لیست انتظار است)
s['touch_wait'] = {}; s['touch_wait_seen'] = {}; state['df'] = make_df(DOWN)
st, txt = bot._touch_register(CID, 'ABC', 'BUY', reason, '1hour'); assert st == 'blocked' and 'نزولی' in txt, (st, txt)
st, txt = bot._touch_register(CID, 'ABC', 'SELL', reason, '1hour'); assert st == 'touch_wait', (st, txt)
# مسیر «برگشت از صف تایید» (flip_from) هم از همین تابع می‌گذرد
s['touch_wait'] = {}; s['touch_wait_seen'] = {}; state['df'] = make_df(UP)
st, txt = bot._touch_register(CID, 'DEF', 'SELL', 'FLIP | ' + reason, '15min', flip_from='BUY'); assert st == 'blocked', (st, txt)
# ثبت کلید: پیش‌فرض خاموش، بخش رژیم، مدیریت‌شده در پریست
k = 'gate_symbol_structure_block_enabled'
assert bot.GATE_REGISTRY[k][1] is False and bot.GATE_REGISTRY[k][2] == 'regime'
import presets; assert presets.BASE_CFG.get(k) is False
print('symbol_structure_selftest ALL OK')
