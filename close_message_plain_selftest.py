"""V3.44.62: پیام بسته‌شدن پوزیشن برای کاربر عادی ساده است؛ ادمین پیام کامل می‌گیرد. اجرا: python3 close_message_plain_selftest.py"""
import sys, types, os, tempfile, time
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ['TELEGRAM_TOKEN'] = '123:abc'; os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3'); os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot'); bot.init_db()
sent = []
bot.send_message = lambda chat_id, text, *a, **k: sent.append((chat_id, text)) or True
bot.save_session = lambda *a, **k: None
bot.journal_append_closed = lambda *a, **k: None

def make():
    return {'symbol': 'CRV', 'side': 'SELL', 'entry_price': 0.3500, 'sl': 0.36, 'tp': 0.33, 'margin': 20.0, 'leverage': 10,
            'amount': 571.0, 'is_real': False, 'opened_at': time.time() - 180, 'trade_id': 't1',
            'entry_reason': '[SETUP Halving] HVL=0.350352|SCN=4',
            'entry_warnings': ['رژیم ۴ ساعته رنج'], 'risk_usdt': 5.7}

for cid in (222, 111):
    s = bot.get_session(cid); s['paper_positions'] = []; s['closed_positions'] = []
    pos = make(); s['paper_positions'].append(pos)
    sent.clear()
    assert bot.close_position(cid, pos, price=0.3494, reason='بستن سر به سر: بعد از -0.65R ضرر به نقطه‌ی ورود برگشت')
    txt = [t for c, t in sent if 'بسته شد' in t][0]
    print(f'--- chat {cid} ---\n{txt}\n')
    if cid == 222:
        for bad in ('ستاپ', 'SETUP', 'رژیم', 'هشدار', 'اندیکاتور', 'سطح:'):
            assert bad not in txt, ('leak', bad)
        for need in ('CRV', 'زمان ورود', 'زمان خروج', 'خروج:', 'PnL خالص', 'علت'):
            assert need in txt, ('missing', need)
    else:
        assert 'SETUP' in txt and 'هشدار' in txt, 'admin lost detail'
print('CLOSE MESSAGE PLAIN OK')
