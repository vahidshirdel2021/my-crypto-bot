"""V3.44.85: مرحله‌ی «حالت معامله» در ویزارد تنظیمات معامله؛ پیش‌فرض معمولی، کاربر می‌تواند عوض کند.
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
def cbs(mk): return [b['callback_data'] for r in mk['inline_keyboard'] for b in r]

# دسترسی کاربر عادی
for c in ('/wiz_tf', '/wiz_mode_done', '/set_wmode_3', '/set_wmode_4', '/set_wmode_5'):
    assert ap.user_command_allowed(c), c
assert not ap.user_command_allowed('/set_wmode_2') and not ap.user_command_allowed('/set_wmode_1')

# کاربر جدید: پیش‌فرض معمولی (کلید ۳)، ادمین دست‌نخورده
su = bot.get_session(USER); sa = bot.get_session(ADMIN)
assert su['active_preset'] == '3' and P.preset_diff(su) == [], su['active_preset']
assert sa['active_preset'] is None

# آخرین مرحله‌ی ویزارد (تایم‌فریم) صفحه‌ی حالت معامله را نشان می‌دهد و ✅ روی معمولی است
out.clear(); bot.process_command('/set_tf_15m', USER)
text, mk = out[-1]
assert 'حالت معامله' in text and any(b['text'].startswith('✅ ⚖️') for r in mk['inline_keyboard'] for b in r), text
assert {'/set_wmode_3', '/set_wmode_4', '/set_wmode_5', '/wiz_mode_done', '/wiz_tf', '/menu'} <= set(cbs(mk)), cbs(mk)
assert cbs(ap.filter_markup(mk)) == cbs(mk)

# کاربر قدیمی بدون حالت: با رسیدن به این مرحله معمولی می‌نشیند
su['active_preset'] = None
out.clear(); bot.process_command('/set_tf_5m', USER)
assert su['active_preset'] == '3' and su['timeframe'] == '5min'

# انتخاب حالت دیگر: همان صفحه ویرایش می‌شود و تنظیمات اعمال می‌شود؛ تایم‌فریم عوض نمی‌شود
for k, auto in (('4', 'minus1'), ('5', 'all'), ('3', 'majority')):
    out.clear(); bot.process_command(f'/set_wmode_{k}', USER)
    text, mk = out[-1]
    assert su['active_preset'] == k and su['touch_auto_mode'] == auto and su['timeframe'] == '5min'
    assert P.preset_diff(su) == []
    assert any(b['text'].startswith('✅') and b['callback_data'] == f'/set_wmode_{k}' for r in mk['inline_keyboard'] for b in r)
# تغییر تایم‌فریم بعد از انتخاب حالت، حالت را خراب نمی‌کند
bot.process_command('/set_wmode_5', USER); bot.process_command('/set_tf_15m', USER)
assert su['active_preset'] == '5' and P.preset_diff(su) == [], P.preset_diff(su)

# برگشت و پایان
out.clear(); bot.process_command('/wiz_tf', USER); assert '/set_tf_15m' in cbs(out[-1][1])
out.clear(); bot.process_command('/wiz_mode_done', USER); assert 'پنل اصلی' in out[-1][0], out[-1][0]
out.clear(); bot.process_command('/set_wmode_9', ADMIN); assert 'شناخته نشد' in out[-1][0]

# ریست کامل کاربر عادی دوباره معمولی می‌شود
su['paper_positions'] = []; ok, _ = bot.full_reset(USER); assert ok and bot.get_session(USER)['active_preset'] == '3'
print('WIZARD MODE OK')
