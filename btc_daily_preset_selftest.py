"""تست V3.44.184: کلید «رژیم روزانه BTC» جزو پریست است و با «ذخیره در پریست» ادمین به کاربران می‌رسد. اجرا: python3 btc_daily_preset_selftest.py"""
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
_tmp = tempfile.mkdtemp()
os.environ['TELEGRAM_TOKEN'] = '123:abc'
os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(_tmp, 'bot.sqlite3')
os.environ['PRESETS_CUSTOM_PATH'] = os.path.join(_tmp, 'presets_custom.json')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot')
bot.init_db()
P = bot.presets_mod
KEY = 'gate_btc_daily_regime_enabled'
bot.send_message = lambda *a, **k: True
bot.edit_page = lambda *a, **k: True
ADMIN, U1, U2 = 111, 222, 333
ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

check('کلید جزو کلیدهای مدیریت‌شده‌ی پریست است', KEY in P.managed_keys() and KEY in P.BASE_CFG)
check('پیش‌فرض کد پریست: روشن', P.BASE_CFG[KEY] is True)
# کاربران قدیمی که کلیدشان خاموش ذخیره شده
for cid in (U1, U2):
    s = bot.get_session(cid); P.apply_preset(s, '3'); s['strategy_config'][KEY] = False
a = bot.get_session(ADMIN); P.apply_preset(a, '3'); a['strategy_config'][KEY] = True
check('شروع: کاربر خاموش، ادمین روشن', not bot.btc_daily_enabled(bot.get_session(U1)) and bot.btc_daily_enabled(a))
# ۱) دکمه‌ی «بروزرسانی تنظیمات» کاربر (بدون ذخیره‌ی ادمین) → پیش‌فرض پریست = روشن
bot.process_command('/refresh_settings', U2, 1)
check('بروزرسانی تنظیمات کاربر: روشن شد', bot.btc_daily_enabled(bot.get_session(U2)))
# ۲) ادمین «ذخیره‌ی تنظیمات فعلی در پریست» می‌زند → کاربران همگام می‌شوند
bot.process_command('/preset_save_3', ADMIN, 1)
check('کلید در نسخه‌ی ذخیره‌شده‌ی ادمین هست و روشن است', P._load_custom()['3']['cfg'].get(KEY) is True)
check('بعد از ذخیره‌ی ادمین: کاربر ۱ هم روشن شد', bot.btc_daily_enabled(bot.get_session(U1)))
# ۳) گزارش پریست/اکانت کاربر آن را فعال نشان می‌دهد
txt_show = bot.preset_active_text('3', bot.get_session(U1))
txt_pf = bot.preset_active_text('3', bot.get_session(U1), actual=True)
check('گزارش «نمایش فعال‌ها»: رژیم روزانه BTC دیده می‌شود', 'رژیم روزانه BTC' in txt_show)
check('گزارش /pf اکانت کاربر: رژیم روزانه BTC دیده می‌شود', 'رژیم روزانه BTC' in txt_pf)
# ۴) ادمین خاموش می‌کند و ذخیره می‌کند → کاربران هم خاموش
a['strategy_config'][KEY] = False
bot.process_command('/preset_save_3', ADMIN, 1)
check('خاموش‌کردن ادمین + ذخیره: به کاربر می‌رسد', not bot.btc_daily_enabled(bot.get_session(U1)))
check('خاموش: در گزارش اکانت کاربر نیست', 'رژیم روزانه BTC' not in bot.preset_active_text('3', bot.get_session(U1), actual=True))
# ۵) بعد از «پیش‌فرض» دوباره روشن می‌شود
bot.process_command('/preset_reset_3', ADMIN, 1)
check('بازگشت به پیش‌فرض کد: کاربر روشن', bot.btc_daily_enabled(bot.get_session(U1)))
# ۶) کاربر عادی دکمه‌ی خاموش‌کردن ندارد
check('کاربر عادی: دکمه‌ی toggle ندارد', '/btc_daily_toggle' not in str(bot._btc_daily_markup(U1, True)))
print('\nALL PASS' if ok else '\nSOME FAILED')
sys.exit(0 if ok else 1)
