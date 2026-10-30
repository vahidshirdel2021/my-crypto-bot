"""تست آفلاین تریلینگ استاپ هوشمند. اجرا: python trailing_selftest.py"""
import os, time, logging
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("TRAIL_PROFILES = {"); b = src.index("BACKGROUND_SCAN_SECONDS =")
sent = []; moves = []; state = {'real_ok': True}
def side_long(sd): return str(sd).upper().startswith('BUY')
def move_stop_loss(chat, sym, sl):
    moves.append(sl); return (True, 'OK') if state['real_ok'] else (False, 'boom')
g = dict(time=time, logger=logging.getLogger('t'), TAKER_FEE_PCT=0.05, side_long=side_long, fmt=lambda v: f'{v:.4f}',
         send_message=lambda c, t, *a, **k: sent.append(t), normalize_price=lambda c, s, p: round(p, 4),
         move_stop_loss=move_stop_loss, USER_SESSIONS={}, save_session=lambda c: None,
         latest_price=lambda s: 0, exchange_latest_price=lambda c, s: 0)
exec(src[a:b], g)
step, apply_, tgt = g['_trail_step'], g['_trail_apply'], g['_trail_target_lock_r']

def pos(side='BUY (Long)', entry=100.0, sl=98.0, tp=110.0, real=False):
    return {'symbol': 'AAA', 'side': side, 'entry_price': entry, 'sl': sl, 'tp': tp, 'risk_distance': abs(entry - sl), 'is_real': real}

def run(p, prices, profile='balanced'):
    """بازپخش مسیر قیمت؛ (بیرون‌آمد؟, قیمت خروج). SL با تیک‌های بعد از آخرین جابه‌جایی سنجیده می‌شود."""
    lg = side_long(p['side'])
    for px in prices:
        hit = (px <= p['sl']) if lg else (px >= p['sl'])
        if hit: return True, p['sl']
        if (px >= p['tp']) if lg else (px <= p['tp']): return True, p['tp']
        act = step(p, px, profile)
        if act: apply_(1, {}, p, act, px)
    return False, None

# --- نردبان ---
fee_r = g['_trail_fee_r'](100, 2)                      # 0.1%/2% = 0.05R
assert abs(fee_r - 0.05) < 1e-9
assert tgt(0.7, 'balanced', fee_r) is None             # قبل از آستانه فعال نمی‌شود
assert abs(tgt(0.8, 'balanced', fee_r) - fee_r) < 1e-9 # سر به سر + کارمزد
assert abs(tgt(3.0, 'balanced', fee_r) - 2.1) < 1e-9   # ۷۰٪ از اوج 3R
assert abs(tgt(5.0, 'balanced', fee_r) - 4.0) < 1e-9
assert tgt(0.5, 'loose', fee_r) is None and tgt(0.7, 'tight', fee_r) is not None
# هرچه سود بزرگ‌تر، «جا دادن» نسبی کمتر
gb = lambda pk: pk - tgt(pk, 'balanced', fee_r)
assert gb(5.0) / 5.0 < gb(2.0) / 2.0 < gb(1.2) / 1.2

# --- مسیر: ۳R سود و بعد برگشت؛ بدون تریلینگ به ضرر می‌رفت ---
path = [100.5, 101, 102, 103, 104, 105, 106, 105.5, 104.5, 103.5, 102.5, 101, 99, 97.5]
p = pos(); out, px = run(p, path)
assert out and px > 102.0, (out, px, p['sl'])            # حداقل ≈ +1R قفل شد، نه ضرر
assert p['trail_active'] and p['sl'] > 100.0 and p['sl'] == max(p['sl'], p['sl_initial'])
print('long: خروج روی', px, f"(≈{(px-100)/2:+.2f}R) | SL اولیه 98")
# بدون تریلینگ همان مسیر به SL اولیه می‌خورد
q = pos(); lo = min(path); assert lo <= q['sl']
# --- فروش ---
sp = [99.5, 99, 98, 97, 96, 95, 94, 94.5, 95.5, 96.5, 97.5, 99, 101, 102.5]
p = pos('SELL (Short)', 100.0, 102.0, 90.0); out, px = run(p, sp)
assert out and px < 98.0, (out, px)
print('short: خروج روی', px, f"(≈{(100-px)/2:+.2f}R)")
# --- SL فقط به سمت سود: بعد از برگشت قیمت عقب نمی‌رود و پایین‌تر از قبل نمی‌آید ---
p = pos(); hist = []
for px in [101, 102, 103, 104, 103.5, 103, 104.5, 102.8]:
    act = step(p, px, 'balanced')
    if act: apply_(1, {}, p, act, px)
    hist.append(p['sl'])
assert all(hist[i] <= hist[i + 1] for i in range(len(hist) - 1)), hist
# --- فاصله از قیمت: SL هیچ‌وقت بالاتر/روی قیمت نمی‌نشیند ---
p = pos(); step(p, 106, 'balanced'); act = step(p, 101.0, 'balanced')   # اوج 3R ثبت شد ولی قیمت پایین آمد
assert act is None or act['new_sl'] <= 101.0 - 0.1 * 2 + 1e-9, act
p = pos(); step(p, 106, 'balanced'); act = step(p, 106, 'balanced')
assert act and act['new_sl'] <= 106 - 0.2 + 1e-9 and abs(act['lock_r'] - 2.1) < 1e-6, act
# --- TP: SL هرگز از TP عبور نمی‌کند ---
p = pos(tp=104.0); step(p, 103.9, 'tight'); act = step(p, 103.9, 'tight')
assert act is None or act['new_sl'] < 104.0
# --- پیام: اولین قفل و هر +0.5R ---
sent.clear(); p = pos()
for px in [101.8, 102.0, 103, 104, 105, 106, 107, 108]:
    act = step(p, px, 'balanced')
    if act: apply_(1, {}, p, act, px)
assert 1 <= len(sent) <= 5, len(sent)
# --- REAL: SL روی صرافی؛ شکست = در پوزیشن ثبت نمی‌شود و ۶۰ ثانیه صبر ---
moves.clear(); state['real_ok'] = False
p = pos(real=True); step(p, 103, 'balanced'); act = step(p, 103, 'balanced')
assert act and apply_(1, {}, p, act, 103) is False and p['sl'] == 98.0 and not p.get('trail_active') and len(moves) == 1
assert apply_(1, {}, p, act, 103) is False and len(moves) == 1      # در بازه‌ی انتظار دوباره تلاش نمی‌کند
state['real_ok'] = True; p['trail_fail_ts'] = 0; p['trail_last_try'] = 0
assert apply_(1, {}, p, act, 103) is True and p['sl'] == moves[-1] and p['trail_active'] and len(moves) == 2
act2 = step(p, 105, 'balanced'); act2 = step(p, 105, 'balanced')
assert act2 and apply_(1, {}, p, act2, 105) is False                # حداقل فاصله‌ی ۱۵ ثانیه بین دو جابه‌جایی REAL
# --- منو و تنظیمات ---
for needle in ["'trail_enabled': True", "'/toggle_trail'", "'/trail_profile_next'", "trailing_scan_once()", "'exit': ['trail',"]:
    assert needle in src, needle
print('ALL OK')
