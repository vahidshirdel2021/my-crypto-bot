# -*- coding: utf-8 -*-
"""تست جریان «انتخاب صرافی → کلید API → اتصال → موجودی → ادامه/شارژ» برای حالت REAL (بدون اینترنت و بدون تلگرام)."""
import json, logging, math, os, sqlite3, tempfile, time
from threading import RLock
from credentials_store import CredentialsStore
from bitunix_client import BitunixError

HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE)
src = open('bot.py', encoding='utf-8').read()
a1 = src.index("_CRED_CACHE = {}          #"); b1 = src.index("# --- V3.42.14: مدیریت پویای دسترسی از پنل ادمین ---")
a2 = src.index("# ===================== V3.44.57: انتخاب صرافی و اتصال حساب REAL"); b2 = src.index("def menu(chat_id,message_id=None):")
a3 = src.index("    if cl=='/mode_real':\n        if PAPER_ONLY:"); b3 = src.index("    if cl.startswith('/set_bal_'):", a3)

td = tempfile.TemporaryDirectory(); dbp = os.path.join(td.name, 'x.sqlite3')
store = CredentialsStore(dbp, key_path=os.path.join(td.name, 'credentials.key'), env_key=''); store.init_table()
SESS = {}; SENT = []; DELETED = []; SAVES = [0]
class ExchangeStateError(RuntimeError): pass
class FakeEx:
    def __init__(self, total, free, boom=None): self.total = total; self.free = free; self.boom = boom
    def fetch_balance(self):
        if self.boom: raise self.boom
        return {'total': {'USDT': self.total}, 'free': {'USDT': self.free}}
BAL = {'total': 100.0, 'free': 80.0}; BUILD = []; FAIL = {'exc': None}
def build_exchange_stub(venue, key, secret):
    BUILD.append((venue, key, secret))
    if FAIL['exc']: raise FAIL['exc']
    return FakeEx(BAL['total'], BAL['free'])
def get_session(chat_id): return SESS.setdefault(chat_id, {'user_state': None, 'trading_mode': 'PAPER', 'paper_positions': [], 'is_bot_active': False, 'real_exchange': 'binance'})
def send_message(chat_id, text, markup=None, message_id=None, parse_mode='Markdown', keep=False): SENT.append({'text': text, 'markup': markup, 'pm': parse_mode})
def edit_page(chat_id, text, markup=None, message_id=None, parse_mode='Markdown'): SENT.append({'text': text, 'markup': markup, 'pm': parse_mode, 'edit': True})
def tg(method, params=None, timeout=10):
    if method == 'deleteMessage': DELETED.append(params['message_id'])
    return {'ok': True}
ENV = {}
g = dict(time=time, math=math, logger=logging.getLogger('rc'), hashlib=__import__('hashlib'), STATE_LOCK=RLock(), USER_SESSIONS=SESS, EXCHANGE_CACHE={},
         REAL_VENUES={'binance': 'Binance Futures', 'bitunix': 'Bitunix Futures'}, REAL_MIN_BALANCE_USDT=5.0, PAPER_ONLY=False,
         CREDENTIALS=store, CredentialsError=Exception, BINANCE_ACCOUNTS=ENV, MARGIN_MODE='isolated', PROTECTION_TRIGGER='mark_price',
         ExchangeStateError=ExchangeStateError, get_session=get_session, save_session=lambda c: SAVES.__setitem__(0, SAVES[0] + 1),
         send_message=send_message, edit_page=edit_page, tg=tg, get_margin_keyboard=lambda: {'inline_keyboard': [[{'text': '10 USDT', 'callback_data': '/set_margin_10'}]]},
         BitunixExchange=None, ccxt=None)
exec(src[a1:b1], g); g['build_exchange'] = build_exchange_stub        # build_exchange واقعی در تست بیتیونیکس/ccxt پوشش داده شده؛ اینجا جعلی
exec(src[a2:b2], g); g['build_exchange'] = build_exchange_stub
def cmd(c, chat=1, mid=5):
    """مسیر دکمه‌ها همان کد process_command (برش داده‌شده از bot.py)"""
    s = get_session(chat); cl = c.lower(); body = src[a3:b3]
    ns = dict(g); ns.update(s=s, cl=cl, chat_id=chat, message_id=mid, logger=logging.getLogger('cmd'))
    code = "def _run():\n" + body + "\n    return 'unhandled'\n"
    exec(code, ns); return ns['_run']()
def last(): return SENT[-1]
def buttons(m): return [b['callback_data'] for row in (m['markup'] or {}).get('inline_keyboard', []) for b in row]
def reset(chat=1):
    SENT.clear(); DELETED.clear(); BUILD.clear(); FAIL['exc'] = None; g['_REAL_PENDING_KEYS'].clear(); g['_cred_cache_clear']()
    SESS.pop(chat, None); store.delete(chat); g['EXCHANGE_CACHE'].clear(); g['PAPER_ONLY'] = False; ENV.clear()
    BAL.update(total=100.0, free=80.0)

# ---------------------------------------------------------------- ۱) منوی انتخاب صرافی
reset(); cmd('/mode_real')
m = last(); assert m['edit'] and buttons(m) == ['/real_pick_binance', '/real_pick_bitunix', '/menu'] and 'صرافی' in m['text'] and '✅' not in str(m['markup'])
g['PAPER_ONLY'] = True; SENT.clear(); cmd('/mode_real'); assert 'قفل' in last()['text'] and g['_real_has_saved'](1, 'bitunix') is False; g['PAPER_ONLY'] = False
get_session(1)['paper_positions'] = [{'symbol': 'X'}]; SENT.clear(); cmd('/mode_real'); assert 'پوزیشن' in last()['text']; get_session(1)['paper_positions'] = []

# ---------------------------------------------------------------- ۲) بیتیونیکس بدون کلید ذخیره‌شده: API Key → Secret → اتصال → موجودی کافی
reset(); cmd('/real_pick_bitunix')
s = get_session(1); m = last()
assert s['user_state'] == 'WAIT_REAL_API_KEY' and s['_real_tmp'] == {'venue': 'bitunix'} and 'Withdraw' in m['text'] and 'پاک' in m['text'] and 'Bitunix' in m['text']
g['handle_creds'] = g['real_handle_credentials_text']
g['real_handle_credentials_text'](1, '  BKEYabcdef1234567890  ', 101)
assert DELETED == [101] and s['user_state'] == 'WAIT_REAL_API_SECRET' and 'Secret' in last()['text']
assert 'BKEYabcdef1234567890' not in json.dumps(s) and g['_REAL_PENDING_KEYS'][1][1] == 'BKEYabcdef1234567890'    # کلید در session (دیتابیس) نیست
g['real_handle_credentials_text'](1, 'SECRETvalue0987654321', 102)
assert DELETED == [101, 102] and BUILD == [('bitunix', 'BKEYabcdef1234567890', 'SECRETvalue0987654321')]
assert s['user_state'] is None and s.get('_real_tmp') is None and 1 not in g['_REAL_PENDING_KEYS']
assert s['real_exchange'] == 'bitunix' and s['trading_mode'] == 'REAL' and s['daily_start_equity'] == 100.0 and s['is_bot_active'] is False
m = last(); assert 'Bitunix Futures' in m['text'] and '100.00' in m['text'] and '80.00' in m['text'] and buttons(m) == ['/set_margin_10']      # ادامه: مارجین
assert store.load(1, 'bitunix') == ('BKEYabcdef1234567890', 'SECRETvalue0987654321')
raw = open(dbp, 'rb').read(); assert b'SECRETvalue0987654321' not in raw and b'BKEYabcdef1234567890' not in raw
assert 'SECRETvalue0987654321' not in json.dumps(SENT) and 'BKEYabcdef1234567890' not in json.dumps(SENT)                  # هیچ پیامی کلید را تکرار نمی‌کند
assert g['account_credentials'](1, 'bitunix') == ('BKEYabcdef1234567890', 'SECRETvalue0987654321') and g['real_venue'](1) == 'bitunix' and g['real_venue_name'](1) == 'Bitunix Futures'

# ---------------------------------------------------------------- ۳) موجودی کم: پیام شارژ، REAL فعال نمی‌شود؛ بعد از شارژ «بررسی مجدد»
reset(); BAL.update(total=2.5, free=2.0)
cmd('/real_new_bitunix'); g['real_handle_credentials_text'](1, 'KEYKEYKEY12345', 1); g['real_handle_credentials_text'](1, 'SECSECSEC12345', 2)
s = get_session(1); m = last()
assert s['trading_mode'] == 'PAPER' and s['real_exchange'] == 'binance'                                          # REAL فعال نشد و صرافی عوض نشد
assert 'شارژ' in m['text'] and '2.00' in m['text'] and '5' in m['text'] and '/real_use_bitunix' in buttons(m) and '/mode_paper' in buttons(m) and '/set_margin_10' not in buttons(m)
assert store.has(1, 'bitunix')                                                                                    # کلید ذخیره شد تا دوباره وارد نکنند
BAL.update(total=60.0, free=50.0); SENT.clear(); BUILD.clear(); cmd('/real_use_bitunix')
assert BUILD == [('bitunix', 'KEYKEYKEY12345', 'SECSECSEC12345')] and s['trading_mode'] == 'REAL' and s['real_exchange'] == 'bitunix' and '/set_margin_10' in buttons(last())

# ---------------------------------------------------------------- ۴) خطای اتصال: دلیل بدون افشای secret، چیزی ذخیره نمی‌شود
reset(); FAIL['exc'] = BitunixError(10003, 'Invalid api key SECRETvalue0987654321', 200, 'account')
cmd('/real_new_bitunix'); g['real_handle_credentials_text'](1, 'KEYKEYKEY12345', 1); g['real_handle_credentials_text'](1, 'SECRETvalue0987654321', 2)
m = last(); assert 'ناموفق' in m['text'] and 'SECRETvalue0987654321' not in m['text'] and '***' in m['text'] and 'Withdraw' not in m['text']
assert '/real_new_bitunix' in buttons(m) and not store.has(1, 'bitunix') and get_session(1)['trading_mode'] == 'PAPER' and get_session(1)['user_state'] is None

# ---------------------------------------------------------------- ۵) ورودی نامعتبر / لغو / مهلت
reset(); cmd('/real_new_binance'); s = get_session(1)
g['real_handle_credentials_text'](1, 'short', 7); assert s['user_state'] == 'WAIT_REAL_API_KEY' and '⚠️' in last()['text'] and DELETED == [7]
g['real_handle_credentials_text'](1, 'has space inside key', 8); assert s['user_state'] == 'WAIT_REAL_API_KEY'
g['real_handle_credentials_text'](1, '/cancel', 9); assert s['user_state'] is None and 'لغو' in last()['text'] and not BUILD
cmd('/real_new_binance'); g['real_handle_credentials_text'](1, 'KEYKEYKEY12345', 1)
t0 = g['_REAL_PENDING_KEYS'][1]; g['_REAL_PENDING_KEYS'][1] = (t0[0], t0[1], time.time() - 10_000)               # مهلت گذشته
g['real_handle_credentials_text'](1, 'SECSECSEC12345', 2); assert 'مهلت' in last()['text'] and not BUILD
# وسط مسیر صرافی عوض شود: کلید قبلی استفاده نمی‌شود
reset(); cmd('/real_new_binance'); g['real_handle_credentials_text'](1, 'KEYKEYKEY12345', 1); cmd('/real_new_bitunix'); assert 1 not in g['_REAL_PENDING_KEYS'] and get_session(1)['_real_tmp'] == {'venue': 'bitunix'}

# ---------------------------------------------------------------- ۶) کلید ذخیره‌شده: انتخاب، استفاده، حذف
reset(); store.save(1, 'bitunix', 'SAVEDKEY9999', 'SAVEDSECRET'); g['_cred_cache_clear']()
cmd('/real_mode' if False else '/mode_real'); assert '✅' in str(last()['markup'])
cmd('/real_pick_bitunix'); m = last(); assert buttons(m) == ['/real_use_bitunix', '/real_new_bitunix', '/real_del_bitunix', '/mode_real'] and '9999' in m['text'] and 'SAVEDSECRET' not in m['text']
BUILD.clear(); cmd('/real_use_bitunix'); assert BUILD == [('bitunix', 'SAVEDKEY9999', 'SAVEDSECRET')] and get_session(1)['trading_mode'] == 'REAL'
get_session(1)['paper_positions'] = [{'symbol': 'X'}]; SENT.clear(); cmd('/real_del_bitunix'); assert 'پوزیشن باز' in last()['text'] and store.has(1, 'bitunix')
get_session(1)['paper_positions'] = []; cmd('/real_del_bitunix'); assert not store.has(1, 'bitunix') and 'حذف شد' in last()['text'] and g['account_credentials'](1, 'bitunix') is None
SENT.clear(); BUILD.clear(); cmd('/real_use_bitunix'); assert 'ذخیره نشده' in last()['text'] and not BUILD
# با پوزیشن باز اتصال/تعویض صرافی مجاز نیست
reset(); store.save(1, 'bitunix', 'SAVEDKEY9999', 'SAVEDSECRET'); g['_cred_cache_clear'](); get_session(1)['paper_positions'] = [{'symbol': 'X'}]
BUILD.clear(); cmd('/real_use_bitunix'); assert 'پوزیشن' in last()['text'] and not BUILD

# ---------------------------------------------------------------- ۷) Binance: کلید env همچنان کار می‌کند؛ Bitunix هیچ‌وقت از env نمی‌آید
reset(); ENV['1'] = {'apiKey': 'ENVKEY123456', 'secret': 'ENVSECRET123'}; g['_cred_cache_clear']()
assert g['account_credentials'](1, 'binance') == ('ENVKEY123456', 'ENVSECRET123') and g['account_credentials'](1, 'bitunix') is None
assert g['real_venue'](1) == 'binance'                                                                           # پیش‌فرض
cmd('/real_pick_binance'); m = last(); assert '/real_use_binance' in buttons(m) and '/real_del_binance' not in buttons(m) and 'ادمین' in m['text']   # حذف فقط برای کلید ذخیره‌شده
BUILD.clear(); cmd('/real_use_binance'); assert BUILD == [('binance', 'ENVKEY123456', 'ENVSECRET123')] and get_session(1)['real_exchange'] == 'binance' and get_session(1)['trading_mode'] == 'REAL'
# کلید ذخیره‌شده‌ی خود کاربر بر env مقدم است
store.save(1, 'binance', 'OWNKEY123456', 'OWNSECRET1234'); g['_cred_cache_clear'](); assert g['account_credentials'](1, 'binance') == ('OWNKEY123456', 'OWNSECRET1234')

# ---------------------------------------------------------------- ۸) get_exchange: صرافی درست و کش
reset(); builds = []
def counting_build(venue, key, secret): builds.append((venue, key, secret)); return FakeEx(1, 1)
g['build_exchange'] = counting_build
store.save(1, 'bitunix', 'AAAA11112222', 'BBBB'); g['_cred_cache_clear']()
assert g['get_exchange'](1) is None                                                                               # صرافی پیش‌فرض binance و کلیدی ندارد
get_session(1)['real_exchange'] = 'bitunix'
e1 = g['get_exchange'](1); e2 = g['get_exchange'](1); assert e1 is e2 and builds == [('bitunix', 'AAAA11112222', 'BBBB')]
store.save(1, 'bitunix', 'NEWKEY33334444', 'NEWSEC'); g['_cred_cache_clear'](); e3 = g['get_exchange'](1); assert e3 is not e1 and len(builds) == 2     # کلید عوض شد: اتصال جدید
def boom_build(*a): raise RuntimeError('down')
g['build_exchange'] = boom_build; g['EXCHANGE_CACHE'].clear(); assert g['get_exchange'](1) is None

# ---------------------------------------------------------------- ۹) ساختار کد
assert "handle_text(chat,data,_um.get('message_id'))" in src and 'def handle_text(chat_id,text,message_id=None):' in src
assert "if current_state in ('WAIT_REAL_API_KEY','WAIT_REAL_API_SECRET'):" in src
assert "except BitunixOrderRejected as exc:" in src and "CREDENTIALS.init_table()" in src and "'real_exchange': 'binance'" in src
print('real_connect_selftest: ALL OK')
