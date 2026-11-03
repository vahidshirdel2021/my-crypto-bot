"""تست آفلاین کلید «رژیم روزانه BTC» (V3.44.130). اجرا: python3 btc_daily_selftest.py"""
import sys, types, os, tempfile, time
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
import numpy as np
import pandas as pd
bot = importlib.import_module('bot')
import access_policy as ap
import presets
bot.init_db()
KEY = 'gate_btc_daily_regime_enabled'
ADMIN, USER = 111, 222
ok_all = True


def check(name, cond, info=''):
    global ok_all
    ok_all &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name, info)


def mk(kind, n=200):
    today = int(time.time() // 86400 * 86400)
    ts = [(today - (n - 1 - i) * 86400) * 1000 for i in range(n)]
    rng = np.random.RandomState(7)
    i = np.arange(n)
    if kind == 'down':
        c = 400 - 1.5 * i + rng.randn(n) * 0.8
    elif kind == 'up':
        c = 100 + 1.5 * i + rng.randn(n) * 0.8
    else:
        c = 100 + rng.randn(n) * 1.0
    o = np.concatenate([[c[0]], c[:-1]])
    h = np.maximum(o, c) + 0.5
    l = np.minimum(o, c) - 0.5
    return pd.DataFrame({'timestamp': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': np.full(n, 1000.0)})


MODE = {'btc': 'down', 'eth': 'up', 'none': False}


def fake_klines(symbol, tf='5min', limit=200):
    if MODE['none']:
        return pd.DataFrame()
    return mk(MODE['eth'] if str(symbol).upper() == 'ETH' else MODE['btc'])


bot.get_klines = fake_klines

tgcalls, sent = [], []
state = {'mid': 5000}


def fake_tg(method, payload=None, timeout=10):
    tgcalls.append((method, payload))
    return {'ok': True, 'result': {'message_id': 1}}


def fake_send(chat_id, text, markup=None, message_id=None, parse_mode='Markdown', keep=False):
    state['mid'] += 1
    sent.append((chat_id, text, markup, keep))
    bot._LAST_SENT.mid = state['mid']
    return True


bot.tg = fake_tg
bot.send_message = fake_send


def reset_cache():
    bot._BTC_DAILY_CACHE.clear()


# ---- ۱) رجیستری / پریست / پیش‌فرض ----
row = bot.GATE_REGISTRY[KEY]
check('رجیستری: پیش‌فرض روشن، بخش btceth', row[1] is True and row[2] == 'btceth')
check('کلید جزو پریست‌ها نیست (مستقل)', KEY not in presets.managed_keys())
a = bot.get_session(ADMIN); u = bot.get_session(USER)
a['timeframe'] = u['timeframe'] = '15min'
check('پیش‌فرض سشن تازه: روشن', bot.btc_daily_enabled(a) and bot.btc_daily_enabled(u))
_n = bot.normalize_session({'strategy_config': {KEY: False}})
check('انتخاب خاموش کاربر بعد از نرمال‌سازی حفظ می‌شود', bot.gate_on(_n, KEY) is False)

# ---- ۲) رژیم نزولی ----
reset_cache(); MODE.update(btc='down', eth='up', none=False)
info = bot.daily_regime_info('BTC')
check('رژیم روزانه‌ی BTC نزولی تشخیص داده شد', info and info['regime'] == 'BEARISH', info)
check('روز اطلاعات = امروز UTC', info and info['day'] == time.strftime('%Y-%m-%d', time.gmtime()))
ok_b, txt_b, _ = bot.btc_daily_verdict('BUY')
ok_s, txt_s, _ = bot.btc_daily_verdict('SELL')
check('نزولی: خرید رد، فروش آزاد', (not ok_b) and ok_s and 'رژیم روزانه BTC' in txt_b, txt_b[:80])
check('گیت چت: خرید رد / فروش آزاد', bot._btc_daily_gate(ADMIN, a, 'AAA', 'BUY')[0] is False and bot._btc_daily_gate(ADMIN, a, 'AAA', 'SELL')[0] is True)
check('متن کاربر عادی ثبت شده (ساده)', bot.block_simple_text(txt_b) and 'نزولی' in bot.block_simple_text(txt_b))
check('کلاس قیف = btc_daily_regime', bot._fn_gate_class('⛔ ' + txt_b) == 'btc_daily_regime')
# precheck از مسیرهای ورود (حتی force)
check('precheck خرید با force هم رد می‌شود', bot._btc_daily_precheck(ADMIN, 'AAA', 'BUY (Long)', 1.0, 0.9, 1.1, True, False) is False)
check('precheck فروش آزاد است', bot._btc_daily_precheck(ADMIN, 'AAA', 'SELL (Short)', 1.0, 1.1, 0.9, False, True) is True)
# معاملات معکوس: جهت نهایی سنجیده می‌شود
a['strategy_config']['gate_inverse_trading_enabled'] = True
check('معکوس روشن: سیگنال SELL = خرید نهایی → رد', bot._btc_daily_gate(ADMIN, a, 'AAA', 'SELL')[0] is False)
check('معکوس روشن: سیگنال BUY = فروش نهایی → آزاد', bot._btc_daily_gate(ADMIN, a, 'AAA', 'BUY')[0] is True)
check('معکوس روشن ولی allow_inverse=False: جهت خام', bot._btc_daily_gate(ADMIN, a, 'AAA', 'BUY', False)[0] is False)
a['strategy_config']['gate_inverse_trading_enabled'] = False
# خاموش
a['strategy_config'][KEY] = False
check('کلید خاموش: گیت و precheck رد نمی‌کنند', bot._btc_daily_gate(ADMIN, a, 'AAA', 'BUY') == (True, '') and bot._btc_daily_precheck(ADMIN, 'AAA', 'BUY (Long)', 1, .9, 1.1, False, True) is True)
a['strategy_config'][KEY] = True

# ---- ۳) صعودی ----
reset_cache(); MODE.update(btc='up', eth='down')
info = bot.daily_regime_info('BTC')
check('رژیم صعودی تشخیص داده شد', info and info['regime'] == 'BULLISH', info)
check('صعودی: فروش رد، خرید آزاد', bot.btc_daily_verdict('SELL')[0] is False and bot.btc_daily_verdict('BUY')[0] is True)

# ---- ۴) رنج ----
reset_cache(); MODE.update(btc='range', eth='range')
info = bot.daily_regime_info('BTC')
check('رنج تشخیص داده شد', info and info['regime'] == 'RANGE', info)
check('رنج: هم خرید هم فروش آزاد', bot.btc_daily_verdict('BUY')[0] and bot.btc_daily_verdict('SELL')[0])

# ---- ۵) نبود داده = آزاد ----
reset_cache(); MODE['none'] = True
check('نبود داده: daily_regime_info = None', bot.daily_regime_info('BTC') is None)
check('نبود داده: خرید و فروش آزاد (fail-open)', bot.btc_daily_verdict('BUY')[0] and bot.btc_daily_verdict('SELL')[0])
MODE['none'] = False

# ---- ۶) خطای لحظه‌ای: آخرین مقدار سالم نگه داشته می‌شود ----
reset_cache(); MODE.update(btc='down')
bot.daily_regime_info('BTC')
bot._BTC_DAILY_CACHE[(bot._venue(), 'BTC')]['ts'] -= 1000      # کش منقضی
MODE['none'] = True
info = bot.daily_regime_info('BTC')
check('خطای شبکه: مقدار قبلی (نزولی) می‌ماند', info and info['regime'] == 'BEARISH', info)
MODE['none'] = False

# ---- ۷) پیام اول روز ----
reset_cache(); MODE.update(btc='down', eth='up')
for sid in (ADMIN, USER):
    s = bot.get_session(sid); s.pop('btc_daily_sent', None); s.pop('btc_daily_try', None); s.pop('btc_daily_mid', None)
sent.clear(); tgcalls.clear()
bot.btc_daily_announce_once()
mine = {c: (t, m, k) for c, t, m, k in sent}
check('پیام برای هر دو چت فرستاده شد', ADMIN in mine and USER in mine, list(mine))
txt_a, mk_a, keep_a = mine[ADMIN]
check('متن: نزولیه + فقط فروش', 'نزولیه' in txt_a and 'فروش' in txt_a and 'خرید' in txt_a, txt_a[:120])
check('پیام ماندگار (keep=True)', keep_a is True)
btns_admin = [b['callback_data'] for r in mk_a['inline_keyboard'] for b in r if 'callback_data' in b]
btns_user = [b['callback_data'] for r in mine[USER][1]['inline_keyboard'] for b in r if 'callback_data' in b]
check('ادمین: دکمه‌ی کلید دارد', '/btc_daily_toggle' in btns_admin, btns_admin)
check('کاربر عادی: دکمه‌ی کلید ندارد', '/btc_daily_toggle' not in btns_user, btns_user)
check('کاربر عادی: جزئیات فنی (ADX) ندارد', 'ADX' not in mine[USER][0] and 'ADX' in txt_a)
n1 = len(sent)
bot.btc_daily_announce_once()
check('بار دوم همان روز: پیام تکراری نمی‌رود', len(sent) == n1)
# روز بعد: رژیم/روز عوض شود → پیام جدید و حذف پیام قبلی
old_mid = bot.get_session(ADMIN)['btc_daily_mid']
bot.get_session(ADMIN)['btc_daily_sent'] = '2000-01-01|BULLISH'; bot.get_session(ADMIN)['btc_daily_try'] = 0
tgcalls.clear()
bot.btc_daily_announce_once()
dels = [p for m, p in tgcalls if m == 'deleteMessage' and p.get('message_id') == old_mid]
check('روز جدید: پیام تازه + حذف پیام روز قبل', len(sent) == n1 + 1 and len(dels) == 1)
check('اشاره‌گر پیام جدید ثبت شد', bot.get_session(ADMIN)['btc_daily_mid'] != old_mid)
check('پیام ماندگار از پاکسازی محافظت می‌شود', bot._message_protected(ADMIN, bot.get_session(ADMIN)['btc_daily_mid']) is True)
# کلید خاموش: پیام نمی‌رود
u['strategy_config'][KEY] = False; u.pop('btc_daily_sent', None); u.pop('btc_daily_try', None)
n2 = len(sent)
bot.btc_daily_announce_once()
check('کلید خاموش: پیام نمی‌رود', all(c != USER for c, *_ in sent[n2:]))
u['strategy_config'][KEY] = True
# صعودی / رنج متن
reset_cache(); MODE.update(btc='up')
check('متن صعودی', 'صعودیه' in bot._btc_daily_text(ADMIN, bot.daily_regime_info('BTC')) and 'فروش امروز متوقف' in bot._btc_daily_text(ADMIN, bot.daily_regime_info('BTC')))
reset_cache(); MODE.update(btc='range')
check('متن رنج', 'رنجه' in bot._btc_daily_text(ADMIN, bot.daily_regime_info('BTC')))

# ---- ۸) کلید روشن/خاموش (ادمین) ----
check('toggle: خاموش می‌شود', bot.btc_daily_toggle(ADMIN) is False and bot.gate_on(a, KEY) is False)
check('toggle: دوباره روشن + اعلام امروز دوباره', bot.btc_daily_toggle(ADMIN) is True and 'btc_daily_sent' not in a)
check('کاربر عادی به /btc_daily_toggle دسترسی ندارد', ap.user_command_allowed('/btc_daily_toggle') is False)

# ---- ۹) نمایش رژیم BTC/ETH با رژیم روزانه ----
reset_cache(); MODE.update(btc='down', eth='up')
full = bot.btc_eth_regime_text('15min')
check('نمایش کامل: رژیم روزانه‌ی BTC و ETH آمده', 'رژیم روزانه' in full and 'BTC' in full and 'ETH' in full and '🔴 نزولی' in full and '🟢 صعودی' in full, full)
pop = bot.btc_eth_regime_text('15min', popup=True)
check('پاپ‌آپ کانال: خط روزانه دارد', 'روزانه' in pop and len(pop) < 200, pop)
plain = bot.btc_eth_regime_text('15min', plain=True)
check('کاربر عادی: روزانه بدون ADX', 'رژیم روزانه' in plain)
daily_part = plain.split('رژیم روزانه', 1)[1]
check('کاربر عادی: بخش روزانه ADX ندارد', 'ADX' not in daily_part.split('ℹ️')[0], daily_part[:120])

# ---- ۱۰) رژیم دقیق مستقل از کلید سراسری ----
bot.set_regime_advanced(False)
reset_cache(); MODE.update(btc='range')
check('کلید سراسری رژیم دقیق خاموش: رژیم روزانه هنوز دقیق (رنج می‌ماند)', bot.daily_regime_info('BTC')['regime'] == 'RANGE')

print('\nALL PASS' if ok_all else '\nSOME FAILED')
sys.exit(0 if ok_all else 1)
