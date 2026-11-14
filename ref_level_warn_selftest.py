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
assert bot.BOT_VERSION == '3.44.169'

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
print('ALL OK')
