"""V3.44.67: دکمه‌های ثابت شروع/توقف اسکن برای کاربر عادی نباید «ممنوع» بدهند."""
import sys, types, os, tempfile
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ.update({'TELEGRAM_TOKEN': '123:abc', 'ADMIN_CHAT_IDS': '111', 'TELEGRAM_SKIP_BACKLOG': 'true',
                   'BOT_DB_PATH': os.path.join(tempfile.mkdtemp(), 'b.sqlite3')})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot'); bot.init_db()
sent = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: sent.append(text) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: sent.append(text) or True
calls = []
bot.start_scan = lambda cid, mid=None: calls.append('start')
bot.stop_scan = lambda cid, reason='manual': calls.append('stop')
bot.menu = lambda *a, **k: None
bot.sync_bottom_keyboard = lambda *a, **k: None
U = 222
for t, want in (('🟢 شروع اسکن', 'start'), ('شروع اسکن', 'start'), ('🔴 توقف اسکن', 'stop'), ('توقف اسکن', 'stop')):
    calls.clear(); sent.clear()
    bot.handle_text(U, t)
    assert calls == [want] and not any('در دسترس نیست' in x for x in sent), (t, calls, sent)
sent.clear(); bot.handle_text(U, 'BTC')
assert any('در دسترس نیست' in x for x in sent)      # تایپ نماد هنوز ممنوع
print('scan_button_user_selftest OK')
