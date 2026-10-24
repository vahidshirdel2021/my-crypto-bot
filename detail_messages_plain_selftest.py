"""V3.44.62: هشدارهای فنی (محافظ BTC، دلیل عدم ورود) برای کاربر عادی پنهان/ساده‌اند؛ ادمین متن کامل می‌گیرد.
اجرا: python3 detail_messages_plain_selftest.py"""
import sys, types, os, tempfile, re
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ['TELEGRAM_TOKEN'] = '123:abc'; os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3'); os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
here = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, here)
import importlib
bot = importlib.import_module('bot'); bot.init_db()
sent = []
bot.send_message = lambda chat_id, text, *a, **k: sent.append((chat_id, text)) or True
USER, ADMIN = 222, 111

# 1) رفتار کمکی
sent.clear(); bot.send_detail_message(USER, '🛡 محافظ BTC ...'); assert sent == [], 'user must get nothing'
sent.clear(); bot.send_detail_message(ADMIN, '🛡 محافظ BTC ...'); assert sent == [(ADMIN, '🛡 محافظ BTC ...')]
sent.clear(); bot.send_detail_message(USER, 'full reason: X', simple_text='🛑 ورود انجام نشد.'); assert sent == [(USER, '🛑 ورود انجام نشد.')]
sent.clear(); bot.send_detail_message(ADMIN, 'full reason: X', simple_text='🛑 ورود انجام نشد.'); assert sent == [(ADMIN, 'full reason: X')]

# 2) پیام‌های مربوطه هنوز با send_message خام فرستاده نمی‌شوند (محافظ در برابر بازگشت)
src = open(os.path.join(here, 'bot.py'), encoding='utf-8').read()
for marker in ('🛡 *محافظ BTC', '🛑 ورود انجام نشد.\\nدلیل', 'به ورود رسید ولی ورود انجام نشد', 'رسید ولی باز نشد', 'به قیمت رسید ولی وارد نشد',
               'ستاپ دیگر معتبر نیست', '❌ ورود `{symbol}` باز نشد: {detail}', 'ورود سریع `{symbol}` باز نشد: {err}'):
    hits = [m.start() for m in re.finditer(re.escape(marker), src)]
    assert hits, ('marker missing', marker)
    for h in hits:
        line = src[src.rfind('\n', 0, h) + 1: src.find('\n', h)]
        assert 'send_detail_message' in line, ('raw send_message still used', marker, line[:100])
print('DETAIL MESSAGES PLAIN OK')
