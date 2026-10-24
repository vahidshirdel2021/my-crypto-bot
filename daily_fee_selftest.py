# -*- coding: utf-8 -*-
"""V3.44.61: تست منطق کارمزد روزانه (daily_fee.py + اجازه‌ی دکمه‌ی کاربر در access_policy)."""
import sys
from datetime import datetime
import daily_fee as df
import access_policy as ap

ok = True
def check(name, cond):
    global ok
    print(('PASS ' if cond else 'FAIL ') + name)
    ok = ok and bool(cond)

tz = df.get_tz('Asia/Tehran')
s, e = df.day_bounds('2026-10-23', tz)
check('day is 24h in Tehran (no DST)', abs((e - s) - 86400) < 1)
check('day_key roundtrip', df.day_key(s + 10, tz) == '2026-10-23' and df.day_key(e - 1, tz) == '2026-10-23' and df.day_key(e, tz) == '2026-10-24')
check('shift_day across month', df.shift_day('2026-10-31', 1) == '2026-11-01' and df.shift_day('2026-03-01', -1) == '2026-02-28')
check('days_after basic', df.days_after('2026-10-20', '2026-10-23') == ['2026-10-21', '2026-10-22', '2026-10-23'])
check('days_after empty', df.days_after('2026-10-23', '2026-10-23') == [])
check('days_after cap', len(df.days_after('2026-01-01', '2026-10-23', 7)) == 7)

pos = [
    {'close_timestamp': s + 100, 'pnl_usdt': 10.0},
    {'close_timestamp': s + 200, 'pnl_usdt': -3.0},
    {'close_timestamp': s + 300, 'pnl_usdt': 5.0, 'platform_fee_status': 'SETTLED'},   # قبلاً per-trade تسویه شده
    {'close_timestamp': e + 5, 'pnl_usdt': 99.0},                                       # روز بعد
    {'close_timestamp': s - 5, 'pnl_usdt': 77.0},                                       # روز قبل
    {'close_timestamp': s + 400, 'pnl_usdt': 2.0, 'is_real': True},
]
p, n = df.day_profit(pos, s, e)
check('net profit sums wins and losses, skips SETTLED/other days', abs(p - 9.0) < 1e-9 and n == 3)
p2, n2 = df.day_profit(pos, s, e, include_paper=False)
check('include_paper=False keeps only real', abs(p2 - 2.0) < 1e-9 and n2 == 1)

check('fee 10% of 9.0', df.compute_fee(9.0, 10) == 0.9)
check('no fee on loss', df.compute_fee(-5, 10) == 0.0 and df.compute_fee(0, 10) == 0.0)
check('no fee under minimum', df.compute_fee(0.005, 10, 0.01) == 0.0)
check('fee rate clamp', df.compute_fee(10, 500) == 10.0 and df.compute_fee(10, -5) == 0.0)

created = datetime(2026, 10, 24, 0, 0, 30, tzinfo=tz).timestamp()
due = df.due_timestamp(created, tz, 12, 6)
check('due is 12:00 same day', df.fmt_due(due, tz) == '12:00' and df.day_key(due, tz) == '2026-10-24')
late = datetime(2026, 10, 24, 13, 0, 0, tzinfo=tz).timestamp()
check('late invoice gets min grace (not instantly overdue)', df.due_timestamp(late, tz, 12, 6) >= late + 6 * 3600 - 1)

msg = df.invoice_message('2026-10-23', 9.0, 10, 0.9, due, tz, 'TXabc_123', 'Asia/Tehran')
check('invoice message has profit, fee, deadline, account, block warning',
      '+9.00 USDT' in msg and '0.90 USDT' in msg and '12:00' in msg and 'TXabc_123' in msg and 'مسدود' in msg)
check('invoice message handles missing account', 'تنظیم نشده' in df.invoice_message('2026-10-23', 9.0, 10, 0.9, due, tz, ''))
check('backtick in account is neutralised', '`' not in df.invoice_message('d', 1, 10, .1, due, tz, 'a`b').split('واریز کنید:')[1].replace('`', '', 2))
check('blocked/paid messages render', 'مسدود' in df.blocked_message('2026-10-23', .9, 'X') and 'فعال' in df.paid_message('2026-10-23', .9))
check('paid message warns if still blocked', 'مسدود می‌ماند' in df.paid_message('d', 1, True))

check('user may press claim button', ap.user_command_allowed('/fee_claim_12'))
check('user may not press admin confirm / debts', not ap.user_command_allowed('/fee_ok_12') and not ap.user_command_allowed('/fee_debts')
      and not ap.user_command_allowed('/fee_paid 1') and not ap.user_command_allowed('/set_fee_account x'))
sys.exit(0 if ok else 1)
