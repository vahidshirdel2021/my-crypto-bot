# -*- coding: utf-8 -*-
"""V3.44.113: منوی «خروج و حفظ سود» برای کاربر عادی + مقدار سود هر معامله / مجموع سود قابل‌تنظیم توسط خود کاربر."""
import logging, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); os.chdir(HERE); sys.path.insert(0, HERE)
src = open('bot.py', encoding='utf-8').read()
import access_policy as ap, ui

# --- ۱) پارس عدد
a = src.index("PROFIT_AMOUNT_MIN = 0.5"); b = src.index("# V3.42: هشدار ضعف سود")
g = dict(PROFIT_AUTOCLOSE_USDT=5.0, TOTAL_PROFIT_AUTOCLOSE_USDT=5.0); exec(src[a:b], g)
P = g['parse_profit_amount']
assert P('6') == 6.0 and P(' 7.5 ') == 7.5 and P('۷٫۵') == 7.5 and P('۱۰') == 10.0 and P('7$') == 7.0 and P('5,5') == 5.5 and P('12 دلار') == 12.0
assert P('0') is None and P('0.1') is None and P('-3') is None and P('abc') is None and P('') is None and P('nan') is None and P('inf') is None and P('1e9') is None and P('100001') is None
# --- ۲) آستانه‌ی هر کاربر
T = g['_profit_thr']
assert T({}, 'single') == 5.0 and T(None, 'total') == 5.0
assert T({'profit_autoclose_usdt': 8}, 'single') == 8.0 and T({'profit_autoclose_usdt': 8}, 'total') == 5.0
assert T({'total_profit_autoclose_usdt': '12.5'}, 'total') == 12.5 and T({'total_profit_autoclose_usdt': 'x'}, 'total') == 5.0
assert T({'profit_autoclose_usdt': 0}, 'single') == 5.0 and T({'profit_autoclose_usdt': 1e9}, 'single') == 5.0     # خارج از بازه => پیش‌فرض
g0 = dict(PROFIT_AUTOCLOSE_USDT=0.0, TOTAL_PROFIT_AUTOCLOSE_USDT=0.0); exec(src[a:b], g0)
assert g0['_profit_thr']({}, 'single') == 0.0 and g0['_profit_thr']({'profit_autoclose_usdt': 4}, 'single') == 4.0   # env=0 => پیش‌فرض خاموش، ولی انتخاب کاربر معتبر

# --- ۳) اسکن‌ها با آستانه‌ی هر کاربر
sa = src.index("def profit_autoclose_scan_once():"); sb = src.index("def profit_alert_scan_once():")
closed = []; prices = {'AAA': 100.0, 'BBB': 100.0}
sessions = {}
env = dict(g, USER_SESSIONS=sessions, logger=logging.getLogger('t'), exchange_latest_price=lambda c, sy: prices[sy], latest_price=lambda sy: prices[sy],
           _position_gross_pnl=lambda p, px: p['pnl'], send_message=lambda *a, **k: None, save_session=lambda c: None,
           close_position=lambda c, p, px=None, reason='': (closed.append((c, p['symbol'], reason)), sessions[c]['paper_positions'].remove(p)))
exec(src[sa:sb], env)
def mk(en_s=False, en_t=False, **kw):
    return dict(profit_autoclose_enabled=en_s, total_profit_autoclose_enabled=en_t, trading_mode='PAPER', paper_positions=[{'symbol': 'AAA', 'pnl': 6.0}, {'symbol': 'BBB', 'pnl': 2.0}], **kw)
# هر معامله: آستانه‌ی ۷ => ۶ دلار کافی نیست؛ آستانه‌ی ۵/پیش‌فرض => AAA بسته می‌شود
sessions.clear(); sessions[1] = mk(en_s=True, profit_autoclose_usdt=7); sessions[2] = mk(en_s=True); sessions[3] = mk(en_s=False)
env['profit_autoclose_scan_once']()
assert [c for c in closed if c[1] == 'AAA'] == [(2, 'AAA', 'بستن خودکار: سود به 5$ رسید')], closed
# مجموع: کاربر ۱ آستانه ۱۰ (مجموع ۸ => نه)، کاربر ۲ آستانه ۸ (=> همه بسته)، کاربر ۳ پیش‌فرض ۵ (=> همه بسته)
closed.clear(); sessions.clear()
sessions[1] = mk(en_t=True, total_profit_autoclose_usdt=10); sessions[2] = mk(en_t=True, total_profit_autoclose_usdt=8); sessions[3] = mk(en_t=True); sessions[4] = mk(en_t=False)
env['total_profit_autoclose_scan_once']()
by = {}
for c, sy, r in closed: by.setdefault(c, []).append((sy, r))
assert set(by) == {2, 3} and len(by[2]) == 2 and 'به 8$ رسید' in by[2][0][1] and 'به 5$ رسید' in by[3][0][1], by

# --- ۴) دسترسی کاربر عادی
for c in ('/profit_menu', '/profit_amt_single', '/profit_amt_total', '/toggle_trail', '/toggle_profit_autoclose', '/toggle_total_profit_autoclose',
          '/toggle_be_auto', '/set_profit_single_7', '/set_profit_total_7.5', '/profit_amt_custom_single', '/profit_amt_custom_total'):
    assert ap.user_command_allowed(c), c
for c in ('/trail_profile_next', '/toggle_be_alert', '/toggle_btc_guard', '/btc_guard_frac_next', '/be_profit_next', '/be_loss_next', '/trade_filter_exit', '/trade_filter_management', '/set_profit_single_', '/set_profit_x_5', '/set_profit_single_5;rm', '/preset_menu'):
    assert not ap.user_command_allowed(c), c
kb = ap.filter_markup(ui.get_settings_menu_keyboard())
cds = [b['callback_data'] for r in kb['inline_keyboard'] for b in r]
assert '/profit_menu' in cds and '/trade_filter_management' not in cds and '/setup_management' not in cds
assert any(b['callback_data'] == '/profit_menu' for r in ui.get_settings_menu_keyboard()['inline_keyboard'] for b in r)
# --- ۵) متن/کیبورد
assert 'USER_EXIT_KEYS' in src and "'/profit_amt_single'" in src and "'/profit_amt_total'" in src and "if is_restricted_user(chat_id) else back_row" in src
assert "'WAIT_PROFIT_AMT_SINGLE', 'WAIT_PROFIT_AMT_TOTAL'):" in src and "profit_autoclose_usdt', 'total_profit_autoclose_usdt'," in src
print('profit_amount_selftest: ALL OK')
