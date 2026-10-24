"""V3.44.62: منوی «🎯 حالت معامله» (معمولی/محافظه‌کار/سخت‌گیر = کلیدهای ۳ تا ۵) برای کاربر عادی و ادمین.
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
import access_policy as ap, presets as P
out = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
USER, ADMIN = 222, 111

# دسترسی
for c in ('/trade_mode_menu', '/trade_mode_set_3', '/trade_mode_set_4', '/trade_mode_set_5'):
    assert ap.user_command_allowed(c), c
assert not ap.user_command_allowed('/trade_mode_set_2') and not ap.user_command_allowed('/preset_menu') and not ap.user_command_allowed('/preset_apply_4')

# دکمه‌ی منو در تنظیمات برای کاربر عادی دیده می‌شود (بعد از فیلتر نقش)
import ui
kb = ap.filter_markup(ui.get_settings_menu_keyboard())
assert '/trade_mode_menu' in [b['callback_data'] for r in kb['inline_keyboard'] for b in r], kb

for cid in (USER, ADMIN):
    s = bot.get_session(cid)
    out.clear(); bot.process_command('/trade_mode_menu', cid)
    text, mk = out[-1]
    assert 'حالت معامله' in text and 'معمولی' in text and 'محافظه‌کار' in text and 'سخت‌گیر' in text, text
    for k, (n, auto, minr) in {'3': ('معمولی', 'majority', 0.15), '4': ('محافظه‌کار', 'minus1', 0.25), '5': ('سخت‌گیر', 'all', 0.35)}.items():
        out.clear(); bot.process_command(f'/trade_mode_set_{k}', cid)
        text, mk = out[-1]
        assert n in text and s['active_preset'] == k, (k, text)
        assert s['touch_auto_mode'] == auto and s['fav_confirm_min_r'] == minr, (k, s['touch_auto_mode'], s['fav_confirm_min_r'])
        assert P.preset_diff(s) == [], P.preset_diff(s)
        assert s['strategy_config']['gate_btceth_aligned_enabled'] is (k == '5')
        assert any(b['text'].startswith('✅') and b['callback_data'] == f'/trade_mode_set_{k}' for r in mk['inline_keyboard'] for b in r)
    out.clear(); bot.process_command('/trade_mode_set_9', cid)
    assert ('شناخته نشد' in out[-1][0]) if cid == ADMIN else ('در دسترس نیست' in out[-1][0]), out[-1][0]
# کاربر عادی فقط پیام ساده می‌بیند (بدون اصطلاح فنی)
out.clear(); bot.process_command('/trade_mode_set_4', USER)
assert 'RSI' not in out[-1][0] and 'کلید ' not in out[-1][0]
# ادمین هنوز منوی پریست کامل را دارد و کلید ۴ همان محافظه‌کار است
out.clear(); bot.process_command('/preset_menu', ADMIN)
assert 'محافظه‌کار' in out[-1][0]
print('TRADE MODE MENU OK')
