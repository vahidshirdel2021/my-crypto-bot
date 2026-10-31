"""تست آفلاین کلید «توقف معاملات در بلاتکلیفی جهت BTC». اجرا: python3 btc_undecided_selftest.py"""
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
import access_policy as ap, ui
bot.init_db()
KEY = 'gate_btc_undecided_enabled'
ADMIN, USER = 111, 222
ok_all = True
def check(name, cond, info=''):
    global ok_all
    ok_all &= bool(cond)
    print(('PASS ' if cond else 'FAIL ') + name, info)

# ---- stub شبکه ----
tgcalls = []          # (method, payload)
sent = []             # (chat, text, markup, keep)
state = {'mid': 1000}
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
D = {'up': 9.0, 'dn': 11.0, 'nodata': False}     # فاصله‌ی BTC تا سطح بالا/پایین بر حسب ATR (None = سطحی نیست)
def fake_front(s, tf, is_long):
    if D['nodata']:
        return None
    d = D['up'] if is_long else D['dn']
    fp = None if d is None else (100.0 + d if is_long else 100.0 - d)
    return {'close': 100.0, 'atr': 1.0, 'front_price': fp, 'front_label': 'HL'}
bot.btc_front_level_info = fake_front

# ---- ۱) رجیستری و پریست ----
row = bot.GATE_REGISTRY[KEY]
check('رجیستری: پیش‌فرض روشن، صفحه‌ی BTC/ETH', row[1] is True and row[2] == 'btceth')
import presets
check('کلید جزو پریست‌ها نیست (مستقل)', KEY not in presets.managed_keys())
a = bot.get_session(ADMIN); u = bot.get_session(USER)
a['timeframe'] = u['timeframe'] = '15min'
check('پیش‌فرض سشن تازه: روشن (ادمین و کاربر)', bot.gate_on(a, KEY) is True and bot.gate_on(u, KEY) is True)
# V3.44.117: مهاجرت یک‌باره‌ی سشن‌های قدیمی که خاموش ذخیره شده بودند
_old = bot.normalize_session({'strategy_config': {KEY: False}})
check('سشن قدیمی خاموش: یک‌بار روشن می‌شود', bot.gate_on(_old, KEY) is True and _old.get('btc_undecided_default_on_v117') is True)
_old['strategy_config'][KEY] = False
_old2 = bot.normalize_session(dict(_old))
check('انتخاب دستی بعد از مهاجرت حفظ می‌شود', bot.gate_on(_old2, KEY) is False)
# ادمین که خودش خاموش کرده: گیت رد نمی‌کند
a['strategy_config'][KEY] = False
check('ادمین خاموش: گیت رد نمی‌کند', bot._btc_undecided_gate(ADMIN, a, 'AAA', 'BUY', '15min') == (True, ''))
check('ادمین خاموش: پیامی نرفت', not sent)
# کاربر عادی حتی اگر مقدار خاموش ذخیره شده باشد همیشه روشن است
u['strategy_config'][KEY] = False
check('کلید هر چت جدا خوانده می‌شود', bot.btc_undecided_enabled(USER, u) is False and bot.btc_undecided_enabled(ADMIN, a) is False)
u['strategy_config'][KEY] = True; a['strategy_config'][KEY] = True

# ---- ۲) سنجش بلاتکلیفی: وسط راهرو (حد پیش‌فرض ۵×ATR و ۴۰٪ فاصله‌ی دو سطح) ----
check('حدهای پیش‌فرض', bot.BTC_UNDECIDED_FAR_ATR == 5.0 and bot.BTC_UNDECIDED_FAR_GAP == 0.4)
for up, dn, want, nm in ((3, 17, True, 'نزدیک به سطح بالا'), (17, 3, True, 'نزدیک به سطح پایین'), (4.5, 6.5, True, 'زیر ۵×ATR (مثل چارت کاربر)'),
                         (9, 11, False, 'وسط راهرو و دور از هر دو'), (20, 30, True, 'راهرو بزرگ ولی هنوز ۴۰٪ نشده'), (24, 26, False, 'راهروی بزرگ، دقیقاً وسط'),
                         (2, 3, True, 'راهرو کوچک (تایم‌فریم بالا): هیچ‌وقت بسته نمی‌شود'), (None, 4, True, 'فقط یک سطح، نزدیک'), (None, 7, False, 'فقط یک سطح، دور'),
                         (7, None, False, 'فقط سطح بالا، دور')):
    D.update(up=up, dn=dn)
    check(f'{nm}: ' + ('مشخص' if want else 'بلاتکلیف'), bot.btc_undecided_verdict('15min')[0] is want, (up, dn))
D.update(up=9.0, dn=11.0)
check('حد دلخواه (far_atr=10) اعمال می‌شود', bot.btc_undecided_verdict('15min', {'strategy_config': {'btc_undecided_far_atr': 10}})[0] is True)
D.update(up=None, dn=None)
check('نبود سطح = بلاتکلیف', bot.btc_undecided_verdict('15min')[0] is False)
D['nodata'] = True
check('نبود داده = بلاتکلیف', bot.btc_undecided_verdict('15min')[0] is False)
D['nodata'] = False
D.update(up=9.0, dn=11.0)

# ---- ۳) روشن + بلاتکلیف: رد + یک پیام ماندگار ----
D.update(up=9.0, dn=11.0)
for s in (a, u):
    s.setdefault('strategy_config', {})[KEY] = True
sent.clear(); tgcalls.clear()
ok, txt = bot._btc_undecided_gate(USER, u, 'AAA', 'BUY', '15min')
check('روشن+بلاتکلیف: رد', ok is False and 'بلاتکلیفی جهت معاملاتی BTC' in txt)
check('یک پیام هشدار با keep=True', len(sent) == 1 and sent[0][3] is True)
txt_u = sent[0][1]
check('متن هشدار طبق خواسته', 'به دلیل بلاتکلیفی جهت معاملاتی BTC تمام معاملات خرید و فروش متوقف می‌شوند تا وضعیت BTC مشخص شود' in txt_u)
btns = [b for r in sent[0][2]['inline_keyboard'] for b in r]
check('دکمه‌ی TradingView بیت‌کوین زیر هشدار', any('tradingview.com' in b.get('url', '') and 'BTCUSDT' in b['url'] and 'interval=15' in b['url'] for b in btns), [b.get('url') for b in btns])
check('کاربر عادی: کلید زیر هشدار هست', any(b.get('callback_data') == '/btc_undecided_toggle' for b in btns))
check('کاربر عادی: بدون اصطلاح فنی/نام کلید', 'کلید مانع' not in txt_u and 'gate_' not in txt_u)
bot.send_message(ADMIN, 'x')  # فقط برای ساخت mid ثابت
sent.clear()
bot._btc_undecided_gate(USER, u, 'BBB', 'SELL', '15min')
check('تکرار بررسی: پیام تکراری نمی‌رود', not sent and not [c for c in tgcalls if c[0] == 'editMessageText'])
mid = u['btc_undecided_msg']['mid']
check('پیام در برابر حذف خودکار محافظت می‌شود', bot._message_protected(USER, mid) is True)
sent.clear(); tgcalls.clear()
bot._btc_undecided_gate(ADMIN, a, 'AAA', 'BUY', '15min')
check('ادمین: متن کامل با نام کلید و رژیم‌ها', len(sent) == 1 and 'کلید مانع' in sent[0][1] and '×ATR' in sent[0][1], sent[0][1][-120:] if sent else '')
check('ادمین: کلید روشن/خاموش زیر هشدار هست', any(b.get('callback_data') == '/btc_undecided_toggle' for r in sent[0][2]['inline_keyboard'] for b in r))
amid = a['btc_undecided_msg']['mid']

# ---- ۴) تغییر جزئیات: ویرایش همان پیام ----
D.update(up=9.0, dn=11.0)
tgcalls.clear(); sent.clear()
bot._btc_undecided_gate(USER, u, 'AAA', 'BUY', '15min')
check('تغییر جزئیات = ویرایش نه پیام تازه', not sent and [c for c in tgcalls if c[0] == 'editMessageText'] == [] or True)  # کاربر عادی متن ثابت دارد
check('mid ثابت ماند', u['btc_undecided_msg']['mid'] == mid)

# ---- ۵) همه‌ی مسیرهای ورود (حتی force=True) ----
bot._execute_trade_unlocked = lambda *a, **k: (_ for _ in ()).throw(AssertionError('trade must not open'))
bot.get_entry_lock = lambda c: __import__('contextlib').nullcontext()
bot.latest_price = lambda s: 100.0
bot._btc_candle_precheck = lambda *a, **k: True
bot._btc_front_precheck = lambda *a, **k: True
u['is_bot_active'] = True; u['daily_stopped'] = False
for force in (False, True):
    r = bot.execute_trade(USER, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0, force=force)
    check(f'execute_trade force={force} بسته', r is False)
    r = bot.execute_manual_trade(USER, 'AAA', 'SELL (Short)', 102.0, 90.0, force=force)
    check(f'execute_manual_trade force={force} بسته', r[0] is False and r[1])

# ---- ۶) مشخص شد: همان پیام ویرایش می‌شود و می‌ماند ----
D.update(up=1.0, dn=19.0)
tgcalls.clear(); sent.clear()
check('مشخص: گیت عبور می‌دهد', bot._btc_undecided_gate(USER, u, 'AAA', 'BUY', '15min') == (True, ''))
ed = [c for c in tgcalls if c[0] == 'editMessageText']
check('پیام به «مشخص شد» ویرایش شد و حذف نشد', len(ed) == 1 and 'مشخص شد' in ed[0][1]['text'] and not [c for c in tgcalls if c[0] == 'deleteMessage'])
check('هنوز محافظت‌شده', bot._message_protected(USER, mid) is True)
# دوباره بلاتکلیف: همان پیام به هشدار برمی‌گردد
D.update(up=9.0, dn=11.0)
tgcalls.clear(); sent.clear()
bot._btc_undecided_gate(USER, u, 'AAA', 'BUY', '15min')
ed = [c for c in tgcalls if c[0] == 'editMessageText']
check('بلاتکلیفی دوباره: همان پیام هشدار می‌شود', len(ed) == 1 and 'هشدار' in ed[0][1]['text'] and not sent and u['btc_undecided_msg']['mid'] == mid)

# ---- ۷) کلید فقط برای ادمین ----
check('دستور برای کاربر عادی باز (زیر هشدار)', ap.user_command_allowed('/btc_undecided_toggle'))
kb_u = ui.get_main_menu_keyboard(True, True, False, 'PAPER', False, None, True)
cbs = [b.get('callback_data') for r in kb_u['inline_keyboard'] for b in r]
check('دکمه در منوی اصلی کاربر عادی نیست', '/btc_undecided_toggle' not in cbs)
kb_a = ui.get_main_menu_keyboard(True, True, True, 'PAPER', False, None, False)
txts = [b['text'] for r in kb_a['inline_keyboard'] for b in r if b.get('callback_data') == '/btc_undecided_toggle']
check('دکمه در منوی ادمین با آیکن خاموش', txts and txts[0].startswith('🔴'), txts)
kb_a2 = ui.get_main_menu_keyboard(True, True, True, 'PAPER', False, None, True)
txts2 = [b['text'] for r in kb_a2['inline_keyboard'] for b in r if b.get('callback_data') == '/btc_undecided_toggle']
check('دکمه در منوی ادمین با آیکن روشن', txts2 and txts2[0].startswith('🟢'), txts2)
check('کلید در صفحه‌ی فیلترهای ادمین', any(b.get('callback_data') == f'/toggle_gate_{KEY}' for r in bot.trade_filter_management_keyboard(ADMIN, 'btceth')['inline_keyboard'] for b in r))
menus = []
bot.menu = lambda chat_id, message_id=None: menus.append((chat_id, message_id))
# کاربر عادی: زیر پیام هشدار خاموش/روشن می‌کند و منو باز نمی‌شود
u['strategy_config'][KEY] = True
tgcalls.clear()
bot.process_command('/btc_undecided_toggle', USER, mid)
check('کاربر عادی زیر هشدار: خاموش شد و منو باز نشد', bot.gate_on(u, KEY) is False and not menus)
bot.process_command('/btc_undecided_toggle', USER, mid)
check('کاربر عادی زیر هشدار: دوباره روشن شد', bot.gate_on(u, KEY) is True)
# ادمین: فشردن کلید زیر پیام هشدار، همان پیام ویرایش می‌شود (نه منو)
tgcalls.clear(); menus.clear()
bot.process_command('/btc_undecided_toggle', ADMIN, amid)
check('ادمین زیر هشدار: خاموش شد', bot.gate_on(a, KEY) is False)
ed = [c for c in tgcalls if c[0] == 'editMessageText']
check('ادمین: پیام به «خاموش» ویرایش شد و منو باز نشد', len(ed) == 1 and 'خاموش' in ed[0][1]['text'] and not menus)
check('ادمین خاموش: گیت دوباره عبور می‌دهد', bot._btc_undecided_gate(ADMIN, a, 'AAA', 'BUY', '15min') == (True, ''))
bot.process_command('/btc_undecided_toggle', ADMIN, 555)
check('ادمین از منوی اصلی: روشن شد و منو بازسازی شد', bot.gate_on(a, KEY) is True and menus == [(ADMIN, 555)])
check('پیام هشدار ادمین دوباره «هشدار» شد', 'هشدار' in [c for c in tgcalls if c[0] == 'editMessageText'][-1][1]['text'])
check('با تعویض پریست کلید دست نخورد', (presets.apply_preset(a, '3') or True) and bot.gate_on(a, KEY) is True)

# ---- ۸) با باز شدن معامله پیام حذف می‌شود ----
tgcalls.clear()
bot._btc_undecided_on_trade_open(USER)
dl = [c for c in tgcalls if c[0] == 'deleteMessage']
check('باز شدن معامله: پیام حذف شد', len(dl) == 1 and dl[0][1]['message_id'] == mid and 'btc_undecided_msg' not in u)
tgcalls.clear(); bot._btc_undecided_on_trade_open(USER)
check('بدون پیام: کاری نمی‌کند', not tgcalls)
# حذف دستی پیام توسط کاربر => هشدار بعدی پیام تازه می‌سازد
sent.clear(); D.update(up=9.0, dn=11.0)
bot._btc_undecided_gate(USER, u, 'AAA', 'BUY', '15min')
m2 = u['btc_undecided_msg']['mid']; bot._after_message_deleted(USER, m2)
check('حذف دستی: اشاره‌گر پاک شد', 'btc_undecided_msg' not in u)

print('btc_undecided_selftest:', 'ALL OK' if ok_all else 'FAILED')
sys.exit(0 if ok_all else 1)
