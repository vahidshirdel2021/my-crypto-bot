# -*- coding: utf-8 -*-
"""V3.44.61: کارمزد روزانه (به‌جای کسر کارمزد از تک‌تک معاملات).

منطق: کارمزد پلتفرم موقع بسته‌شدن هر معامله کم نمی‌شود. آخر هر روز، مجموع سود/زیان خالص همان روز هر کاربر
حساب می‌شود؛ اگر مجموع مثبت بود، «فاکتور» کارمزد (درصد × سود روز) ساخته می‌شود و به کاربر پیام می‌رود که تا
ساعت مشخصی (پیش‌فرض ۱۲:۰۰ روز بعد) آن را به حساب ادمین واریز کند؛ در غیر این صورت ورود معامله‌ی جدید برایش مسدود می‌شود.

این فایل عمداً مستقل از bot.py است (فقط محاسبه و متن پیام) تا بدون تلگرام و بدون ccxt قابل تست باشد.
دیتابیس، تلگرام و حلقه‌ی زمانی در bot.py هستند.
"""
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
except Exception:          # pragma: no cover
    ZoneInfo = None

DAY_FMT = '%Y-%m-%d'


def get_tz(name):
    """منطقه‌ی زمانی را برمی‌گرداند؛ اگر zoneinfo نبود، برای تهران UTC+3:30 ثابت (بدون DST) و برای بقیه UTC."""
    name = (name or 'UTC').strip()
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:
            pass
    if name == 'Asia/Tehran':
        return timezone(timedelta(hours=3, minutes=30))
    return timezone.utc


def day_key(ts, tz):
    return datetime.fromtimestamp(float(ts), tz).strftime(DAY_FMT)


def day_bounds(day, tz):
    """(شروع، پایان) یک روز تقویمی (YYYY-MM-DD) در منطقه‌ی tz به‌صورت timestamp؛ پایان خودش جزو روز نیست."""
    d = datetime.strptime(day, DAY_FMT)
    start = datetime(d.year, d.month, d.day, tzinfo=tz)
    nxt = d + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    return start.timestamp(), end.timestamp()


def shift_day(day, delta):
    return (datetime.strptime(day, DAY_FMT) + timedelta(days=int(delta))).strftime(DAY_FMT)


def days_after(last_day, upto_day, max_days=7):
    """روزهای بعد از last_day تا upto_day (هر دو شامل upto)، قدیمی‌ترین اول؛ حداکثر max_days روز آخر."""
    out = []
    d = shift_day(last_day, 1)
    while d <= upto_day and len(out) < 400:
        out.append(d)
        d = shift_day(d, 1)
    return out[-int(max_days):] if max_days else out


def day_profit(closed_positions, start_ts, end_ts, include_paper=True):
    """(جمع PnL خالص، تعداد معامله) معاملات بسته‌شده در [start_ts, end_ts).

    معامله‌ای که قبلاً در حالت قدیمی «کسر از هر معامله» تسویه شده (platform_fee_status == 'SETTLED')
    شمرده نمی‌شود تا موقع گذار به حالت روزانه دوبار کارمزد گرفته نشود.
    """
    total = 0.0
    n = 0
    for p in closed_positions or []:
        try:
            ts = float(p.get('close_timestamp') or 0)
        except Exception:
            continue
        if not (start_ts <= ts < end_ts):
            continue
        if p.get('platform_fee_status') == 'SETTLED':
            continue
        if not include_paper and not p.get('is_real'):
            continue
        try:
            total += float(p.get('pnl_usdt') or 0.0)
        except Exception:
            continue
        n += 1
    return total, n


def compute_fee(profit, rate_pct, min_profit=0.01):
    """کارمزد = سود × نرخ٪ (گرد‌شده به ۲ رقم)؛ فقط وقتی سود روز از حداقل بیشتر باشد. در غیر این صورت ۰."""
    try:
        profit = float(profit)
        rate = min(100.0, max(0.0, float(rate_pct)))
    except Exception:
        return 0.0
    if profit <= float(min_profit):
        return 0.0
    return round(profit * rate / 100.0, 2)


def due_timestamp(created_ts, tz, due_hour=12, min_grace_hours=6):
    """مهلت پرداخت: ساعت due_hour همان روزی که فاکتور ساخته شد؛ ولی اگر فاکتور دیر ساخته شد (مثلاً ربات
    خاموش بوده)، حداقل min_grace_hours ساعت از لحظه‌ی ساخت مهلت داده می‌شود تا فوراً مسدود نشود."""
    now = datetime.fromtimestamp(float(created_ts), tz)
    due = now.replace(hour=int(due_hour), minute=0, second=0, microsecond=0)
    return max(due.timestamp(), float(created_ts) + float(min_grace_hours) * 3600.0)


def fmt_due(due_ts, tz):
    dt = datetime.fromtimestamp(float(due_ts), tz)
    return dt.strftime('%H:%M')


def _clean(text):
    return str(text or '').replace('`', "'").strip()


def invoice_message(day, profit, rate_pct, fee, due_ts, tz, account, tz_label=''):
    acct = _clean(account)
    acct_line = (f'`{acct}`' if acct else '⚠️ حساب پرداخت هنوز توسط ادمین تنظیم نشده؛ لطفاً با ادمین هماهنگ کنید.')
    tzl = f' ({tz_label})' if tz_label else ''
    return (f'💰 *کارمزد روزانه*\n\n'
            f'دیروز ({day}) سود خالص شما `{profit:+.2f} USDT` بود.\n'
            f'کارمزد پلتفرم ({rate_pct:g}٪): `{fee:.2f} USDT`\n\n'
            f'⏰ تا ساعت `{fmt_due(due_ts, tz)}`{tzl} امروز فرصت دارید کارمزد معاملاتتان را به حساب ادمین واریز کنید:\n'
            f'{acct_line}\n\n'
            f'⚠️ در صورت عدم واریز، حساب شما مسدود می‌شود (ورود معامله‌ی جدید ممکن نیست).\n'
            f'بعد از واریز، دکمه‌ی «✅ واریز کردم» را بزنید تا ادمین بررسی و تایید کند.')


def blocked_message(day, fee, account):
    acct = _clean(account)
    acct_line = f'\n{chr(96)}{acct}{chr(96)}' if acct else ''
    return (f'⛔ *حساب شما مسدود شد*\n\n'
            f'مهلت پرداخت کارمزد روز {day} (`{fee:.2f} USDT`) تمام شد و واریز تایید نشده است.\n'
            f'ورود معامله‌ی جدید غیرفعال است؛ پوزیشن‌های باز همچنان توسط ربات مدیریت می‌شوند.'
            f'{acct_line}\n\n'
            f'بعد از واریز، دکمه‌ی «✅ واریز کردم» را بزنید؛ با تایید ادمین حساب فوراً باز می‌شود.')


def paid_message(day, fee, still_blocked=False):
    tail = '\n⚠️ هنوز فاکتور پرداخت‌نشده‌ی دیگری دارید؛ حساب شما تا تسویه‌ی آن مسدود می‌ماند.' if still_blocked \
        else '\n✅ حساب شما فعال است.'
    return f'✅ پرداخت کارمزد روز {day} (`{fee:.2f} USDT`) تایید شد.{tail}'
