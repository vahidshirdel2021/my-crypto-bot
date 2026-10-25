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
for marker in ('· سیگنال {side_fa}', '🛡 *محافظ BTC', '🛑 ورود انجام نشد.\\nدلیل', 'به ورود رسید ولی ورود انجام نشد', 'رسید ولی باز نشد', 'به قیمت رسید ولی وارد نشد',
               'ستاپ دیگر معتبر نیست', '❌ ورود `{symbol}` باز نشد: {detail}', 'ورود سریع `{symbol}` باز نشد: {err}'):
    hits = [m.start() for m in re.finditer(re.escape(marker), src)]
    assert hits, ('marker missing', marker)
    for h in hits:
        line = src[src.rfind('\n', 0, h) + 1: src.find('\n', h)]
        assert 'send_detail_message' in line, ('raw send_message still used', marker, line[:100])
# 3) هشدار «⚠️ هشدار ورود ...»: کاربر عادی متن ساده می‌گیرد، ادمین متن کامل
warn_txt = '⚠️ هشدار ورود: کلوز آخرین کندل بسته‌شده‌ی BTC (15م) زیر سطح است؛ لطفاً صبور باشید'
# V3.44.73: کاربر عادی حالا یک جمله‌ی ساده (بدون اصطلاح تخصصی) می‌گیرد؛ ادمین متن کامل + نام دقیق کلید مانع.
sent.clear(); bot._btc_front_warn(USER, 'CRV', 'BUY', '15min', warn_txt, {'front_price': 81200.7, 'warn_price': 81200.7, 'block': 'near'})
assert len(sent) == 1 and sent[0][0] == USER and 'صبور باشید' in sent[0][1] and 'ATR' not in sent[0][1] and 'کلوز' not in sent[0][1] and 'سطح مقاومتی' not in sent[0][1] and 'CRV' in sent[0][1] and 'هشدار ورود' not in sent[0][1], sent
for code, bad in (('chop', ('رد و برگشت', 'ATR', 'کندل', 'کلوز')), ('side', ('کلوز', 'ATR', 'کندل')), ('nodata', ('ATR', 'کلوز'))):
    bot._BTC_FRONT_WARNED.clear(); sent.clear()
    bot._btc_front_warn(USER, 'CRV', 'SELL', '15min', warn_txt, {'warn_price': 1.0, 'block': code} if code != 'nodata' else None)
    assert len(sent) == 1 and 'صبور باشید' in sent[0][1] and not any(b in sent[0][1] for b in bad), (code, sent)
bot._BTC_FRONT_WARNED.clear()
sent.clear(); bot._btc_front_warn(ADMIN, 'CRV', 'BUY', '15min', warn_txt, {'front_price': 81200.7, 'warn_price': 81200.7})
assert len(sent) == 1 and sent[0][0] == ADMIN and 'صبور باشید' in sent[0][1] and 'CRV' in sent[0][1], sent

# 4) V3.44.74: دلیل‌های رد ورود: ادمین نام دقیق دکمه‌ی مانع را می‌بیند؛ کاربر عادی فقط متن ساده (بدون «کلید/فیلتر»)
bot._reject_record = lambda *a, **k: None
cases = [('فیلتر ممنوعیت فروش فعال است', 'block_sell', 'ممنوع کردن فروش', 'ورود به معامله‌ی فروش در حال حاضر مجاز نیست.'),
         ('کول‌داون نماد X', 'gate_cooldown_enabled', 'استراحت بعد از هر معامله', 'روی این ارز تازه معامله بسته شده؛ کمی صبر می‌کنیم تا دوباره وارد شویم.')]
for reason, key, label, simple in cases:
    bot._blk(ADMIN, reason, key=key, simple=simple)
    r = bot._LAST_BLOCK_REASON.pop(ADMIN)
    assert f'«{label}»' in r and 'کلید مانع' in r, r
    assert bot.block_simple_text(r) == simple
    sent.clear(); bot.send_detail_message(USER, f'🛑 ورود انجام نشد.\nدلیل: {r}', simple_text='🛑 ورود انجام نشد.' + f'\n{bot.block_simple_text(r)}')
    assert len(sent) == 1 and simple in sent[0][1] and 'کلید' not in sent[0][1] and 'فیلتر' not in sent[0][1] and label not in sent[0][1], sent
    sent.clear(); bot.send_detail_message(ADMIN, f'🛑 ورود انجام نشد.\nدلیل: {r}', simple_text='x')
    assert f'«{label}»' in sent[0][1]
print('DETAIL MESSAGES PLAIN OK')
