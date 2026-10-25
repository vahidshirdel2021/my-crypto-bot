"""V3.44.75: کلید «حالت دستیار» در منوی اصلی برای همه‌ی کاربران (کاربر عادی هم). اجرا: python3 assist_main_menu_selftest.py"""
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
sent = []
def fake_send(chat_id, text, markup=None, message_id=None, parse_mode='Markdown', keep=False):
    sent.append((chat_id, text, markup, message_id)); return True
bot.send_message = fake_send
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, parse_mode='Markdown': sent.append((chat_id, text, markup, message_id)) or True
bot.sync_bottom_keyboard = lambda *a, **k: None
USER, ADMIN = 222, 111

def cbtn(markup):
    return {b['callback_data']: b['text'] for r in markup['inline_keyboard'] for b in r}

for cid in (USER, ADMIN):
    bot.get_session(cid)['assist_mode_enabled'] = False
    sent.clear(); bot.process_command('/menu', cid)
    b = cbtn(sent[0][2]); assert '/assist_main_toggle' in b and b['/assist_main_toggle'].startswith('🔴'), (cid, b)
    # روشن کردن: منوی اصلی در جا (با همان message_id) بازسازی می‌شود و وضعیت عوض می‌شود
    sent.clear(); bot.process_command('/assist_main_toggle', cid, 777)
    assert 'در دسترس نیست' not in sent[0][1], sent
    assert bot.get_session(cid)['assist_mode_enabled'] is True
    assert len(sent) == 1 and sent[0][3] == 777 and cbtn(sent[0][2])['/assist_main_toggle'].startswith('🟢'), sent
    # خاموش کردن
    sent.clear(); bot.process_command('/assist_main_toggle', cid, 777)
    assert bot.get_session(cid)['assist_mode_enabled'] is False and cbtn(sent[0][2])['/assist_main_toggle'].startswith('🔴')
# متن پنل کاربر عادی وضعیت دستیار را نشان می‌دهد
bot.get_session(USER)['assist_mode_enabled'] = True
sent.clear(); bot.process_command('/menu', USER)
assert 'حالت دستیار' in sent[0][1] and 'ورود فقط با تایید شما' in sent[0][1], sent[0][1]
# کیبوردِ فیلترشده‌ی کاربر عادی هنوز دکمه را دارد
import access_policy as ap
assert '/assist_main_toggle' in cbtn(ap.filter_markup(sent[0][2])) and ap.user_command_allowed('/assist_main_toggle')
# دکمه‌های تایید ورود (✅/❌) برای کاربر عادی مجازند
for c in ('/assist_ok_a1', '/assist_no_a1', '/assist_open_a1', '/assist_pending'):
    assert ap.user_command_allowed(c), c
# مسیر قدیمی ادمین دست‌نخورده
assert 'toggle_assist_mode' in open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
print('ASSIST MAIN MENU OK')
