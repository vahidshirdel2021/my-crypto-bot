"""تست یکپارچه‌ی حالت ۳ و ۴ (نفوذ + پولبک + ادامه) در مسیر چندتایم‌فریمی: python scn34_selftest.py  (V3.44.187)
داده‌ی ساختگی مثل mtf_mode_selftest: سقف/کف 200/100، ATR مؤثر ۲ => سطوح 100، 112.5، 125، 137.5 ...
سناریو ۳ (BUY): کندل ۱ساعته‌ی شکست بالای ۱۲۵ ← کندل ۱ساعته‌ی پولبک (کف نزدیک ۱۲۵، کلوز بالای آن، صعودی) ← کندل ۱۵د صعودی.
سناریو ۴ (SELL): آینه‌ی همان داده (p' = 300 - p) روی سطح ۱۷۵."""
import numpy as np
import pandas as pd
import strategy as st
from strategy import calculate_indicators, strategy_halving_mtf

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

rng = np.random.default_rng(5)
T0 = pd.Timestamp('2026-10-30 00:00', tz='UTC')
N_CALM_HOURS = 24 * 8


def build(mirror=False, with_fvg=True):
    rows = []
    t = [T0]
    def add(o, h, l, c):
        if mirror:
            o, h, l, c = 300 - o, 300 - l, 300 - h, 300 - c
        rows.append([t[0].value // 10**6, o, h, l, c, 100.0 + rng.random()])
        t[0] += pd.Timedelta(minutes=15)
    for _ in range(N_CALM_HOURS * 4):                  # روزهای آرام زیر ۱۲۵
        c = 123.3 + rng.normal(0, 0.2)
        add(c, c + 0.3, c - 0.3, c)
    # h0: ساعت آرام با سقف ۱۲۴٫۵
    add(123.8, 124.0, 123.7, 123.9); add(123.9, 124.2, 123.8, 124.1)
    add(124.1, 124.5 if with_fvg else 125.1, 124.0, 124.3); add(124.3, 124.4, 124.1, 124.2)
    # h1: شکست بالای ۱۲۵ (کلوز ساعت ۱۲۵٫۶)
    add(124.2, 124.8, 124.1 if with_fvg else 123.6, 124.7); add(124.7, 125.2, 124.6, 125.1)
    add(125.1, 125.5, 125.0, 125.4); add(125.4, 125.8, 125.3, 125.6)
    # h2: پولبک به ۱۲۵٫۰۵ و برگشت (کلوز ساعت ۱۲۵٫۸۵ > اوپن ۱۲۵٫۴۵) - کف h2 بالاتر از سقف h0 => FVG صعودی
    lo_pb = 125.05
    add(125.45, 125.6, lo_pb, 125.2); add(125.2, 125.4, lo_pb, 125.3)
    add(125.3, 125.7, 125.2, 125.6); add(125.6, 125.95, 125.5, 125.85)
    # کندل ورود ۱۵د (صعودی با بدنه‌ی خوب) + کندل در حال تشکیل
    add(125.85, 126.25, 125.8, 126.2)
    add(126.2, 126.3, 126.1, 126.2)
    df15 = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    x = df15.copy()
    x['h'] = (x['timestamp'] // 3_600_000) * 3_600_000
    g = x.groupby('h').agg(open=('open', 'first'), high=('high', 'max'), low=('low', 'min'),
                           close=('close', 'last'), volume=('volume', 'sum')).reset_index().rename(columns={'h': 'timestamp'})
    return calculate_indicators(df15), calculate_indicators(g[['timestamp', 'open', 'high', 'low', 'close', 'volume']])


BASE = {'halving_model_enabled': True, 'halving_high': 200.0, 'halving_low': 100.0, 'halving_k_atr': 4.0,
        'halving_min_depth': 3, 'halving_max_depth': 12, 'halving_atr_override': 2.0, 'halving_depth_freeze': False,
        'mtf_mode_enabled': True, 'gate_pd_level_enabled': False}

if __name__ == "__main__":
    for mirror, want, scn_no, lp in ((False, 'BUY', '3', 126.2), (True, 'SELL', '4', 300 - 126.2)):
        tag = f"حالت {scn_no} ({want})"
        d15, d1 = build(mirror=mirror, with_fvg=True)
        atr1 = float(d1['atr'].iloc[-2])
        print(f"   ATR ۱ساعته = {atr1:.3f}")
        # ۱) پیش‌فرض خود استراتژی: کلید روشن => سیگنال
        s, r = strategy_halving_mtf(d15, d1, {**BASE, 'fvg_enabled': False}, live_price=lp)
        print("   →", s, (r or '')[:200])
        check(f"{tag}: با پیش‌فرض جدید (کلید ادامه‌ی روند روشن) سیگنال می‌دهد", s == want and f'SCN={scn_no}' in (r or ''), r[:120] if r else r)
        # ۲) کلید خاموش (رفتار قدیمی) => سیگنال ۳/۴ نیست
        s0, r0 = strategy_halving_mtf(d15, d1, {**BASE, 'fvg_enabled': False, 'sweep_enable_retest_continuation': False}, live_price=lp)
        check(f"{tag}: با کلید خاموش (رفتار قدیمی) سناریو {scn_no} صادر نمی‌شود", f'SCN={scn_no}' not in (r0 or ''), r0)
        # ۳) FVG روشن و FVG سالم هست => سیگنال
        s1, r1 = strategy_halving_mtf(d15, d1, {**BASE, 'fvg_enabled': True}, live_price=lp)
        check(f"{tag}: FVG روشن + FVG سالم => سیگنال", s1 == want and f'SCN={scn_no}' in (r1 or ''), r1[:120] if r1 else r1)
        # ۴) FVG روشن و بدون FVG => رد با دلیل جدید در قیف
        d15n, d1n = build(mirror=mirror, with_fvg=False)
        s2, r2 = strategy_halving_mtf(d15n, d1n, {**BASE, 'fvg_enabled': True}, live_price=lp)
        check(f"{tag}: FVG روشن + بدون FVG => رد با دلیلِ «دیده شد ولی FVG سالم نبود»", s2 is None and 'FVG سالم نبود' in (r2 or ''), r2)
        # ۵) سوییچ مستقل هر سناریو هنوز کار می‌کند
        s3, r3 = strategy_halving_mtf(d15, d1, {**BASE, 'fvg_enabled': False, f'scenario_{scn_no}_enabled': False}, live_price=lp)
        check(f"{tag}: خاموش‌کردن scenario_{scn_no}_enabled جلوی سیگنال را می‌گیرد", f'SCN={scn_no}' not in (r3 or ''), r3)

    # ---- پیش‌فرض‌ها و مهاجرت یک‌باره (بات واقعی)
    import importlib, sys, types, os, tempfile
    for _n in ('aiohttp', 'ccxt', 'ccxt.async_support'):
        try:
            __import__(_n)
        except Exception:
            sys.modules[_n] = types.ModuleType(_n)
    _tmp = tempfile.mkdtemp()
    os.environ.update({'TELEGRAM_TOKEN': '123:abc', 'ADMIN_CHAT_IDS': '111', 'BOT_DB_PATH': os.path.join(_tmp, 'bot.sqlite3'),
                       'PRESETS_CUSTOM_PATH': os.path.join(_tmp, 'presets_custom.json'), 'FUNNEL_DIR': os.path.join(_tmp, 'funnel'),
                       'TELEGRAM_SKIP_BACKLOG': 'true'})
    import presets as P
    bot = importlib.import_module('bot')
    bot.init_db()
    check("پیش‌فرض استراتژی/پریست/منو برای کلید ادامه‌ی روند روشن است",
          st.STRATEGY_DEFAULTS['sweep_enable_retest_continuation'] is True and P.BASE_CFG['sweep_enable_retest_continuation'] is True
          and bot.GATE_REGISTRY['sweep_enable_retest_continuation'][1] is True)
    check("نشست جدید: کلید ادامه‌ی روند روشن",
          bot.default_session()['strategy_config'].get('sweep_enable_retest_continuation') is True)
    old_ss = {'strategy_config': {'sweep_enable_retest_continuation': False}}
    bot._migrate_retest_cont_v187(old_ss)
    check("مهاجرت: مقدار خاموشِ قدیمیِ نشست ذخیره‌شده یک‌بار روشن می‌شود",
          old_ss['strategy_config']['sweep_enable_retest_continuation'] is True and old_ss.get('retest_cont_default_v187') is True)
    old_ss['strategy_config']['sweep_enable_retest_continuation'] = False       # انتخاب دستیِ بعدی کاربر
    bot._migrate_retest_cont_v187(old_ss)
    check("مهاجرت: بار دوم انتخاب دستی را دست نمی‌زند", old_ss['strategy_config']['sweep_enable_retest_continuation'] is False)

    print("\nALL PASS" if ok else "\nSOME FAILED")
    raise SystemExit(0 if ok else 1)
