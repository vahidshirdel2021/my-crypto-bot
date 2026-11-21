"""تست V3.44.185: «خروج زودهنگام» (کلوز کندل ۵ دقیقه روی -X R + باطل‌شدن سطح ورود). اجرا: python3 early_exit_selftest.py"""
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
import pandas as pd
bot = importlib.import_module('bot')
bot.init_db()
P = bot.presets_mod
import access_policy as AP
sent = []
bot.send_message = lambda chat_id, text, markup=None, message_id=None, parse_mode='Markdown', keep=False: sent.append((chat_id, text, markup)) or True
bot.edit_page = lambda *a, **k: True
ADMIN, USER = 111, 222
ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

NOW = 1_800_000_000.0
OPEN = NOW - 1000            # ورود
def pos(side='BUY (Long)', entry=100.0, sl=90.0, **kw):
    p = {'symbol': 'AAA', 'side': side, 'entry_price': entry, 'sl': sl, 'tp': entry + (entry - sl) * 2 if 'BUY' in side else entry - (sl - entry) * 2,
         'risk_distance': abs(entry - sl), 'opened_at': OPEN, 'entry_reason': 'سطح HVL=100.0 ...'}
    p.update(kw); return p
def sess(**kw):
    s = {'early_cut_enabled': True, 'early_cut_r': 0.5, 'early_invalid_enabled': False, 'early_invalid_minutes': 30}
    s.update(kw); return s
T1 = OPEN + 300              # اولین کندل کامل بعد از ورود

# ---- کلید ۱: بستن روی -X R ----
d = bot.early_exit_decision(sess(), pos(), T1, 94.9)           # -0.51R
check('خرید: کلوز -0.51R → بستن', d and d[0] == 'cut' and abs(d[2] + 0.51) < 1e-6, d)
check('خرید: کلوز -0.40R → بدون بستن', bot.early_exit_decision(sess(), pos(), T1, 96.0) is None)
check('خرید: دقیقاً روی -0.50R → بستن', (bot.early_exit_decision(sess(), pos(), T1, 95.0) or ('',))[0] == 'cut')
d = bot.early_exit_decision(sess(), pos('SELL (Short)', 100, 110), T1, 105.5)
check('فروش: کلوز -0.55R → بستن', d and d[0] == 'cut', d)
check('فروش: کلوز سودده → بدون بستن', bot.early_exit_decision(sess(), pos('SELL (Short)', 100, 110), T1, 97.0) is None)
check('آستانه‌ی ۰.۷: -0.6R بسته نمی‌شود', bot.early_exit_decision(sess(early_cut_r=0.7), pos(), T1, 94.0) is None)
check('کلید خاموش: بدون بستن', bot.early_exit_decision(sess(early_cut_enabled=False), pos(), T1, 90.5) is None)
check('کندلی که پیش از ورود باز شده حساب نمی‌شود', bot.early_exit_decision(sess(), pos(), OPEN - 300, 94.0) is None)
check('استاپ سر به سر (SL=ورود): اعمال نمی‌شود', bot.early_exit_decision(sess(), pos(sl=100.0, risk_distance=10.0), T1, 94.0) is None)
check('استاپ در سود (خرید SL>ورود): اعمال نمی‌شود', bot.early_exit_decision(sess(), pos(sl=101.0, risk_distance=10.0), T1, 94.0) is None)
check('بدون risk_distance از SL محاسبه می‌شود', (bot.early_exit_decision(sess(), {k: v for k, v in pos().items() if k != 'risk_distance'}, T1, 94.0) or ('',))[0] == 'cut')

# ---- کلید ۲: باطل‌شدن سطح ورود ----
S2 = sess(early_cut_enabled=False, early_invalid_enabled=True)
d = bot.early_exit_decision(S2, pos(), T1, 98.0)               # سطح 100، بافر 0.1R=1 → کلوز < 99
check('خرید: کلوز زیر سطح (فراتر از بافر) → باطل', d and d[0] == 'invalid', d)
check('خرید: کلوز کمی زیر سطح (داخل بافر) → بدون بستن', bot.early_exit_decision(S2, pos(), T1, 99.5) is None)
check('خرید: کلوز بالای سطح → بدون بستن', bot.early_exit_decision(S2, pos(), T1, 101.0) is None)
d = bot.early_exit_decision(S2, pos('SELL (Short)', 100, 110), T1, 102.0)
check('فروش: کلوز بالای سطح → باطل', d and d[0] == 'invalid', d)
check('بعد از مهلت ۳۰ دقیقه: اعمال نمی‌شود', bot.early_exit_decision(S2, pos(), OPEN + 3600, 98.0) is None)
check('معامله‌ی معکوس: کلید ۲ اعمال نمی‌شود', bot.early_exit_decision(S2, pos(inverse_trade=True), T1, 98.0) is None)
check('بدون سطح در دلیل ورود: کلید ۲ اعمال نمی‌شود', bot.early_exit_decision(S2, pos(entry_reason='بدون سطح'), T1, 98.0) is None)
check('سطح از entry_snapshot خوانده می‌شود', (bot.early_exit_decision(S2, pos(entry_reason='', entry_snapshot={'level': {'level': 100.0}}), T1, 98.0) or ('',))[0] == 'invalid')
check('کلید ۲ خاموش: بدون بستن', bot.early_exit_decision(sess(early_cut_enabled=False), pos(), T1, 98.0) is None)
check('هر دو روشن و هر دو برقرار: cut اول', (bot.early_exit_decision(sess(early_invalid_enabled=True), pos(), T1, 94.0) or ('',))[0] == 'cut')
check('اعمال دو کلید روی ورودی ناقص بدون خطا', bot.early_exit_decision({}, {}, 0, 1) is None)

# ---- حلقه‌ی اسکن (کندل و قیمت و بستن شبیه‌سازی‌شده) ----
state = {'candle': None, 'price': 94.0}
closed = []
bot.get_klines = lambda sym, tf='5min', limit=200: (pd.DataFrame({'timestamp': [0, state['candle'][0] * 1000, 0], 'close': [0, state['candle'][1], 0]}) if state['candle'] else None)
bot.latest_price = lambda sym: state['price']
def fake_close(chat_id, p, price=None, reason='manual'):
    s = bot.get_session(chat_id)
    if p in s['paper_positions']:
        s['paper_positions'].remove(p); closed.append((p['symbol'], price, reason)); return True
    return False
bot.close_position = fake_close
_real_time = time.time
time.time = lambda: NOW            # now//300 → کندل بسته‌شده = NOW-300..NOW
exp = (int(NOW // 300) - 1) * 300
s = bot.get_session(USER); s['paper_positions'] = []; s['trading_mode'] = 'PAPER'
s['early_cut_enabled'] = True; s['early_cut_r'] = 0.5
p1 = pos(opened_at=exp - 400)      # قبل از کندل بسته‌شده وارد شده
s['paper_positions'].append(p1)
state['candle'] = (exp, 94.0)
bot.early_exit_scan_once()
check('اسکن: معامله بسته شد با دلیل خروج زودهنگام', len(closed) == 1 and 'خروج زودهنگام' in closed[0][2] and closed[0][1] == 94.0, closed)
# کندل قبل از ورود: بدون بستن
closed.clear(); p2 = pos(opened_at=exp + 10); s['paper_positions'].append(p2)
bot.early_exit_scan_once()
check('اسکن: کندل پیش از ورود → بدون بستن', not closed and p2 in s['paper_positions'])
# هر کندل یک‌بار سنجیده می‌شود
p3 = pos(opened_at=exp - 400); p3['early_chk_ts'] = exp; s['paper_positions'].append(p3)
bot.early_exit_scan_once()
check('اسکن: کندل سنجیده‌شده دوباره سنجیده نمی‌شود', not closed and p3 in s['paper_positions'])
# کلید خاموش
s['paper_positions'][:] = []; s['early_cut_enabled'] = False
p4 = pos(opened_at=exp - 400); s['paper_positions'].append(p4)
bot.early_exit_scan_once()
check('اسکن: کلید خاموش → بدون بستن', not closed)
# بسته نشدن → تلاش دوباره بعد از مهلت
s['early_cut_enabled'] = True; bot.close_position = lambda *a, **k: False
bot.early_exit_scan_once()
check('اسکن: بستن ناموفق → early_fail_ts ثبت می‌شود', p4.get('early_fail_ts') == NOW, p4.get('early_fail_ts'))
time.time = _real_time

# ---- پریست، دکمه‌ها، دسترسی ----
check('کلیدها جزو کلیدهای مدیریت‌شده‌ی پریست‌اند', all(k in P.managed_keys() for k in ('early_cut_enabled', 'early_cut_r', 'early_invalid_enabled', 'early_invalid_minutes')))
check('پیش‌فرض پریست: کلید ۱ روشن، کلید ۲ خاموش', P.BASE_SESSION['early_cut_enabled'] is True and P.BASE_SESSION['early_invalid_enabled'] is False and P.BASE_SESSION['early_cut_r'] == 0.5)
check('سشن تازه: پیش‌فرض‌ها', bot.default_session()['early_cut_enabled'] is True and bot.default_session()['early_invalid_enabled'] is False)
a = bot.get_session(ADMIN); P.apply_preset(a, '3'); u = bot.get_session(USER); P.apply_preset(u, '3')
kb_admin = str(bot.trade_filter_management_keyboard(ADMIN, 'exit'))
kb_user = str(bot.trade_filter_management_keyboard(USER, 'exit'))
check('ادمین: دکمه‌های خروج زودهنگام را دارد', all(c in kb_admin for c in ('/toggle_early_cut', '/toggle_early_invalid', '/early_cut_r_next', '/early_invalid_min_next')))
check('کاربر عادی: دکمه‌ها را ندارد', not any(c in kb_user for c in ('/toggle_early_cut', '/toggle_early_invalid', '/early_cut_r_next', '/early_invalid_min_next')))
check('کاربر عادی: دستورها مجاز نیست', not any(AP.user_command_allowed(c, paper=True) for c in ('/toggle_early_cut', '/toggle_early_invalid', '/early_cut_r_next', '/early_invalid_min_next')))
bot.process_command('/toggle_early_cut', ADMIN, 1)
check('ادمین: کلید ۱ خاموش شد', a['early_cut_enabled'] is False)
bot.process_command('/toggle_early_cut', ADMIN, 1)
bot.process_command('/toggle_early_invalid', ADMIN, 1)
check('ادمین: کلید ۲ روشن شد', a['early_invalid_enabled'] is True)
seq = []
for _ in range(5):
    bot.process_command('/early_cut_r_next', ADMIN, 1); seq.append(a['early_cut_r'])
check('آستانه: ۰.۵ → ۰.۶ → ۰.۷ → ۰.۳ → ۰.۴ → ۰.۵', seq == [0.6, 0.7, 0.3, 0.4, 0.5], seq)
seq = []
for _ in range(4):
    bot.process_command('/early_invalid_min_next', ADMIN, 1); seq.append(a['early_invalid_minutes'])
check('مهلت: ۳۰ → ۴۵ → ۶۰ → ۱۵ → ۳۰', seq == [45, 60, 15, 30], seq)
# ذخیره‌ی ادمین به کاربر می‌رسد
u['early_cut_enabled'] = False
bot.process_command('/preset_save_3', ADMIN, 1)
check('ذخیره‌ی پریست ادمین: کلید ۱ به کاربر رسید', u['early_cut_enabled'] is True)
check('ذخیره‌ی پریست ادمین: کلید ۲ (روشن) به کاربر رسید', u['early_invalid_enabled'] is True)
check('گزارش پریست اکانت کاربر: خروج زودهنگام دیده می‌شود', 'خروج زودهنگام' in bot.preset_active_text('3', u, actual=True))
print('\nALL PASS' if ok else '\nSOME FAILED')
sys.exit(0 if ok else 1)
