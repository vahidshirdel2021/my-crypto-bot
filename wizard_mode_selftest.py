"""V3.44.169: مرحله‌ی «حالت معامله» از ویزارد حذف شد؛ بعد از تایم‌فریم مستقیم منوی اصلی باز می‌شود و پیش‌فرض «معمولی» است.
اجرا: python3 wizard_mode_selftest.py"""
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
import access_policy as ap, presets as P
out = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
USER, ADMIN = 222, 111

assert ap.user_command_allowed('/wiz_tf') and ap.user_command_allowed('/wiz_mode_done')
assert not ap.user_command_allowed('/set_wmode_3') and not ap.user_command_allowed('/set_wmode_4')

su = bot.get_session(USER); sa = bot.get_session(ADMIN)
assert su['active_preset'] == '3' and P.preset_diff(su) == []
assert sa['active_preset'] is None

# آخرین مرحله‌ی ویزارد = تایم‌فریم؛ بعدش منوی اصلی (بدون صفحه‌ی حالت معامله)
out.clear(); bot.process_command('/set_tf_15m', USER)
text, mk = out[-1]
assert 'پنل اصلی' in text and 'حالت معامله' not in text and 'set_wmode' not in str(mk), text
assert su['timeframe'] == '15min' and su['active_preset'] == '3'

# کاربر قدیمی بدون پریست: بعد از تایم‌فریم «معمولی» می‌نشیند
su['active_preset'] = None
out.clear(); bot.process_command('/set_tf_5m', USER)
assert su['active_preset'] == '3' and su['timeframe'] == '5min'

# ریست کامل کاربر عادی دوباره معمولی می‌شود
su['paper_positions'] = []; ok, _ = bot.full_reset(USER); assert ok and bot.get_session(USER)['active_preset'] == '3'
print('WIZARD MODE REMOVED OK')
