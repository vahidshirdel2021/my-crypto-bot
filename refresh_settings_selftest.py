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
import tempfile
bot.presets_mod.set_custom_path(os.path.join(tempfile.mkdtemp(), 'presets_custom.json'))
ADMIN, USER = 987101, 987102
sa = bot.get_session(ADMIN); su = bot.get_session(USER)
for k in ('ref_level_warn_enabled',): sa[k] = True
sa['ref_level_warn_btc'] = False; sa['ref_level_warn_eth'] = False; sa['ref_level_warn_sol'] = True
assert bot.presets_mod.save_custom(sa, '3')
# کاربر قبل از بروزرسانی: همه روشن (پیش‌فرض)
su['ref_level_warn_btc'] = su['ref_level_warn_eth'] = su['ref_level_warn_sol'] = True
su['timeframe'] = '5min'; su['active_preset'] = '3'
out.clear()
bot.process_command('/refresh_settings', USER, 1)
assert out and 'بروزرسانی شد' in out[-1][0] and 'پریست' not in out[-1][0], out
assert (su['ref_level_warn_btc'], su['ref_level_warn_eth'], su['ref_level_warn_sol']) == (False, False, True), su
assert su['ref_level_warn_enabled'] is True and su['timeframe'] == '5min'      # تایم‌فریم کاربر دست‌نخورده
rep = bot.preset_active_text('3', su, actual=True)
assert 'BTC: 🔴 خاموش' in rep and 'ETH: 🔴 خاموش' in rep and 'SOL: 🟢 روشن' in rep, rep
# نمای خودِ پریست (بدون سشن) هم از نسخه‌ی ذخیره‌شده خوانده می‌شود
rep2 = bot.preset_active_text('3')
assert 'SOL: 🟢 روشن' in rep2 and 'BTC: 🔴 خاموش' in rep2, rep2
# دکمه در منوی کاربر هست
import ui, access_policy
assert any(b['callback_data'] == '/refresh_settings' for r in access_policy.filter_markup(ui.get_settings_menu_keyboard())['inline_keyboard'] for b in r)
print('REFRESH SETTINGS OK')
