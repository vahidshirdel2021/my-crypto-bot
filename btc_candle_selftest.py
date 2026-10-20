"""تست آفلاین کلید «هم‌جهتی با کندل در حال تشکیل BTC». اجرا: python btc_candle_selftest.py"""
import os, time, logging, hashlib, threading
import pandas as pd
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
log = logging.getLogger('t')

# ---------------------------------------------------------------- ۱) حکم خالص کندل BTC ----------
a = src.index("# ===================== V3.44.42: کلید «هم‌جهتی با کندل در حال تشکیل BTC»")
b = src.index("def btc_eth_regime_rows(")
HELPERS = src[a:b]
st = {'rows': None, 'price': None, 'calls': 0, 'stale_first': False}
CACHE = {}


def mk_rows(tf_secs, open_px, close_px, fresh=True):
    now = time.time()
    start = int(now // tf_secs) * tf_secs
    last_ts = start if fresh else start - tf_secs
    return pd.DataFrame([{'timestamp': (last_ts - tf_secs) * 1000, 'open': 99.0, 'high': 101.0, 'low': 98.0, 'close': open_px, 'volume': 1.0},
                         {'timestamp': last_ts * 1000, 'open': open_px, 'high': max(open_px, close_px), 'low': min(open_px, close_px), 'close': close_px, 'volume': 1.0}])


def fake_klines(sym, tf, n):
    st['calls'] += 1
    assert sym == 'BTC'
    rows = st['rows']
    if callable(rows):
        rows = rows()
    return rows


g = dict(os=os, time=time, logger=log, _TF_SECONDS={'5min': 300, '15min': 900, '1hour': 3600, '4hour': 14400},
         TIMEFRAME_MAP={'5min': '5min', '15min': '15min', '1hour': '1hour', '4hour': '4hour'},
         TF_DISPLAY={'5min': '5م', '15min': '15م', '1hour': '1س', '4hour': '4س'},
         DATA_LOCK=threading.RLock(), DATA_CACHE=CACHE, get_klines=fake_klines,
         latest_price=lambda s: st['price'], fmt=lambda v: f'{float(v):.2f}')
exec(HELPERS, g)
v = g['btc_candle_verdict']
P = g['_BTC_CANDLE_BLOCK_PREFIX']

# کندل صعودی: خرید مجاز، فروش ممنوع
st.update(rows=mk_rows(300, 100.0, 100.5), price=100.5)
assert v('5min', 'BUY') == (True, '')
ok, t = v('5min', 'SELL'); assert not ok and t.startswith(P) and 'صعودی' in t and 'فروش' in t, t
# کندل نزولی: فروش مجاز، خرید ممنوع
st.update(rows=mk_rows(300, 100.0, 99.5), price=99.5)
assert v('5min', 'SELL') == (True, '')
ok, t = v('5min', 'BUY'); assert not ok and 'نزولی' in t, t
# قیمت لحظه‌ای از کلوز کش‌شده مهم‌تر است (کندل در همین ثانیه برگشته)
st.update(rows=mk_rows(300, 100.0, 100.5), price=99.9)
assert not v('5min', 'BUY')[0] and v('5min', 'SELL')[0]
# بدون قیمت لحظه‌ای: از کلوز ردیف آخر استفاده می‌شود
st.update(rows=mk_rows(300, 100.0, 100.5), price=None)
assert v('5min', 'BUY')[0]
# کندل خنثی (باز == قیمت): هیچ جهتی هم‌جهت نیست
st.update(rows=mk_rows(300, 100.0, 100.0), price=100.0)
assert not v('5min', 'BUY')[0] and not v('5min', 'SELL')[0]
print(v('5min', 'BUY')[1])
# نبود داده: بسته (fail-closed)
st.update(rows=pd.DataFrame(), price=100.0)
ok, t = v('5min', 'BUY'); assert not ok and 'در دسترس نیست' in t, t
st.update(rows=None, price=100.0)
assert not v('5min', 'SELL')[0]
# تایم‌فریم ناشناخته
assert not v('7min', 'BUY')[0]
# کش کهنه (آخرین ردیف کندل قبلی است): یک‌بار کش دور زده و دوباره دریافت می‌شود
CACHE['BTC:5min:60'] = {'x': 1}
seq = [mk_rows(300, 100.0, 99.0, fresh=False), mk_rows(300, 100.0, 100.8, fresh=True)]
st.update(rows=lambda: seq.pop(0) if len(seq) > 1 else seq[0], price=100.8, calls=0)
assert v('5min', 'BUY')[0] and st['calls'] == 2 and 'BTC:5min:60' not in CACHE, (st, CACHE)
# اگر بعد از دور زدن کش هم کهنه ماند: بسته
st.update(rows=mk_rows(300, 100.0, 100.8, fresh=False), price=100.8, calls=0)
assert not v('5min', 'BUY')[0] and st['calls'] == 2
# تایم‌فریم‌های دیگر
for tf, secs in (('15min', 900), ('1hour', 3600), ('4hour', 14400)):
    st.update(rows=mk_rows(secs, 50.0, 51.0), price=51.0)
    assert v(tf, 'BUY')[0] and not v(tf, 'SELL')[0], tf
# حداقل بدنه‌ی تنظیم‌پذیر (متغیر محیطی)
g2 = dict(g); g2['BTC_CANDLE_MIN_BODY_PCT'] = 0.0
exec(HELPERS.replace("BTC_CANDLE_MIN_BODY_PCT = max(0.0, float(os.environ.get('BTC_CANDLE_MIN_BODY_PCT', '0') or 0))", "BTC_CANDLE_MIN_BODY_PCT = 0.05"), g2)
st.update(rows=mk_rows(300, 100.0, 100.02), price=100.02)          # +0.02٪ < 0.05٪ => خنثی
assert not g2['btc_candle_verdict']('5min', 'BUY')[0]
st.update(rows=mk_rows(300, 100.0, 100.2), price=100.2)            # +0.2٪ => صعودی
assert g2['btc_candle_verdict']('5min', 'BUY')[0]

# ---------------------------------------------------------------- ۲) پیش‌بررسی + مسیرهای ورود (حتی با force) ----------
a = src.index("def _btc_candle_precheck(")
b = src.index("def _log_grid_levels_sync(")
S = {'cfg': {'gate_btc_candle_enabled': True}, 'timeframe': '5min', 'daily_stopped': False, 'is_bot_active': True, 'scan_generation': 0}
LBR = {}
ex = {'unlocked': 0}


class _L:
    def __enter__(self): return self
    def __exit__(self, *a): return False


def blk(chat_id, reason):
    LBR[chat_id] = reason
    return False


g3 = dict(time=time, logger=log, _BLK_CTX={}, _LAST_BLOCK_REASON=LBR, get_session=lambda c: S, gate_on=lambda s, k: bool(S['cfg'].get(k, False)),
          side_long=lambda side: 'BUY' in str(side).upper() or 'LONG' in str(side).upper(),
          btc_candle_verdict=v, _BTC_CANDLE_BLOCK_PREFIX=P, _blk=blk, latest_price=lambda s: 100.0, get_entry_lock=lambda c: _L(),
          _execute_trade_unlocked=lambda *a, **k: (ex.__setitem__('unlocked', ex['unlocked'] + 1) or True))
exec(src[a:b], g3)
et, em = g3['execute_trade'], g3['execute_manual_trade']

# BTC صعودی => فروش (حتی force=True / دستی) رد می‌شود و به قفل/اجرا نمی‌رسد
st.update(rows=mk_rows(300, 100.0, 100.5), price=100.5)
ex['unlocked'] = 0; LBR.clear()
assert et(1, 'AAA', 'SELL (Short)', 100.0, 102.0, 90.0) is False and ex['unlocked'] == 0 and LBR[1].startswith(P)
assert et(1, 'AAA', 'SELL (Short)', 100.0, 102.0, 90.0, force=True) is False and ex['unlocked'] == 0
ok, err = em(1, 'AAA', 'SELL (Short)', 102.0, 90.0, entry_price=100.0, force=True)
assert ok is False and err.startswith(P) and ex['unlocked'] == 0, (ok, err)
ok, err = em(1, 'AAA', 'SELL (Short)', 102.0, 90.0, entry_price=100.0)
assert ok is False and err.startswith(P) and ex['unlocked'] == 0
print(err)
# هم‌جهت: عبور
assert et(1, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0) is True and ex['unlocked'] == 1
ok, err = em(1, 'AAA', 'BUY (Long)', 98.0, 110.0, entry_price=100.0, force=True); assert ok and ex['unlocked'] == 2
# کلید خاموش: رفتار قبلی و هیچ دریافت داده‌ای انجام نمی‌شود
S['cfg']['gate_btc_candle_enabled'] = False; st['calls'] = 0
assert et(1, 'AAA', 'SELL (Short)', 100.0, 102.0, 90.0, force=True) is True and st['calls'] == 0
ok, err = em(1, 'AAA', 'SELL (Short)', 102.0, 90.0, entry_price=100.0, force=True); assert ok and st['calls'] == 0
S['cfg']['gate_btc_candle_enabled'] = True
# معاملات معکوس: جهت نهایی (برعکس‌شده) سنجیده می‌شود. سیگنال خرید در BTC نزولی => معامله‌ی فروش => مجاز
S['cfg']['gate_inverse_trading_enabled'] = True
st.update(rows=mk_rows(300, 100.0, 99.5), price=99.5)
assert et(1, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0) is True
assert et(1, 'AAA', 'SELL (Short)', 100.0, 102.0, 90.0) is False
S['cfg'].pop('gate_inverse_trading_enabled')
# نبود داده => ورود دستی هم انجام نمی‌شود
st.update(rows=pd.DataFrame(), price=None)
ok, err = em(1, 'AAA', 'BUY (Long)', 98.0, 110.0, entry_price=100.0, force=True); assert not ok and 'در دسترس نیست' in err

# ---------------------------------------------------------------- ۳) صف تایید حرکت: صبر تا هم‌جهت شدن ----------
a = src.index("def _fav_move_r("); b = src.index("FAV_CARDS_PER_LIST =")
SF = {'cfg': {'gate_btc_candle_enabled': True}, 'paper_positions': [], 'trading_mode': 'PAPER'}
calls = {'exec': 0, 'flip': 0, 'btc': 'BEARISH', 'card': 0}
now0 = time.time()
rows = [{'timestamp': now0 - 120, 'close': 100.0}, {'timestamp': now0 - 60, 'close': 100.8}, {'timestamp': now0, 'close': 100.8}]
gf = dict(os=os, logger=log, time=time, FAV_CONFIRM_MIN_RR=0.0, FAV_CONFIRM_CANCEL_R=1.0, FAV_REVERSE_TO_TOUCH=True,
          _FAV_FLIP_TAG='x', _TF_SECONDS={'5min': 300}, _LAST_BLOCK_REASON={}, hashlib=hashlib,
          exchange_latest_price=lambda c, s: 100.8, latest_price=lambda s: 100.8,
          get_klines=lambda sym, tf, n: pd.DataFrame(rows),
          get_session=lambda c: SF, save_session=lambda c: None, _fav_update_card=lambda *a, **k: None,
          gate_on=lambda s, k: bool(SF['cfg'].get(k, False)), _BTC_CANDLE_BLOCK_PREFIX=P,
          btc_candle_verdict=lambda tf, sig: (True, '') if (calls['btc'] == ('BULLISH' if sig == 'BUY' else 'BEARISH')) else (False, f"{P} {calls['btc']}"),
          execute_trade=lambda *a, **k: (calls.__setitem__('exec', calls['exec'] + 1) or True),
          _auto_trend_gate=lambda *a, **k: False, _assist_queue_signal=lambda *a, **k: (calls.__setitem__('card', calls['card'] + 1) or 'ok'),
          _touch_register=lambda *a, **k: (calls.__setitem__('flip', calls['flip'] + 1) or ('touch_wait', 'x')))
exec(src[src.index("_FINAL_REGIME_FA = "):src.index("def _final_regime_check(")], gf)
exec(src[a:b], gf)


def mkr(expires=600):
    return {'id': 'r1', 'symbol': 'AAA', 'sig': 'BUY', 'side_label': 'BUY (Long)', 'entry': 100.0, 'sl': 98.0, 'tp': 110.0,
            'reason': 'r', 'tf': '5min', 'min_r': 0.3, 'max_r': 1.0, 'created_at': now0 - 200, 'expires_at': now0 + expires,
            'last_eval_ts': 0.0, 'status': 'waiting'}


# کندل BTC خلاف خرید: سیگنال در صف می‌ماند (نه معامله، نه حذف)
r = mkr(); gf['_fav_process_one'](1, SF, r)
assert r['status'] == 'waiting' and calls['exec'] == 0 and r.get('btc_blocked') and P in r['btc_hold'], r
gf['_fav_process_one'](1, SF, r); assert r['status'] == 'waiting' and calls['exec'] == 0       # تیک بعدی هم همان کندل را دوباره می‌سنجد
# کندل BTC صعودی شد: همان تیک بعدی وارد می‌شود
calls['btc'] = 'BULLISH'; gf['_fav_process_one'](1, SF, r)
assert r['status'] == 'opened' and calls['exec'] == 1 and not r.get('btc_blocked'), r
# مهلت تمام می‌شود و کندل BTC هرگز هم‌جهت نشد: بدون ورود، بدون برعکس‌شدن، علت = btc
r = mkr(expires=-1); calls.update(exec=0, flip=0, btc='BEARISH'); gf['_fav_process_one'](1, SF, r)
assert r['status'] == 'expired' and r['why'] == 'btc' and calls['exec'] == 0 and calls['flip'] == 0, r
# حالت دستیار: کارت ساخته می‌شود (ورودِ کارت در execute_trade رد می‌شود)، صف منتظر BTC نمی‌ماند
SF['assist_mode_enabled'] = True; calls.update(exec=0, card=0, btc='BEARISH')
r = mkr(); gf['_fav_process_one'](1, SF, r); assert r['status'] == 'card_sent' and calls['card'] == 1 and calls['exec'] == 0, r
SF['assist_mode_enabled'] = False
# کلید خاموش: رفتار قبلی
SF['cfg']['gate_btc_candle_enabled'] = False; calls.update(exec=0, btc='BEARISH')
r = mkr(); gf['_fav_process_one'](1, SF, r); assert r['status'] == 'opened' and calls['exec'] == 1, r

# ---------------------------------------------------------------- ۴) اوردر معلق: حذف نمی‌شود، منتظر می‌ماند ----------
a = src.index("def check_pending_orders("); b = src.index("# مدت اعتبار پیام‌های کانال سیگنال")
SP = {'pending_orders': [{'symbol': 'AAA', 'side': 'SELL', 'trigger_price': None, 'entry_price': 100.0, 'sl': 102.0, 'tp': 90.0,
                          'margin': 10, 'leverage': 5, 'triggered': True, 'order_id': 'o1'}], 'trade_amount_usdt': 5, 'leverage': 3, 'paper_positions': []}
sent = []; res = {'v': (False, f'{P} (5م) در حال تشکیل صعودی است')}
gp = dict(logger=log, get_session=lambda c: SP, latest_price=lambda s: 100.0, fmt=lambda v: str(v), send_message=lambda c, t, *a, **k: sent.append(t),
          side_long=g3['side_long'], save_session=lambda c: None, time=time, _BTC_CANDLE_BLOCK_PREFIX=P,
          execute_manual_trade=lambda *a, **k: res['v'])
exec(src[a:b], gp)
gp['check_pending_orders'](1)
assert len(SP['pending_orders']) == 1 and len(sent) == 1 and 'منتظر' in sent[0], (SP, sent)
gp['check_pending_orders'](1); assert len(SP['pending_orders']) == 1 and len(sent) == 1       # پیام تکراری نمی‌رود
res['v'] = (True, ''); gp['check_pending_orders'](1)
assert SP['pending_orders'] == [] and 'باز شد' in sent[-1], (SP, sent)
res['v'] = (False, 'سقف تعداد پوزیشن پر است')
SP['pending_orders'] = [{'symbol': 'AAA', 'side': 'BUY', 'entry_price': 100.0, 'sl': 98.0, 'tp': 110.0, 'margin': 10, 'leverage': 5, 'triggered': True}]
gp['check_pending_orders'](1); assert SP['pending_orders'] == [] and 'باز نشد' in sent[-1]       # خطاهای دیگر مثل قبل حذف می‌کنند

# ---------------------------------------------------------------- ۵) ثبت کلید + وصل بودن در مسیرهای خودکار ----------
i = src.index("'gate_btc_candle_enabled': ("); assert "False, 'entry_rules'" in src[i:i + 260]
assert "'btc_candle', sig" in src and "_bc_ok, _bc_txt = btc_candle_verdict(tf, side)" in src
fq = src[src.index("def fav_quick_entry("):src.index("def fav_queue_list(")]
assert 'btc_candle' not in fq        # ورود سریع دستی خودش از execute_manual_trade (پیش‌بررسی) رد می‌شود، نه با منطق جدا
assert "BOT_VERSION = '3.44.42'" in src
print('ALL OK')
