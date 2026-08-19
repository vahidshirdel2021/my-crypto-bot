# -*- coding: utf-8 -*-
"""
بک‌تست استراتژی‌های ربات روی داده تاریخی CoinEx
=================================================

این اسکریپت دقیقاً همان منطق فایل strategy.py (تولید سیگنال، محاسبه SL/TP و
امتیاز کیفیت) و همان منطق حد ضرر دنبال‌کننده (trailing stop) که در bot.py
پیاده‌سازی شده را روی داده کندل تاریخی اجرا می‌کند تا نتیجه واقعی هر
استراتژی/جهت را روی یک بازه زمانی مشخص (مثلاً یک ماه صعودی یا نزولی) بسنجد.

⚠️ این اسکریپت باید جایی اجرا شود که به اینترنت و API عمومی CoinEx دسترسی
دارد (مثلاً همان سروری که ربات روی آن دیپلوی شده). محیط چتی که این فایل در
آن ساخته شده، دسترسی شبکه ندارد و نمی‌تواند مستقیماً داده را دانلود کند.

نصب پیش‌نیاز:
    pip install ccxt pandas numpy

مثال اجرا — تست Long روی یک ماه صعودی:
    python backtest.py --symbol BTC/USDT:USDT --timeframe 15m \
        --start 2025-10-01 --end 2025-11-01 \
        --strategy breakout --side long

مثال اجرا — تست Short روی یک ماه نزولی:
    python backtest.py --symbol BTC/USDT:USDT --timeframe 15m \
        --start 2025-02-01 --end 2025-03-01 \
        --strategy breakout --side short

استراتژی‌های قابل انتخاب: trend | breakout | mean_reversion
(دقیقاً همان‌هایی که در منوی ربات هستند. dynamic چون به رژیم لحظه‌ای بازار
[هم‌راستایی BTC/ETH] وابسته است، در اینجا معادل breakout با فیلتر جهت دستی
شبیه‌سازی می‌شود؛ یعنی --strategy breakout --side long/short همان رفتار
dynamic را در یک رژیم قطعی شبیه‌سازی می‌کند.)
"""

import argparse
import math

import pandas as pd

from strategy import (
    calculate_indicators, get_signal_with_reason, build_trade_plan,
    FILTER_DEFAULTS, STRATEGY_DEFAULTS, TIMEFRAME_PARAM_ADJUST,
)

PAPER_CONSERVATIVE_OHLC = True  # اگر در یک کندل هم SL و هم TP لمس شود، بدترین حالت (SL) فرض می‌شود؛ دقیقاً مطابق bot.py


# ---------------------------------------------------------------------------
# همان فرمول قفل حد ضرر دنبال‌کننده که در bot.py هست (خط به خط یکسان)
# ---------------------------------------------------------------------------
def trailing_locked_r(entry, risk_distance, current_price, is_long):
    try:
        entry = float(entry); risk_distance = float(risk_distance); current_price = float(current_price)
    except Exception:
        return None
    if risk_distance <= 0 or not math.isfinite(risk_distance):
        return None
    r = (current_price - entry) / risk_distance if is_long else (entry - current_price) / risk_distance
    if r < 1.0:
        return None
    step = math.floor(r * 2) / 2.0
    return max(0.0, step - 1.0)


# ---------------------------------------------------------------------------
# دانلود داده تاریخی از CoinEx با ccxt (صفحه‌بندی خودکار)
# ---------------------------------------------------------------------------
def fetch_ohlcv_coinex(symbol, timeframe, start_iso, end_iso, market_type='swap'):
    import time as _time
    import ccxt  # وارد کردن دیرهنگام تا بدون نصب ccxt هم بقیه اسکریپت قابل استفاده/تست باشد

    exchange = ccxt.coinex({
        'enableRateLimit': True,
        'timeout': 30000,
        'options': {
            'defaultType': market_type,
        },
    })
    # این مرحله (گرفتن لیست ارزها/تنظیمات واریز-برداشت) برای دریافت کندل لازم نیست و
    # روی برخی VPN/ISPها این endpoint خاص Fail می‌شود؛ با غیرفعال‌کردن قابلیت آن در ccxt کاملاً دورش می‌زنیم.
    exchange.has['fetchCurrencies'] = False

    def _with_retry(fn, *a, retries=5, delay=3, **kw):
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                return fn(*a, **kw)
            except Exception as exc:
                last_err = exc
                print(f'⚠️ تلاش {attempt}/{retries} ناموفق ({exc.__class__.__name__}: {exc}); {delay} ثانیه صبر و تلاش دوباره...')
                _time.sleep(delay)
        raise last_err

    _with_retry(exchange.load_markets)
    since = exchange.parse8601(start_iso + 'T00:00:00Z')
    until = exchange.parse8601(end_iso + 'T00:00:00Z')
    rows = []
    cursor = since
    limit = 1000
    while True:
        batch = _with_retry(exchange.fetch_ohlcv, symbol, timeframe=timeframe, since=cursor, limit=limit)
        if not batch:
            break
        rows.extend(batch)
        last_ts = batch[-1][0]
        if last_ts >= until or len(batch) < limit:
            break
        cursor = last_ts + 1
        print(f'  ... {len(rows)} کندل تا الان دریافت شد', end='\r')
    if not rows:
        raise RuntimeError('داده‌ای از CoinEx دریافت نشد؛ نماد/تایم‌فریم/بازه را بررسی کنید.')
    df = pd.DataFrame(rows, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])
    df = df[(df['ts'] >= since) & (df['ts'] <= until)].drop_duplicates('ts').reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# هسته بک‌تست: دقیقاً مطابق strategy.py + منطق مدیریت پوزیشن paper در bot.py
# ---------------------------------------------------------------------------
# نگاشت تایم‌فریم سبک ccxt (که برای دانلود داده استفاده می‌شود) به کلید تایم‌فریم استراتژی
# (که آستانه‌های ADX/امتیاز/R:R را بر اساس آن تنظیم می‌کند - مطابق TIMEFRAME_PARAM_ADJUST در strategy.py)
CCXT_TO_STRATEGY_TF = {
    '5m': '5min', '15m': '15min', '1h': '1hour', '4h': '4hour', '1d': 'multi',
}


def run_backtest(df, strategy_type='breakout', side='both', filters=None, strategy_config=None,
                  margin_usdt=50.0, leverage=5, taker_fee_pct=0.05, use_trailing=True,
                  strategy_timeframe='1hour'):
    filters = {**FILTER_DEFAULTS, **(filters or {})}
    strategy_config = {**STRATEGY_DEFAULTS, **(strategy_config or {})}

    ind = calculate_indicators(df)
    if ind.empty or len(ind) < 65:
        raise RuntimeError('داده کافی نیست (حداقل ~۶۵ کندل لازم است).')

    trades = []
    n = len(ind)
    i = 60
    while i < n - 1:
        # پنجره‌ای که آخرین کندل کامل‌شده روی ایندکس -2 آن قرار دارد (دقیقاً مطابق نحوه فراخوانی در bot.py)
        window = ind.iloc[: i + 2]
        sig, reason = get_signal_with_reason(
            window, timeframe_mode='single', timeframe=strategy_timeframe,
            strategy_type=strategy_type, filters=filters, strategy_config=strategy_config,
        )
        if sig not in ('BUY', 'SELL'):
            i += 1
            continue
        if side == 'long' and sig != 'BUY':
            i += 1
            continue
        if side == 'short' and sig != 'SELL':
            i += 1
            continue

        plan, _ = build_trade_plan(window, sig, strategy_config, strategy_type, strategy_timeframe)
        if not plan:
            i += 1
            continue

        entry = plan['entry']; sl = plan['sl']; tp = plan['tp']
        is_long = (sig == 'BUY')
        risk_distance = abs(entry - sl)
        entry_idx = i  # کندل i همان کندلی است که سیگنال روی close آن صادر شده (window.iloc[-2])
        entry_time = ind.iloc[entry_idx]['ts'] if 'ts' in ind.columns else entry_idx

        cur_sl = sl
        locked_r = 0.0
        trailing_activated = False
        exit_price = None
        exit_reason = None
        exit_idx = None

        j = entry_idx + 1
        while j < n:
            row = ind.iloc[j]
            high, low, close = float(row['high']), float(row['low']), float(row['close'])

            if is_long:
                hit_tp = high >= tp
                hit_sl = low <= cur_sl
            else:
                hit_tp = low <= tp
                hit_sl = high >= cur_sl

            if hit_tp and hit_sl and PAPER_CONSERVATIVE_OHLC:
                exit_price, exit_reason = cur_sl, 'SL (همان کندل)'
            elif hit_tp:
                exit_price, exit_reason = tp, 'TP'
            elif hit_sl:
                exit_price, exit_reason = cur_sl, 'SL'

            if exit_price is not None:
                exit_idx = j
                break

            if use_trailing and filters.get('trailing_stop', True):
                lr = trailing_locked_r(entry, risk_distance, close, is_long)
                if lr is not None:
                    new_sl = entry + (lr * risk_distance if is_long else -lr * risk_distance)
                    is_better = (new_sl > cur_sl) if is_long else (new_sl < cur_sl)
                    if is_better and lr > locked_r:
                        cur_sl = new_sl
                        locked_r = lr
                        trailing_activated = True
            j += 1

        if exit_price is None:
            # پوزیشن تا انتهای بازه داده بسته نشد؛ روی آخرین قیمت موجود می‌بندیم و علامت‌گذاری می‌کنیم
            exit_price = float(ind.iloc[-1]['close'])
            exit_reason = 'پایان بازه داده (باز مانده)'
            exit_idx = n - 1

        price_change_frac = ((exit_price - entry) / entry) if is_long else ((entry - exit_price) / entry)
        notional = margin_usdt * leverage
        fee_usdt = notional * (taker_fee_pct / 100.0) * 2
        pnl_usdt = notional * price_change_frac - fee_usdt
        realized_r = (pnl_usdt + fee_usdt) / (margin_usdt * leverage * (risk_distance / entry)) if risk_distance else 0.0

        trades.append({
            'side': 'LONG' if is_long else 'SHORT',
            'entry_time': entry_time,
            'entry': entry, 'sl_initial': sl, 'tp': tp,
            'exit': exit_price, 'exit_reason': exit_reason,
            'trailing_activated': trailing_activated, 'locked_r': locked_r,
            'quality_score': plan['score'], 'planned_rr': plan['rr'],
            'realized_r': realized_r, 'pnl_usdt': pnl_usdt, 'fee_usdt': fee_usdt,
        })
        i = exit_idx + 1 if exit_idx else i + 1  # تا بسته شدن پوزیشن، سیگنال جدید بررسی نمی‌شود (هم‌زمان با ربات: یک پوزیشن هر نماد)

    return trades


def summarize(trades, initial_balance=1000.0):
    if not trades:
        print('❌ هیچ معامله‌ای در این بازه ثبت نشد (سیگنال/فیلترها هیچ ورودی معتبری تولید نکردند).')
        return
    df = pd.DataFrame(trades)
    wins = df[df['pnl_usdt'] > 0]
    losses = df[df['pnl_usdt'] <= 0]
    win_rate = len(wins) / len(df) * 100
    net_pnl = df['pnl_usdt'].sum()
    gross_win = wins['pnl_usdt'].sum()
    gross_loss = abs(losses['pnl_usdt'].sum())
    pf = (gross_win / gross_loss) if gross_loss > 0 else float('inf')
    avg_r = df['realized_r'].mean()
    equity = initial_balance + df['pnl_usdt'].cumsum()
    running_max = equity.cummax()
    max_dd = (equity - running_max).min()
    trail_rate = df['trailing_activated'].mean() * 100

    print('\n' + '=' * 50)
    print(f'📊 نتیجه بک‌تست  |  {len(df)} معامله')
    print('=' * 50)
    print(f'✅ برد: {len(wins)}   ❌ باخت: {len(losses)}   نرخ موفقیت: {win_rate:.1f}%')
    print(f'💰 سود/زیان خالص: {net_pnl:+.2f} USDT   (موجودی اولیه فرضی: {initial_balance:.0f})')
    print(f'📈 Profit Factor: {"∞" if pf == float("inf") else f"{pf:.2f}"}')
    print(f'⚖️ میانگین R هر معامله: {avg_r:+.2f}R')
    print(f'📉 حداکثر افت سرمایه: {max_dd:+.2f} USDT')
    print(f'🛡️ درصد معاملاتی که تریلینگ‌استاپ فعال شد: {trail_rate:.1f}%')
    print('=' * 50)
    print('\nآخرین ۱۰ معامله:')
    cols = ['entry_time', 'side', 'entry', 'exit', 'exit_reason', 'realized_r', 'pnl_usdt']
    print(df[cols].tail(10).to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description='بک‌تست استراتژی ربات روی داده تاریخی CoinEx')
    ap.add_argument('--symbol', default='BTC/USDT:USDT', help='نماد ccxt، مثال BTC/USDT:USDT')
    ap.add_argument('--timeframe', default='15m', help='5m, 15m, 1h, 4h ...')
    ap.add_argument('--start', required=True, help='YYYY-MM-DD')
    ap.add_argument('--end', required=True, help='YYYY-MM-DD')
    ap.add_argument('--strategy', default='breakout', choices=['trend', 'breakout', 'mean_reversion'])
    ap.add_argument('--side', default='both', choices=['long', 'short', 'both'])
    ap.add_argument('--margin', type=float, default=50.0)
    ap.add_argument('--leverage', type=int, default=5)
    ap.add_argument('--no-trailing', action='store_true', help='تریلینگ‌استاپ را خاموش کن (برای مقایسه)')
    ap.add_argument('--strategy-timeframe', default=None, choices=list(TIMEFRAME_PARAM_ADJUST.keys()),
                     help='کلید تایم‌فریم برای آستانه‌های ADX/امتیاز/R:R (پیش‌فرض: نگاشت خودکار از --timeframe)')
    ap.add_argument('--csv', default=None, help='مسیر خروجی CSV اختیاری برای لیست کامل معاملات')
    args = ap.parse_args()

    strategy_tf = args.strategy_timeframe or CCXT_TO_STRATEGY_TF.get(args.timeframe, '1hour')
    print(f'⏳ دریافت داده {args.symbol} | {args.timeframe} | {args.start} تا {args.end} از CoinEx ...')
    df = fetch_ohlcv_coinex(args.symbol, args.timeframe, args.start, args.end)
    print(f'✅ {len(df)} کندل دریافت شد. | آستانه‌های استراتژی بر اساس تایم‌فریم: {strategy_tf}')

    trades = run_backtest(
        df, strategy_type=args.strategy, side=args.side,
        margin_usdt=args.margin, leverage=args.leverage,
        use_trailing=not args.no_trailing,
        strategy_timeframe=strategy_tf,
    )
    summarize(trades)

    if args.csv and trades:
        pd.DataFrame(trades).to_csv(args.csv, index=False)
        print(f'\n💾 لیست کامل معاملات ذخیره شد: {args.csv}')


if __name__ == '__main__':
    main()
