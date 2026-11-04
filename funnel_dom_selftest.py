"""V3.44.138: ثبت وضعیت جهت غالب بازار (dom) روی رکورد «touch» قیف. اجرا: python3 funnel_dom_selftest.py"""
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
os.environ['TELEGRAM_TOKEN'] = '123:abc'; os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3'); os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot'); bot.init_db()
assert bot.BOT_VERSION == '3.44.139'
s = bot.get_session(111); now = time.time()
bot.funnel_log.ENABLED = True
emitted = []
bot._fn_emit = lambda chat_id, kind, **kw: emitted.append((kind, kw))
bot._fn_count = lambda *a, **k: None
bot._fn_symbol_ctx = lambda *a, **k: {}
bot._fn_market_ctx = lambda *a, **k: {}
bot._fn_ctx = lambda *a, **k: {}
reg = []
bot.funnel_log.shadow_register = lambda *a, **k: reg.append((a, k)) or True

def load(b, sl):
    s['touch_wait'] = {}
    for i in range(b):
        s['touch_wait'][f'B{i}'] = {'id': f'B{i}', 'symbol': f'B{i}', 'touch_sig': 'BUY', 'dir': 'BUY', 'status': 'waiting', 'created_at': now, 'expires_at': now + 1800}
    for i in range(sl):
        s['touch_wait'][f'S{i}'] = {'id': f'S{i}', 'symbol': f'S{i}', 'touch_sig': 'SELL', 'dir': 'SELL', 'status': 'waiting', 'created_at': now, 'expires_at': now + 1800}

def dom_of(sig, b, sl):
    load(b, sl); emitted.clear()
    rec = {'id': 'X', 'symbol': 'X', 'touch_sig': sig, 'tf': '15min', 'created_at': now, 'touch_price': 100.0}
    bot._fn_touch_created(111, s, rec, {'entry': 100.0, 'sl': 99.0, 'tp': 102.0, 'rr': 2.0}, None)
    kind, kw = emitted[-1]; assert kind == 'touch'
    return kw['dom']

d = dom_of('BUY', 1, 6);  assert d['c'] == 'opposed' and d['d'] == 'SELL' and (d['b'], d['s']) == (1, 6), d
d = dom_of('SELL', 1, 6); assert d['c'] == 'aligned' and d['d'] == 'SELL', d
d = dom_of('BUY', 2, 2);  assert d['c'] == 'undecided' and d['d'] is None, d
# مستقل از کلیدهای گیت (خاموش) ثبت می‌شود
s.setdefault('strategy_config', {})['gate_touch_bias_block_enabled'] = False
d = dom_of('SELL', 6, 3); assert d['c'] == 'opposed' and d['d'] == 'BUY' and d['p'] == bot.TOUCH_BIAS_PCT, d
# V3.44.139: ثبت ردیابی واکنش به سطح (react) با level و مهلت = ۱۱ کندل
reg.clear(); load(0, 0)
rec = {'id': 'Y', 'symbol': 'Y', 'touch_sig': 'BUY', 'tf': '15min', 'created_at': now, 'touch_price': 100.0, 'level_value': 99.5}
bot._fn_touch_created(111, s, rec, {'entry': 100.0, 'sl': 99.0, 'tp': 102.0, 'rr': 2.0}, None)
rk = [x for x in reg if x[0][1] == 'react']
assert len(rk) == 1 and rk[0][1]['level'] == 99.5 and rk[0][1]['due_s'] == (bot.funnel_log.REACT_CANDLES + 3) * 900, reg
reg.clear(); rec2 = dict(rec, id='Z'); rec2.pop('level_value')
bot._fn_touch_created(111, s, rec2, {'entry': 100.0, 'sl': 99.0, 'tp': 102.0, 'rr': 2.0}, None)
assert not [x for x in reg if x[0][1] == 'react']          # بدون سطح = بدون react
print('funnel_dom_selftest ALL OK')
