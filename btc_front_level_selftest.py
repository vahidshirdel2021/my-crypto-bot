"""تست آفلاین کلید «فاصله تا سطح جلویی BTC». اجرا: python btc_front_level_selftest.py"""
import os, time, math, logging, hashlib, threading, re
import numpy as np
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, 'bot.py'), encoding='utf-8').read()
import strategy as stg
log = logging.getLogger('t')

a = src.index("# ===================== V3.44.44: کلید «فاصله تا سطح جلویی BTC»")
b = src.index("def btc_eth_regime_rows(")
HELPERS = src[a:b]

# ---------- داده‌ی ساختگی BTC: ۶۵۰ کندل ۵دقیقه‌ای تا شروع کندل جاری (آخرین ردیف = کندل در حال تشکیل) ----------
SECS = 300
def mk_df(n=650, fresh=True, base=83000.0):
    now = time.time(); start = int(now // SECS) * SECS
    last_ts = start if fresh else start - SECS
    rng = np.random.default_rng(7)
    ts = [(last_ts - (n - 1 - i) * SECS) for i in range(n)]
    px = base + np.cumsum(rng.normal(0, 25, n)) + 400 * np.sin(np.linspace(0, 12, n))
    rows = []
    for i in range(n):
        o = px[i - 1] if i else px[0]; c = px[i]
        rows.append({'timestamp': ts[i] * 1000, 'open': o, 'high': max(o, c) + 15, 'low': min(o, c) - 15, 'close': c, 'volume': 10.0})
    return pd.DataFrame(rows)

st = {'df': mk_df(), 'klines': 0, 'ind': 0, 'range': (126148.0, 2816.0), 'sent': []}
CACHE, LOCK = {}, threading.RLock()

def fake_klines(sym, tf, n):
    st['klines'] += 1
    assert sym == 'BTC'
    d = st['df']
    return d() if callable(d) else d

def counting_ind(df):
    st['ind'] += 1
    return stg.calculate_indicators(df)

g = dict(os=os, time=time, math=math, threading=threading, logger=log,
         _TF_SECONDS={'5min': 300}, TIMEFRAME_MAP={'5min': '5min'}, TF_DISPLAY={'5min': '5م'},
         DATA_LOCK=LOCK, DATA_CACHE=CACHE, get_klines=fake_klines, fmt=lambda v: f'{float(v):.2f}',
         STRATEGY_DEFAULTS=stg.STRATEGY_DEFAULTS, calculate_indicators=counting_ind,
         _quick_opposing_levels=stg._quick_opposing_levels,
         get_halving_range_sync=lambda sym: st['range'],
         _with_halving_cfg=lambda cfg, rng: ({**cfg, 'halving_high': float(rng[0]), 'halving_low': float(rng[1])} if (cfg or {}).get('halving_model_enabled') and rng else cfg),
         _log_grid_levels_sync=lambda sym: [],
         send_message=lambda c, t, *a, **k: st['sent'].append((c, t)), send_detail_message=lambda c, t, *a, **k: st['sent'].append((c, t)),
         gate_on=lambda s, k: bool((s.get('cfg') or {}).get(k, False)))
exec(HELPERS, g)
_real_info = g['btc_front_level_info']
def _info_noside(s, tf, is_long):
    # بخش‌های ۱ تا ۸ فقط منطق «فاصله» را می‌سنجند؛ سنجش «سمت سطح» (V3.44.54) در بخش ۹ جدا و با تابع واقعی تست می‌شود.
    i = _real_info(s, tf, is_long)
    if i:
        i['side_ok'] = True
        i['chop'] = False            # کلاف هم در بخش ۱۰ جدا تست می‌شود
    return i
g['btc_front_level_info'] = _info_noside
info_f, verdict, warn, gate = _info_noside, g['btc_front_level_verdict'], g['_btc_front_warn'], g['_btc_front_gate']
PFX = g['_BTC_FRONT_PREFIX']

def S(**cfg):
    return {'strategy_config': dict(cfg.pop('sc', {})), 'cfg': cfg}

# ---------------------------------------------------------------- ۱) سنجش فاصله (سطوح قدیمی) ----------
s0 = S()
bi = info_f(s0, '5min', True); si = info_f(s0, '5min', False)
assert bi and si, (bi, si)
assert bi['front_price'] > bi['close'] > si['front_price'], (bi, si)      # خرید: سطح بالاتر، فروش: سطح پایین‌تر
assert math.isclose(bi['dist'], bi['front_price'] - bi['close']) and math.isclose(bi['dist_atr'], bi['dist'] / bi['atr'])
last_closed = float(st['df'].iloc[-2]['close']); assert math.isclose(bi['close'], last_closed)   # کلوز آخرین کندل بسته‌شده، نه کندل در حال تشکیل
print('front BUY:', bi['front_label'], round(bi['dist_atr'], 2), 'ATR | SELL:', si['front_label'], round(si['dist_atr'], 2), 'ATR')
# آستانه: کمی کمتر از فاصله‌ی واقعی => معقول؛ کمی بیشتر => نامعقول (با هشدار و متن درست)
lo_thr, hi_thr = bi['dist_atr'] * 0.9, bi['dist_atr'] * 1.1
ok, t, i2 = verdict(S(sc={'btc_front_min_atr': lo_thr}), '5min', 'BUY'); assert ok and t == '' and i2['ok']
ok, t, i2 = verdict(S(sc={'btc_front_min_atr': hi_thr}), '5min', 'BUY')
assert (not ok and t.startswith(PFX) and 'بیتکوین (BTC) به سطح مقاومتی نزدیک است و تا واکنش به سطح منتظر ورود می‌مانیم' in t
       and 'لطفاً صبور باشید' in t and bi['front_label'] in t), t
print(t)
# آستانه‌ی صفر = هرگز مسدود نمی‌کند
ok, t, _i = verdict(S(sc={'btc_front_min_atr': 1e6}), '5min', 'SELL'); assert not ok and 'سطح حمایتی نزدیک است' in t and 'مقاومتی' not in t, t   # فروش: سطح پایینی = حمایت
assert verdict(S(sc={'btc_front_min_atr': 0}), '5min', 'SELL')[0]
# پیش‌فرض ۱×ATR از متغیر محیطی/ثابت
assert g['BTC_FRONT_MIN_ATR'] == 1.0 and bi['min_atr'] == 1.0

# ---------------------------------------------------------------- ۲) بدون سطح روبه‌رو / نبود داده ----------
g2 = dict(g); g2['_quick_opposing_levels'] = lambda *a, **k: []
exec(HELPERS, g2)
ok, t, i2 = g2['btc_front_level_verdict'](S(), '5min', 'BUY'); assert ok and i2['front_price'] is None       # سطحی روبه‌رو نیست => مانعی نیست
for bad in (None, pd.DataFrame(), mk_df(20)):                                                            # نبود داده => نگه‌داشتن (fail-closed)
    st['df'] = bad; g['_BTC_FRONT_CACHE'].clear()
    ok, t, i2 = verdict(S(), '5min', 'BUY'); assert not ok and i2 is None and 'در دسترس نیست' in t and 'صبور باشید' in t, t
# کش کهنه (آخرین ردیف کندل قبلی): یک‌بار کش دور زده می‌شود؛ اگر باز کهنه بود => نگه‌داشتن
CACHE['BTC:5min:650'] = {'x': 1}; st['klines'] = 0
seq = [mk_df(fresh=False), mk_df(fresh=True)]
st['df'] = lambda: seq.pop(0) if len(seq) > 1 else seq[0]
g['_BTC_FRONT_CACHE'].clear()
assert info_f(S(), '5min', True) is not None and st['klines'] == 2 and 'BTC:5min:650' not in CACHE
st['df'] = mk_df(fresh=False); g['_BTC_FRONT_CACHE'].clear(); st['klines'] = 0
assert info_f(S(), '5min', True) is None and st['klines'] == 2
assert info_f(S(), '7min', True) is None                                                                   # تایم‌فریم ناشناخته
st['df'] = mk_df()

# ---------------------------------------------------------------- ۳) کش: با همان کندل بسته‌شده دوباره محاسبه نمی‌شود ----------
g['_BTC_FRONT_CACHE'].clear(); st['ind'] = 0
r1 = info_f(S(), '5min', True); r2 = info_f(S(), '5min', True); assert r1 == r2 and st['ind'] == 1
info_f(S(), '5min', False); assert st['ind'] == 2                                                          # جهت دیگر = کلید کش دیگر
info_f(S(sc={'btc_front_min_atr': 3.0}), '5min', True); assert st['ind'] == 3                              # آستانه‌ی دیگر = کلید کش دیگر
# کندل بسته‌شده‌ی جدید => محاسبه‌ی تازه
d = st['df'].copy(); d['timestamp'] = d['timestamp'] + SECS * 1000
st['df'] = d; ts_new = float(d.iloc[-1]['timestamp']) / 1000
g['time'] = type('T', (), {'time': staticmethod(lambda: ts_new + 10)})()      # ساعت = یک کندل جلوتر (آخرین ردیف همچنان در حال تشکیل)
exec("import time as _t", g)
info_f(S(), '5min', True); assert st['ind'] == 4
g['time'] = time; st['df'] = mk_df()

# ---------------------------------------------------------------- ۴) مدل نصف‌کردن: سطوح درخت (BTC با سقف/کف تاریخی خودش) ----------
sh = S(sc={'halving_model_enabled': True, 'halving_k_atr': 3.0, 'halving_max_depth': 14, 'halving_min_depth': 3})
g['_BTC_FRONT_CACHE'].clear()
hb = info_f(sh, '5min', True); hs = info_f(sh, '5min', False)
assert hb and hs and hb['front_price'] > hb['close'] > hs['front_price'], (hb, hs)
assert 'نصف' in hb['front_label'], hb['front_label']                                                       # همان سیستم سطوح حساب (نصف‌کردن)
print('halving front:', hb['front_label'], round(hb['dist_atr'], 2), 'ATR')
st['range'] = None; g['_BTC_FRONT_CACHE'].clear()
ok, t, i2 = verdict(sh, '5min', 'BUY'); assert not ok and i2 is None and 'در دسترس نیست' in t           # نصف‌کردن روشن ولی سقف/کف BTC نیست => نگه‌داشتن
st['range'] = (126148.0, 2816.0)

# ---------------------------------------------------------------- ۵) هشدار ورود: یک‌بار برای هر سطح؛ معکوس؛ بدون هشدار وقتی معقول است ----------
g['_BTC_FRONT_CACHE'].clear(); g['_BTC_FRONT_WARNED'].clear(); st['sent'].clear()
bad = S(sc={'btc_front_min_atr': 1e6})          # هر فاصله‌ای نامعقول
for _ in range(4):
    ok, t = gate(7, bad, 'AAA', 'BUY', '5min'); assert not ok and t.startswith(PFX)
assert len(st['sent']) == 1 and st['sent'][0][0] == 7 and 'AAA' in st['sent'][0][1] and 'خرید' in st['sent'][0][1] and 'صبور' in st['sent'][0][1], st['sent']
gate(7, bad, 'BBB', 'BUY', '5min'); assert len(st['sent']) == 2                                          # نماد دیگر = هشدار جدا
gate(7, bad, 'AAA', 'SELL', '5min'); assert len(st['sent']) == 3 and 'فروش' in st['sent'][-1][1]         # جهت دیگر (سطح پایینی) = هشدار جدا
gate(8, bad, 'AAA', 'BUY', '5min'); assert len(st['sent']) == 4                                          # چت دیگر = هشدار جدا
n1 = len(st['sent']); ok, t = gate(55, bad, 'NEW', 'BUY', '5min', warn=False); assert not ok and len(st['sent']) == n1      # مسیر دستی: هشدار جدا نمی‌رود (دلیل رد را خودش نشان می‌دهد)
good = S(sc={'btc_front_min_atr': 0}); n0 = len(st['sent'])
assert gate(7, good, 'AAA', 'BUY', '5min') == (True, '') and len(st['sent']) == n0                       # معقول: بی‌صدا و عبور
# معاملات معکوس: جهت نهایی برعکس‌شده سنجیده می‌شود (سیگنال خرید => معامله‌ی فروش => سطح پایینی)
seen = []
g['btc_front_level_verdict'] = lambda s_, tf, sig, **k: (seen.append(sig) or (True, '', None))
gate(1, S(gate_inverse_trading_enabled=True), 'AAA', 'BUY', '5min'); gate(1, S(), 'AAA', 'BUY', '5min')
assert seen == ['SELL', 'BUY'], seen
g['btc_front_level_verdict'] = verdict
# استثنا در محاسبه => نگه‌داشتن + هشدار، بدون کرش
g['btc_front_level_verdict'] = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
ok, t = gate(9, S(), 'ZZZ', 'BUY', '5min'); assert not ok and 'خطا' in t
g['btc_front_level_verdict'] = verdict

# ---------------------------------------------------------------- ۶) صف تایید حرکت: صبر (رد نمی‌شود) تا فاصله معقول شود ----------
a2 = src.index("def _fav_move_r("); b2 = src.index("FAV_CARDS_PER_LIST =")
SF = {'cfg': {'gate_btc_front_level_enabled': True}, 'paper_positions': [], 'trading_mode': 'PAPER'}
calls = {'exec': 0, 'card': 0, 'flip': 0, 'front_ok': False}
now0 = time.time()
rows = [{'timestamp': now0 - 120, 'close': 100.0}, {'timestamp': now0 - 60, 'close': 100.8}, {'timestamp': now0, 'close': 100.8}]
FRONT_TXT = f'{PFX}: فاصله تا سطح جلویی در BTC (5م) محاسبه شد و معقول نیست'
gf = dict(os=os, logger=log, time=time, FAV_CONFIRM_MIN_RR=0.0, FAV_CONFIRM_CANCEL_R=1.0, FAV_REVERSE_TO_TOUCH=True,
          _FAV_FLIP_TAG='x', _TF_SECONDS={'5min': 300}, _LAST_BLOCK_REASON={}, hashlib=hashlib,
          exchange_latest_price=lambda c, s: 100.8, latest_price=lambda s: 100.8,
          get_klines=lambda sym, tf, n: pd.DataFrame(rows),
          get_session=lambda c: SF, save_session=lambda c: None, _fav_update_card=lambda *a, **k: None,
          gate_on=lambda s, k: bool(SF['cfg'].get(k, False)), _BTC_CANDLE_BLOCK_PREFIX='⛔ کندل BTC',
          btc_candle_verdict=lambda tf, sig: (True, ''),
          _btc_front_gate=lambda chat_id, s, sym, sig, tf, *a, **k: (True, '') if calls['front_ok'] else (False, FRONT_TXT),
          _btc_front_flags=lambda s: (bool(SF['cfg'].get('gate_btc_front_level_enabled', False)), bool(SF['cfg'].get('gate_btc_chop_enabled', False))),
          execute_trade=lambda *a, **k: (calls.__setitem__('exec', calls['exec'] + 1) or True),
          _auto_trend_gate=lambda *a, **k: False, _assist_queue_signal=lambda *a, **k: (calls.__setitem__('card', calls['card'] + 1) or 'ok'),
          _touch_register=lambda *a, **k: (calls.__setitem__('flip', calls['flip'] + 1) or ('touch_wait', 'x')))
exec(src[src.index("_FINAL_REGIME_FA = "):src.index("def _final_regime_check(")], gf)
exec(src[a2:b2], gf)

def mkr(expires=600):
    return {'id': 'r1', 'symbol': 'AAA', 'sig': 'BUY', 'side_label': 'BUY (Long)', 'entry': 100.0, 'sl': 98.0, 'tp': 110.0,
            'reason': 'r', 'tf': '5min', 'min_r': 0.3, 'max_r': 1.0, 'created_at': now0 - 200, 'expires_at': now0 + expires,
            'last_eval_ts': 0.0, 'status': 'waiting'}

r = mkr(); gf['_fav_process_one'](1, SF, r)
assert r['status'] == 'waiting' and calls['exec'] == 0 and r.get('front_blocked') and r['front_hold'] == FRONT_TXT, r      # در صف می‌ماند، نه معامله، نه حذف
gf['_fav_process_one'](1, SF, r); assert r['status'] == 'waiting' and calls['exec'] == 0                                  # تیک بعدی هم دوباره می‌سنجد
calls['front_ok'] = True; gf['_fav_process_one'](1, SF, r)
assert r['status'] == 'opened' and calls['exec'] == 1 and not r.get('front_blocked') and not r.get('front_hold'), r
assert "if r.get('front_hold') and r.get('status') == 'waiting':" in src                  # دلیل نگه‌داشتن روی کارت صف تایید حرکت دیده می‌شود
# مهلت تمام می‌شود و فاصله هرگز معقول نشد: بدون ورود، بدون برعکس‌شدن، علت = front
r = mkr(expires=-1); calls.update(exec=0, flip=0, front_ok=False); gf['_fav_process_one'](1, SF, r)
assert r['status'] == 'expired' and r['why'] == 'front' and calls['exec'] == 0 and calls['flip'] == 0, r
# حالت دستیار: کارت دستیار هم تا معقول شدن فاصله ساخته نمی‌شود (مثل رژیم بازار)
SF['assist_mode_enabled'] = True; calls.update(card=0, exec=0)
r = mkr(); gf['_fav_process_one'](1, SF, r); assert r['status'] == 'waiting' and calls['card'] == 0, r
calls['front_ok'] = True; gf['_fav_process_one'](1, SF, r); assert r['status'] == 'card_sent' and calls['card'] == 1, r
SF['assist_mode_enabled'] = False
# کلید خاموش: رفتار قبلی (بدون هیچ سنجشی)
SF['cfg']['gate_btc_front_level_enabled'] = False; calls.update(exec=0, front_ok=False)
r = mkr(); gf['_fav_process_one'](1, SF, r); assert r['status'] == 'opened' and calls['exec'] == 1, r

# ---------------------------------------------------------------- ۷) ثبت کلید + سیم‌کشی مسیرها ----------
i = src.index("'gate_btc_front_level_enabled': ("); assert "True, 'entry_rules'" in src[i:i + 260]
assert src.count("_btc_front_gate(") >= 3 and src.count("gate_on(s, 'gate_btc_front_level_enabled')") == 1 and src.count("_btc_front_flags(s)") == 5     # تعریف + صف تایید + لیست انتظار + مسیر مستقیم + پیش‌بررسی همه‌ی مسیرها
assert "_btc_front_gate(chat_id, s, symbol, sig, tf, front=_ff, chop=_fc)" in src and "_btc_front_gate(chat_id, s, symbol, side, tf, front=_ff, chop=_fc)" in src
assert "asyncio.to_thread(_btc_front_gate, chat_id, s, symbol, sig, tf, True, True, _ff, _fc)" in src
assert "'btc_front', sig" in src and "'front': 'فاصله‌ی BTC تا سطح جلویی معقول نشد'" in src
et_src = src[src.index("def execute_trade("):src.index("def execute_manual_trade(")]
em_src = src[src.index("def execute_manual_trade("):src.index("def _log_grid_levels_sync(")]
assert "_btc_front_precheck(chat_id, symbol, side, signal_price, sl, tp, force, True)" in et_src
assert "_btc_front_precheck(chat_id, symbol, side, price, sl, tp, force, bool(force))" in em_src      # ⚡ ورود سریع/تایید کارت از همین مسیر می‌گذرند
assert "str(err).startswith(_BTC_FRONT_PREFIX)" in src                                         # اوردر معلق حذف نمی‌شود
assert re.search(r"BOT_VERSION = '3\.44\.\d+'", src)

# ---------------------------------------------------------------- ۸) پیش‌بررسی روی همه‌ی مسیرها (ورود سریع/تایید کارت هم بسته) ----------
a3 = src.index("def _btc_candle_precheck("); b3 = src.index("def _log_grid_levels_sync(")
SX = {'cfg': {'gate_btc_front_level_enabled': True}, 'timeframe': '5min', 'daily_stopped': False, 'is_bot_active': True, 'scan_generation': 0}
LBR = {}; ex = {'unlocked': 0}; fg = {'ok': False, 'calls': []}

class _L:
    def __enter__(self): return self
    def __exit__(self, *a): return False

def blk(chat_id, reason):
    LBR[chat_id] = reason; return False

def fake_gate(chat_id, s, symbol, sig, tf, warn=True, allow_inverse=True, front=True, chop=True):
    fg['calls'].append((sig, warn, allow_inverse))
    return (True, '') if fg['ok'] else (False, f'{PFX}: بیتکوین (BTC) به سطح مقاومتی نزدیک است و تا واکنش به سطح منتظر ورود می‌مانیم؛ لطفاً صبور باشید')

g4 = dict(time=time, logger=log, _BLK_CTX={}, _LAST_BLOCK_REASON=LBR, get_session=lambda c: SX, gate_on=lambda s, k: bool(SX['cfg'].get(k, False)),
          side_long=lambda side: 'BUY' in str(side).upper() or 'LONG' in str(side).upper(),
          btc_candle_verdict=lambda tf, sig: (True, ''), _BTC_CANDLE_BLOCK_PREFIX='⛔ کندل BTC', _blk=blk, _btc_front_gate=fake_gate,
          latest_price=lambda s: 100.0, get_entry_lock=lambda c: _L(),
          _execute_trade_unlocked=lambda *a, **k: (ex.__setitem__('unlocked', ex['unlocked'] + 1) or True))
exec(src[a3:b3], g4)
et2, em2 = g4['execute_trade'], g4['execute_manual_trade']
# فاصله نامعقول: همه‌ی مسیرها بسته‌اند، حتی force (تایید کارت) و ⚡ ورود سریع
ex['unlocked'] = 0; LBR.clear()
assert et2(1, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0) is False and ex['unlocked'] == 0 and LBR[1].startswith(PFX)
assert fg['calls'][-1] == ('BUY', True, True)                                     # خودکار: هشدار ورود فرستاده می‌شود
assert et2(1, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0, force=True) is False and ex['unlocked'] == 0     # تایید دستی کارت دستیار
assert fg['calls'][-1] == ('BUY', False, True)                                    # دستی: هشدار جدا نه؛ دلیل رد به کاربر نشان داده می‌شود
ok, err = em2(1, 'AAA', 'BUY (Long)', 98.0, 110.0, entry_price=100.0, force=True)   # ⚡ ورود سریع
assert ok is False and err.startswith(PFX) and 'صبور باشید' in err and ex['unlocked'] == 0, (ok, err)
assert fg['calls'][-1] == ('BUY', False, True)
ok, err = em2(1, 'AAA', 'SELL (Short)', 102.0, 90.0, entry_price=100.0)             # دستی معمولی (بدون force)
assert ok is False and err.startswith(PFX) and ex['unlocked'] == 0 and fg['calls'][-1] == ('SELL', True, False)
# فاصله معقول: عبور
fg['ok'] = True
assert et2(1, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0) is True and ex['unlocked'] == 1
assert et2(1, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0, force=True) is True
ok, err = em2(1, 'AAA', 'BUY (Long)', 98.0, 110.0, entry_price=100.0, force=True); assert ok and ex['unlocked'] == 3
# کلید خاموش: هیچ سنجشی انجام نمی‌شود
SX['cfg']['gate_btc_front_level_enabled'] = False; fg['ok'] = False; fg['calls'].clear()
assert et2(1, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0, force=True) is True and fg['calls'] == []
SX['cfg']['gate_btc_front_level_enabled'] = True

# اوردر معلق: با پیام «هشدار ورود» حذف نمی‌شود و منتظر می‌ماند
a5 = src.index("def check_pending_orders("); b5 = src.index("# مدت اعتبار پیام‌های کانال سیگنال")
SP = {'pending_orders': [{'symbol': 'AAA', 'side': 'BUY', 'trigger_price': None, 'entry_price': 100.0, 'sl': 98.0, 'tp': 110.0,
                          'margin': 10, 'leverage': 5, 'triggered': True, 'order_id': 'o1'}], 'trade_amount_usdt': 5, 'leverage': 3, 'paper_positions': []}
sent2 = []
gp2 = dict(logger=log, get_session=lambda c: SP, latest_price=lambda s: 100.0, fmt=lambda v: str(v), send_message=lambda c, t, *a, **k: sent2.append(t), send_detail_message=lambda c, t, *a, **k: sent2.append(t),
           side_long=g4['side_long'], save_session=lambda c: None, time=time, _BTC_CANDLE_BLOCK_PREFIX='⛔ کندل BTC', _BTC_FRONT_PREFIX=PFX,
           execute_manual_trade=lambda *a, **k: (False, f'{PFX}: بیتکوین (BTC) به سطح مقاومتی نزدیک است'))
exec(src[a5:b5], gp2)
gp2['check_pending_orders'](1); assert len(SP['pending_orders']) == 1 and len(sent2) == 1 and 'منتظر' in sent2[0]
gp2['check_pending_orders'](1); assert len(SP['pending_orders']) == 1 and len(sent2) == 1

# ---------------------------------------------------------------- ۹) ریست آمار و موجودی ----------
import tempfile, json as _json
a6 = src.index("def _reset_start_balance("); b6 = src.index("def analyze(chat_id,symbol):")
tmpd = tempfile.mkdtemp(); jpath = os.path.join(tmpd, 'trade_journal.json')
_json.dump({'version': 1, 'trades': [{'chat_id': 1, 'trade_id': 'a'}, {'chat_id': 2, 'trade_id': 'b'}, {'chat_id': 1, 'trade_id': 'c'}]}, open(jpath, 'w'))
SR = {}
def fresh(mode='PAPER', **kw):
    SR.clear()
    SR.update({'trading_mode': mode, 'paper_balance': 742.5, 'paper_start_balance': 5000.0, 'paper_positions': [],
               'closed_positions': [{'pnl_usdt': 3, 'is_real': mode == 'REAL'}] * 4, 'trade_audit': [1], 'trade_pipeline_audit': [1], 'assist_log': [1],
               'scan_stats': {'scans': 9, 'symbols': 9, 'signals': 9, 'entries': 9, 'blocked': 9, 'data_errors': 9, 'reason_counts': {'x': 1}},
               'platform_fee_total_usdt': 4.2, 'platform_fee_trade_count': 3, 'daily_stopped': True, 'daily_start_equity': 700.0,
               'fav_wait': {'f1': {'status': 'waiting'}, 'f2': {'status': 'opened'}, 'f3': {'status': 'expired'}},
               'touch_wait': {'t1': {'status': 'waiting'}, 't2': {'status': 'entered_manual'}}, 'strategy_config': {'keep': 1}})
    SR.update(kw)
gr = dict(os=os, json=_json, time=time, math=math, logger=log, get_session=lambda c: SR, save_session=lambda c: None,
          exchange_balance=lambda c: 321.0, default_session=lambda: {'paper_balance': 1000.0},
          _journal_path=lambda: jpath, _JOURNAL_LOCK=threading.RLock(),
          closed_for_mode=lambda s, real=None: [p for p in s.get('closed_positions', []) if bool(p.get('is_real')) == bool(real)])
exec(src[a6:b6], gr)
rs, rp = gr['reset_stats'], gr['reset_stats_prompt_text']
fresh(); p = rp(1); assert '5000.00' in p and 'اولیه' in p and 'پوزیشن باز' in p
ok, msg = rs(1)
assert ok and SR['paper_balance'] == 5000.0 and SR['paper_start_balance'] == 5000.0 and SR['daily_start_equity'] == 5000.0 and SR['daily_stopped'] is False, SR
assert SR['closed_positions'] == [] and SR['trade_audit'] == [] and SR['trade_pipeline_audit'] == [] and SR['assist_log'] == []
assert SR['scan_stats'] == {'scans': 0, 'symbols': 0, 'signals': 0, 'entries': 0, 'blocked': 0, 'data_errors': 0, 'reason_counts': {}}
assert SR['platform_fee_total_usdt'] == 0.0 and SR['platform_fee_trade_count'] == 0
assert set(SR['fav_wait']) == {'f1'} and set(SR['touch_wait']) == {'t1'} and SR['strategy_config'] == {'keep': 1}      # در حال انتظارها و تنظیمات می‌مانند
assert '5000.00' in msg and '`4`' in msg and '`2` رکورد' in msg, msg
left = _json.load(open(jpath))['trades']; assert [x['trade_id'] for x in left] == ['b']                  # فقط ژورنال همین چت برداشته شد
baks = [f for f in os.listdir(tmpd) if '.reset-1-' in f]; assert len(baks) == 1
assert [x['trade_id'] for x in _json.load(open(os.path.join(tmpd, baks[0])))['trades']] == ['a', 'c']       # پشتیبان کامل، نه حذف
# پوزیشن باز: ریست انجام نمی‌شود و چیزی تغییر نمی‌کند
fresh(paper_positions=[{'symbol': 'X'}]); ok, msg = rs(1)
assert not ok and SR['paper_balance'] == 742.5 and len(SR['closed_positions']) == 4
# موجودی اولیه ثبت‌نشده (سشن قدیمی): پیش‌فرض ۱۰۰۰ و در پیام مشخص است
fresh(paper_start_balance=None); assert 'ثبت نشده' in rp(1); ok, msg = rs(1)
assert ok and SR['paper_balance'] == 1000.0 and 'پیش‌فرض' in msg
# حساب واقعی: موجودی صرافی دست نمی‌خورد، فقط آمار پاک و مبنای ریسک از صرافی
fresh(mode='REAL'); assert 'صرافی' in rp(1); ok, msg = rs(1)
assert ok and SR['paper_balance'] == 742.5 and SR['daily_start_equity'] == 321.0 and SR['closed_positions'] == []
# ثبت موجودی اولیه از منو و دکمه
assert "s['paper_start_balance']=v" in src and "'paper_start_balance': None" in src
assert 'reset_stats_prompt_text(chat_id)' in src and 'ریست آمار و موجودی' in open(os.path.join(HERE, 'ui.py'), encoding='utf-8').read()

print('ALL OK')

# ---------------------------------------------------------------- ۹) V3.44.54: سمت درست سطح (کلوز بسته‌شده‌ی BTC نسبت به نزدیک‌ترین سطح) ----------
SC0 = {'btc_front_min_atr': 0, 'btc_chop_flips': 0}
def fake_levels(up, down):
    # up/down: فاصله‌ی سطح بالا/پایین از ورودی (None = نبود)
    def f(df, entry, is_long, grid=None, cfg=None):
        out = []
        if is_long and up is not None: out.append((entry + up, 'سطح بالا'))
        if (not is_long) and down is not None: out.append((entry - down, 'سطح پایین'))
        return out
    return f

def side_env(up, down):
    g9 = dict(g); g9['_quick_opposing_levels'] = fake_levels(up, down); exec(HELPERS, g9)
    g9['_quick_opposing_levels'] = fake_levels(up, down)     # exec بالا نام را روی تابع واقعی برنمی‌گرداند؛ برای اطمینان دوباره تنظیم می‌شود
    g9['_BTC_FRONT_CACHE'].clear(); g9['_BTC_FRONT_WARNED'].clear()
    return g9

# سناریوی تصویر: کلوز 82,021.62 ، سطح پایین 81,859 (۱۶۲.۶۲ پایین‌تر) ، سطح بالا 82,822.92 (۸۰۱.۳ بالاتر) => BTC بالای نزدیک‌ترین سطح
g9 = side_env(up=801.30, down=162.62); sv, si9 = g9['btc_front_level_verdict'], g9['btc_front_level_info']
ok, t, i9 = sv(S(sc=SC0), '5min', 'SELL')
assert not ok and i9['side_ok'] is False and i9['ref_above'] is False, (ok, t, i9)                    # فروش وقتی BTC بالای سطح بسته: به هیچ عنوان
assert t.startswith(PFX) and 'بالای سطح' in t and 'با فروش نمی‌خواند' in t and 'زیر سطح ببندد' in t and 'رد نمی‌شود' in t, t
ok, t, i9 = sv(S(sc=SC0), '5min', 'BUY')
assert ok and t == '' and i9['side_ok'] is True, (ok, t, i9)                                          # خرید همین‌جا مجاز است
# حتی وقتی آستانه‌ی فاصله صفر است (فاصله مانع نیست) فروش بسته می‌ماند؛ اولویت با سمت سطح است
assert not sv(S(sc=SC0), '5min', 'SELL')[0]
# وارونه: نزدیک‌ترین سطح بالای کلوز => BTC پایین سطح بسته => خرید بسته، فروش مجاز
g9 = side_env(up=40.0, down=700.0); sv = g9['btc_front_level_verdict']
ok, t, i9 = sv(S(sc=SC0), '5min', 'BUY')
assert not ok and i9['ref_above'] is True and 'زیر سطح' in t and 'با خرید نمی‌خواند' in t and 'بالای سطح ببندد' in t, t
assert sv(S(sc=SC0), '5min', 'SELL')[0]
# فقط یک سطح، پایین کلوز: فروش بسته، خرید باز ؛ فقط یک سطح، بالای کلوز: برعکس
g9 = side_env(up=None, down=100.0); sv = g9['btc_front_level_verdict']
assert not sv(S(sc=SC0), '5min', 'SELL')[0] and sv(S(sc=SC0), '5min', 'BUY')[0]
g9 = side_env(up=100.0, down=None); sv = g9['btc_front_level_verdict']
assert not sv(S(sc=SC0), '5min', 'BUY')[0] and sv(S(sc=SC0), '5min', 'SELL')[0]
# هیچ سطحی نیست: مانعی نیست (مثل قبل)
g9 = side_env(up=None, down=None); sv = g9['btc_front_level_verdict']
assert sv(S(sc={'btc_chop_flips': 0}), '5min', 'SELL')[0] and sv(S(sc={'btc_chop_flips': 0}), '5min', 'BUY')[0]
# سمت درست ولی فاصله‌ی نامعقول: همان پیام فاصله می‌آید (رفتار قبلی)
g9 = side_env(up=40.0, down=700.0); sv = g9['btc_front_level_verdict']
ok, t, _i = sv(S(sc={'btc_front_min_atr': 1e6, 'btc_chop_flips': 0}), '5min', 'SELL'); assert not ok and 'سطح حمایتی نزدیک است' in t, t
# هشدار ورود: یک‌بار برای هر سطح مرجع در سمت نادرست، با جهت درست در متن
g9 = side_env(up=801.30, down=162.62); st['sent'].clear()
G9 = g9['_btc_front_gate']; sent9 = []
g9['send_message'] = g9['send_detail_message'] = lambda c, t, *a, **k: sent9.append((c, t))
for _ in range(3):
    ok, t = G9(5, S(sc=SC0), 'XYZ', 'SELL', '5min'); assert not ok
assert len(sent9) == 1 and 'فروش' in sent9[0][1] and 'XYZ' in sent9[0][1], sent9
assert G9(5, S(sc=SC0), 'XYZ', 'BUY', '5min') == (True, '')
# معاملات معکوس: سیگنال خرید => معامله‌ی فروش => سمت سطح برای فروش سنجیده می‌شود
ok, t = G9(5, S(sc=SC0, gate_inverse_trading_enabled=True), 'INV', 'BUY', '5min'); assert not ok and 'با فروش نمی‌خواند' in t, t
# فراخوانان دیگر info (محافظ BTC) فقط به front_price/dist_atr نگاه می‌کنند و دست‌نخورده‌اند
i_guard = g9['btc_front_level_info'](S(sc={'btc_chop_flips': 0}), '5min', True); assert i_guard['front_price'] is None or i_guard['front_price'] > i_guard['close']
print('side-of-level OK')


# ---------------------------------------------------------------- ۱۰) V3.44.55: BTC در حالت نامشخص (کلاف دور سطح) ----------
L = 82000.0
def lvl_abs(df, entry, is_long, grid=None, cfg=None):
    # یک سطح مطلق L؛ فقط در سمتی که «روبه‌روی» جهت است برمی‌گردد (مثل تابع واقعی)
    return [(L, 'سطح آزمایشی')] if ((is_long and L > entry) or ((not is_long) and L < entry)) else []

def mk_closes(closes_tail, base_noise=6.0, n=650):
    """n-کندل آرام و دور از سطح (۸۱۵۰۰)، سپس closes_tail به‌عنوان کلوزهای کندل‌های بسته‌شده؛ آخر یک کندل در حال تشکیل."""
    now = time.time(); start = int(now // SECS) * SECS
    ts = [(start - (n - 1 - i) * SECS) * 1000 for i in range(n)]
    rng = np.random.default_rng(3)
    cl = list(81500.0 + rng.normal(0, base_noise, n - len(closes_tail) - 1)) + list(closes_tail) + [closes_tail[-1]]
    rows = []
    for i, c in enumerate(cl):
        o = cl[i - 1] if i else c
        rows.append({'timestamp': ts[i], 'open': o, 'high': max(o, c) + 15, 'low': min(o, c) - 15, 'close': c, 'volume': 10.0})
    return pd.DataFrame(rows)

def chop_env(closes_tail):
    g10 = dict(g); st['df'] = mk_closes(closes_tail); exec(HELPERS, g10)
    g10['_quick_opposing_levels'] = lvl_abs
    g10['_BTC_FRONT_CACHE'].clear(); g10['_BTC_FRONT_WARNED'].clear()
    return g10

# سناریوی تصویر دوم: ۱۶ کلوز که مدام دور سطح بالا و پایین می‌روند (رد و برگشت ≥ ۳) ⇒ خرید و فروش هر دو بسته
choppy = [L + d for d in (-60, 70, -40, 55, -70, 40, -50, 60, 45, -55, 50, -65, 60, -45, 35, -40)]
g10 = chop_env(choppy); cv = g10['btc_front_level_verdict']
S0 = S(sc={'btc_front_min_atr': 0})
for sig in ('BUY', 'SELL'):
    ok, t, i10 = cv(S0, '5min', sig)
    assert not ok and i10['chop'] and i10['chop_flips'] >= 3 and i10['chop_window'] >= 12, (sig, ok, t, i10)
    assert t.startswith(PFX) and 'حالت نامشخص' in t and 'رد نمی‌شود' in t and 'رد و برگشت' in t, t
# کلید بستن: btc_chop_flips=0 ⇒ فیلتر کلاف خاموش (فقط چک‌های قبلی)
g10['_BTC_FRONT_CACHE'].clear()
i_off = g10['btc_front_level_info'](S(sc={'btc_front_min_atr': 0, 'btc_chop_flips': 0}), '5min', False); assert i_off['chop'] is False
# بعد از کلاف، شکست قطعی: ۳ کلوز پشت‌سرهم زیر سطح و ≥ ۰٫۵ATR فاصله ⇒ کلاف حساب نمی‌شود؛ فروش مجاز (BTC زیر سطح)، خرید همچنان با «سمت سطح» بسته
broke = choppy[:-3] + [L - 250, L - 300, L - 320]
g10 = chop_env(broke); cv = g10['btc_front_level_verdict']
ok, t, i10 = cv(S0, '5min', 'SELL'); assert ok and not i10['chop'] and i10['chop_flips'] >= 3, (ok, t, i10)
ok, t, i10 = cv(S0, '5min', 'BUY'); assert not ok and not i10['chop'] and 'با خرید نمی‌خواند' in t, t
# شکست ناقص: ۳ کلوز یک طرف ولی خیلی نزدیک سطح (< ۰٫۵ATR) ⇒ هنوز کلاف
tight = choppy[:-3] + [L - 4, L - 6, L - 5]
g10 = chop_env(tight); i10 = g10['btc_front_level_info'](S0, '5min', False); assert i10['chop'] and i10['chop_flips'] >= 3, i10
# بازار تمیز: فقط یک عبور از سطح (شکست) یا اصلاً عبوری نیست ⇒ کلاف نیست
clean = [L + 300] * 5 + [L - 200, L - 260, L - 300, L - 320, L - 350, L - 360, L - 380, L - 400, L - 420, L - 430, L - 440]
g10 = chop_env(clean); i10 = g10['btc_front_level_info'](S0, '5min', False); assert not i10['chop'] and i10['chop_flips'] == 1, i10
# هشدار کلاف: یک‌بار برای هر سطح/جهت (پیام تکراری نمی‌سازد)
g10 = chop_env(choppy); sent10 = []; g10['send_message'] = g10['send_detail_message'] = lambda c, t, *a, **k: sent10.append((c, t))
G10 = g10['_btc_front_gate']
for _ in range(3):
    ok, t = G10(9, S(sc={'btc_front_min_atr': 0}, gate_btc_front_level_enabled=True), 'KLF', 'BUY', '5min'); assert not ok
assert len(sent10) == 1 and 'حالت نامشخص' in sent10[0][1] and 'KLF' in sent10[0][1], sent10

# ---------------------------------------------------------------- ۱۱) کلید مستقل «BTC کلاف» (gate_btc_chop_enabled) ----------
i = src.index("'gate_btc_chop_enabled': ("); assert "True, 'entry_rules'" in src[i:i + 260]       # پیش‌فرض روشن، صفحه‌ی «شرایط ورود»
g10 = chop_env(choppy); cv = g10['btc_front_level_verdict']
for sig in ('BUY', 'SELL'):
    ok, t, _i = cv(S0, '5min', sig, front=False, chop=True);  assert not ok and 'حالت نامشخص' in t, (sig, t)      # فقط کلید کلاف روشن: کلاف را می‌بندد
    ok, t, _i = cv(S0, '5min', sig, front=True, chop=False);  assert 'حالت نامشخص' not in t, (sig, t)               # فقط کلید سطح روشن: کلاف دیده نمی‌شود
    assert cv(S0, '5min', sig, front=False, chop=False)[0] is True                                                   # هر دو خاموش در خود تابع: مانعی نیست
# فقط کلید کلاف روشن، بازار تمیز و سمت اشتباه: چک «سمت سطح» اعمال نمی‌شود؛ با هر دو روشن همان خرید بسته می‌شود
g10 = chop_env(clean); cv = g10['btc_front_level_verdict']
assert cv(S0, '5min', 'BUY', front=False, chop=True)[0] is True
ok, t, _i = cv(S0, '5min', 'BUY', front=True, chop=True); assert not ok and 'با خرید نمی‌خواند' in t, t
# فقط کلید سطح روشن در یک بازار کلاف: چک کلاف اعمال نمی‌شود (جهتِ مجاز ورود دارد)
g10 = chop_env(choppy[:-1] + [L - 300]); cv = g10['btc_front_level_verdict']
assert cv(S0, '5min', 'SELL', front=True, chop=False)[0] is True
# پیش‌بررسی همه‌ی مسیرها: کلیدها مستقل‌اند و پرچم درست به گیت می‌رسد
rec5 = []
g5 = dict(g4); g5['_btc_front_gate'] = lambda *a, **k: (rec5.append((k.get('front'), k.get('chop'))) or (True, ''))
exec(src[a3:b3], g5); g5['_btc_front_gate'] = lambda *a, **k: (rec5.append((k.get('front'), k.get('chop'))) or (True, ''))
pc = g5['_btc_front_precheck']; cfg_keep = SX['cfg']
for cfg_, want in (({'gate_btc_chop_enabled': True}, [(False, True)]), ({'gate_btc_front_level_enabled': True}, [(True, False)]),
                   ({'gate_btc_front_level_enabled': True, 'gate_btc_chop_enabled': True}, [(True, True)]), ({}, [])):
    SX['cfg'] = cfg_; rec5.clear()
    assert pc(1, 'AAA', 'BUY (Long)', 100.0, 98.0, 110.0, False, True) is True and rec5 == want, (cfg_, rec5)
SX['cfg'] = cfg_keep
print('independent chop toggle OK')
print('btc_front_level_selftest: ALL OK')
