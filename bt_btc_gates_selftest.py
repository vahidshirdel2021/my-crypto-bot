"""تست آفلاین گیت‌های BTC بک‌تست. اجرا: python3 bt_btc_gates_selftest.py"""
import sys, types, os, tempfile, time as _time
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
_tmp = tempfile.mkdtemp()
os.environ.update({'TELEGRAM_TOKEN': '123:abc', 'ADMIN_CHAT_IDS': '111', 'BOT_DB_PATH': os.path.join(_tmp, 'bot.sqlite3'),
                   'PRESETS_CUSTOM_PATH': os.path.join(_tmp, 'presets_custom.json'), 'TELEGRAM_SKIP_BACKLOG': 'true',
                   'HALVING_RANGE_OVERRIDE': '{"ETHUSDT":[4953.0,80.0],"BTCUSDT":[126199.5,2817.15]}'})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib, numpy as np, pandas as pd
bot = importlib.import_module('bot'); bot.init_db()
import bt_btc_gates as G
ok_all = True
def check(name, cond, info=''):
    global ok_all; ok_all &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name, '' if cond else info)

TF = 900_000; N = 1400; T0 = 1767225600000
TS = T0 + np.arange(N) * TF
def mk(close, rng=0.3):
    c = np.asarray(close, float); o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({'timestamp': TS, 'open': o, 'high': np.maximum(o, c) + rng, 'low': np.minimum(o, c) - rng, 'close': c, 'volume': np.full(N, 100.0)})
up = mk(100 + np.arange(N) * 0.05)
down = mk(300 - np.arange(N) * 0.05)
K = 1000
TSK = int(TS[K])
H = lambda ql=None: {'calculate_indicators': bot.calculate_indicators, 'quick_levels': ql or bot._quick_opposing_levels,
     'with_halving_cfg': bot._with_halving_cfg, 'regime': bot.regime_from_ind_df, 'defaults': bot.STRATEGY_DEFAULTS,
     'front_min_atr': 1.0, 'chop': (3, 16, 3, 0.5), 'far_atr': 5.0, 'far_gap': 0.4, 'candle_min_body': 0.0}
def F(**k):
    d = {x: False for x in G.GATE_KEYS}; d.update(k); return d
cfg = {'halving_model_enabled': False}

# --- aligned
g = G.BtcGates(up, up, cfg, F(aligned=True), H())
check('aligned: هر دو صعودی -> BUY/SELL هر دو رد نمی‌شوند (جهت سنجیده نمی‌شود)', g.check(TSK, 'BUY')[0] and g.check(TSK, 'SELL')[0])
g = G.BtcGates(up, down, cfg, F(aligned=True), H())
check('aligned: ناهم‌جهت -> رد', g.check(TSK, 'BUY') == (False, 'aligned'))
g = G.BtcGates(up, None, cfg, F(aligned=True), H())
check('aligned: بدون داده‌ی ETH -> رد', g.check(TSK, 'BUY') == (False, 'aligned'))
# --- candle (بدنه‌ی آخرین کندل بسته‌شده)
g = G.BtcGates(up, None, cfg, F(candle=True), H())
check('candle: BTC صعودی: خرید آزاد، فروش بسته', g.check(TSK, 'BUY')[0] and g.check(TSK, 'SELL') == (False, 'candle'))
g = G.BtcGates(down, None, cfg, F(candle=True), H())
check('candle: BTC نزولی: فروش آزاد، خرید بسته', g.check(TSK, 'SELL')[0] and g.check(TSK, 'BUY') == (False, 'candle'))
# --- نبود داده
g = G.BtcGates(up, None, cfg, F(candle=True), H())
check('ts ناموجود -> nodata', g.check(TSK + 1, 'BUY') == (False, 'nodata'))
check('کندل آخرِ داده (بدون open بعدی) -> nodata', g.check(int(TS[-1]), 'BUY') == (False, 'nodata'))
# --- سطح جلویی با سطوح ساختگی
c0 = float(up['close'].iloc[K])
def ql_factory(levels):
    def ql(ind, entry, is_long, grid, cfg):
        return [(p, n) for p, n in levels if ((p > entry) if is_long else (p < entry))]
    return ql
atr = float(bot.calculate_indicators(up.iloc[:K + 2])['atr'].iloc[-2])
g = G.BtcGates(up, None, cfg, F(front=True), H(ql_factory([(c0 - 10 * atr, 'L')])))
check('front: BTC بالای سطح: خرید آزاد، فروش رد', g.check(TSK, 'BUY')[0] and g.check(TSK, 'SELL') == (False, 'front'))
g = G.BtcGates(up, None, cfg, F(front=True), H(ql_factory([(c0 + 0.3 * atr, 'L'), (c0 - 10 * atr, 'M')])))
check('front: سطح مقابل نزدیک (<1×ATR) -> خرید رد', g.check(TSK, 'BUY') == (False, 'front'))
g = G.BtcGates(up, None, cfg, F(front=True), H(ql_factory([(c0 + 3 * atr, 'U'), (c0 - 1.5 * atr, 'D')])))
check('front: BTC بالای نزدیک‌ترین سطح و سطح مقابل دور (۳×ATR) -> خرید آزاد', g.check(TSK, 'BUY')[0])
g = G.BtcGates(up, None, cfg, F(front=True), H(ql_factory([(c0 + 3 * atr, 'U'), (c0 - 10 * atr, 'D')])))
check('front: نزدیک‌ترین سطح بالای قیمت است -> خرید رد (سمت اشتباه سطح)', g.check(TSK, 'BUY') == (False, 'front'))
g = G.BtcGates(up, None, cfg, F(front=False, chop=False), H())
check('هیچ گیتی روشن نیست -> همیشه آزاد', g.check(TSK, 'BUY')[0])
# --- کلاف: کلوزها دور سطح رفت‌وبرگشت
osc = 100 + np.arange(N) * 0.0
osc = osc + np.where(np.arange(N) % 2 == 0, 0.4, -0.4)
osc_df = mk(osc, rng=0.1)
g = G.BtcGates(osc_df, None, cfg, F(chop=True), H(ql_factory([(100.0, 'L')])))
check('chop: رد و برگشت پیاپی -> رد', g.check(TSK, 'BUY') == (False, 'chop') and g.check(TSK, 'SELL') == (False, 'chop'))
g = G.BtcGates(up, None, cfg, F(chop=True), H(ql_factory([(c0 - 10 * atr, 'L')])))
check('chop: روند یک‌طرفه -> کلاف نیست', g.check(TSK, 'BUY')[0])
# --- بلاتکلیفی
g = G.BtcGates(up, None, cfg, F(undecided=True), H(ql_factory([(c0 + 40 * atr, 'U'), (c0 - 40 * atr, 'D')])))
check('undecided: وسط راهروی دو سطح دور -> هر دو جهت رد', g.check(TSK, 'BUY') == (False, 'undecided') and g.check(TSK, 'SELL') == (False, 'undecided'))
g = G.BtcGates(up, None, cfg, F(undecided=True), H(ql_factory([(c0 + 2 * atr, 'U'), (c0 - 40 * atr, 'D')])))
check('undecided: نزدیک یکی از سطوح -> آزاد', g.check(TSK, 'BUY')[0])
g = G.BtcGates(up, None, cfg, F(undecided=True), H(ql_factory([])))
check('undecided: بدون هیچ سطحی -> بسته', g.check(TSK, 'BUY') == (False, 'undecided'))
# --- بدون نشت آینده: تغییر داده‌ی بعد از کندل K+1 (و high/low/close خود K+1) نتیجه را عوض نمی‌کند
def verdicts(btc, eth):
    gg = G.BtcGates(btc, eth, cfg, F(aligned=True, candle=True, front=True, chop=True, undecided=True), H())
    return [gg.check(TSK, s) for s in ('BUY', 'SELL')]
base_v = verdicts(up, up)
fut = up.copy(); fut.loc[K + 1:, ['high', 'low', 'close']] = [999.0, 1.0, 500.0]
fut.loc[K + 2:, 'open'] = 777.0
check('بدون نشت آینده (BTC)', verdicts(fut, up) == base_v, (base_v, verdicts(fut, up)))
check('بدون نشت آینده (ETH)', verdicts(up, fut) == base_v)
# --- رژیم روزانه‌ی BTC (V3.44.131): خرید در رژیم نزولی رد، فروش در رژیم صعودی رد، رنج آزاد، نبود داده آزاد، بدون نشت آینده
DAY = G.DAY_MS; ND = 320; TD0 = T0 - 280 * DAY            # روزها هم‌تراز UTC؛ روز T0 هنوز در داده هست
TSD = TD0 + np.arange(ND) * DAY
def mkd(close, rng=0.5):
    c = np.asarray(close, float); o = np.concatenate([[c[0]], c[:-1]])
    return pd.DataFrame({'timestamp': TSD, 'open': o, 'high': np.maximum(o, c) + rng, 'low': np.minimum(o, c) - rng, 'close': c, 'volume': np.full(ND, 1000.0)})
d_up = mkd(100 + np.arange(ND) * 1.0)
d_dn = mkd(500 - np.arange(ND) * 1.0)
d_rg = mkd(300 + np.where(np.arange(ND) % 2 == 0, 0.6, -0.6) + np.sin(np.arange(ND) / 7.0) * 0.5, rng=0.2)
mk_g = lambda dd, **k: G.BtcGates(None, None, cfg, F(daily=True), H(), daily_df=dd, tf_ms=TF)
g = mk_g(d_up)
check('daily: رژیم صعودی -> فروش رد با تگ daily، خرید آزاد', g.check(TSK, 'SELL') == (False, 'daily') and g.check(TSK, 'BUY')[0], (g.check(TSK, 'SELL'), g.daily_regime(TSK + TF)))
g = mk_g(d_dn)
check('daily: رژیم نزولی -> خرید رد با تگ daily، فروش آزاد', g.check(TSK, 'BUY') == (False, 'daily') and g.check(TSK, 'SELL')[0], (g.check(TSK, 'BUY'), g.daily_regime(TSK + TF)))
g = mk_g(d_rg)
check('daily: رنج -> هر دو جهت آزاد', g.check(TSK, 'BUY')[0] and g.check(TSK, 'SELL')[0], g.daily_regime(TSK + TF))
check('daily: بدون داده‌ی روزانه -> آزاد (fail-open)', G.BtcGates(None, None, cfg, F(daily=True), H(), daily_df=None, tf_ms=TF).check(TSK, 'BUY')[0])
g = mk_g(d_up)
check('daily: ورود بعد از پایان داده (شکاف >۱ روز) -> آزاد', g.check(int(TSD[-1]) + 5 * DAY, 'SELL')[0])
check('daily: دادهٔ کمتر از ۶۰ کندل -> آزاد', mk_g(d_up.iloc[:50]).check(int(TSD[48]) + DAY + TF, 'SELL')[0])
# مرز روز: رژیم روز D با کندل بسته‌ی D-1 تعیین می‌شود؛ ورود دقیقاً در ۰۰:۰۰ UTC روز جدید از کندل روز قبل استفاده می‌کند
g = mk_g(d_up); kday = 200
e_mid = int(TSD[kday]) + 12 * 3_600_000
r_mid = g.daily_regime(e_mid); r_next0 = g.daily_regime(int(TSD[kday + 1]))
check('daily: وسط روز و ابتدای روز بعد هر دو از کندل بسته‌شده‌ی روز قبل', r_mid is not None and r_next0 is not None)
# بدون نشت آینده: عوض کردن کندل «امروز» و روزهای بعد رژیم را عوض نمی‌کند
fd = d_up.copy(); fd.loc[kday:, ['open', 'high', 'low', 'close']] = [1.0, 1.0, 1.0, 1.0]
a = mk_g(d_up).daily_regime(e_mid); b = mk_g(fd).daily_regime(e_mid)
check('daily: بدون نشت آینده (تغییر کندل امروز و بعد)', a == b, (a, b))
# تغییر کندل بسته‌شده‌ی دیروز واقعاً اثر دارد (سقوط دیروز -> دیگر صعودی نیست)
fy = d_up.copy(); fy.loc[kday - 1, ['open', 'high', 'low', 'close']] = [1.0, 1.0, 1.0, 1.0]
check('daily: به کندل بسته‌شده‌ی دیروز حساس است', a == 'BULLISH' and mk_g(fy).daily_regime(e_mid) != 'BULLISH', (a, mk_g(fy).daily_regime(e_mid)))
# هم‌ارزی با ربات زنده: رژیم بک‌تست == regime_from_ind_df(advanced=True) روی ۲۰۰ کندل روزانه‌ی منتهی به «امروز» (۱۹۹ بسته + ۱ در حال تشکیل)
rs = np.random.RandomState(7)
d_rw = mkd(300 + np.cumsum(rs.normal(0.0, 6.0, ND)) + np.sin(np.arange(ND) / 25.0) * 80, rng=3.0)
seen = set(); mism = []
for dfx in (d_up, d_dn, d_rg, d_rw):
    gx = mk_g(dfx)
    for kd in range(120, 300, 9):
        live_df = dfx.iloc[max(0, kd - 199):kd + 1].reset_index(drop=True)          # آخرین ردیف = امروز (در حال تشکیل)
        want = bot.regime_from_ind_df(bot.calculate_indicators(live_df), advanced=True)
        got = gx.daily_regime(int(TSD[kd]) + 6 * 3_600_000)
        seen.add(want)
        if want != got:
            mism.append((kd, want, got))
check('daily: هم‌ارز رژیم زنده (۴ سری × ۲۰ روز)', not mism, mism[:5])
check('daily: تست هم‌ارزی هر سه رژیم را پوشش داد', {'BULLISH', 'BEARISH', 'RANGE'} <= seen, seen)
# همراه با گیت‌های دیگر: daily اول سنجیده می‌شود و فقط وقتی روشن است اثر دارد
g = G.BtcGates(up, None, cfg, F(candle=True, daily=False), H(), daily_df=d_up, tf_ms=TF)
check('daily خاموش: داده‌ی روزانه نادیده گرفته می‌شود', g.check(TSK, 'BUY')[0])
check('daily در active وقتی روشن است', 'daily' in mk_g(d_up).active and 'daily' not in G.BtcGates(None, None, cfg, F(), H()).active)
# --- اتصال در bot.py: کلید رژیم روزانه روی سشن -> گیت ساخته می‌شود و داده‌ی روزانه‌ی BTC دانلود می‌شود
calls_h = []
def fake_fetch(sym, tf_, a_ms, b_ms):
    calls_h.append((sym, tf_)); return d_up.copy() if tf_ == '1day' else up.copy()
_orig_fetch = bot._backtest_fetch_history; bot._backtest_fetch_history = fake_fetch
try:
    S_on = {'strategy_config': {k: False for k in bot._BT_GATE_KEYS.values()}}
    S_on['strategy_config'][bot.BTC_DAILY_KEY] = True
    m_ = {'start_ms': int(TS[200]), 'end_ms': int(TS[N - 5]), 'warm_ms': 10 * DAY}
    check('bot: daily در _BT_GATE_KEYS و نام فارسی', bot._BT_GATE_KEYS.get('daily') == 'gate_btc_daily_regime_enabled' and 'daily' in bot._BT_GATE_FA)
    check('bot: پرچم‌ها فقط daily روشن', [k for k, v in bot._bt_gate_flags(S_on).items() if v] == ['daily'])
    gg = bot._bt_build_gates(S_on, {'halving_model_enabled': False}, '15min', 'ETH', up, m_)
    check('bot: گیت ساخته شد، فقط داده‌ی روزانه‌ی BTC دانلود شد', gg is not None and gg.active == ['daily'] and calls_h == [('BTCUSDT', '1day')], calls_h)
    check('bot: گیت ساخته‌شده نتیجه‌ی درست می‌دهد (صعودی: فروش رد)', gg.check(TSK, 'SELL') == (False, 'daily') and gg.check(TSK, 'BUY')[0])
    line_ = bot._bt_gate_line(gg, {'stats': {'gate_blocked': {'daily': 7}, 'signals': 20}})
    check('bot: خط خروجی گیت‌ها «رژیم روزانه BTC» را نشان می‌دهد', 'رژیم روزانه BTC' in line_ and 'رد شده: 7 از 20' in line_, line_)
    S_off = {'strategy_config': {k: False for k in bot._BT_GATE_KEYS.values()}}
    check('bot: همه خاموش -> بدون گیت', bot._bt_build_gates(S_off, {}, '15min', 'ETH', up, m_) is None)
    bot._backtest_fetch_history = lambda *a, **k: d_up.iloc[:30].copy()
    try:
        bot._bt_build_gates(S_on, {'halving_model_enabled': False}, '15min', 'ETH', up, m_); raised = False
    except RuntimeError:
        raised = True
    check('bot: داده‌ی روزانه‌ی ناکافی -> خطای صریح (نه اجرای بی‌صدا بدون گیت)', raised)
finally:
    bot._backtest_fetch_history = _orig_fetch
check('inbot_backtest: TF_MS شامل 1day', __import__('inbot_backtest').TF_MS.get('1day') == 86_400_000)
# --- ادغام با simulate: رد شدن‌ها شمرده می‌شوند و ورودی نمی‌سازند
import inbot_backtest as ib, strategy as st
calls = []
def fake_sig(primary, md, mode, tf, strat, filters, cfg_, regime, live_price=None):
    return ('BUY', 'fake') if int(primary.iloc[-2]['timestamp']) % (TF * 50) == 0 else (None, 'no')
ib.get_signal_with_reason = fake_sig
ib.build_trade_plan = lambda primary, sig, cfg_, st_, strategy_timeframe=None, grid_levels=None, live_price=None, **k: ({'entry': live_price, 'sl': live_price - 1, 'tp': live_price + 1}, 'fake')
flat = mk(np.full(N, 100.0))
r0 = ib.simulate(flat, cfg, {}, '15min', start_ms=int(TS[760]), end_ms=int(TS[N - 5]), trail_enabled=False)
gate_closed = lambda ts, sig: (False, 'chop')
r1 = ib.simulate(flat, cfg, {}, '15min', start_ms=int(TS[760]), end_ms=int(TS[N - 5]), trail_enabled=False, entry_gate=gate_closed)
check('simulate: بدون گیت معامله دارد', r0['trades'] > 0, r0['trades'])
check('simulate: گیت بسته -> صفر معامله و شمارش رد', r1['trades'] == 0 and r1['stats']['signals'] > 0 and r1['stats']['gate_blocked'].get('chop') == r1['stats']['signals'], r1['stats'])
check('simulate: گیتی که خطا بدهد = رد با nodata', ib.simulate(flat, cfg, {}, '15min', start_ms=int(TS[760]), end_ms=int(TS[N - 5]), trail_enabled=False, entry_gate=lambda a, b: 1 / 0)['stats']['gate_blocked'].get('nodata', 0) > 0)
print('ALL OK' if ok_all else 'SOME FAILED'); sys.exit(0 if ok_all else 1)
