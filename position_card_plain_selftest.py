"""V3.44.62: کارت پوزیشن برای کاربر عادی ساده است (بدون ستاپ/سطح/سناریو/هم‌جهتی/هشدار)، ادمین کارت کامل می‌گیرد.
اجرا: python3 position_card_plain_selftest.py"""
import sys, types, os, tempfile
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try: __import__(name)
    except Exception: sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ['TELEGRAM_TOKEN'] = '123:abc'; os.environ['ADMIN_CHAT_IDS'] = '111'
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3'); os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib, numpy as np, pandas as pd
bot = importlib.import_module('bot'); bot.init_db()

sent = []
bot.send_photo = lambda chat_id, png, caption, markup=None, keep=False, **k: sent.append((chat_id, caption)) or True
bot.save_session = lambda *a, **k: None

n = 120
idx = pd.date_range('2026-10-23', periods=n, freq='15min')
base = 7.6 + np.cumsum(np.random.RandomState(1).randn(n)) * 0.01
df = pd.DataFrame({'open': base, 'high': base + 0.03, 'low': base - 0.03, 'close': base + 0.005, 'volume': 1000.0}, index=idx)
df['timestamp'] = idx
try:
    df = bot.calculate_indicators(df)
except Exception:
    pass
trade = {'symbol': 'INJ', 'side': 'SELL', 'timeframe': '15min', 'entry_price': 7.5635, 'tp': 7.2, 'sl': 7.746,
         'margin': 20.0, 'leverage': 10, 'is_real': False,
         'entry_reason': '[SETUP Halving] HVL=7.6078|SCN=4', 'amount': 50.0, 'tp_level_name': 'قبل از سطح نصف‌کردن عمق 7 (7.19516)',
         'market_adx_at_entry': 23.2, 'symbol_adx_at_entry': 21.6, 'timeframe_bull_pct_at_entry': 0, 'timeframe_bear_pct_at_entry': 100,
         'entry_warnings': ['BTC خلاف جهت']}
USER, ADMIN = 222, 111
sent.clear(); bot.chart(USER, 'INJ', df, dict(trade)); assert sent, 'user card not sent'
u = sent[0][1]
sent.clear(); bot.chart(ADMIN, 'INJ', df, dict(trade)); assert sent, 'admin card not sent'
a = sent[0][1]
print('--- USER ---\n' + u + '\n--- ADMIN ---\n' + a)
for bad in ('ستاپ', 'SETUP', 'سطح:', 'سناریو', 'سطح هدف', 'هم‌جهتی', 'هشدار'):
    assert bad not in u, ('leak to user', bad)
for need in ('نماد', 'تایم‌فریم', 'ورود', 'حد سود', 'حد ضرر', 'نسبت پاداش به ریسک'):
    assert need in u, ('missing for user', need)
for need in ('SETUP', 'سناریو', 'سطح هدف', 'هم‌جهتی', 'هشدار'):
    assert need in a, ('admin lost', need)
print('POSITION CARD PLAIN OK')
