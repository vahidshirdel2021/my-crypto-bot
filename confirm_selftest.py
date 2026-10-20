"""V3.44.38: تایید «بله / خیر» برای دکمه‌های ورود / رد / بستن دستی. اجرا: python3 confirm_selftest.py"""
import hashlib, logging, os, re, time
from threading import RLock

src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index('# ===================== V3.44.38: تایید «بله / خیر»')
b = src.index('# --- V3.38.3: کیبورد ثابت پایین چت', a)
calls, sent, executed = [], [], []
S = {'auto_trend_pending': {'r1': {'sig': 'BUY', 'symbol': 'ETH'}}, 'fav_wait': {'f1': {'symbol': 'RLC'}}, 'touch_wait': {'t1': {'symbol': 'ZK'}}}
REC = {'a1': {'symbol': 'CHZ', 'sig': 'BUY'}}
TG_OK = {'v': True}


def fake_tg(method, payload=None, timeout=10):
    calls.append((method, payload))
    return {'ok': True, 'result': {'message_id': 900}} if TG_OK['v'] else None


g = dict(hashlib=hashlib, time=time, re=re, RLock=RLock, logger=logging.getLogger('t'), tg=fake_tg,
         get_session=lambda c: S, _assist_find=lambda s, i: REC.get(i),
         send_message=lambda c, t, *x, **k: sent.append(t),
         begin_callback_context=lambda *x: None, end_callback_context=lambda: None,
         process_command=lambda cmd, chat, mid=None: executed.append((cmd, chat, mid)))
exec(src[a:b], g)
need, handle, prompt, label = g['_confirm_needed'], g['_confirm_handle'], g['_confirm_prompt'], g['_confirm_label']

# 1) کدام دستورها سؤال می‌خواهند
for c in ('/assist_ok_a1', '/assist_no_a1', '/assist_rev_a1', '/autotg_ok_r1', '/autotg_no_r1', '/fq_qe_buy_f1', '/tw_qe_sell_t1',
          '/qt_buy_BTC', '/qt_sell_ETH', '/fq_rej_f1', '/pclose_50_BTC', '/pclose_100_ETH', '/cancel_pending_ab12', '/cancel_watch_BTC'):
    assert need(c), c
for c in ('/assist_farok_a1', '/assist_tgok_a1', '/assist_revok_a1', '/qt_tgok_buy_BTC', '/qtm_buy_BTC', '/qt_foo', '/assist_save_a1', '/assist_open_a1',
          '/fq_ext_f1', '/fq_ref_f1', '/confirm_close_BTC', '/confirm_manual_entry', '/cancel_pending_all', '/cancel_pending_all_prompt',
          '/menu', '/noop', '/cfm_abcd1234', '/cfmno_abcd1234'):
    assert not need(c), c

# 2) برچسب‌ها
assert label(1, '/assist_ok_a1') == 'ورود خرید CHZ', label(1, '/assist_ok_a1')
assert label(1, '/assist_rev_a1') == 'ورود معکوس فروش CHZ', label(1, '/assist_rev_a1')
assert label(1, '/assist_no_a1') == 'رد سیگنال CHZ', label(1, '/assist_no_a1')
assert label(1, '/fq_qe_buy_f1') == 'ورود سریع خرید RLC'
assert label(1, '/tw_qe_sell_t1') == 'ورود سریع فروش ZK'
assert label(1, '/qt_sell_eth') == 'ورود سریع فروش ETH'
assert label(1, '/pclose_75_btc') == 'بستن 75٪ از معامله‌ی BTC'
assert label(1, '/autotg_ok_r1') == 'ورود خرید ETH'
assert label(1, '/assist_ok_unknown') == 'ورود', label(1, '/assist_ok_unknown')

CARD = {'inline_keyboard': [[{'text': '✅ ورود', 'callback_data': '/assist_ok_a1'}, {'text': '❌ رد', 'callback_data': '/assist_no_a1'}]]}


def pending_tok():
    return next(iter(g['_CONFIRM_PENDING']))


# 3) روی کارت خصوصی: فقط دکمه‌ها عوض می‌شود، دستور اجرا نمی‌شود
assert prompt(7, '/assist_ok_a1', {'reply_markup': CARD}, 555, False)
assert calls[-1][0] == 'editMessageReplyMarkup' and calls[-1][1]['message_id'] == 555
kb = calls[-1][1]['reply_markup']['inline_keyboard']
assert kb[1][0]['callback_data'].startswith('/cfm_') and kb[1][1]['callback_data'].startswith('/cfmno_') and 'CHZ' in kb[0][0]['text']
assert executed == []
tok = pending_tok()

# 4) «بله»: دکمه‌های اصلی برمی‌گردد و دستور اصلی عیناً اجرا می‌شود (فقط یک بار)
handle(7, '/cfm_' + tok, 555)
assert calls[-1][0] == 'editMessageReplyMarkup' and calls[-1][1]['reply_markup'] == CARD
assert executed == [('/assist_ok_a1', 7, 555)], executed
handle(7, '/cfm_' + tok, 555)                       # لمس دوباره = منقضی؛ دوباره اجرا نمی‌شود
assert len(executed) == 1 and 'منقضی' in sent[-1]

# 5) «خیر»: دکمه‌ها برمی‌گردد و چیزی اجرا نمی‌شود
executed.clear()
prompt(7, '/assist_no_a1', {'reply_markup': CARD}, 555, False)
handle(7, '/cfmno_' + pending_tok(), 555)
assert calls[-1][1]['reply_markup'] == CARD and executed == [] and not g['_CONFIRM_PENDING']

# 6) زیر پست کانال: پیام جدا در چت خصوصی؛ «بله» همان دستور را با message_id=None اجرا می‌کند
prompt(7, '/qt_buy_BTC', {'reply_markup': CARD}, None, True)
assert calls[-1][0] == 'sendMessage' and 'BTC' in calls[-1][1]['text']
handle(7, '/cfm_' + pending_tok(), 900)
assert calls[-1][0] == 'deleteMessage' and executed == [('/qt_buy_BTC', 7, None)], executed

# 7) اگر پیام تایید ارسال/ویرایش نشد: False (در حلقه یعنی اجرا نمی‌شود)
TG_OK['v'] = False
assert prompt(7, '/assist_ok_a1', {'reply_markup': CARD}, 555, False) is False
assert not g['_CONFIRM_PENDING']
TG_OK['v'] = True

# 8) تایید کاربر دیگر یا توکن نامعتبر هرگز اجرا نمی‌کند
executed.clear()
prompt(7, '/assist_ok_a1', {'reply_markup': CARD}, 555, False)
handle(8, '/cfm_' + pending_tok(), 555)
assert executed == []
print('confirm_selftest OK')
