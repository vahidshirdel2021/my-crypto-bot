"""V3.44.104: رأی «رژیم نماد در تایم‌فریم فعال» روی خودِ bot.py (دیتابیس موقت، بدون تلگرام). اجرا: python3 symreg_vote_selftest.py"""
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

asked = []
state = {'df': pd.DataFrame({'close': [1.0] * 100}), 'reg': 'BEARISH'}
def fake_klines(symbol, tf, limit=200):
    asked.append((symbol, tf)); return state['df']
bot.get_klines = fake_klines
bot._signal_channel_symbol_regime = lambda df: state['reg']

def votes(tf, sig_dir):
    v = bot._touch_votes('XYZ', tf, '', ('symreg',))
    assert len(v) == 1 and v[0]['key'] == 'symreg', v
    r = bot._touch_summarize(v, 'all', fixed_dir=sig_dir)
    return v[0], r

# سیگنال فروش: رژیم نزولی = رأی مثبت (موافق)، رژیم صعودی = رأی منفی (مخالف)
state['reg'] = 'BEARISH'; v, r = votes('15min', 'SELL')
assert v['vote'] == 'SELL' and v['status'] == 'ok' and r['agree'] == 1 and r['auto_ok'] is True, (v, r)
assert 'نزولی' in v['detail'] and '15' in v['detail'], v
state['reg'] = 'BULLISH'; v, r = votes('15min', 'SELL')
assert v['vote'] == 'BUY' and v['status'] == 'against' and r['agree'] == 0 and r['auto_ok'] is False, (v, r)
# سیگنال خرید: برعکس
state['reg'] = 'BULLISH'; v, r = votes('5min', 'BUY'); assert v['status'] == 'ok', v
state['reg'] = 'BEARISH'; v, r = votes('5min', 'BUY'); assert v['status'] == 'against', v
# رنج یا نبود داده = بدون رأی
for reg in ('RANGE', None):
    state['reg'] = reg; v, r = votes('15min', 'SELL'); assert v['vote'] is None and v['status'] == 'wait', (reg, v)
# روی ۱ ساعته: کندل‌های همان تایم‌فریم فعال گرفته می‌شود و رژیم با آن سنجیده می‌شود
asked.clear(); state['reg'] = 'BEARISH'; v, r = votes('1hour', 'SELL')
assert asked == [('XYZ', '1hour')] and v['status'] == 'ok' and '1س' in v['detail'], (asked, v)
# داده‌ی ناکافی (کمتر از ۶۰ کندل) یا خطا = بدون رأی
state['df'] = pd.DataFrame({'close': [1.0] * 30}); state['reg'] = 'BEARISH'
v, r = votes('15min', 'SELL'); assert v['vote'] is None
state['df'] = pd.DataFrame({'close': [1.0] * 100})
def boom(*a, **k): raise RuntimeError('x')
bot.get_klines = boom; v, r = votes('15min', 'SELL'); assert v['vote'] is None
# گروه مستقل با وزن ۱ (با گروه «روند» ادغام نمی‌شود)
assert bot._TOUCH_GROUP['symreg'] == 'symreg' and bot._TOUCH_GROUP_W['symreg'] == 1 and 'symreg' in bot._TOUCH_KEYS
# کلید ثبت‌شده: پیش‌فرض خاموش، در بخش رژیم، و جزو کلیدهای مدیریت‌شده‌ی پریست
k = 'gate_fc_symreg_enabled'
assert bot.GATE_REGISTRY[k][1] is False and bot.GATE_REGISTRY[k][2] == 'regime'
import presets
assert presets.BASE_CFG.get(k) is False
print('symreg_vote_selftest ALL OK')
