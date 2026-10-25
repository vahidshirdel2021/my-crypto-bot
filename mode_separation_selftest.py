"""V3.44.65: جداسازی گزارش‌های حساب کاغذی و واقعی. اجرا: python3 mode_separation_selftest.py"""
import sys, types, os, tempfile, time
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try:
        __import__(name)
    except Exception:
        sys.modules[name] = types.ModuleType(name)
if not hasattr(sys.modules['aiohttp'], 'ClientSession'):
    sys.modules['aiohttp'].ClientTimeout = lambda **k: None
    sys.modules['aiohttp'].TCPConnector = lambda **k: None
    sys.modules['aiohttp'].ClientSession = object
os.environ['TELEGRAM_TOKEN'] = '123:abc'
os.environ['ADMIN_CHAT_IDS'] = '111'
td = tempfile.mkdtemp()
os.environ['BOT_DB_PATH'] = os.path.join(td, 'bot.sqlite3')
os.environ['TRADE_JOURNAL_PATH'] = os.path.join(td, 'journal.json')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot'); bot.init_db()

CID = 222
s = bot.get_session(CID)
now = time.time()
def mk(real, pnl, sym):
    return {'symbol': sym, 'side': 'BUY', 'is_real': real, 'pnl_usdt': pnl, 'close_timestamp': now - 60, 'opened_at': now - 600,
            'entry_price': 1, 'tp': 2, 'sl': 0.5, 'close_reason': 'tp', 'risk_usdt': 1.0, 'trade_id': f'{sym}-{real}'}
s['closed_positions'] = [mk(False, 10.0, 'AAA'), mk(False, 5.0, 'BBB'), mk(True, -3.0, 'CCC')]
for t in s['closed_positions']:
    bot.journal_append_closed(CID, {**t, 'close_timestamp': t['close_timestamp']})

s['trading_mode'] = 'PAPER'
assert len(bot.closed_for_mode(s)) == 2 and all(not p['is_real'] for p in bot.closed_for_mode(s))
assert abs(sum(p['pnl_usdt'] for p in bot.closed_for_mode(s)) - 15.0) < 1e-9
t = bot.daily_pnl_text(CID); assert '+15.00' in t and 'کاغذی' in t, t
assert 'CCC' not in bot.today_trades_report(CID) and 'AAA' in bot.today_trades_report(CID)
assert '`2`' in bot.performance_period_report(CID, 'all')
assert len(bot._journal_trades_for(CID)) == 2
assert all(r['mode'] == 'PAPER' for r in [bot.audit_trade_record(p) for p in bot.closed_for_mode(s)])

s['trading_mode'] = 'REAL'
assert len(bot.closed_for_mode(s)) == 1 and bot.closed_for_mode(s)[0]['symbol'] == 'CCC'
t = bot.daily_pnl_text(CID); assert '-3.00' in t and 'واقعی' in t, t
tr = bot.today_trades_report(CID); assert 'CCC' in tr and 'AAA' not in tr
assert '`1`' in bot.performance_period_report(CID, 'all')
assert len(bot._journal_trades_for(CID)) == 1 and len(bot._journal_trades_for(CID, 'all')) == 3
assert 'واقعی' in bot.reset_stats_prompt_text(CID)

# ریست در حالت REAL فقط تاریخچه‌ی واقعی را پاک می‌کند
bot.exchange_balance = lambda chat_id: 100.0
ok, msg = bot.reset_stats(CID); assert ok, msg
assert [p['symbol'] for p in s['closed_positions']] == ['AAA', 'BBB'], s['closed_positions']
assert len(bot._journal_trades_for(CID, 'all')) == 2
s['trading_mode'] = 'PAPER'
assert len(bot.closed_for_mode(s)) == 2
print('mode separation: ALL OK')
