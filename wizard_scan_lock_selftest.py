"""V3.44.180: «تنظیمات معامله» فقط وقتی اسکن متوقف است؛ در حال اسکن پیام هشدار می‌دهد."""
import sys, types, os, tempfile, json
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
out = []
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
CID = 987001
s = bot.get_session(CID)
for cmd in ('/check_wizard', '/wiz_tf', '/wiz_lev', '/wiz_max', '/wiz_same'):
    s['is_bot_active'] = True; out.clear()
    bot.process_command(cmd, CID, 1)
    assert out and 'اسکن' in out[-1][0] and any(b['callback_data'] == '/stop_scan' for r in out[-1][1]['inline_keyboard'] for b in r), (cmd, out)
s['is_bot_active'] = False; out.clear()
bot.process_command('/check_wizard', CID, 1)
assert out and any(b['callback_data'].startswith('/set_margin_') for r in out[-1][1]['inline_keyboard'] for b in r), out
print('WIZARD SCAN LOCK OK')
