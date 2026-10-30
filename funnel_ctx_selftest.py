"""تست زمینه‌ی جدید قیف (V3.44.107): settings/cfg، رژیم نماد و بازار در touch، ورود تأخیریِ فرضی (touch_d1/d2)،
نگه‌داشتن‌های صف، هم‌زمانی پوزیشن‌ها و کارمزد در trade_close. اجرا: python3 funnel_ctx_selftest.py"""
import sys, types, os, tempfile, json, time, glob
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try:
        __import__(name)
    except Exception:
        sys.modules[name] = types.ModuleType(name)
_tmp = tempfile.mkdtemp()
os.environ.update({'TELEGRAM_TOKEN': '123:abc', 'ADMIN_CHAT_IDS': '111', 'BOT_DB_PATH': os.path.join(_tmp, 'bot.sqlite3'),
                   'PRESETS_CUSTOM_PATH': os.path.join(_tmp, 'presets_custom.json'), 'FUNNEL_DIR': os.path.join(_tmp, 'funnel'),
                   'TELEGRAM_SKIP_BACKLOG': 'true'})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
import pandas as pd
bot = importlib.import_module('bot')
import funnel_log
bot.init_db()
P = bot.presets_mod

bot.send_message = lambda chat_id, text, markup=None, *a, **k: True
bot.edit_page = lambda *a, **k: True
bot._touch_update_card = lambda *a, **k: None
bot._fav_update_card = lambda *a, **k: None

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

def events(kind=None):
    out = []
    for p in sorted(glob.glob(os.path.join(os.environ['FUNNEL_DIR'], 'funnel_*.jsonl'))):
        for line in open(p, encoding='utf-8'):
            e = json.loads(line)
            if kind is None or e['kind'] == kind:
                out.append(e)
    return out

# ---- stub های داده (بدون شبکه)
bot._symbol_active_tf_regime = lambda sym, tf: 'BULLISH'
bot._symbol_h4_regime = lambda sym: 'BEARISH'
bot._symbol_tf_regimes = lambda sym: {'5min': 'BULLISH', '15min': 'RANGE'}
bot._trend_snapshot_cached = lambda sym, tf: {'score': -1, 'adx': 22.54, 'rsi': 45.12, 'atr_pct': 0.3512, 'volume_ratio': 1.234}
def fake_klines(sym, tf, n=160):
    closes = [100.0 + i * 0.1 for i in range(max(n, 30))]
    return pd.DataFrame({'timestamp': [1.7e9 + i * 3600 for i in range(len(closes))], 'open': closes, 'high': closes, 'low': closes, 'close': closes, 'volume': [1.0] * len(closes)})
bot.get_klines = fake_klines
bot.latest_price = lambda sym: 100.0
bot.exchange_latest_price = lambda cid, sym: 100.0
bot._touch_votes = lambda symbol, tf, reason, keys, ind_df=None, cfg=None: [{'key': k, 'label': k, 'vote': 'SELL', 'detail': ''} for k in bot._TOUCH_KEYS if k in keys]

ADMIN = 111
s = bot.get_session(ADMIN)
P.apply_preset(s, '3')
s['fav_confirm_enabled'] = True
s['is_bot_active'] = True
plan = {'entry': 100.0, 'sl': 101.0, 'tp': 97.0, 'rr': 3.0, 'score': 80, 'quality_label': 'A'}
bot._touch_register(ADMIN, 'AAA', 'SELL', 'reason HVL=100 [SETUP Daily]', '15min', plan)

# ---- ۱) settings + cfg
st = events('settings'); tv = events('touch')
check("رکورد settings نوشته شد", len(st) >= 1 and st[0].get('cfg') and st[0].get('gates_on') and st[0]['v'] == bot.BOT_VERSION, st[:1])
check("هش cfg در touch همان هش settings است", tv and tv[0].get('cfg') == st[-1]['cfg'], (tv[0].get('cfg'), st[-1]['cfg']))
check("settings شامل کلیدهای مهم (۵$ و صف)", 'profit_autoclose_enabled' in st[0]['tog'] and 'fav_confirm_enabled' in st[0]['tog'], list(st[0]['tog'])[:5])
n0 = len(events('settings'))
bot._fn_cfg(ADMIN, s)
check("بدون تغییر، settings دوباره نوشته نمی‌شود", len(events('settings')) == n0)
bot._FN_CFG_CACHE.clear()
s.setdefault('strategy_config', {})['gate_cooldown_enabled'] = not bot.gate_on(s, 'gate_cooldown_enabled')   # مقدار گیت‌ها در strategy_config است
h_new = bot._fn_cfg(ADMIN, s)
check("تغییر یک کلید → هش و رکورد settings جدید", h_new != st[-1]['cfg'] and len(events('settings')) == n0 + 1, (h_new, st[-1]['cfg']))

# ---- ۲) رژیم نماد و بازار در touch
t0 = tv[0]
check("sctx رژیم نماد (مستقل از کلید) ثبت شد", t0.get('sctx') and t0['sctx']['reg'] == 'B' and t0['sctx']['h4'] == 'S' and t0['sctx']['tfr'] == {'5min': 'B', '15min': 'R'}, t0.get('sctx'))
check("sctx شامل ADX/RSI/ATR٪/حجم", t0['sctx']['adx'] == 22.5 and t0['sctx']['rsi'] == 45.1 and t0['sctx']['atr_pct'] == 0.351 and t0['sctx']['vol_ratio'] == 1.23, t0['sctx'])
check("mkt شامل BTC/ETH و تغییرات", t0.get('mkt') and t0['mkt'].get('btc_reg') == 'S' and 'btc_c4h' in t0['mkt'] and 'eth_c24h' in t0['mkt'], t0.get('mkt'))

# ---- ۳) سایه‌های تأخیری ثبت شدند
sks = sorted({x['sk'] for x in funnel_log._SHADOW if x['tid'] == t0['tid']})
check("سایه‌ی touch و touch_d1 و touch_d2 ثبت شد", {'touch', 'touch_d1', 'touch_d2'} <= set(sks), sks)

# ---- ۴) حل سایه‌ی تأخیری روی کندل‌های ساختگی
TF = 900
base = (int(time.time()) // TF) * TF - 8 * 3600          # کندل برخورد: ۸ ساعت قبل
def mk(rows):
    return pd.DataFrame({'timestamp': [base + i * TF for i in range(len(rows))], 'open': [r[0] for r in rows], 'high': [r[1] for r in rows],
                         'low': [r[2] for r in rows], 'close': [r[3] for r in rows], 'volume': [1.0] * len(rows)})
# SELL: ورود طرح ۱۰۰، SL=101، TP=97. کندل ۰ (برخورد) کلوز ۹۹.۸؛ کندل ۱ کلوز ۹۹.۵؛ کندل ۲ به TP می‌رسد
rows = [(100, 100.4, 99.7, 99.8), (99.8, 100.0, 99.4, 99.5), (99.5, 99.6, 96.8, 97.0)] + [(97, 97.2, 96.9, 97.0)] * 40
funnel_log._SHADOW[:] = []
for sk, dl in (('touch_d1', 0), ('touch_d2', 1)):
    funnel_log.shadow_register('T-OK', sk, {'chat': 1}, 'AAA', 'SELL', 100.0, 101.0, 97.0, '15min', TF, start_ts=base + 300, delay=dl)
# void: کلوز کندل برخورد بالاتر از SL
funnel_log.shadow_register('T-VOID', 'touch_d1', {'chat': 1}, 'BBB', 'SELL', 100.0, 101.0, 97.0, '15min', TF, start_ts=base + 300, delay=0)
for x in funnel_log._SHADOW:
    x['due'] = 0
rows_void = [(100, 101.6, 99.9, 101.5)] + [(101.5, 101.6, 101.4, 101.5)] * 40
dfs = {'AAA': mk(rows), 'BBB': mk(rows_void)}
n = funnel_log.shadow_run_once(lambda sym, tf, lim: dfs[sym])
sh = {(e['tid'], e['sk']): e for e in events('shadow')}
d1, d2, dv = sh.get(('T-OK', 'touch_d1')), sh.get(('T-OK', 'touch_d2')), sh.get(('T-VOID', 'touch_d1'))
check("هر سه سایه‌ی تأخیری حل شد", n == 3 and d1 and d2 and dv, n)
check("d1: ورود روی کلوز کندل برخورد (۹۹.۸) و TP رسید", d1 and abs(d1['entry'] - 99.8) < 1e-9 and d1['outcome'] == 'tp' and d1['plan_entry'] == 100.0, d1)
check("d1: shift_r = ‎-۰.۲ (فروش پایین‌تر از طرح = بدتر)", d1 and abs(d1['shift_r'] + 0.2) < 1e-6, d1 and d1.get('shift_r'))
check("d2: ورود روی کلوز کندل بعدی (۹۹.۵) و TP رسید", d2 and abs(d2['entry'] - 99.5) < 1e-9 and d2['outcome'] == 'tp' and d2['delay'] == 1, d2)
check("void: قیمت کلوز بالاتر از SL → outcome=void/beyond_sl", dv and dv['outcome'] == 'void' and dv['void'] == 'beyond_sl', dv)

# ---- ۵) نگه‌داشتن‌های صف + نوع لغو در fav_final
rec = {'id': 'F1', 'tid': 'F1', 'symbol': 'AAA', 'sig': 'SELL', 'tf': '15min', 'created_at': time.time() - 1500, 'status': 'confirmed',
       'why': 'front', 'confirmed_at': time.time(), 'eval_n': 5, 'last_x': 0.2, 'cancel_kind': 'live', 'cancel_r': -1.02}
bot._fn_hold_tick(rec, 'front', 'کلاف دور سطح BTC')
bot._fn_hold_tick(rec, 'front', 'کلاف دور سطح BTC')
bot._fn_hold_tick(rec, 'btc')
check("کلاف از فاصله‌ی سطح تفکیک شد", set(rec['hold_ticks'].keys()) == {'chop', 'btc'} and rec['hold_ticks']['chop']['n'] == 2, rec['hold_ticks'])
try:
    bot._fn_fav_final(ADMIN, rec, 'cancelled')
except Exception as e:
    check("fav_final بدون خطا", False, repr(e))
ff = events('fav_final')
last = ff[-1] if ff else {}
check("fav_final: hold_ticks/نوع لغو/R لغو/تاخیر تایید", last.get('hold_ticks', {}).get('chop', [0])[0] == 2 and last.get('cancel_kind') == 'live' and last.get('cancel_r') == -1.02
      and last.get('confirm_delay_min') is not None and last.get('hold_delay_min') is not None, last)

# ---- ۶) هم‌زمانی در ورود و کارمزد در بسته شدن
s['paper_positions'] = [{'trade_id': 'A', 'side': 'BUY'}, {'trade_id': 'B', 'side': 'SELL'}, {'trade_id': 'C', 'side': 'SELL'}, {'trade_id': 'NEW', 'side': 'SELL'}]
bot._fn_trade_event(ADMIN, 'NEW', 'position_opened', {'symbol': 'AAA', 'side': 'SELL', 'entry_price': 100.0, 'sl': 101.0, 'tp': 97.0, 'planned_rr': 3.0, 'entry_reason': 'x'})
en = events('entry')[-1]
check("entry: ۳ پوزیشن دیگر (۲ هم‌جهت، ۱ مخالف)", en.get('open_other') == 3 and en.get('open_same_dir') == 2 and en.get('open_opp_dir') == 1 and en.get('mkt'), en)
s['closed_positions'] = [{'trade_id': 'NEW', 'symbol': 'AAA', 'side': 'SELL', 'realized_r': -1.0, 'fee_usdt': 0.31, 'platform_fee_usdt': 0.05, 'pnl_gross_usdt': -5.2,
                          'pnl_before_platform_fee_usdt': -5.5, 'risk_usdt': 5.0, 'margin': 50.0, 'leverage': 10, 'opened_at': 1.7e9}]
bot._fn_trade_event(ADMIN, 'NEW', 'position_closed', {'pnl_usdt': -5.55, 'reason': 'SL', 'duration_seconds': 600})
tc = events('trade_close')[-1]
check("trade_close: کارمزد و ناخالص", tc.get('fee_usdt') == 0.31 and tc.get('pnl_gross_usdt') == -5.2 and tc.get('platform_fee_usdt') == 0.05 and tc.get('leverage') == 10, tc)

# ---- ۷) خاموش کردن با FUNNEL_CTX=0 تصمیم‌ها را عوض نمی‌کند
bot._FN_CTX_ON = False
check("با FUNNEL_CTX=0 زمینه None است", bot._fn_symbol_ctx('ZZZ', '15min') is None and bot._fn_market_ctx('15min') is None)
bot._FN_CTX_ON = True

print("\nALL PASS" if ok else "\nSOME FAILED")
sys.exit(0 if ok else 1)
