import os, time, logging
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("# ===================== V3.44.28: بستن سر به سر")
b = src.index("# V3.43.15: ۳۰ دقیقه‌ی آخر هر کندل ۴ ساعته (مرز کندل‌ها")
block = src[a:b]
sent = []; tgc = []; closed = []; dele = []
S = {'trading_mode': 'PAPER', 'paper_positions': [], 'be_close_alert_enabled': False, 'be_close_auto_enabled': False,
     'be_close_profit_r': 1.0, 'be_close_loss_r': 0.5}
px = {'v': 100.0}
def mkpos(sym='AAA', side='BUY'):
    return {'symbol': sym, 'side': side, 'entry_price': 100.0, 'sl': 99.0 if side == 'BUY' else 101.0, 'tp': 103.0 if side == 'BUY' else 97.0,
            'risk_distance': 1.0, 'peak_favorable_price': None, 'peak_adverse_price': None}
def _close(chat, pos, price=None, reason=''):
    closed.append((pos['symbol'], price, reason))
    if pos in S['paper_positions']: S['paper_positions'].remove(pos)
    return True
g = dict(os=os, time=time, logger=logging.getLogger('t'), USER_SESSIONS={1: S}, get_session=lambda c: S, save_session=lambda c: None,
         side_long=lambda s: 'BUY' in str(s).upper(), fmt=lambda v: str(v), is_allowed=lambda c: True,
         tg=lambda m, pl=None, t=10: (tgc.append((m, pl)) or {'ok': True, 'result': {'message_id': 9}}),
         schedule_auto_delete=lambda c, m, ttl=None: dele.append(m), PROFIT_ALERT_BUTTONS_TTL=1800,
         send_message=lambda c, t, *a, **k: sent.append(t), close_position=_close,
         latest_price=lambda sym: px['v'], exchange_latest_price=lambda c, sym: px['v'])
exec(block, g)
K = g['_be_kind']
# منطق خالص
assert K(0.0, 1.0, 0.0, 1.0, 0.5) == 'profit' and K(-0.2, 1.2, 0.0, 1.0, 0.5) == 'profit'
assert K(0.3, 0.9, 0.0, 1.0, 0.5) is None                 # اوج به آستانه نرسیده
assert K(0.5, 1.2, 0.0, 1.0, 0.5) is None                 # هنوز به ورود برنگشته
assert K(0.0, 0.0, 0.5, 1.0, 0.5) == 'loss' and K(0.2, 0.0, 0.6, 1.0, 0.5) == 'loss'
assert K(-0.3, 0.0, 0.4, 1.0, 0.5) is None and K(-0.3, 0.0, 0.6, 1.0, 0.5) is None   # هنوز منفی است یا کف کافی نبوده
cfg = g['_be_cfg']; assert cfg({}) == (1.0, 0.5) and cfg({'be_close_loss_r': 5}) == (1.0, 0.95)

def run(*prices):
    for v in prices:
        px['v'] = v; g['be_close_scan_once']()
def fresh(**kw):
    sent.clear(); tgc.clear(); closed.clear(); dele.clear()
    S.update(be_close_alert_enabled=False, be_close_auto_enabled=False, be_close_profit_r=1.0, be_close_loss_r=0.5, trading_mode='PAPER'); S.update(kw)
    p = mkpos(); S['paper_positions'] = [p]; return p

# هر دو کلید خاموش = هیچ اتفاقی
p = fresh(); run(101.5, 100.0, 99.5, 100.0); assert not closed and not tgc and 'be_peak_r' not in p
# خودکار، سودی: +1.5R بعد برگشت به ورود
p = fresh(be_close_auto_enabled=True); run(100.5, 101.5, 100.6); assert not closed; run(100.0)
assert len(closed) == 1 and closed[0][1] == 100.0 and 'سر به سر' in closed[0][2] and S['paper_positions'] == []
# خودکار، سودی: اوج فقط 0.8R => نه
p = fresh(be_close_auto_enabled=True); run(100.8, 100.0, 99.9); assert not closed
# خودکار، ضرری: -0.6R بعد برگشت به ورود
p = fresh(be_close_auto_enabled=True); run(99.7, 99.4, 99.8); assert not closed; run(100.0)
assert len(closed) == 1 and 'ضرر' in closed[0][2]
# ضرری: فقط -0.4R => نه
p = fresh(be_close_auto_enabled=True); run(99.6, 100.0, 100.3); assert not closed
# فروش (Short): سودی
S2 = mkpos('BBB', 'SELL'); p = fresh(be_close_auto_enabled=True); S['paper_positions'] = [S2]; run(98.8, 99.5, 100.0); assert closed and closed[0][0] == 'BBB'
# فروش: ضرری
S2 = mkpos('CCC', 'SELL'); fresh(be_close_auto_enabled=True); S['paper_positions'] = [S2]; run(100.6, 100.0); assert closed and closed[0][0] == 'CCC'
# فقط هشدار: یک پیام با دکمه، پوزیشن بسته نمی‌شود، تکرار نمی‌شود
p = fresh(be_close_alert_enabled=True); run(101.3, 100.0)
assert not closed and len(tgc) == 1 and tgc[0][1]['reply_markup']['inline_keyboard'][0][0]['callback_data'] == '/becl_AAA' and 'AAA' in tgc[0][1]['text'] and dele == [9]
run(101.4, 100.0, 99.9); assert len(tgc) == 1                       # همان حالت دوباره پیام نمی‌دهد
run(99.4, 100.0); assert len(tgc) == 2                              # حالت ضرری مستقل است (اوج قبلی سودی بوده؛ اینجا کف 0.6R)
# هر دو کلید: بستن + پیام اطلاع
p = fresh(be_close_alert_enabled=True, be_close_auto_enabled=True); run(101.2, 100.0)
assert len(closed) == 1 and sent and 'خودکار' in sent[-1] and not tgc
# بستن ناموفق: بعد از ۶۰ ثانیه دوباره تلاش می‌شود، نه هر چرخه
fails = []
def _bad(chat, pos, price=None, reason=''): fails.append(1); return False
g['close_position'] = _bad
p = fresh(be_close_auto_enabled=True); run(101.2, 100.0, 100.0, 100.0); assert len(fails) == 1
p['be_fail_ts'] -= 61; run(100.0); assert len(fails) == 2
g['close_position'] = _close
# اوج/کفِ کندلی (قیمت‌های ذخیره‌شده‌ی پوزیشن) هم حساب می‌شود، حتی اگر در نمونه‌برداری لحظه‌ای دیده نشده باشد
p = fresh(be_close_auto_enabled=True); p['peak_favorable_price'] = 101.4; run(100.0); assert len(closed) == 1
# REAL: پوزیشن غیرواقعی رد می‌شود
p = fresh(be_close_auto_enabled=True, trading_mode='REAL'); run(101.5, 100.0); assert not closed
# دکمه
p = fresh(); g['handle_be_close'](1, 'aaa'); assert closed and 'سر به سر' in closed[0][2]
sent.clear(); g['handle_be_close'](1, 'ZZZ'); assert 'دیگر باز نیست' in sent[-1]
print('be_close_selftest OK')
