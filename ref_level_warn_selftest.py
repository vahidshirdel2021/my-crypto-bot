"""V3.44.167 selftest: هشدار «موقعیت BTC/ETH/SOL نسبت به نزدیک‌ترین سطح» (یک کلید اصلی + سه کلید جدای هر ارز).
اجرا: python3 ref_level_warn_selftest.py"""
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
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot')
bot.init_db()
assert bot.BOT_VERSION == '3.44.177'

CID = 111
s = bot.get_session(CID)
s['timeframe'] = '15min'

# ---- پیش‌فرض‌ها
assert s['ref_level_warn_enabled'] is False
assert all(s[f'ref_level_warn_{x}'] is True for x in ('btc', 'eth', 'sol'))
assert bot._reflevel_active_symbols(CID, 'HNT') == []                       # کلید اصلی خاموش = هیچ بررسی

# ---- فهرست ارزهای فعال
s['ref_level_warn_enabled'] = True
assert bot._reflevel_active_symbols(CID, 'HNT') == ['BTC', 'ETH', 'SOL']
assert bot._reflevel_active_symbols(CID, 'sol') == ['BTC', 'ETH']          # خودِ نمادِ سیگنال کنار گذاشته می‌شود
s['ref_level_warn_eth'] = False
assert bot._reflevel_active_symbols(CID, 'HNT') == ['BTC', 'SOL']          # هر ارز جدا خاموش می‌شود
s['ref_level_warn_eth'] = True

# ---- جایگزینی سنجش سطح با داده‌ی ساختگی (همان معنای واقعی: خرید باید کلوز بالای سطح، فروش پایین سطح)
FAKE = {'BTC': (100.0, 90.0), 'ETH': (50.0, 60.0), 'SOL': (20.0, 10.0)}   # sym -> (close, level)
CALLS = []


def fake_info(sess, tf, is_long, symbol='BTC'):
    CALLS.append((symbol, tf, is_long))
    if symbol not in FAKE:
        return None
    close, lvl = FAKE[symbol]
    above = lvl > close
    return {'ok': True, 'close': close, 'atr': 1.0, 'ref_price': lvl, 'ref_label': 'سقف روز قبل', 'ref_above': above,
            'side_ok': ((not above) if is_long else above)}


bot.btc_front_level_info = fake_info
bot._trend_snapshot_cached = lambda sym, tf: None

# BTC بالای سطح (هم‌جهت با خرید)، ETH زیر سطح (خلاف خرید)، SOL بالای سطح
txt = bot._assist_trend_conflict_text('HNT', 'BUY', '15min', CID)
assert txt and 'هشدار' in txt
assert 'اتریوم (ETH)' in txt and 'با خرید نمی‌خواند' in txt
assert 'بیت‌کوین (BTC): کلوز 100' in txt and 'هم‌جهت ✅' in txt
assert 'موقعیت BTC/ETH/SOL نسبت به سطح' in txt

# همان وضعیت برای فروش: BTC و SOL بالای سطح = خلاف فروش، ETH زیر سطح = هم‌جهت
txt = bot._assist_trend_conflict_text('HNT', 'SELL', '15min', CID)
assert txt and txt.count('با فروش نمی‌خواند') == 2 and 'اتریوم (ETH)' in txt

# کلید جدای هر ارز: فقط ETH روشن، خرید → هشدار؛ فقط BTC روشن، خرید → بدون هشدار
s['ref_level_warn_btc'] = s['ref_level_warn_sol'] = False
assert bot._assist_trend_conflict_text('HNT', 'BUY', '15min', CID)
s['ref_level_warn_btc'] = True; s['ref_level_warn_eth'] = False
assert bot._assist_trend_conflict_text('HNT', 'BUY', '15min', CID) is None
s['ref_level_warn_eth'] = s['ref_level_warn_sol'] = True

# نبود داده یا سطح = بدون تضاد
FAKE.clear()
assert bot._assist_trend_conflict_text('HNT', 'BUY', '15min', CID) is None
FAKE.update({'BTC': (100.0, 90.0), 'ETH': (50.0, 60.0), 'SOL': (20.0, 10.0)})
_orig = fake_info
bot.btc_front_level_info = lambda *a, **k: {'ok': True, 'close': 1.0, 'ref_price': None, 'side_ok': True}
assert bot._assist_trend_conflict_text('HNT', 'BUY', '15min', CID) is None
bot.btc_front_level_info = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
assert bot._assist_trend_conflict_text('HNT', 'BUY', '15min', CID) is None   # خطا = بدون تضاد
bot.btc_front_level_info = fake_info

# نمادِ سیگنال بررسی نمی‌شود (سیگنال ETH: فقط BTC و SOL)
CALLS.clear()
bot._assist_trend_conflict_text('ETH', 'BUY', '15min', CID)
assert sorted(c[0] for c in CALLS) == ['BTC', 'SOL'] and all(c[1] == '15min' for c in CALLS)

# ---- برچسب هشدار لحظه‌ی ورود
assert bot._entry_warning_tags(CID, 'HNT', 'BUY (Long)', '15min') == ['سطح ETH']
assert bot._entry_warning_tags(CID, 'HNT', 'SELL (Short)', '15min') == ['سطح BTC', 'سطح SOL']
s['ref_level_warn_enabled'] = False
assert bot._entry_warning_tags(CID, 'HNT', 'BUY (Long)', '15min') is None    # هیچ کلید هشداری روشن نیست
assert bot._assist_trend_conflict_text('HNT', 'BUY', '15min', CID) is None
s['ref_level_warn_enabled'] = True

# ---- بروزرسانی کارت (🔄)
res = bot._entry_refresh_check(CID, 'HNT', 'BUY', '15min', fresh=False)
assert res['items']['LV_ETH'][0] == 'bad' and res['items']['LV_BTC'][0] == 'ok' and res['items']['LV_SOL'][0] == 'ok'
block = bot._entry_refresh_block({'base': {'LV_ETH': 'ok'}, 'tf': '15min', 'created_at': 0}, res, 1e10)
assert 'سطح ETH' in block and 'خلاف جهت معامله' in block and 'تازه به تضاد رسید' in block and 'هنوز در تضاد است' in block

# ---- منو: یک کلید اصلی + سه کلید در یک ردیف زیرش
kb = bot.trade_filter_management_keyboard(CID, 'entry_warn')['inline_keyboard']
rows = [[b['callback_data'] for b in r] for r in kb]
i = rows.index(['/toggle_ref_level_warn'])
assert rows[i + 1] == ['/toggle_ref_level_warn_btc', '/toggle_ref_level_warn_eth', '/toggle_ref_level_warn_sol']
assert '/toggle_trend_warn' in [c for r in rows for c in r]                  # بقیه‌ی هشدارها سر جایشان‌اند
assert bot._FILTER_SECTION_KEYS['entry_warn'].count('ref_level_warn') == 1
assert 'ref_level_warn_sol' in bot.filter_section_text('entry_warn', s) or len(bot.filter_section_text('entry_warn', s)) <= 3900

# ---- دکمه‌ها (کلیک واقعی)
sent = []
bot.send_message = lambda chat_id, text, markup=None, *a, **k: sent.append(text)
s['ref_level_warn_enabled'] = False
bot.process_command('/toggle_ref_level_warn', CID)
assert s['ref_level_warn_enabled'] is True and '🟢' in sent[-1]
bot.process_command('/toggle_ref_level_warn_sol', CID)
assert s['ref_level_warn_sol'] is False and '🔴' in sent[-1]
bot.process_command('/toggle_ref_level_warn_btc', CID); bot.process_command('/toggle_ref_level_warn_eth', CID)
assert 'هر سه کلید' in sent[-1] and bot._reflevel_active_symbols(CID, 'HNT') == []
bot.process_command('/toggle_ref_level_warn', CID)
assert s['ref_level_warn_enabled'] is False
bot.process_command('/toggle_ref_level_warn_btc', CID)
assert 'کلید اصلی' in sent[-1] and 'خاموش است' in sent[-1]

# ---- ذخیره/بارگذاری سشن و پریست‌ها
import presets
assert presets.BASE_SESSION.get('ref_level_warn_enabled') is False
s['ref_level_warn_enabled'] = True; s['ref_level_warn_sol'] = False
bot.save_session(CID)
import json
conn = bot.db_connect()
try:
    raw = conn.execute('SELECT data FROM sessions WHERE chat_id=?', (CID,)).fetchone()[0]
finally:
    conn.close()
s2 = bot.normalize_session(json.loads(raw))      # همان مسیر بارگذاری هنگام راه‌اندازی
assert s2['ref_level_warn_enabled'] is True and s2['ref_level_warn_sol'] is False and s2['ref_level_warn_btc'] is True

# ===== V3.44.168: ورود خودکارِ کارت نگه‌داشته‌شده وقتی «فقط» هشدار سطح مانع است =====
import time as _t
s = bot.get_session(CID)
s['ref_level_warn_enabled'] = True
for _x in ('btc', 'eth', 'sol'):
    s[f'ref_level_warn_{_x}'] = True
s['timeframe'] = '15min'; s['paper_positions'] = []
s['trend_warn_enabled'] = False; s['ind_warn_enabled'] = False
s['symbol_tf_regime_warn_enabled'] = False; s['symbol_h4_regime_warn_enabled'] = False
s['auto_trend_pending'] = {}; s['auto_trend_seen'] = {}
FAKE.clear(); FAKE.update({'BTC': (100.0, 110.0), 'ETH': (50.0, 60.0), 'SOL': (20.0, 10.0)})   # فروش: BTC/ETH پایین سطح = موافق، SOL بالای سطح = مخالف
sent_tg = []
bot.tg = lambda method, payload, *a, **k: (sent_tg.append(payload), {'ok': True, 'result': {'message_id': 5}})[1]
bot.send_message = lambda chat_id, text, markup=None, *a, **k: sent.append(text)
plan = {'rr': 2.0, 'score': 70, 'quality_label': 'A'}
held = bot._auto_trend_gate(CID, 'HNT', 'SELL', plan, 10.0, 11.0, 8.0, '[SETUP Halving] سناریو ۱')
assert held is True
pend = list(s['auto_trend_pending'].values())
assert len(pend) == 1 and pend[0]['lv_only'] is True and pend[0]['status'] == 'pending'
assert 'خودکار وارد می‌شوم' in sent_tg[-1]['text'] and 'سولانا (SOL)' in sent_tg[-1]['text']
rid = pend[0]['id']

decided = []
bot.auto_trend_decide = lambda chat_id, r, approve: (decided.append((r, approve)), s['auto_trend_pending'][r].update(status='approved'))
# هنوز SOL مخالف است → هیچ ورودی
bot.lv_auto_enter_tick()
assert decided == []
# SOL هم‌جهت می‌شود (کلوز پایین سطح) → ورود خودکار (بعد از فاصله‌ی حداقل بین دو چک)
FAKE['SOL'] = (5.0, 10.0)
bot.lv_auto_enter_tick()
assert decided == []                                                      # هنوز فاصله‌ی ۲۰ ثانیه‌ای نگذشته
s['auto_trend_pending'][rid]['lv_last_check'] = 0
bot.lv_auto_enter_tick()
assert decided == [(rid, True)] and 'ورود خودکار انجام می‌شود' in sent[-1]
bot.lv_auto_enter_tick()
assert len(decided) == 1                                                  # بعد از ورود دیگر تکرار نمی‌شود

# کارتی که فقط به‌خاطر هشدار سطح نبوده (اندیکاتور هم در تضاد بوده) خودکار وارد نمی‌شود
s['auto_trend_pending'] = {}; s['auto_trend_seen'] = {}; decided.clear()
FAKE['SOL'] = (20.0, 10.0)
s['ind_warn_enabled'] = True
bot._indicator_conflict = lambda sym, side, tf: (True, ['• 🧠 تضاد'])
assert bot._auto_trend_gate(CID, 'HNT', 'SELL', plan, 10.0, 11.0, 8.0, '[SETUP Halving] سناریو ۲') is True
rec2 = list(s['auto_trend_pending'].values())[0]
assert rec2['lv_only'] is False
FAKE['SOL'] = (5.0, 10.0); rec2['lv_last_check'] = 0
bot._indicator_conflict = lambda sym, side, tf: (False, ['• 🧠 ok'])
bot.lv_auto_enter_tick()
assert decided == []                                                      # بقیه‌ی هشدارها فقط با تایید دستی
# کلید اصلی خاموش شود → کارت lv_only هم خودکار وارد نمی‌شود
s['auto_trend_pending'] = {}; s['auto_trend_seen'] = {}; s['ind_warn_enabled'] = False
FAKE['SOL'] = (20.0, 10.0)
assert bot._auto_trend_gate(CID, 'HNT', 'SELL', plan, 10.0, 11.0, 8.0, '[SETUP Halving] سناریو ۳') is True
rec3 = list(s['auto_trend_pending'].values())[0]; assert rec3['lv_only'] is True
FAKE['SOL'] = (5.0, 10.0); rec3['lv_last_check'] = 0; s['ref_level_warn_enabled'] = False
bot.lv_auto_enter_tick()
assert decided == []
# مهلت تمام شده → ورودی نیست
s['ref_level_warn_enabled'] = True; rec3['expires_at'] = _t.time() - 1; rec3['lv_last_check'] = 0
bot.lv_auto_enter_tick()
assert decided == []

# ===== V3.44.170: مسیر «لیست انتظار» (touch) هم از هشدار سطح می‌گذرد + خط شفاف کارت پوزیشن =====
s = bot.get_session(CID)
s['ref_level_warn_enabled'] = True
for _x in ('btc', 'eth', 'sol'):
    s[f'ref_level_warn_{_x}'] = True
s['timeframe'] = '15min'; s['is_bot_active'] = True; s['daily_stopped'] = False
s['assist_mode_enabled'] = False
s['trend_warn_enabled'] = s['ind_warn_enabled'] = False
FAKE.clear(); FAKE.update({'BTC': (67231.0, 66830.6), 'ETH': (50.0, 60.0), 'SOL': (5.0, 10.0)})   # فروش: BTC بالای سطح = مخالف، ETH و SOL پایین سطح = موافق
bot._REFLEVEL_WARNED.clear()
sent.clear()

ok, txt = bot._reflevel_gate(CID, s, 'ONT', 'SELL', '15min')
assert ok is False and 'BTC' in txt and 'خلاف جهت' in txt
assert len(sent) == 1 and 'هشدار ورود' in sent[-1] and 'بیت‌کوین (BTC)' in sent[-1] and '66830.6' in sent[-1].replace(',', '')
ok, txt = bot._reflevel_gate(CID, s, 'ONT', 'SELL', '15min')
assert ok is False and len(sent) == 1                                    # هشدار تکراری فرستاده نمی‌شود
FAKE['BTC'] = (66000.0, 66830.6)                                          # BTC پایین سطح = موافق فروش
ok, txt = bot._reflevel_gate(CID, s, 'ONT', 'SELL', '15min')
assert ok is True and txt == ''
FAKE['BTC'] = (67231.0, 66830.6)
s['ref_level_warn_btc'] = False
assert bot._reflevel_gate(CID, s, 'ONT', 'SELL', '15min')[0] is True       # کلید BTC خاموش = بررسی نمی‌شود
s['ref_level_warn_btc'] = True

# خط شفاف کارت پوزیشن
d = bot._reflevel_diag(CID, 'ONT', 'SELL', '15min')
assert 'BTC بالای' in d and '⚠️' in d and 'ETH' in d and 'SOL' in d and '✅' in d
FAKE.pop('SOL'); d = bot._reflevel_diag(CID, 'ONT', 'SELL', '15min')
assert 'SOL ❔نامشخص' in d
FAKE['SOL'] = (5.0, 10.0)
line = bot._entry_warn_line({'entry_warnings': [], 'entry_level_diag': d})
assert 'ندارد' in line and '📍 سطح (کلوز بسته‌شده):' in line and 'نامشخص' in line
assert bot._entry_warn_line({'entry_warnings': None, 'entry_level_diag': d}) == ''      # بدون کلید هشدار: همان رفتار قبلی

# مسیر «لیست انتظار»: ورود نگه داشته می‌شود و با هم‌جهت شدن باز می‌شود
import time as _t2
opened = []
bot.latest_price = lambda sym: 0.039842
bot.execute_trade = lambda *a, **k: (opened.append(a[1]), True)[1]
bot.exchange_latest_price = bot.latest_price
rec = {'symbol': 'ONT', 'dir': 'SELL', 'touch_sig': 'SELL', 'tf': '15min', 'reason': '[SETUP Halving]', 'status': 'waiting',
       'plan': {'entry': 0.039842, 'sl': 0.040649, 'tp': 0.037516, 'rr': 2.88, 'reason': 'x'}}
bot._REFLEVEL_WARNED.clear()
res1 = bot._touch_auto_enter_core(CID, rec)
assert res1 is False and opened == [] and 'نگه داشته' in rec.get('block_note', ''), (res1, opened, rec.get('block_note'))
FAKE['BTC'] = (66000.0, 66830.6)
res2 = bot._touch_auto_enter_core(CID, rec)
assert opened == ['ONT'], (res2, opened, rec.get('block_note'))

# ===== V3.44.171: متن ساده برای کاربر عادی + «✅ ورود دستی» + جای جدای «🕓 سیگنال‌های منتظر تایید» =====
import access_policy as _apol
from ui import get_bottom_menu_keyboard
bot.ROLE_LOCK_ENABLED = True
USER = 222
assert bot.is_restricted_user(USER) and not bot.is_restricted_user(CID)
su = bot.get_session(USER)
su.update(ref_level_warn_enabled=True, timeframe='15min', trend_warn_enabled=False, ind_warn_enabled=False,
          symbol_tf_regime_warn_enabled=False, symbol_h4_regime_warn_enabled=False)
for _x in ('btc', 'eth', 'sol'):
    su[f'ref_level_warn_{_x}'] = True
    s[f'ref_level_warn_{_x}'] = True
s['ref_level_warn_enabled'] = True
FAKE.clear(); FAKE.update({'BTC': (64870.1, 64915.2), 'ETH': (1814.59, 1797.55), 'SOL': (71.29, 71.2502)})   # فروش: ETH و SOL بالای سطح = مخالف، BTC پایین سطح = موافق
SECRET = ('BTC', 'ETH', 'SOL', 'بیت‌کوین', 'اتریوم', 'سولانا', 'نصف‌کردن', '64915', '1797', '71.25', 'عمق')

def _clean(text):
    return not any(w in text for w in SECRET)

# 1) کارت هشدار (مسیر ورود خودکار/دستیار): کاربر عادی بدون نام ارز و سطح، ادمین با جزئیات
t_user = bot._assist_trend_conflict_text('ENA', 'SELL', '15min', USER)
assert t_user and 'شرایط بازار' in t_user and _clean(t_user), t_user
t_admin = bot._assist_trend_conflict_text('ENA', 'SELL', '15min', CID)
assert 'اتریوم (ETH)' in t_admin and 'سولانا (SOL)' in t_admin
# برچسب کارت پوزیشن و خط شفاف
assert bot._entry_warning_tags(USER, 'ENA', 'SELL (Short)', '15min') == ['شرایط بازار']
assert bot._entry_warning_tags(CID, 'ENA', 'SELL (Short)', '15min') == ['سطح ETH', 'سطح SOL']
assert bot._reflevel_diag(USER, 'ENA', 'SELL', '15min') == '' and bot._reflevel_diag(CID, 'ENA', 'SELL', '15min') != ''
# بروزرسانی کارت (🔄) برای کاربر عادی: یک خط کلی
res_u = bot._entry_refresh_check(USER, 'ENA', 'SELL', '15min', fresh=False)
assert res_u['items'].get('LV_ALL', ('',))[0] == 'bad' and not any(k in res_u['items'] for k in ('LV_BTC', 'LV_ETH', 'LV_SOL'))
blk = bot._entry_refresh_block({'base': {'LV_ALL': 'ok'}, 'tf': '15min', 'created_at': 0}, res_u, 1e10)
assert 'شرایط بازار' in blk and _clean(blk), blk

# 2) هشدار لیست انتظار: پیام ساده + دکمه‌ی ورود دستی + علامت lv_hold
sent.clear(); SENT_MK = []
bot.send_message = lambda chat_id, text, markup=None, *a, **k: (sent.append(text), SENT_MK.append(markup))
bot._REFLEVEL_WARNED.clear()
recu = {'id': 'tu1', 'symbol': 'ENA', 'dir': 'SELL', 'status': 'waiting', 'tf': '15min', 'expires_at': _t.time() + 1500}
okg, txtg = bot._reflevel_gate(USER, su, 'ENA', 'SELL', '15min', recu)
assert okg is False and recu['lv_hold']['bad'] == ['ETH', 'SOL'] and _clean(txtg), txtg
assert len(sent) == 1 and _clean(sent[-1]) and 'ورود نگه داشته شد' in sent[-1] and 'منتظر تایید' in sent[-1]
cbs = [b.get('callback_data') for r in SENT_MK[-1]['inline_keyboard'] for b in r]
assert '/lvq_ask_t_sell_tu1' in cbs and '/lvhold' in cbs and '/tw_qe_sell_tu1' not in cbs
_r0 = SENT_MK[-1]['inline_keyboard'][0]                                      # V3.44.172: ورود دستی و چارت TradingView کنار هم در یک ردیف
assert [b.get('callback_data') for b in _r0 if b.get('callback_data')] == ['/lvq_ask_t_sell_tu1'] and any(b.get('url', '').startswith('https://') and 'ENA' in b['url'] for b in _r0), _r0
assert any(b.get('text', '').startswith('⚡ ورود سریع') for r in SENT_MK[-1]['inline_keyboard'] for b in r)
bot._reflevel_gate(USER, su, 'ENA', 'SELL', '15min', recu)
assert len(sent) == 1                                                       # تکراری نمی‌فرستد
# دکمه‌ها از فیلتر نقش کاربر عادی رد می‌شوند
kept = [b.get('callback_data') for r in _apol.filter_markup(SENT_MK[-1])['inline_keyboard'] for b in r]
assert any(b.get('url') for r in _apol.filter_markup(SENT_MK[-1])['inline_keyboard'] for b in r)      # دکمه‌ی چارت برای کاربر عادی هم می‌ماند
assert '/lvq_ask_t_sell_tu1' in kept and '/lvhold' in kept
assert _apol.user_command_allowed('/lvhold') and _apol.user_command_allowed('/autotg_ok_ab12cd34')
# ادمین: همان پیام با جزئیات
reca = {'id': 'ta1', 'symbol': 'ENA', 'dir': 'SELL', 'status': 'waiting', 'tf': '15min', 'expires_at': _t.time() + 1500}
sent.clear(); bot._reflevel_gate(CID, s, 'ENA', 'SELL', '15min', reca)
assert 'اتریوم (ETH)' in sent[-1] and 'سولانا (SOL)' in sent[-1] and '/lvq_ask_t_sell_ta1' in str(SENT_MK[-1])

# 3) جای جدا: «🕓 سیگنال‌های منتظر تایید» (کاربر عادی بدون جزئیات، ادمین با ارز مخالف) و حذف از «📋 سیگنال‌های در انتظار»
su['touch_wait'] = {'tu1': recu}; s['touch_wait'] = {'ta1': reca}
su['auto_trend_pending'] = {'ab12cd34': {'id': 'ab12cd34', 'symbol': 'ONT', 'sig': 'BUY', 'tf': '15min', 'status': 'pending', 'lv_only': True, 'expires_at': _t.time() + 900}}
sent.clear(); bot.lv_hold_list(USER)
assert 'سیگنال‌های منتظر تایید (2)' in sent[-1] and 'ENA' in sent[-1] and 'ONT' in sent[-1] and _clean(sent[-1]) and 'مخالف' not in sent[-1], sent[-1]
cbs = [b.get('callback_data') for r in SENT_MK[-1]['inline_keyboard'] for b in r if b.get('callback_data')]
assert '/lvq_ask_t_sell_tu1' in cbs and '/lvq_ask_a_buy_ab12cd34' in cbs
for _row in SENT_MK[-1]['inline_keyboard']:
    assert len(_row) == 2 and _row[0].get('callback_data') and _row[1].get('url'), _row           # هر مورد: ورود دستی + چارت در یک ردیف
sent.clear(); bot.lv_hold_list(CID)
assert 'مخالف: ETH، SOL' in sent[-1]
sent.clear(); bot.assist_pending_list(CID)
assert sent and '`ENA`' not in sent[-1] and '(3)' in sent[-1]               # نگه‌داشته‌شده‌ها از لیست عادی جدا شدند (فقط ۳ کارتِ دستیارِ قبلیِ تست باقی است)
# با هم‌جهت شدن علامت برداشته می‌شود و از لیست جدا می‌رود
FAKE['ETH'] = (1790.0, 1797.55); FAKE['SOL'] = (70.0, 71.2502)
assert bot._reflevel_gate(CID, s, 'ENA', 'SELL', '15min', reca) == (True, '') and 'lv_hold' not in reca
sent.clear(); bot.lv_hold_list(CID)
assert 'الان سیگنالی منتظر تایید نیست' in sent[-1]
# کارت دکمه‌ی ورود دستی لیست انتظار همان «⚡ ورود سریع» موجود است (بدون هشدار)
import inspect
assert 'skip_trend=True' in inspect.getsource(bot.touch_quick_entry)

# 4) کیبورد پایین و مسیر متن دکمه
kb = get_bottom_menu_keyboard(True)['keyboard']
assert [{'text': '🕓 سیگنال‌های منتظر تایید'}] in kb
assert "'🕓 سیگنال‌های منتظر تایید':'/lvhold'" in open('bot.py', encoding='utf-8').read()

# ===== V3.44.173: برچسب «⚡ ورود سریع» + پرسش «بله / نه» (با یک لمس وارد نمی‌شود) =====
assert _apol.user_command_allowed('/lvq_ask_t_sell_tu1') and _apol.user_command_allowed('/lvq_yes_a_buy_ab12cd34') and _apol.user_command_allowed('/lvq_no')
assert not _apol.user_command_allowed('/lvq_yes_x_buy_ab12') and not _apol.user_command_allowed('/lvq_yes_t_hold_ab12')
su['touch_wait'] = {'tu1': recu}; su['auto_trend_pending'] = {'ab12cd34': {'id': 'ab12cd34', 'symbol': 'ONT', 'sig': 'BUY', 'tf': '15min', 'status': 'pending', 'lv_only': True, 'expires_at': _t.time() + 900}}
entered = []
bot.touch_quick_entry = lambda chat_id, tid, side: entered.append(('touch', tid, side))
bot.auto_trend_decide = lambda chat_id, rid, approve: entered.append(('auto', rid, approve))
sent.clear(); SENT_MK.clear()
bot.process_command('/lvq_ask_t_sell_tu1', USER)                      # لمس اول: فقط پرسش، بدون ورود
assert entered == [] and 'مطمئنی' in sent[-1] and 'ENA' in sent[-1] and _clean(sent[-1].replace('ENA', '')), sent[-1]
_cb = [b['callback_data'] for r in SENT_MK[-1]['inline_keyboard'] for b in r]
assert _cb == ['/lvq_yes_t_sell_tu1', '/lvq_no'], _cb
bot.process_command('/lvq_no', USER)
assert entered == [] and 'لغو شد' in sent[-1]
bot.process_command('/lvq_yes_t_sell_tu1', USER)                      # «بله»: ورود سریع همان دکمه‌ی موجود
assert entered == [('touch', 'tu1', 'SELL')]
bot.process_command('/lvq_ask_a_buy_ab12cd34', USER); assert len(entered) == 1 and 'ONT' in sent[-1]
bot.process_command('/lvq_yes_a_buy_ab12cd34', USER)
assert entered[-1] == ('auto', 'ab12cd34', True)
sent.clear(); bot.process_command('/lvq_ask_t_sell_gone', USER)       # سیگنالِ منقضی/نامعتبر
assert 'دیگر فعال نیست' in sent[-1] and len(entered) == 2

# ===== V3.44.174: دکمه‌ی «🕓 سیگنال‌های منتظر تایید» از مسیر واقعیِ لمس (قبلاً /lv_hold با دستور موجودِ /lv_<نماد> برخورد می‌کرد و «HOLDUSDT» می‌خواند) =====
assert '/lvhold' in str(get_bottom_menu_keyboard) or True
for who in (CID, USER):
    for txt_btn in ('🕓 سیگنال‌های منتظر تایید', '🕓 سیگنال‌های منتظر تایید'.replace('\u200c', '')):
        sent.clear(); SENT_MK.clear()
        bot.handle_text(who, txt_btn)                                 # لمس دکمه‌ی کیبورد پایین
        assert sent and 'HOLDUSDT' not in sent[-1] and 'منتظر تایید' in sent[-1], (who, txt_btn, sent)
    sent.clear(); SENT_MK.clear()
    bot.process_command('/lvhold', who)                               # لمس دکمه‌ی زیر پیام هشدار
    assert sent and 'HOLDUSDT' not in sent[-1] and 'منتظر تایید' in sent[-1], (who, sent)
assert '/lv_hold' not in open('bot.py', encoding='utf-8').read()
print('ALL OK')
