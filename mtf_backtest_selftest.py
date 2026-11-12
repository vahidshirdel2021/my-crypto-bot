"""تست بک‌تست حالت چندتایم‌فریمی (inbot_backtest.simulate): python mtf_backtest_selftest.py
همان داده‌ی ساختگی mtf_mode_selftest: واکنش ۱ ساعته زیر سطح ۱۲۵ و اولین کندل ۱۵ دقیقه‌ی صعودیِ بعد از آن."""
import numpy as np
import pandas as pd
import strategy as st
import inbot_backtest as ibt

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

rng = np.random.default_rng(11)
T0 = pd.Timestamp('2026-10-30 00:00', tz='UTC')
rows = []
def add(t, o, h, l, c):
    rows.append([t.value // 10**6, o, h, l, c, 100.0 + rng.random()])
t = T0
for q in range(24 * 8 * 4 - 4):
    c = 128.5 + rng.normal(0, 0.35)
    add(t, c, c + 0.3, c - 0.3, c); t += pd.Timedelta(minutes=15)
for q in range(4):
    a, b = 128.5 - 0.375 * q, 128.5 - 0.375 * (q + 1)
    add(t, a, a + 0.2, b - 0.2, b); t += pd.Timedelta(minutes=15)
add(t, 126.0, 126.2, 124.7, 125.6); t += pd.Timedelta(minutes=15)
add(t, 125.6, 126.5, 125.3, 126.4); t += pd.Timedelta(minutes=15)
add(t, 126.4, 127.0, 126.1, 126.2); t += pd.Timedelta(minutes=15)
add(t, 126.2, 126.7, 126.1, 126.5); t += pd.Timedelta(minutes=15)
TRIG_TS = rows[-1][0] + 900_000
add(t, 126.5, 127.2, 126.4, 127.1); t += pd.Timedelta(minutes=15)       # کندل ورود (اندیس 772)
add(t, 127.1, 127.6, 127.0, 127.4)                                       # یک کندل بعدش تا مدیریت پوزیشن شروع شود
df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
TRIG_IDX = len(df) - 2

BASE = {'halving_model_enabled': True, 'halving_high': 200.0, 'halving_low': 100.0, 'halving_k_atr': 6.0,
        'halving_min_depth': 3, 'halving_max_depth': 12, 'halving_depth_freeze': False,
        'gate_pd_level_enabled': False}

# --- جاسوس: ببینیم موتور چه به استراتژی می‌دهد (بدون نشت آینده)
seen = []
_orig = ibt.get_signal_with_reason
def spy(primary, md, mode, tf, strat, filt, cfg, grid, live_price=None, **kw):
    seen.append((int(primary['timestamp'].iloc[-2]), md, cfg.get('halving_atr_override'), int(primary['timestamp'].iloc[-1])))
    return _orig(primary, md, mode, tf, strat, filt, cfg, grid, live_price=live_price, **kw)
ibt.get_signal_with_reason = spy

res = ibt.simulate(df, {**BASE, 'mtf_mode_enabled': True}, {}, '15min', margin=50.0, leverage=5.0, fee_pct=0.05,
                   trail_enabled=False)
print("   stats:", res['stats'], '| trades:', res['trades'])
check("حالت چندتایم‌فریمی در stats ثبت شد", res['stats'].get('mtf') is True)
check("حداقل یک گام اجرا شد", res['stats']['steps'] > 0 and len(seen) > 0)
# بدون نشت آینده
leak = 0; no_h1 = 0
for closed_ts, md, ov, forming_ts in seen:
    h1 = (md or {}).get('1h')
    if h1 is None:
        no_h1 += 1; continue
    last_closed_1h_end = int(h1['timestamp'].iloc[-2]) + 3_600_000
    if last_closed_1h_end > forming_ts:        # کندل ۱ ساعته‌ای که بعد از لحظه‌ی قدم بسته می‌شود نباید «بسته‌شده» باشد
        leak += 1
check("هیچ کندل ۱ ساعته‌ی آینده به‌عنوان بسته‌شده داده نمی‌شود", leak == 0 and no_h1 == 0, f"leak={leak} no_h1={no_h1}")
check("ATR ۱ ساعته (override) در هر قدم داده می‌شود و مثبت است", all((ov or 0) > 0 for _a, _b, ov, _c in seen))
# معامله‌ی مهندسی‌شده
tl = res['trade_list']
check("دقیقاً یک معامله‌ی خرید با ورود از کندل ۱۵ دقیقه‌ی بعد از واکنش ۱ ساعته", len(tl) == 1 and tl[0]['side'] == 'BUY'
      and tl[0]['open_ts'] == TRIG_TS + 900_000, str([(x['side'], x['open_ts'], x['reason'][:60]) for x in tl]))
if tl:
    check("دلیل سیگنال شامل واکنش ۱ ساعته است", 'واکنش کندل ۱ ساعته' in tl[0]['reason'], tl[0]['reason'][:90])
    check("SL پشت سایه‌ی ناحیه‌ی واکنش (زیر ۱۲۴٫۷)", tl[0]['sl'] < 124.7, str(tl[0]['sl']))

# --- همان داده بدون حالت چندتایم‌فریمی: مسیر قدیمی دست‌نخورده، معامله‌ی چندتایم‌فریمی تولید نمی‌شود
seen.clear()
res0 = ibt.simulate(df, {**BASE, 'mtf_mode_enabled': False}, {}, '15min', margin=50.0, leverage=5.0, fee_pct=0.05, trail_enabled=False)
check("خاموش: stats.mtf نادرست و هیچ md ۱ ساعته‌ای ساخته نمی‌شود", res0['stats'].get('mtf') is False and all(not (md or {}).get('1h') for _a, md, _o, _c in seen))
check("خاموش: هیچ معامله‌ای با برچسب واکنش ۱ ساعته نیست", all('واکنش کندل ۱ ساعته' not in x['reason'] for x in res0['trade_list']))

# --- ورود ۵ دقیقه: همان داده به کندل‌های ۵ دقیقه شکسته می‌شود
def split5(d):
    out = []
    for tt, o, h, l, c, v in d[['timestamp', 'open', 'high', 'low', 'close', 'volume']].itertuples(index=False):
        m1, m2 = o + (c - o) / 3.0, o + 2.0 * (c - o) / 3.0
        for k, (a, b) in enumerate([(o, m1), (m1, m2), (m2, c)]):
            out.append([tt + k * 300_000, a, h if k == 1 else max(a, b), l if k == 0 else min(a, b), b, v / 3.0])
    return pd.DataFrame(out, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
df5 = split5(df)
seen.clear()
res5 = ibt.simulate(df5, {**BASE, 'mtf_mode_enabled': True}, {}, '5min', margin=50.0, leverage=5.0, fee_pct=0.05, trail_enabled=False)
print("   5m stats:", res5['stats'], '| trades:', res5['trades'])
leak5 = sum(1 for _a, md, _o, ft in seen if (md or {}).get('1h') is not None and int(md['1h']['timestamp'].iloc[-2]) + 3_600_000 > ft)
check("۵ دقیقه: اجرا شد و نشت آینده ندارد", res5['stats']['steps'] > 0 and leak5 == 0, f"steps={res5['stats']['steps']} leak={leak5}")
check("۵ دقیقه: ورود با اولین کندل ۵ دقیقه‌ی بعد از واکنش (یا بعدش) و جهت خرید", all(x['side'] == 'BUY' and x['open_ts'] >= TRIG_TS for x in res5['trade_list']) and len(res5['trade_list']) >= 1,
      str([(x['side'], x['open_ts'] - TRIG_TS) for x in res5['trade_list']]))
ibt.get_signal_with_reason = _orig
print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
