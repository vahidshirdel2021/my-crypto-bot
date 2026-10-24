"""V3.44.62: ویزارد تنظیمات معامله بعد از «حداکثر پوزیشن»، «حداکثر پوزیشن هم‌جهت» را هم می‌پرسد.
اجرا: python3 wizard_same_dir_selftest.py"""
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
bot.send_message = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, **k: out.append((text, markup)) or True
USER, ADMIN = 222, 111

def cbs(markup):
    return [b.get('callback_data') for row in (markup or {}).get('inline_keyboard', []) for b in row]

for cid in (USER, ADMIN):
    s = bot.get_session(cid); s['max_same_direction_positions'] = 2
    # مرحله‌ی قبل: حداکثر پوزیشن → حالا باید سؤال هم‌جهت بیاید (نه تایم‌فریم)
    out.clear(); bot.process_command('/set_max_5', cid)
    assert out, 'no page'
    text, mk = out[-1]
    assert s['max_open_positions'] == 5
    assert 'هم‌جهت' in text, text
    assert any(c and c.startswith('/set_wsame_') for c in cbs(mk)) and not any(c and c.startswith('/set_tf_') for c in cbs(mk)), cbs(mk)
    assert '/set_wsame_0' in cbs(mk) and '/set_wsame_3' in cbs(mk)
    # گزینه‌ی فعلی تیک دارد
    assert any('✅' in b['text'] for row in mk['inline_keyboard'] for b in row if b['callback_data'] == '/set_wsame_2')
    # انتخاب → ذخیره + ادامه‌ی ویزارد با تایم‌فریم
    out.clear(); bot.process_command('/set_wsame_3', cid)
    assert s['max_same_direction_positions'] == 3, s['max_same_direction_positions']
    text, mk = out[-1]
    assert 'تایم‌فریم' in text and any(c and c.startswith('/set_tf_') for c in cbs(mk)), (text, cbs(mk))
    out.clear(); bot.process_command('/set_wsame_0', cid)
    assert s['max_same_direction_positions'] == 0
print('user+admin wizard flow OK')

# کاربر عادی: دستور ویزارد مجاز، منوی جداگانه‌ی هم‌جهت هنوز بسته
import access_policy as ap
assert ap.user_command_allowed('/set_wsame_3') and ap.user_command_allowed('/set_wsame_0')
assert not ap.user_command_allowed('/set_max_same_3') and not ap.user_command_allowed('/same_dir_menu')
# منوی ادمین (محدودیت‌ها) همچنان کار می‌کند
out.clear(); bot.process_command('/set_max_same_5', ADMIN)
assert bot.get_session(ADMIN)['max_same_direction_positions'] == 5
print('WIZARD SAME DIR OK')
