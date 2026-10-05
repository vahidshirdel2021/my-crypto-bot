import sys, numpy as np, pandas as pd
sys.path.insert(0, '.')
import strategy as S

HI, LO = 100.0, 90.0
def mk(rows, atr=1.0):
    d = pd.DataFrame(rows, columns=['open','high','low','close'])
    d['atr'] = atr
    d['body_ratio'] = (d['close']-d['open']).abs()/(d['high']-d['low']).clip(lower=1e-9)
    d['volume_ratio'] = 1.0
    return d
def cfgx(**kw): return {**S.STRATEGY_DEFAULTS, **kw}
def F(d, c): return S._detect_failed_retest_reversal(d, len(d)-1, HI, LO, 'PDH','PDL','سقف','کف', 1.0, c)
def C(d, c): return S._detect_retest_continuation(d, len(d)-1, HI, LO, 'PDH','PDL','سقف','کف', 1.0, c)
def W(d, c): return S._detect_named_level_sweep(d, len(d)-1, HI, LO, 'PDH','PDL','سقف','کف', c, True, True)[:2]

inside = [(95,95.5,94.5,95)]*10
up_break = [(99.5,101.5,99.2,101.2)]
up_hold  = [(101.2,102,101,101.8)]*3
dn_break = [(90.5,90.8,88.5,88.8)]
dn_hold  = [(88.8,89,88,88.2)]*3
cfg = cfgx()
ok = lambda name, cond: (print(('PASS ' if cond else 'FAIL ') + name), cond)[1]
res = []

# --- ۶ حالت استاندارد ---
d = mk(inside + up_break + up_hold + [(101.0,101.2,98.8,99.0)]);  s = F(d, cfg)
res.append(ok('5: بعد از شکست رو به بالا + اولین کندل برگشت => SELL', s[0]=='SELL'))
res.append(ok('5: همان کندل «ادامه» نیست', C(d, cfg)[0] is None))
d = mk(inside + dn_break + dn_hold + [(89.0,91.2,88.8,91.0)]);    s = F(d, cfg)
res.append(ok('6: آینه => BUY', s[0]=='BUY'))
d = mk(inside + up_break + up_hold + [(100.3,101.2,99.9,101.0)]); s = C(d, cfg)
res.append(ok('3: شکست + پولبک نگه‌داشته + ادامه => BUY', s[0]=='BUY'))
res.append(ok('3: همان کندل «شکست کاذب» نیست', F(d, cfg)[0] is None))
d = mk(inside + dn_break + dn_hold + [(89.7,90.1,88.8,89.0)]);    s = C(d, cfg)
res.append(ok('4: آینه => SELL', s[0]=='SELL'))
d = mk(inside + [(99.2,100.5,98.9,99.1)]); s = W(d, cfg)
res.append(ok('1: فتیله از PDH رد شد و برگشت (ریکلیم) => SELL', s[0]=='SELL' and 'ریکلیم نزولی' in s[1]))
d = mk(inside + [(90.8,91.2,89.5,91.0)]); s = W(d, cfg)
res.append(ok('2: آینه => BUY', s[0]=='BUY'))

# --- «برخورد بدون نفوذ» (۱/۲ طبق تعریف) ---
d = mk(inside + [(99.4,99.95,98.8,99.0)]); s = W(d, cfg)
res.append(ok('1-touch: فتیله به ۰.۰۵ATR زیر PDH رسید + فتیله‌ی بلند => SELL', s[0]=='SELL' and 'بدون نفوذ' in s[1]))
res.append(ok('1-touch: با خاموش‌کردن scenario_touch_enabled => None', W(d, cfgx(scenario_touch_enabled=False))[0] is None))
d = mk(inside + [(99.8,99.95,98.5,98.6)]); res.append(ok('1-touch: فتیله‌ی کوتاه (ضعیف) => None', W(d, cfg)[0] is None))
d = mk(inside + [(90.6,91.2,90.05,91.0)]); s = W(d, cfg)
res.append(ok('2-touch: آینه => BUY', s[0]=='BUY' and 'بدون نفوذ' in s[1]))
d = mk(inside + [(97,97.5,96.5,97.2)]); res.append(ok('وسط رنج هیچ‌چیز صادر نمی‌شود', W(d,cfg)[0] is None and F(d,cfg)[0] is None and C(d,cfg)[0] is None))

# --- منفی‌ها / باگ‌های ثابت‌شده ---
rows = inside + up_break + [(101,101.2,98,98.5)] + [(98.5-0.1*k,98.7-0.1*k,98.0-0.1*k,98.2-0.1*k) for k in range(25)] + [(95.0,95.2,94.0,94.2)]
d = mk(rows)
res.append(ok('باگ: کندل نزولیِ ۵ATR دور از PDH دیگر «شکست کاذب» نیست', F(d, cfg)[0] is None))
res.append(ok('   (حالت قدیمی همان باگ را نشان می‌داد)', F(d, cfgx(scenario_precision_v2=False))[0]=='SELL'))
d = mk(inside + up_break + [(101,101.2,98,98.5)] + [(98.5,98.8,98.0,98.3)]*2 + [(98.3,98.4,97.3,97.5)])
res.append(ok('۵ فقط روی اولین کندل بازگشت (نه چند کندل بعد)', F(d, cfg)[0] is None))
d = mk(inside + up_break + [(101,101.2,98,98.5)] + [(99.8,101.0,99.5,100.8)])
res.append(ok('۳: اگر بین شکست و پولبک close داخل رنج بوده => ادامه نیست', C(d, cfg)[0] is None))
res.append(ok('   (حالت قدیمی اینجا BUY می‌داد)', C(d, cfgx(scenario_precision_v2=False))[0]=='BUY'))
d = mk(inside + [(100.0,100.15,99.0,100.05)] + [(100.05,100.3,98.6,99.0)])
res.append(ok('close فقط ۰.۰۵ATR بالای سطح، «نفوذ» حساب نمی‌شود => ۵ نیست', F(d, cfg)[0] is None))

# --- ماشین‌حالت: ۳ و ۵ هرگز هم‌زمان ---
for last in [(100.3,101.2,99.9,101.0), (101.0,101.2,98.8,99.0), (100.0,100.9,99.6,100.2)]:
    d = mk(inside + up_break + up_hold + [last])
    res.append(ok(f'انحصار ۳/۵ روی کندل close={last[3]}', not (C(d,cfg)[0] and F(d,cfg)[0])))

# --- تست کل پایپ‌لاین ---
def build(day2_rows, vols=None):
    step = 5*60*1000; t0 = int(pd.Timestamp('2026-01-01', tz='UTC').timestamp()*1000)
    rows = []
    rng = np.random.default_rng(1)
    for i in range(288):                       # روز اول: سقف دقیقاً 100 و کف دقیقاً 90
        c = 95 + 3*np.sin(i/20.0)
        rows.append([c-0.2, c+0.5, c-0.5, c+0.1, 100.0])
    rows[50][2] = 90.0; rows[50][1] = max(rows[50][1], 92)
    rows[120][1] = 100.0
    for i in range(110):                        # روز دوم: رنج آرام داخل
        c = 95 + 0.4*np.sin(i/5.0)
        rows.append([c-0.2, c+0.5, c-0.5, c+0.1, 100.0])
    for k, r in enumerate(day2_rows):
        v = (vols or {}).get(k, 100.0)
        rows.append([r[0], r[1], r[2], r[3], v])
    rows.append([rows[-1][3]]*4 + [100.0])      # کندل نیمه‌باز (نادیده گرفته می‌شود)
    df = pd.DataFrame(rows, columns=['open','high','low','close','volume'])
    df['timestamp'] = [t0 + i*step for i in range(len(df))]
    return S.calculate_indicators(df)

base = dict(daily_p4_mode=False, enabled_setup_tags=['Daily'], level_cluster_enabled=False, active_setup_enabled=False)
def run(day2_rows, vols=None, **kw):
    df = build(day2_rows, vols)
    sig, reason = S._strategy_liquidity_sweep_5m_impl(df, None, {**base, **kw}, None, '5min', True)
    return sig, S.extract_scenario_tag(reason), reason
pre = [(95.0,95.4,94.6,95.1)]*5
ev5 = pre + [(99.5,101.6,99.2,101.3)] + [(101.3,102.0,101.1,101.8)]*3 + [(101.2,101.3,98.6,98.9)]
sig, scn, _ = run(ev5);                        res.append(ok(f'پایپ‌لاین: ۵ => SELL/SCN=5 (got {sig}/{scn})', sig=='SELL' and scn=='5'))
# تاییدیه‌ی سخت‌گیرانه‌ی ۵/۶ که رد می‌شود: لگ شکست پرحجم، کندل برگشت کم‌حجم و بدنه‌ضعیف
ev5w = pre + [(99.5,101.6,99.2,101.3)] + [(101.3,102.0,101.1,101.8)]*3 + [(100.1,101.3,98.2,99.9)]
vols = {5: 900.0, 9: 90.0}
sig, scn, r = run(ev5w, vols, confirm_fakeout_enabled=True)
res.append(ok(f'پایپ‌لاین: ۵ ردشده با تاییدیه، از در پشتی ۱ نمی‌شود (got {sig}/{scn})', sig is None or scn != '1'))
sig_l, scn_l, _ = run(ev5w, vols, confirm_fakeout_enabled=True, scenario_precision_v2=False)
res.append(ok(f'   (قدیمی: همان کندل SELL/SCN=1 صادر می‌کرد — got {sig_l}/{scn_l})', sig_l=='SELL' and scn_l=='1'))
ev1 = pre + [(95.0,95.4,94.6,95.1)]*3 + [(99.2,100.6,98.9,99.1)]
sig, scn, _ = run(ev1);                        res.append(ok(f'پایپ‌لاین: ۱ => SELL/SCN=1 (got {sig}/{scn})', sig=='SELL' and scn=='1'))
ev1t = pre + [(95.0,95.4,94.6,95.1)]*3 + [(99.5,99.96,99.3,99.4)]
sig, scn, r = run(ev1t);                       res.append(ok(f'پایپ‌لاین: ۱ برخورد-بدون-نفوذ => SELL/SCN=1 (got {sig}/{scn})', sig=='SELL' and scn=='1' and 'بدون نفوذ' in r))
ev3 = pre + [(99.5,101.6,99.2,101.3)] + [(101.3,102.0,101.1,101.8)]*3 + [(100.2,100.7,99.9,100.6)]
sig, scn, _ = run(ev3);                        res.append(ok(f'پایپ‌لاین: ۳ => BUY/SCN=3 (got {sig}/{scn})', sig=='BUY' and scn=='3'))
print('\n%d/%d passed' % (sum(res), len(res)))
sys.exit(0 if all(res) else 1)
