"""V3.44.169: منوی «🎯 حالت معامله» (معمولی/محافظه‌کار/سخت‌گیر) حذف شده؛ فقط یک حالت (معمولی) است.
اجرا: python3 trade_mode_menu_selftest.py"""
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
import access_policy as ap, presets as P, ui
out = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
USER, ADMIN = 222, 111

# دسترسی: هیچ دستور انتخاب حالت برای کاربر عادی باز نیست
for c in ('/trade_mode_menu', '/trade_mode_set_3', '/trade_mode_set_4', '/trade_mode_set_5', '/set_wmode_3', '/set_wmode_4', '/preset_menu', '/preset_apply_4'):
    assert not ap.user_command_allowed(c), c
# دکمه‌ای در منوی تنظیمات نیست
kb = ui.get_settings_menu_keyboard()
assert '/trade_mode_menu' not in [b['callback_data'] for r in kb['inline_keyboard'] for b in r]
assert 'محافظه‌کار' not in str(kb) and 'سخت‌گیر' not in str(kb)
# دستورهای حذف‌شده برای ادمین هم هندلر ندارند (پیام «شناخته نشد» نمی‌دهند و حالت عوض نمی‌شود)
sa = bot.get_session(ADMIN); before = sa.get('active_preset')
out.clear(); bot.process_command('/trade_mode_set_4', ADMIN)
assert sa.get('active_preset') == before
# کاربر جدید روی «معمولی» می‌نشیند
su = bot.get_session(USER)
assert su['active_preset'] == '3' and P.preset_diff(su) == []
assert su['touch_auto_mode'] == 'majority' and su['fav_confirm_min_r'] == 0.15
# منوی ادمین: فقط یک پریست
out.clear(); bot.process_command('/preset_menu', ADMIN)
text, mk = out[-1]
assert 'معمولی' in text and 'محافظه‌کار' not in text and 'سخت‌گیر' not in text, text
cbs = [b['callback_data'] for r in mk['inline_keyboard'] for b in r]
assert '/preset_apply_3' in cbs and not any(f'/preset_apply_{n}' in cbs for n in '1245')
# پنل اصلی خط «حالت معامله» ندارد
out.clear(); bot.menu(USER)
assert 'حالت معامله' not in out[-1][0], out[-1][0]
print('TRADE MODE MENU REMOVED OK')
