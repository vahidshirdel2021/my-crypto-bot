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

مثال اجرا — تست استراتژی واقعی زنده (Liquidity Sweep روی 5 دقیقه‌ای، همان
چیزی که در ربات با active_strategy=dynamic اجرا می‌شود، شامل پلکان سه‌مرحله‌ای
TP و تریلینگ‌استاپ ساختاری):
    python backtest.py --symbol DOT/USDT:USDT --timeframe 5m \
        --start 2026-07-01 --end 2026-08-01 \
        --strategy dynamic --side both

استراتژی‌های قابل انتخاب: trend | breakout | mean_reversion | dynamic
(دقیقاً همان‌هایی که در منوی ربات هستند. برای 5m/15m، dynamic دقیقاً همان
منطق Liquidity Sweep + پلکان PDH/EQ/PDL را که در bot.py فعال است شبیه‌سازی
می‌کند. برای تایم‌فریم‌های بالاتر [1h/4h]، dynamic معادل breakout با فیلتر
جهت دستی شبیه‌سازی می‌شود؛ یعنی --strategy breakout --side long/short همان
رفتار dynamic را در یک رژیم قطعی شبیه‌سازی می‌کند.)

توجه (به‌روزرسانی معماری): این بک‌تست اکنون دقیقاً همان رفتار جدید bot.py را
شبیه‌سازی می‌کند: پلکان سه‌مرحله‌ای TP (۵۰٪ روی EQ + انتقال SL به Break-even،
۳۰٪ روی مرز مقابل رنج، ۲۰٪ باقی‌مانده روی اکستنشن)، تریلینگ‌استاپ ساختاری بر
اساس سوینگ (compute_swing_stop، همان تابع bot.py)، و **بدون** هیچ خروج
زودهنگام/هوشمند بر اساس ضعف اندیکاتور یا MFE (آن منطق طبق تصمیم معماری از
bot.py و از این بک‌تست هر دو حذف شده است).
"""

import argparse

import pandas as pd

from signal_engine.common.htf import closed_htf_slice, primary_decision_close_ms

from strategy import (
    calculate_indicators, get_signal_with_reason, build_trade_plan, compute_swing_stop,
    FILTER_DEFAULTS, STRATEGY_DEFAULTS, TIMEFRAME_PARAM_ADJUST,
)

PAPER_CONSERVATIVE_OHLC = True  # اگر در یک کندل هم SL و هم TP لمس شود، بدترین حالت (SL) فرض می‌شود؛ دقیقاً مطابق bot.py


# ---------------------------------------------------------------------------
# تریلینگ‌استاپ ساختاری بر اساس سوینگ — دقیقاً همان تابع strategy.compute_swing_stop
# که bot.py هم برای مدیریت پوزیشن باز استفاده می‌کند (به‌جای پلکان قدیمی R که
# اینجا بود و اکنون از هر دو فایل حذف شده است).
# ---------------------------------------------------------------------------


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
    df['timestamp'] = df['ts']  # strategy.py برای محاسبه PDH/PDL روزانه ستون 'timestamp' را انتظار دارد
    return df


# ---------------------------------------------------------------------------
# هسته بک‌تست: دقیقاً مطابق strategy.py + منطق مدیریت پوزیشن paper در bot.py
# ---------------------------------------------------------------------------
# نگاشت تایم‌فریم سبک ccxt (که برای دانلود داده استفاده می‌شود) به کلید تایم‌فریم استراتژی
# (که آستانه‌های ADX/امتیاز/R:R را بر اساس آن تنظیم می‌کند - مطابق TIMEFRAME_PARAM_ADJUST در strategy.py)
CCXT_TO_STRATEGY_TF = {
    '5m': '5min', '15m': '15min', '1h': '1hour', '4h': '4hour', '1d': '1day',
}


def run_backtest(df, strategy_type='breakout', side='both', filters=None, strategy_config=None,
                  margin_usdt=50.0, leverage=5, taker_fee_pct=0.05, use_trailing=True,
                  strategy_timeframe='1hour', htf_frames=None):
    """
    htf_frames: دیکشنری اختیاری {'1d': daily_df, '4h': four_h_df, ...} برای فعال‌سازی
    واقعی فیلتر روند ساختاری HTF در بک‌تست (همان کلیدهایی که get_signal_with_reason
    در strategy.py انتظار دارد). هر دیتافریم باید ستون 'timestamp' (ثانیه یا میلی‌ثانیه،
    خودکار تشخیص داده می‌شود) داشته باشد. در هر گام فقط کندل‌های HTF که قبل از زمان
    کندل جاری primary کامل شده‌اند به مدل داده می‌شود (بدون نگاه به آینده).
    """
    filters = {**FILTER_DEFAULTS, **(filters or {})}
    strategy_config = {**STRATEGY_DEFAULTS, **(strategy_config or {})}

    ind = calculate_indicators(df)
    if ind.empty or len(ind) < 65:
        raise RuntimeError('داده کافی نیست (حداقل ~۶۵ کندل لازم است).')

    ts_col = 'ts' if 'ts' in ind.columns else 'timestamp'
    htf_frames = htf_frames or {}
    htf_ts = {}
    for key, hdf in htf_frames.items():
        if hdf is None or hdf.empty:
            continue
        h = hdf.copy()
        h['timestamp'] = pd.to_numeric(h['timestamp'], errors='coerce')
        h = h.dropna(subset=['timestamp']).sort_values('timestamp').reset_index(drop=True)
        htf_ts[key] = h

    def _htf_slice_at(decision_close_ms):
        # IMPORTANT: HTF timestamps are candle OPEN times. A candle is usable
        # only after its actual CLOSE time has passed. This mirrors live behavior.
        md = {}
        key_to_tf = {
            '1h': '1h', '4h': '4h', '1d': '1d', '1w': '1w',
        }
        for key, h in htf_ts.items():
            tf = key_to_tf.get(key, key)
            try:
                closed = closed_htf_slice(h, decision_close_ms, tf)
            except ValueError:
                continue
            if len(closed) >= 20:
                md[key] = closed
        return md or None


    trades = []
    n = len(ind)
    i = 60
    while i < n - 1:
        # پنجره‌ای که آخرین کندل کامل‌شده روی ایندکس -2 آن قرار دارد (دقیقاً مطابق نحوه فراخوانی در bot.py)
        window = ind.iloc[: i + 2]
        decision_close_ms = primary_decision_close_ms(window, strategy_timeframe)
        market_data_dict = _htf_slice_at(decision_close_ms) if htf_ts and decision_close_ms is not None else None
        sig, reason = get_signal_with_reason(
            window, market_data_dict=market_data_dict, timeframe_mode='single', timeframe=strategy_timeframe,
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

        plan, _ = build_trade_plan(window, sig, strategy_config, strategy_type, strategy_timeframe,
                                    market_data_dict=market_data_dict)
        if not plan:
            i += 1
            continue

        entry = plan['entry']; sl = plan['sl']; tp = plan['tp']
        tp1 = plan.get('tp1', tp); tp2 = plan.get('tp2', tp); tp3 = plan.get('tp3', tp)
        tp1_pct = float(plan.get('tp1_pct') or 0.0); tp2_pct = float(plan.get('tp2_pct') or 0.0)
        tp3_pct = float(plan.get('tp3_pct') or (1.0 - tp1_pct - tp2_pct))
        is_long = (sig == 'BUY')
        risk_distance = abs(entry - sl)
        entry_idx = i  # کندل i همان کندلی است که سیگنال روی close آن صادر شده (window.iloc[-2])
        entry_time = ind.iloc[entry_idx]['ts'] if 'ts' in ind.columns else entry_idx

        cur_sl = sl
        tp1_done = False; tp2_done = False; breakeven_done = False
        trailing_activated = False; swing_level = None
        exit_price = None
        exit_reason = None
        exit_idx = None

        # پلکان سه‌مرحله‌ای TP (بند ۴): سود/کارمزد هر پله جداگانه محاسبه و
        # در پایان با پای نهایی جمع می‌شود — دقیقاً مطابق _partial_close_position
        # + close_position در bot.py.
        notional_full = margin_usdt * leverage
        fee_pct = taker_fee_pct / 100.0
        partial_legs = []  # هر ورودی: (fraction, exit_price, reason)

        j = entry_idx + 1
        while j < n:
            row = ind.iloc[j]
            high, low, close = float(row['high']), float(row['low']), float(row['close'])

            # --- Tier 1: نیمی از حجم دقیقاً روی EQ ---
            if not tp1_done and tp1_pct > 0:
                hit1 = (high >= tp1) if is_long else (low <= tp1)
                if hit1:
                    tp1_done = True
                    partial_legs.append((tp1_pct, tp1, 'TP1 (EQ)'))
                    cur_sl = entry  # Break-even کل باقی‌مانده بلافاصله پس از پله اول
                    breakeven_done = True

            # --- Tier 2: ۳۰٪ حجم روی مرز مقابل رنج (فقط پس از تکمیل پله اول) ---
            if tp1_done and not tp2_done and tp2_pct > 0:
                hit2 = (high >= tp2) if is_long else (low <= tp2)
                if hit2:
                    tp2_done = True
                    partial_legs.append((tp2_pct, tp2, 'TP2 (مرز مقابل)'))

            # --- Tier 3 (باقی‌مانده) و SL نهایی ---
            hit_tp3 = (high >= tp3) if is_long else (low <= tp3)
            hit_sl = (low <= cur_sl) if is_long else (high >= cur_sl)
            if hit_tp3 and hit_sl and PAPER_CONSERVATIVE_OHLC:
                exit_price, exit_reason = cur_sl, ('SL (Break-even)' if breakeven_done else 'SL')
            elif hit_tp3:
                exit_price, exit_reason = tp3, 'TP3 (اکستنشن نهایی)'
            elif hit_sl:
                exit_price, exit_reason = cur_sl, ('SL (Break-even)' if breakeven_done else 'SL')

            if exit_price is not None:
                exit_idx = j
                break

            # --- تریلینگ‌استاپ ساختاری بر اساس سوینگ (بند ۵)، فقط بهبود SL، هرگز بدتر ---
            if use_trailing and filters.get('trailing_stop', True):
                swing_df = ind.iloc[: j + 1]
                new_sl, sw_level = compute_swing_stop(
                    swing_df, is_long,
                    lookback=int(strategy_config.get('swing_lookback', 12)),
                    buffer_atr=float(strategy_config.get('swing_buffer_atr', 0.40)),
                    confirm_candles=int(strategy_config.get('swing_confirm_candles', 2)),
                    buffer_wick_pct=float(strategy_config.get('swing_buffer_wick_pct', 0.0015)),
                )
                if new_sl is not None:
                    is_better = (new_sl > cur_sl) if is_long else (new_sl < cur_sl)
                    if is_better:
                        cur_sl = new_sl
                        swing_level = sw_level
                        trailing_activated = True

            # مدیریت هوشمند/خروج زودهنگام بر اساس ضعف روند یا MFE عمداً اینجا
            # وجود ندارد (بند ۳ درخواست کاربر): تنها راه خروج، پلکان TP یا SL است.

            j += 1

        if exit_price is None:
            exit_price = float(ind.iloc[-1]['close'])
            exit_reason = 'پایان بازه داده (باز مانده)'
            exit_idx = n - 1

        # --- جمع‌بندی PnL کل معامله (پله‌های جزئی + پای نهایی) ---
        total_pnl_usdt = 0.0
        total_fee_usdt = 0.0
        for frac, leg_price, _leg_reason in partial_legs:
            leg_notional = notional_full * frac
            leg_move = ((leg_price - entry) / entry) if is_long else ((entry - leg_price) / entry)
            leg_fee = leg_notional * fee_pct  # فقط پای خروج این پله (تقریب معقول، مطابق _partial_close_position)
            total_pnl_usdt += leg_notional * leg_move - leg_fee
            total_fee_usdt += leg_fee

        final_frac = max(0.0, 1.0 - sum(f for f, _, _ in partial_legs))
        final_notional = notional_full * final_frac
        final_move = ((exit_price - entry) / entry) if is_long else ((entry - exit_price) / entry)
        final_fee = final_notional * fee_pct * 2  # پای ورود + پای خروج نهایی (تقریب رفت‌وبرگشت کامل)
        total_pnl_usdt += final_notional * final_move - final_fee
        total_fee_usdt += final_fee

        realized_r = (total_pnl_usdt + total_fee_usdt) / (margin_usdt * leverage * (risk_distance / entry)) if risk_distance else 0.0
        tiers_hit = '+'.join([leg_reason for _, _, leg_reason in partial_legs] + [exit_reason])

        trades.append({
            'side': 'LONG' if is_long else 'SHORT',
            'entry_time': entry_time,
            'entry': entry, 'sl_initial': sl, 'tp1': tp1, 'tp2': tp2, 'tp': tp3,
            'exit': exit_price, 'exit_reason': exit_reason, 'tiers_hit': tiers_hit,
            'trailing_activated': trailing_activated, 'breakeven_done': breakeven_done,
            'quality_score': plan['score'], 'planned_rr': plan['rr'],
            'realized_r': realized_r, 'pnl_usdt': total_pnl_usdt, 'fee_usdt': total_fee_usdt,
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
    ap.add_argument('--strategy', default='breakout', choices=['trend', 'breakout', 'mean_reversion', 'dynamic'])
    ap.add_argument('--side', default='both', choices=['long', 'short', 'both'])
    ap.add_argument('--margin', type=float, default=50.0)
    ap.add_argument('--leverage', type=int, default=5)
    ap.add_argument('--no-trailing', action='store_true', help='تریلینگ‌استاپ را خاموش کن (برای مقایسه)')
    ap.add_argument('--legacy', action='store_true',
                     help='برای مقایسه‌ی قبل/بعد: تمام فیلترهای اضافه‌شده‌ی این نسخه را خاموش می‌کند '
                          '(reclaim-confirm، فیلتر روند HTF، سوینگ فرکتال پیشرفته، قفل‌سود پله‌ای/ATR) '
                          'تا دقیقاً روی همان داده با کد قدیمی مقایسه شود')
    ap.add_argument('--strategy-timeframe', default=None, choices=list(TIMEFRAME_PARAM_ADJUST.keys()),
                     help='کلید تایم‌فریم برای آستانه‌های ADX/امتیاز/R:R (پیش‌فرض: نگاشت خودکار از --timeframe)')
    ap.add_argument('--csv', default=None, help='مسیر خروجی CSV اختیاری برای لیست کامل معاملات')
    args = ap.parse_args()

    strategy_tf = args.strategy_timeframe or CCXT_TO_STRATEGY_TF.get(args.timeframe, '1hour')
    print(f'⏳ دریافت داده {args.symbol} | {args.timeframe} | {args.start} تا {args.end} از CoinEx ...')
    df = fetch_ohlcv_coinex(args.symbol, args.timeframe, args.start, args.end)
    print(f'✅ {len(df)} کندل دریافت شد. | آستانه‌های استراتژی بر اساس تایم‌فریم: {strategy_tf}')

    # داده‌ی HTF برای فیلتر روند ساختاری (فقط اگر --legacy نباشد، چون آن‌جا این فیلتر
    # خاموش است و گرفتن این داده صرفاً وقت تلف می‌کند). با ~۲۰۰ روز عقب‌تر از --start
    # شروع می‌کنیم تا سوینگ‌های HTF لازم برای همان اولین کندل‌های بازه هم موجود باشند.
    htf_frames = {}
    if not args.legacy:
        htf_start = (pd.Timestamp(args.start) - pd.Timedelta(days=220)).strftime('%Y-%m-%d')
        try:
            print('⏳ دریافت داده روزانه (برای فیلتر روند HTF) ...')
            htf_frames['1d'] = fetch_ohlcv_coinex(args.symbol, '1d', htf_start, args.end)
            if strategy_tf == '1hour':
                print('⏳ دریافت داده ۴ساعته (برای فیلتر روند HTF) ...')
                htf_frames['4h'] = fetch_ohlcv_coinex(args.symbol, '4h', htf_start, args.end)
        except Exception as exc:
            print(f'⚠️ دریافت داده HTF ناموفق بود ({exc})؛ فیلتر روند HTF در این اجرا عملاً غیرفعال می‌ماند.')
            htf_frames = {}

    legacy_cfg_override = None
    if args.legacy:
        legacy_cfg_override = {
            "require_reclaim_confirm": False,   # B1/B3/S1/S3 بدون شرط ری‌کلیم (رفتار قدیم)
            "htf_trend_filter_enabled": False,  # بدون بلاک خلاف‌جهت HTF
            "use_advanced_swing_stop": False,   # تریلینگ با رولینگ‌مینیمم قدیمی به‌جای سوینگ فرکتال
            "profit_lock_r_ladder": [],         # بدون قفل سود پله‌ای
            "atr_trail_start_r": 999.0,         # عملاً تریلینگ ATR فعال را خاموش می‌کند
            "multi_level_source_fallback_enabled": False,  # بدون فال‌بک هفتگی/ماهانه
        }
        print('⚠️  حالت --legacy فعال است: reclaim-confirm، فیلتر HTF، سوینگ پیشرفته و قفل‌سود پله‌ای/ATR خاموش شدند.')

    trades = run_backtest(
        df, strategy_type=args.strategy, side=args.side,
        margin_usdt=args.margin, leverage=args.leverage,
        use_trailing=not args.no_trailing,
        strategy_timeframe=strategy_tf,
        strategy_config=legacy_cfg_override,
        htf_frames=htf_frames,
    )
    summarize(trades)

    if args.csv and trades:
        pd.DataFrame(trades).to_csv(args.csv, index=False)
        print(f'\n💾 لیست کامل معاملات ذخیره شد: {args.csv}')


if __name__ == '__main__':
    main()
