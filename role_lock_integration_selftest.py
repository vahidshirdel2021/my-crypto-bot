"""V3.44.59: تست واقعیِ قفل نقش‌ها روی خودِ bot.py (دیتابیس موقت، بدون تلگرام). اجرا: python3 role_lock_integration_selftest.py"""
import sys, types, os, tempfile
# stubs for packages not installed in this sandbox
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
os.environ['BOT_DB_PATH'] = os.path.join(tempfile.mkdtemp(), 'bot.sqlite3')
os.environ['TELEGRAM_SKIP_BACKLOG'] = 'true'
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot')
bot.init_db()
print('imported; admins =', bot.ADMIN_CHAT_IDS, 'lock =', bot.ROLE_LOCK_ENABLED)

sent = []
def fake_send(chat_id, text, markup=None, message_id=None, parse_mode='Markdown', keep=False):
    sent.append((chat_id, text, markup)); return True
bot.send_message = fake_send
bot.edit_page = lambda chat_id, text, markup=None, message_id=None, parse_mode='Markdown': sent.append((chat_id, text, markup)) or True

USER, ADMIN = 222, 111
# 1) کاربر عادی: دستورهای ممنوع => پیام ممنوع، و هیچ هندلر استراتژی اجرا نشود
for cmd in ('/trade_filter_management', '/setup_management', '/market_report', '/btc_eth_regime', '/entry_diag',
            '/export_trade_data', '/admin_panel', '/toggle_halving_model', '/manage_watchlist', '/preset_menu',
            '/back:/trade_filter_management', '/halving_depth_cycle', '/trade_audit'):
    sent.clear()
    bot.process_command(cmd, USER)
    assert len(sent) == 1 and 'در دسترس نیست' in sent[0][1], (cmd, sent)
# 2) ادمین همان دستورها را می‌گیرد (نه پیام ممنوع)
for cmd in ('/trade_filter_management', '/setup_management', '/menu_reports'):
    sent.clear()
    bot.process_command(cmd, ADMIN)
    assert sent and not any('در دسترس نیست' in str(x[1]) for x in sent), (cmd, sent)
# 3) کاربر عادی: دستورهای مجاز کار می‌کنند و کیبوردشان تمیز است
sent.clear(); bot.process_command('/menu', USER)
assert sent and 'در دسترس نیست' not in sent[0][1]
txt = sent[0][1]
assert 'تایم‌فریم' not in txt and 'استراتژی' not in txt and 'لاگ ورود' not in txt, txt
sent.clear(); bot.process_command('/menu', ADMIN)
assert 'تایم‌فریم' in sent[0][1] and 'استراتژی' in sent[0][1]
sent.clear(); bot.process_command('/menu_settings', USER)
assert sent and 'در دسترس نیست' not in sent[0][1]
# 4) متن: نام نماد (تحلیل) برای کاربر عادی ممنوع، برای ادمین مجاز
called = []
bot.analyze = lambda chat, val: called.append((chat, val)) or ('تحلیل', None)
sent.clear(); bot.handle_text(USER, 'BTC'); assert not called and 'در دسترس نیست' in sent[0][1], (called, sent)
sent.clear(); bot.handle_text(ADMIN, 'BTC'); assert called == [(ADMIN, 'BTC')], called
# دکمه‌ی ثابت متنی (رژیم) برای کاربر عادی ممنوع
sent.clear(); bot.handle_text(USER, '🧭 رژیم BTC/ETH'); assert 'در دسترس نیست' in sent[0][1], sent
# وضعیت انتظار باقی‌مانده پاک می‌شود
s = bot.get_session(USER); s['user_state'] = 'WAIT_BACKTEST_SYMBOL'
sent.clear(); bot.handle_text(USER, 'ETH'); assert bot.get_session(USER)['user_state'] is None
# کلید API هنوز قابل تایپ است
seen = []
bot.real_handle_credentials_text = lambda chat, raw, mid: seen.append(raw)
s = bot.get_session(USER); s['user_state'] = 'WAIT_REAL_API_KEY'
bot.handle_text(USER, 'KEY123'); assert seen == ['KEY123']
# 5) فیلتر لایه‌ی tg(): دکمه‌ی ادمین حتی اگر کسی بفرستد به کاربر عادی نمی‌رسد
posted = []
class R: status_code = 200; text = ''; 
    
def fake_post(url, json=None, data=None, files=None, timeout=None):
    posted.append(json or data); r = R(); r.json = lambda: {'ok': True, 'result': {'message_id': 1}}; return r
bot.requests.post = fake_post
mk = {'inline_keyboard': [[{'text': 'a', 'callback_data': '/admin_panel'}, {'text': 'b', 'callback_data': '/open_positions'}]]}
posted.clear(); bot.tg('sendMessage', {'chat_id': USER, 'text': 't', 'reply_markup': mk})
assert [b['callback_data'] for r in posted[0]['reply_markup']['inline_keyboard'] for b in r] == ['/open_positions'], posted
posted.clear(); bot.tg('sendMessage', {'chat_id': ADMIN, 'text': 't', 'reply_markup': mk})
assert len(posted[0]['reply_markup']['inline_keyboard'][0]) == 2
posted.clear(); bot.tg('sendMessage', {'chat_id': -100123, 'text': 't', 'reply_markup': mk})
assert len(posted[0]['reply_markup']['inline_keyboard'][0]) == 2, 'کانال دست‌نخورده'
assert len(mk['inline_keyboard'][0]) == 2, 'ورودی تغییر نکند'
# 6) قفل وقتی ADMIN خالی است خاموش می‌ماند
assert not bot._ap.is_restricted(USER, set())
# 7) مینی‌اپ
print('INTEGRATION OK')

# 7) مینی‌اپ: کاربر عادی سطوح نام‌دار را نمی‌بیند، ادمین می‌بیند
import hmac, hashlib, json as _json, time as _t, urllib.parse as _up
import pandas as pd
def make_init(uid):
    d = {'user': _json.dumps({'id': uid}), 'auth_date': str(int(_t.time()))}
    chk = '\n'.join(f'{k}={v}' for k, v in sorted(d.items()))
    sk = hmac.new(b'WebAppData', bot.TELEGRAM_TOKEN.encode(), hashlib.sha256).digest()
    d['hash'] = hmac.new(sk, chk.encode(), hashlib.sha256).hexdigest()
    return _up.urlencode(d)
bot.get_klines = lambda sym, tf, n: pd.DataFrame({'timestamp': [1700000000000, 1700000300000], 'open': [1, 1], 'high': [2, 2], 'low': [0.5, 0.5], 'close': [1.5, 1.6]})
bot._miniapp_find_position = lambda cid, sym: {'side': 'BUY', 'entry_price': 1.5, 'sl': 1.0, 'tp': 2.0, 'is_real': False}
bot.compute_trade_setup_levels = lambda df, tf, pos: (None, 1.9, 1.1, 'Daily', 'PDH', 1.9)
bot._is_halving_trade = lambda pos: False
c = bot.app.test_client()
r_user = c.post('/miniapp/api/data', json={'initData': make_init(USER), 'symbol': 'BTC', 'tf': '5min'}).get_json()
r_admin = c.post('/miniapp/api/data', json={'initData': make_init(ADMIN), 'symbol': 'BTC', 'tf': '5min'}).get_json()
assert 'error' not in r_user, r_user
print('user miniapp:', r_user['levels'], r_user['position'])
print('admin miniapp:', r_admin['levels'], r_admin['position'])
assert r_user['levels'] == [] and 'setup_tag' not in r_user['position']
assert r_user['position']['entry_price'] == 1.5 and r_user['position']['sl'] == 1.0 and r_user['position']['tp'] == 2.0
assert r_admin['levels'] and r_admin['position'].get('setup_tag') == 'Daily'
assert c.get('/').get_data(as_text=True) == 'OK'
print('MINIAPP OK')
