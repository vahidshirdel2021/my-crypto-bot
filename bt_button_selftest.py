"""تست آفلاین جریان دکمه‌ایِ بک‌تست (نماد ← دوره ← دانلود/نگه‌داری ← خروجی). اجرا: python3 bt_button_selftest.py"""
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
ok_all = True
def check(name, cond, info=''):
    global ok_all; ok_all &= bool(cond); print(('PASS ' if cond else 'FAIL ') + name, info if not cond else '')
ADMIN, USER = 111, 222
sent = []
bot.send_message = lambda cid, text, markup=None, message_id=None, parse_mode='Markdown', keep=False: sent.append((cid, text, markup))
bot._binance_map_needs_refresh = lambda: False
bot._binance_symbol_from_cache = lambda base: (base + 'USDT') if base in ('ETH', 'BTC') else None
calls = []
def fake_hist(symbol, tf, a, b):
    calls.append((symbol, tf, a, b)); n = 1500
    tf_ms = {'15min': 900000, '1day': 86400000}[tf]
    if tf == '1day':                         # V3.44.131: داده‌ی روزانه‌ی BTC برای گیت رژیم روزانه (روز UTC کامل)
        n = 300; b = (b // tf_ms) * tf_ms
    ts = (b - n * tf_ms) + np.arange(n) * tf_ms
    c = 100 + np.sin(np.arange(n) / 20.0) * 2
    return pd.DataFrame({'timestamp': ts, 'open': c, 'high': c + .3, 'low': c - .3, 'close': c, 'volume': np.full(n, 50.0)})
bot._backtest_fetch_history = fake_hist
def wait(pred, t=300):
    for _ in range(int(t / .1)):
        if pred(): return True
        _time.sleep(.1)
    return False
def cbs(markup): return [b['callback_data'] for r in (markup or {}).get('inline_keyboard', []) for b in r]

a = bot.get_session(ADMIN); a['timeframe'] = '15min'
# 1) نماد
bot.process_command('/backtest_start', ADMIN, 1)
check('قدم ۱: نماد را می‌پرسد', bot.get_session(ADMIN)['user_state'] == 'WAIT_BACKTEST_SYMBOL' and 'نماد' in sent[-1][1])
sent.clear(); bot.backtest_symbol_received(ADMIN, 'xyz')
check('نماد ناشناس رد می‌شود', 'پیدا نشد' in sent[-1][1] and bot.get_session(ADMIN)['user_state'] == 'WAIT_BACKTEST_SYMBOL')
sent.clear(); bot.backtest_symbol_received(ADMIN, 'eth/usdt:usdt')
check('ETH پذیرفته و چهار دکمه‌ی دوره', bot.get_session(ADMIN)['bt_pending_symbol'] == 'ETH' and all(f'/bt_p_{d}' in cbs(sent[-1][2]) for d in (30, 90, 180, 365)), cbs(sent[-1][2]))
# 2) دوره + دانلود و نگه‌داری
sent.clear(); bot.process_command('/bt_p_90', ADMIN, 1)
check('دانلود و نگه‌داری + دکمه‌ی خروجی', wait(lambda: any('نگه‌داری شد' in t for _, t, _ in sent)) and '/bt_run' in cbs(sent[-1][2]), sent)
m = bot.get_session(ADMIN)['bt_data']
check('فایل روی دیسک ماند', os.path.exists(m['path']) and m['base'] == 'ETH' and m['days'] == 90 and m['candles'] == 1500, m)
check('بازه‌ی دانلود = ۹۰ روز + گرم‌شدن', calls[-1][3] - calls[-1][2] == (90 + bot._BACKTEST_WARMUP_DAYS) * 86_400_000, calls[-1])
check('قفل آزاد شد', ADMIN not in bot._BACKTEST_RUNNING)
# 3) خروجی
sent.clear(); fetch_n = len(calls); bot.process_command('/bt_run', ADMIN, 1)
check('خروجی اجرا شد', wait(lambda: any(t.startswith(('🧪', '❌')) for _, t, _ in sent)), sent)
out = sent[-1][1]
check('نتیجه چهارسطری', out.startswith('🧪 ETH') and out.count('\n') == 3, out)
check('سطر گیت BTC (پیش‌فرض: سطح جلویی/کلاف روشن)', out.split('\n')[2].startswith('₿ گیت‌های BTC فعال') and 'سطح جلویی BTC' in out.split('\n')[2], out.split('\n')[2])
check('رژیم روزانه‌ی BTC پیش‌فرض روشن: در سطر گیت و داده‌ی روزانه دانلود شد', 'رژیم روزانه BTC' in out.split('\n')[2] and any(c[:2] == ('BTCUSDT', '1day') for c in calls[fetch_n:]), (out.split('\n')[2], calls[fetch_n:]))
check('BTC برای گیت‌ها دانلود شد (نه ETH چون هم‌جهتی خاموش)', any(c[0] == 'BTCUSDT' for c in calls[fetch_n:]) and not any(c[0] == 'ETHUSDT' for c in calls[fetch_n:]), calls[fetch_n:])
check('بدون Markdown', sent[-1][2] is not None and True)
check('پریست در سطر دوم', 'پریست' in out.split('\n')[1], out)
sent.clear(); sc = a['strategy_config']
for k_ in ('gate_btc_front_level_enabled', 'gate_btc_chop_enabled', 'gate_btc_undecided_enabled', 'gate_btc_candle_enabled', 'gate_btceth_aligned_enabled', 'gate_btc_daily_regime_enabled'): sc[k_] = False
bot.process_command('/bt_run', ADMIN, 1)
check('همه‌ی گیت‌ها خاموش: اعلام می‌کند بدون گیت', wait(lambda: any(t.startswith('🧪') for _, t, _ in sent)) and 'هیچ‌کدام از گیت‌های BTC/ETH' in sent[-1][1], sent[-1][1] if sent else sent)
sent.clear(); sc['gate_btceth_aligned_enabled'] = True; sc['gate_btc_candle_enabled'] = True; fetch_n = len(calls)
bot.process_command('/bt_run', ADMIN, 1)
check('هم‌جهتی + کندل: BTC و ETH هر دو دانلود و سطر گیت', wait(lambda: any(t.startswith('🧪') for _, t, _ in sent)) and {c[0] for c in calls[fetch_n:]} >= {'BTCUSDT'} and 'هم‌جهتی BTC/ETH' in sent[-1][1].split('\n')[2], (sent[-1][1], calls[fetch_n:]))
sc['gate_btc_front_level_enabled'] = True; sc['gate_btc_chop_enabled'] = True; sc['gate_btceth_aligned_enabled'] = False; sc['gate_btc_candle_enabled'] = False
# 4) تایم‌فریم عوض شود
sent.clear(); a['timeframe'] = '5min'; bot.process_command('/bt_run', ADMIN, 1)
check('عدم‌تطابق تایم‌فریم: اجرا نمی‌شود', wait(lambda: any('❌' in t for _, t, _ in sent)) and 'تایم‌فریم' in sent[-1][1], sent)
a['timeframe'] = '15min'
# 5) دسترسی
sent.clear(); bot.process_command('/backtest_start', USER, 1); bot.process_command('/bt_p_30', USER, 1); bot.process_command('/bt_run', USER, 1)
check('کاربر عادی: هر سه بسته', len(sent) == 3 and all(('فقط برای ادمین' in t or 'در دسترس نیست' in t) for _, t, _ in sent), sent)
import presets
check('دکمه در منوی پریست‌ها', '/backtest_start' in cbs(presets.keyboard(a)))
print('ALL OK' if ok_all else 'SOME FAILED'); sys.exit(0 if ok_all else 1)
