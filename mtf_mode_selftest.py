"""تست مستقل «حالت چندتایم‌فریمی» (۱س سطح/واکنش ← ۱۵د ورود): python mtf_mode_selftest.py
داده‌ی ساختگی: سقف/کف 200/100، ATR مؤثر ۲ (درخت ۱ ساعته) => عمق ۳ و سطوح 100، 112.5، 125، 137.5 ...
کندل ۱ ساعته‌ی واکنش: سایه‌ی بلند زیر ۱۲۵ و کلوز ۱۲۷٫۲؛ بعدش اولین کندل ۱۵ دقیقه‌ی صعودی."""
import numpy as np
import pandas as pd
import strategy as st
from strategy import (calculate_indicators, strategy_halving_mtf, get_signal_with_reason, _mtf_entry_trigger,
                      _compute_prev_day_levels, build_trade_plan, _halving_atr, _hv_detect_cell)

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

rng = np.random.default_rng(11)
T0 = pd.Timestamp('2026-10-30 00:00', tz='UTC')          # ابتدای یک ساعت کامل
N_HOURS_BEFORE = 24 * 8


def build(trigger_bull=True, with_trigger=True):
    rows = []
    def add(t, o, h, l, c):
        rows.append([t.value // 10**6, o, h, l, c, 100.0 + rng.random()])
    # ساعت‌های قبل: نوسان آرام دور ۱۲۸٫۵
    t = T0
    for q in range(N_HOURS_BEFORE * 4 - 4):
        c = 128.5 + rng.normal(0, 0.35)
        add(t, c, c + 0.3, c - 0.3, c); t += pd.Timedelta(minutes=15)
    # یک ساعت انتقال به ۱۲۷
    for q in range(4):
        a, b = 128.5 - 0.375 * q, 128.5 - 0.375 * (q + 1)
        add(t, a, a + 0.2, b - 0.2, b); t += pd.Timedelta(minutes=15)
    react_hour_start = t
    # ساعت واکنش (۴ کندل ۱۵ دقیقه): سایه به ۱۲۴٫۷ زیر سطح ۱۲۵ و برگشت به ۱۲۶٫۵
    add(t, 126.0, 126.2, 124.7, 125.6); t += pd.Timedelta(minutes=15)
    add(t, 125.6, 126.5, 125.3, 126.4); t += pd.Timedelta(minutes=15)
    add(t, 126.4, 127.0, 126.1, 126.2); t += pd.Timedelta(minutes=15)
    add(t, 126.2, 126.7, 126.1, 126.5); t += pd.Timedelta(minutes=15)
    trig_start = t
    if with_trigger:
        if trigger_bull:
            add(t, 126.5, 127.2, 126.4, 127.1)      # کندل ورود: صعودی با بدنه‌ی خوب
        else:
            add(t, 126.9, 127.0, 126.1, 126.2)      # کندل ورود: نزولی
        t += pd.Timedelta(minutes=15)
    add(t, rows[-1][4], rows[-1][4] + 0.1, rows[-1][4] - 0.1, rows[-1][4])      # کندل در حال تشکیل ۱۵ دقیقه
    df15 = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    # تجمیع به ۱ ساعته (آخرین ردیف = ساعت در حال تشکیل)
    x = df15.copy()
    x['h'] = (x['timestamp'] // 3_600_000) * 3_600_000
    g = x.groupby('h').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
                           close=('close', 'last'), volume=('volume', 'sum')).reset_index().rename(columns={'h': 'timestamp'})
    return calculate_indicators(df15), calculate_indicators(g[['timestamp', 'open', 'high', 'low', 'close', 'volume']])


CFG = {'halving_model_enabled': True, 'halving_high': 200.0, 'halving_low': 100.0, 'halving_k_atr': 4.0,
       'halving_min_depth': 3, 'halving_max_depth': 12, 'halving_atr_override': 2.0, 'halving_depth_freeze': False,
       'mtf_mode_enabled': True, 'gate_pd_level_enabled': False}

# ---- ۱) override ATR و کلید قفل عمق
d15, d1 = build()
dd, _a, _b = _compute_prev_day_levels(d15)
check("override ATR مقدار داده‌شده را برمی‌گرداند", abs(_halving_atr(dd, len(dd) - 2, CFG) - 2.0) < 1e-9)
check("بدون override از خود کندل‌ها حساب می‌شود", _halving_atr(dd, len(dd) - 2, {}) != 2.0)
ctx = st._halving_context(dd, len(dd) - 2, st._halving_cfg(CFG))
check("درخت ۱ ساعته: عمق ۳ و فاصله‌ی سطوح ۱۲٫۵", ctx['depth'] == 3 and abs(ctx['step'] - 12.5) < 1e-9, f"depth={ctx['depth']} step={ctx['step']}")
prices = sorted(x['price'] for x in ctx['levels'])
check("سطح ۱۲۵ در درخت هست", any(abs(p - 125.0) < 1e-9 for p in prices), str(prices))

# ---- ۲) واکنش ۱ ساعته + تأیید ۱۵ دقیقه => BUY
sig, reason = strategy_halving_mtf(d15, d1, CFG, live_price=127.1)
print("   →", sig, (reason or '')[:160])
check("واکنش ۱ ساعته + کندل ۱۵د صعودی = BUY", sig == 'BUY' and 'MTF=1H' in reason, reason[:120] if reason else reason)
check("برچسب ستاپ Halving در reason", '[SETUP Halving]' in (reason or ''))

# ---- ۳) از مسیر get_signal_with_reason
s2, r2 = get_signal_with_reason(d15, {'1h': d1}, 'single', '15min', 'dynamic', None, CFG, None, live_price=127.1)
check("get_signal_with_reason حالت چندتایم‌فریمی را صدا می‌زند", s2 == 'BUY' and 'MTF=1H' in (r2 or ''))
s3, r3 = get_signal_with_reason(d15, None, 'single', '15min', 'dynamic', None, CFG, None, live_price=127.1)
check("بدون داده‌ی ۱ ساعته سیگنال نمی‌دهد", s3 is None and '۱ ساعته' in (r3 or ''), r3)
s4, r4 = get_signal_with_reason(d15, {'1h': d1}, 'single', '1hour', 'dynamic', None, CFG, None, live_price=127.1)
check("روی تایم‌فریم غیر از ۱۵ دقیقه حالت چندتایم‌فریمی اعمال نمی‌شود", 'MTF=1H' not in (r4 or ''))

# ---- ۴) کندل ورود نزولی => سیگنال نمی‌دهد
d15b, d1b = build(trigger_bull=False)
sb, rb = strategy_halving_mtf(d15b, d1b, CFG, live_price=126.2)
check("کندل ۱۵د نزولی = ورود تأیید نمی‌شود", sb is None and 'تأیید نشد' in (rb or ''), rb)

# ---- ۵) هنوز کندل ۱۵د بعد از واکنش کامل نشده
d15c, d1c = build(with_trigger=False)
sc, rc = strategy_halving_mtf(d15c, d1c, CFG, live_price=126.5)
check("قبل از کامل‌شدن اولین کندل ۱۵د بعد از واکنش، ورود نیست", sc is None, rc)

# ---- ۶) پلن: هدف از سطح ۱ ساعته (۱۳۷٫۵) و SL پشت سوینگ ۸ کندل اخیر
plan, why = build_trade_plan(d15, 'BUY', CFG, 'liquidity_sweep', strategy_timeframe='15min', live_price=127.1)
print("   plan:", None if not plan else {k: plan[k] for k in ('entry', 'sl', 'tp', 'rr')}, why if not plan else '')
check("پلن ساخته شد", plan is not None, why)
if plan:
    check("TP = سطح بعدی درخت ۱ ساعته (۱۳۷٫۵)", abs(plan['tp'] - 137.5) < 1e-6, str(plan['tp']))
    check("SL پشت سایه‌ی ناحیه‌ی واکنش (زیر ۱۲۴٫۷)", plan['sl'] < 124.7, str(plan['sl']))
    cfg_off = {**CFG, 'mtf_mode_enabled': False}
    p2, _w2 = build_trade_plan(d15, 'BUY', cfg_off, 'liquidity_sweep', strategy_timeframe='15min', live_price=127.1)
    check("بدون حالت چندتایم‌فریمی SL فقط پشت خود کندل آخر است (بالاتر از ۱۲۵)", (p2 is None) or p2['sl'] > 125.0, str(None if not p2 else p2['sl']))


# ---- ۸) ورود با ۵ دقیقه (سطوح و واکنش همچنان از ۱ ساعته)
def split5(df15):
    rows = []
    for r in df15[['timestamp', 'open', 'high', 'low', 'close', 'volume']].itertuples(index=False):
        t, o, h, l, c, v = r
        m1, m2 = o + (c - o) / 3.0, o + 2.0 * (c - o) / 3.0
        pts = [(o, m1), (m1, m2), (m2, c)]
        for k, (a, b) in enumerate(pts):
            hi = h if k == 1 else max(a, b)
            lo = l if k == 0 else min(a, b)
            rows.append([t + k * 300_000, a, hi, lo, b, v / 3.0])
    return pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

raw15 = d15[['timestamp', 'open', 'high', 'low', 'close', 'volume']].iloc[:-1]       # بدون کندل در حال تشکیل
r5 = split5(raw15)
# اولین کندل ۵ دقیقه‌ی بعد از ساعت واکنش بسته شده و یک کندل ۵ دقیقه‌ی در حال تشکیل بعدش
last_trig = r5.iloc[-3:]            # سه کندل ۵ دقیقه‌ی کندل ورود
r5_cut = r5.iloc[:-2]               # فقط اولین کندل ۵ دقیقه‌ی ورود بسته‌شده + یکی در حال تشکیل
forming = r5_cut.iloc[-1:].copy(); forming['timestamp'] += 300_000
d5 = calculate_indicators(pd.concat([r5_cut, forming], ignore_index=True))
CFG5 = {**CFG}
s5, rs5 = strategy_halving_mtf(d5, d1, CFG5, live_price=float(r5_cut['close'].iloc[-1]))
print("   →", s5, (rs5 or '')[:150])
check("ورود با کندل ۵ دقیقه: BUY با همان واکنش ۱ ساعته", s5 == 'BUY' and 'کلوز 5 دقیقه' in (rs5 or ''), rs5)
s6, r6 = get_signal_with_reason(d5, {'1h': d1}, 'single', '5min', 'dynamic', None, CFG5, None, live_price=float(r5_cut['close'].iloc[-1]))
check("get_signal_with_reason روی تایم‌فریم ۵ دقیقه هم حالت چندتایم‌فریمی را اعمال می‌کند", s6 == 'BUY' and 'MTF=1H' in (r6 or ''))
pl5, w5 = build_trade_plan(d5, 'BUY', CFG5, 'liquidity_sweep', strategy_timeframe='5min', live_price=float(r5_cut['close'].iloc[-1]))
check("پلن ۵ دقیقه: TP سطح ۱ ساعته و SL پشت سوینگ ۲ ساعت", pl5 is not None and abs(pl5['tp'] - 137.5) < 1e-6 and pl5['sl'] < 124.7, str(pl5 and (pl5['sl'], pl5['tp'])) + ' ' + str(w5))

# ---- ۷) سمت bot / UI / دسترسی
import sys, types
for _m in ('aiohttp','ccxt','dotenv','matplotlib','matplotlib.pyplot','matplotlib.dates','requests'):
    if _m not in sys.modules:
        try:
            __import__(_m)
        except ImportError:
            sys.modules[_m] = types.ModuleType(_m)
try:
    import bot
    import ui
    s = {'timeframe': '1hour', 'strategy_config': {**st.get_timeframe_preset('1hour'), 'gate_h4_tier_enabled': False, 'halving_model_enabled': True}}
    bot._mtf_set(1, s, True)
    c = s['strategy_config']
    check("روشن‌کردن از تایم‌فریم غیرمجاز: ورود پیش‌فرض ۱۵ دقیقه + رتبه‌ی نرم ۴س خاموش", s['timeframe'] == '15min' and c['mtf_mode_enabled'] and not c['gate_h4_tier_enabled'])
    check("k و عمق از تایم‌فریم ۱ ساعته", bot._halving_eff_tf(c, '15min') == '1hour' and c['halving_k_atr'] == bot.HALVING_TF_DEFAULTS['1hour']['halving_k_atr'])
    bot._halving_tf_store({**c}, '15min')
    bot._mtf_set(1, s, False)
    c = s['strategy_config']
    check("خاموش‌کردن: رتبه‌ی نرم به حالت قبلی برمی‌گردد", c['mtf_mode_enabled'] is False and c['gate_h4_tier_enabled'] is False)
    s5s = {'timeframe': '15min', 'strategy_config': {**st.get_timeframe_preset('15min'), 'gate_h4_tier_enabled': False, 'halving_model_enabled': True}}
    bot._mtf_set(1, s5s, True, entry_tf='5min')
    check("ورود ۵ دقیقه: تایم‌فریم جلسه ۵ دقیقه و k/عمق ۱ ساعته", s5s['timeframe'] == '5min' and s5s['strategy_config']['mtf_mode_enabled'] and bot._halving_eff_tf(s5s['strategy_config'], '5min') == '1hour')
    bot._mtf_set(1, s5s, True, entry_tf='15min')
    check("تعویض به ۱۵ دقیقه، حالت روشن می‌ماند و رتبه‌ی نرم خاموش", s5s['timeframe'] == '15min' and s5s['strategy_config']['mtf_mode_enabled'] and not s5s['strategy_config']['gate_h4_tier_enabled'])
    bot._mtf_set(1, s5s, False)
    check("خاموش‌کردن بعد از تعویض: رتبه‌ی نرم به حالت اول", s5s['strategy_config']['gate_h4_tier_enabled'] is False)
    kb = ui.get_timeframe_keyboard('15min', True)
    texts = [(b['text'], b['callback_data']) for r in kb['inline_keyboard'] for b in r]
    check("کیبورد ویزارد گزینه‌ی چندتایم‌فریمی دارد و تیک روی همان است", any(cb == '/set_tf_mtf' and t.startswith('✅') for t, cb in texts)
          and not any(cb == '/set_tf_15m' and t.startswith('✅') for t, cb in texts))
    kb5 = ui.get_timeframe_keyboard('5min', True)
    t5 = [(b['text'], b['callback_data']) for r in kb5['inline_keyboard'] for b in r]
    check("کیبورد ویزارد: گزینه‌ی ورود ۵ دقیقه تیک می‌خورد", any(cb == '/set_tf_mtf5' and t.startswith('✅') for t, cb in t5) and not any(cb == '/set_tf_mtf' and t.startswith('✅') for t, cb in t5))
    kb3 = ui.get_setup_management_keyboard({'timeframe': '5min', 'strategy_config': {'halving_model_enabled': True, 'mtf_mode_enabled': True}})
    check("منوی ستاپ: دکمه‌ی تعویض تایم‌فریم ورود", any(b['callback_data'] == '/toggle_mtf_entry_tf' for r in kb3['inline_keyboard'] for b in r))
    kb2 = ui.get_setup_management_keyboard({'strategy_config': {'halving_model_enabled': True, 'mtf_mode_enabled': True}})
    check("منوی ستاپ دکمه‌ی روشن/خاموش چندتایم‌فریمی دارد", any(b['callback_data'] == '/toggle_mtf_mode' for r in kb2['inline_keyboard'] for b in r))
    import access_policy, re
    pats = [p for p in access_policy._USER_PATTERNS]
    check("کاربر عادی می‌تواند در ویزارد گزینه‌ی چندتایم‌فریمی را بزند", any(p.match('/set_tf_mtf') for p in pats))
    check("تاگل منوی ستاپ فقط برای ادمین است", not any(p.match('/toggle_mtf_mode') or p.match('/toggle_mtf_entry_tf') for p in pats))
    check("کاربر عادی گزینه‌ی ویزارد ۵ دقیقه را هم می‌تواند بزند", any(p.match('/set_tf_mtf5') for p in pats))
except ImportError as e:
    print("SKIP bot-level checks (import error):", e)

print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
