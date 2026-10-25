"""V3.44.63: «🔴 توقف اسکن» (کیبورد ثابت پایین چت + دکمه‌ی منو + /stop_scan) برای همه‌ی کاربران همیشه کار می‌کند،
حتی وقتی حساب به‌خاطر کارمزد پرداخت‌نشده مسدود است. اجرا: python3 stop_scan_always_selftest.py"""
import sys, types, os, tempfile
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
import access_policy as ap
USER = 222
# ۱) دروازه‌ی حساب مسدود (کارمزد پرداخت‌نشده)
for c in ('/stop_scan', '🔴 توقف اسکن', 'توقف اسکن', '🔴 توقف'):
    assert bot.fee_block_allows(c), ('blocked-fee user cannot stop scan', c)
for c in ('/start_scan', '🟢 شروع اسکن', 'شروع اسکن', '/reload_and_start', '/manual_trade', '/mode_real'):
    assert not bot.fee_block_allows(c), ('must stay blocked', c)
assert bot.fee_block_allows('/open_positions') and bot.fee_block_allows('/fee_menu') and bot.fee_block_allows('🔄 پوزیشن‌ها')   # قبلی‌ها سالم
# ۲) قفل نقش: کاربر عادی مجاز است
assert all(ap.user_command_allowed(c) for c in ('/stop_scan', '🔴 توقف اسکن', 'توقف اسکن', '🔴 توقف'))
# ۳) اجرای واقعی: اسکن متوقف می‌شود (کاربر عادی، حساب مسدود)
out = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append(text) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append(text) or True
bot.sync_bottom_keyboard = lambda chat_id, text, *a, **k: out.append(text)
bot.exchange_balance = lambda c: 100.0
with bot._FEE_STATE_LOCK:
    bot._FEE_BLOCKED.add(USER)
assert bot.is_fee_blocked(USER)
for cmd in ('🔴 توقف اسکن', '/stop_scan'):
    s = bot.get_session(USER); s['is_bot_active'] = True
    out.clear(); bot.process_command(cmd, USER)
    assert s['is_bot_active'] is False and any('اسکن متوقف شد' in t for t in out), (cmd, out)
print('STOP SCAN ALWAYS OK')
