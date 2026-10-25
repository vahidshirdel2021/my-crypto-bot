# -*- coding: utf-8 -*-
"""V3.44.77: تست پست‌کردن پیام تایپ‌شده‌ی ادمین در کانال (بدون تلگرام). اجرا: python3 admin_channel_post_selftest.py"""
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
os.environ['TELEGRAM_TOKEN'] = '123:abc'
os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['SIGNAL_CHANNEL_ID'] = '-1001234567890'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3')
os.environ['SIGNAL_CHANNEL_SETTINGS_FILE'] = os.path.join(tempfile.mkdtemp(), 'sc.json')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot')
bot.init_db()

sent, tg_calls = [], []
def fake_send(chat_id, text, markup=None, *a, **k):
    sent.append((chat_id, text, markup)); return True
bot.send_message = fake_send
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: sent.append((chat_id, text, markup)) or True
def fake_tg(method, payload=None, timeout=10):
    tg_calls.append((method, dict(payload or {})))
    if method == 'sendMessage':
        return {'ok': True, 'result': {'message_id': 777}}
    return {'ok': True}
bot.tg = fake_tg
bot.analyze = lambda chat, sym: ('ANALYSIS ' + sym, None)

ADMIN, USER = 111, 222
ok = True
def check(name, cond):
    global ok
    ok &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name)
def reset(): sent.clear(); tg_calls.clear()

# 1) ادمین متن آزاد می‌فرستد => عیناً (بدون parse_mode و بدون حذف خودکار) به کانال می‌رود
reset(); txt = 'سلام دوستان\nامروز بازار *_[خطرناک]_* است'
bot.handle_text(ADMIN, txt)
posts = [c for c in tg_calls if c[0] == 'sendMessage']
check('admin text posted once to channel', len(posts) == 1 and posts[0][1]['chat_id'] == '-1001234567890')
check('text unchanged, no parse_mode', posts and posts[0][1]['text'] == txt and 'parse_mode' not in posts[0][1])
check('no auto-delete timer scheduled', 777 not in bot._CHANNEL_MSG_TIMERS)
check('admin got confirmation + delete button', sent and '✅' in sent[-1][1] and 'admin_chpost_del_777' in str(sent[-1][2]))

# 2) دکمه‌ی حذف از کانال
reset(); bot.process_command('/admin_chpost_del_777', ADMIN)
check('delete button calls deleteMessage on channel', tg_calls and tg_calls[0][0] == 'deleteMessage' and tg_calls[0][1] == {'chat_id': '-1001234567890', 'message_id': 777})
reset(); bot.process_command('/admin_chpost_del_777', USER)
check('non-admin cannot delete', not tg_calls)

# 3) کاربر عادی هرگز پست نمی‌کند
reset(); bot.handle_text(USER, 'سلام من کاربر هستم')
check('regular user never posts', not [c for c in tg_calls if c[0] == 'sendMessage' and c[1]['chat_id'] == '-1001234567890'])

# 4) نماد تنها همچنان تحلیل می‌شود، دستور و ورودیِ در انتظار پست نمی‌شوند
reset(); bot.handle_text(ADMIN, 'BTC')
check('bare symbol still analysed', not tg_calls and any('ANALYSIS BTC' in str(x[1]) for x in sent))
reset(); bot.handle_text(ADMIN, '/menu')
check('commands not posted', not [c for c in tg_calls if c[0] == 'sendMessage' and c[1]['chat_id'] == '-1001234567890'])
s = bot.get_session(ADMIN); s['user_state'] = 'WAIT_PENDING_TRIGGER'; bot.save_session(ADMIN)
reset(); bot.handle_text(ADMIN, '123.5')
s['user_state'] = None; bot.save_session(ADMIN)
check('input awaited by another flow not posted', not [c for c in tg_calls if c[0] == 'sendMessage' and c[1]['chat_id'] == '-1001234567890'])
reset(); bot.handle_text(ADMIN, '📊 وضعیت بازار')
check('fixed menu buttons not posted', not [c for c in tg_calls if c[0] == 'sendMessage' and c[1]['chat_id'] == '-1001234567890'])

# 5) کلید خاموش => پست نمی‌شود؛ و از منوی تنظیمات کانال قابل عوض‌شدن است و ذخیره می‌شود
reset(); bot.process_command('/toggle_signal_adminpost', ADMIN)
check('toggle turns it off + persisted', bot._SIGNAL_CHANNEL_FLAGS['admin_post'] is False and bot._load_signal_channel_flag('admin_post', True) is False)
reset(); bot.handle_text(ADMIN, 'یک پیام معمولی')
check('switch off => nothing posted', not [c for c in tg_calls if c[0] == 'sendMessage' and c[1]['chat_id'] == '-1001234567890'])
check('settings menu shows the switch', 'toggle_signal_adminpost' in str(bot.signal_channel_settings_keyboard()) and 'خاموش' in bot.signal_channel_settings_report())
bot.process_command('/toggle_signal_adminpost', ADMIN)
check('toggle back on', bot._SIGNAL_CHANNEL_FLAGS['admin_post'] is True)

# 6) متن خیلی طولانی و کانالِ تنظیم‌نشده
reset(); bot.handle_text(ADMIN, 'الف' * 5000)
check('too-long text refused, not posted', not [c for c in tg_calls if c[0] == 'sendMessage'] and any('خیلی طولانی' in str(x[1]) for x in sent))
bot.SIGNAL_CHANNEL_ID = ''
check('no channel configured => feature inactive', not bot.admin_channel_post_applies(ADMIN, 'سلام', None))

print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
