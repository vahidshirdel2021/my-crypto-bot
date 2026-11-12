# -*- coding: utf-8 -*-
"""
بک‌تست داخل ربات (V3.44.125)
============================
همان مسیر زنده‌ی ربات را روی کندل‌های تاریخی دوباره اجرا می‌کند، با تنظیمات خودِ همان کاربر:
    calculate_indicators -> get_signal_with_reason -> build_trade_plan -> مدیریت SL/TP/تریلینگ

قواعد بدون نشت آینده (look-ahead):
  * در هر قدم فقط کندل‌های «بسته‌شده» تا آن لحظه دیده می‌شوند؛ ردیف «در حال تشکیل» فقط قیمت بازشدنِ کندل بعدی است
    (open=high=low=close)، دقیقاً مثل لحظه‌ای که ربات بعد از کلوز کندل اسکن می‌کند.
  * کندل‌های ۱ساعته/۴ساعته از خودِ کندل‌های ۱۵دقیقه ساخته می‌شوند و کندل ناقصِ ساعت جاری فقط تا همان لحظه جمع می‌شود.
  * اگر در یک کندل هم SL و هم TP لمس شود، SL حساب می‌شود (همان PAPER_CONSERVATIVE_OHLC ربات).

گیت‌های ورودی BTC (V3.44.127) از طریق entry_gate اختیاری وصل می‌شوند (bt_btc_gates.py).
حالت چندتایم‌فریمی (V3.44.160): اگر cfg['mtf_mode_enabled'] روشن و تایم‌فریم ۵/۱۵ دقیقه باشد، کندل‌های ۱ ساعته از خودِ کندل‌های
ورود ساخته می‌شوند (ساعت جاری ناقص و فقط تا لحظه‌ی همان قدم) و ATR هموار ۱ ساعته (میانه‌ی ۲۰۰ کندل بسته‌شده) برای درخت سطوح
در هر قدم تازه می‌شود؛ سطوح و واکنش از ۱ ساعته، ورود از کندل بسته‌شده‌ی ۵/۱۵ دقیقه (strategy_halving_mtf).
آنچه عمداً شبیه‌سازی نمی‌شود (در خروجی هم نوشته می‌شود): رأی‌گیری فیلترها، صف تایید، فیلتر ساعت،
سقف ریسک روزانه، ورود/خروج پله‌ای (tp_stages)، محافظ BTC بعد از ورود و هم‌جهتی با بازار (۱۰ شاخص).
"""
from __future__ import annotations

import time
from typing import Callable, Dict, List, Optional

import numpy as np
import pandas as pd

from strategy import calculate_indicators, get_signal_with_reason, build_trade_plan

TF_MS = {'5min': 300_000, '15min': 900_000, '1hour': 3_600_000, '4hour': 14_400_000, '1day': 86_400_000}
WINDOW = 650          # همان klimit زنده برای 5m/15m/1h
HTF_LIMIT = 160       # همان limit زنده برای 1h/4h
WARMUP = 700          # حداقل کندل قبل از شروع بازه


def _htf_groups(ts: np.ndarray, period_ms: int) -> np.ndarray:
    return (ts // period_ms).astype(np.int64)


def _build_htf_complete(df: pd.DataFrame, period_ms: int):
    """کندل‌های کامل HTF + شناسه گروه هر کندل ۱۵دقیقه‌ای. خروجی: (frame بر اساس group، آرایه group هر ردیف)."""
    g = _htf_groups(df['timestamp'].values.astype(np.int64), period_ms)
    agg = df.assign(_g=g).groupby('_g', sort=True).agg(
        timestamp=('timestamp', 'first'), open=('open', 'first'), high=('high', 'max'),
        low=('low', 'min'), close=('close', 'last'), volume=('volume', 'sum'))
    agg['timestamp'] = agg.index.values.astype(np.int64) * period_ms
    return agg, g


def _htf_view(agg: pd.DataFrame, g: np.ndarray, df: pd.DataFrame, i: int):
    """HTF تا لحظه‌ی کلوز کندل i: گروه‌های قبلی کامل + گروه جاری فقط تا کندل i (ناقص)."""
    gi = int(g[i])
    done = agg.loc[agg.index < gi].tail(HTF_LIMIT - 1)
    j0 = i
    while j0 > 0 and g[j0 - 1] == gi:
        j0 -= 1
    part = df.iloc[j0:i + 1]
    row = {'timestamp': int(gi * 0), 'open': float(part['open'].iloc[0]), 'high': float(part['high'].max()),
           'low': float(part['low'].min()), 'close': float(part['close'].iloc[-1]), 'volume': float(part['volume'].sum())}
    cur = pd.DataFrame([row])
    cur['timestamp'] = int(agg.loc[gi, 'timestamp']) if gi in agg.index else int(part['timestamp'].iloc[0])
    out = pd.concat([done.reset_index(drop=True)[['timestamp', 'open', 'high', 'low', 'close', 'volume']], cur], ignore_index=True)
    return out


def simulate(df: pd.DataFrame, cfg: dict, filters: dict, timeframe: str = '15min', start_ms: Optional[int] = None,
             end_ms: Optional[int] = None, margin: float = 50.0, leverage: float = 5.0, fee_pct: float = 0.05,
             start_balance: float = 1000.0, trail_enabled: bool = True, trail_profile: str = 'balanced',
             trail_fn: Optional[Callable] = None, side_text=('BUY (Long)', 'SELL (Short)'),
             progress: Optional[Callable[[int, int], None]] = None, strategy_type: str = 'dynamic',
             cooldown_bars: int = 0, max_seconds: Optional[float] = None,
             entry_gate: Optional[Callable] = None) -> Dict:
    """کندل‌های df باید صعودی و شامل ستون‌های timestamp(ms)/open/high/low/close/volume باشند و کمی قبل از start_ms شروع شوند."""
    df = df.sort_values('timestamp').reset_index(drop=True)
    for c in ('open', 'high', 'low', 'close', 'volume'):
        df[c] = pd.to_numeric(df[c], errors='coerce')
    df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce').astype('int64')
    ts = df['timestamp'].values
    n = len(df)
    tf_ms = TF_MS.get(timeframe, 900_000)
    halving_on = bool(isinstance(cfg, dict) and cfg.get('halving_model_enabled'))
    # در مدل نصف‌کردن، get_signal_with_reason اصلاً از HTF (md) استفاده نمی‌کند؛ پس ساختنش فقط وقت تلف کردن است.
    use_htf = (strategy_type == 'dynamic' and timeframe in ('5min', '15min', '1hour') and not halving_on)
    htf_specs = {'5min': [('1h', 3_600_000), ('4h', 14_400_000)], '15min': [('1h', 3_600_000), ('4h', 14_400_000)],
                 '1hour': [('4h', 14_400_000)]}.get(timeframe, []) if use_htf else []
    htf = {k: _build_htf_complete(df, pm) for k, pm in htf_specs}
    # V3.44.160: حالت چندتایم‌فریمی (سطوح/واکنش ۱ ساعته، ورود ۵/۱۵ دقیقه)
    mtf_on = bool(halving_on and cfg.get('mtf_mode_enabled') and timeframe in ('5min', '15min'))
    mtf_agg = mtf_g = mtf_med = mtf_keys = None
    md_cache: Dict[int, pd.DataFrame] = {}
    mtf_warm = 0
    if mtf_on:
        mtf_agg, mtf_g = _build_htf_complete(df, 3_600_000)
        _i1 = calculate_indicators(mtf_agg.reset_index(drop=True)[['timestamp', 'open', 'high', 'low', 'close', 'volume']])
        mtf_med = pd.to_numeric(_i1['atr'], errors='coerce').rolling(200, min_periods=60).median().values
        mtf_keys = mtf_agg.index.values
        mtf_warm = int(105 * 3_600_000 / tf_ms) + 50          # حداقل ۱۰۰ کندل ۱ ساعته برای strategy_halving_mtf
    # اندیکاتورها (EMA/ATR/ADX/RSI/MACD/رولینگ) همه علّی‌اند؛ یک‌بار روی کل تاریخچه حساب می‌شوند (به‌جای هر قدم).
    # تفاوتِ شروع پنجره با زنده فقط در گرم‌شدن EMAهاست که بعد از چند صد کندل صفر می‌شود.
    ind_all = calculate_indicators(df)
    if len(ind_all) != n:
        raise RuntimeError('داده تاریخی کندل نامعتبر/ناقص دارد (ردیف‌های خالی).')

    first = 0
    if start_ms is not None:
        first = int(np.searchsorted(ts, start_ms, side='left'))
    first = max(first, WARMUP, mtf_warm)
    last = n - 2 if end_ms is None else min(n - 2, int(np.searchsorted(ts, end_ms, side='left')) - 1)
    if last <= first:
        raise RuntimeError('داده کافی برای این بازه نیست (حداقل ~۷۰۰ کندل قبل از شروع بازه لازم است).')

    t0 = time.time()
    trades: List[dict] = []
    stats = {'signals': 0, 'plan_failed': 0, 'steps': 0, 'with_stages': 0, 'gate_blocked': {}, 'mtf': mtf_on}
    fee_rate = float(fee_pct) / 100.0
    i = first
    cool_until = -1
    total_steps = last - first + 1
    while i <= last:
        if max_seconds and time.time() - t0 > max_seconds:
            raise RuntimeError('زمان بک‌تست از سقف مجاز گذشت؛ بازه را کوتاه‌تر کنید.')
        if progress and (i - first) % 500 == 0:
            progress(i - first, total_steps)
        if i < cool_until:
            i += 1
            continue
        stats['steps'] += 1
        lo_i = max(0, i - WINDOW + 1)
        closed = ind_all.iloc[lo_i:i + 1]
        nxt_open = float(df['open'].iloc[i + 1])
        frow = closed.iloc[-1].to_dict()
        frow.update({'timestamp': int(ts[i + 1]), 'open': nxt_open, 'high': nxt_open, 'low': nxt_open,
                     'close': nxt_open, 'volume': 0.0})
        primary = pd.concat([closed, pd.DataFrame([frow])], ignore_index=True)
        cfg_i = cfg
        try:
            md = {}
            for key, (agg, g) in htf.items():
                md[key] = calculate_indicators(_htf_view(agg, g, df, i))
            if mtf_on:
                gi = int(mtf_g[i])
                if gi not in md_cache:        # بخش بسته‌شده‌ی ۱ ساعته در طول همان ساعت ثابت است؛ فقط ردیف در حال تشکیل (نادیده‌گرفته می‌شود) فرق می‌کند
                    md_cache.clear()
                    md_cache[gi] = calculate_indicators(_htf_view(mtf_agg, mtf_g, df, i))
                md['1h'] = md_cache[gi]
                pos = int(np.searchsorted(mtf_keys, gi, side='left')) - 1       # آخرین کندل ۱ ساعته‌ی کامل
                med = float(mtf_med[pos]) if pos >= 0 and np.isfinite(mtf_med[pos]) else 0.0
                if med <= 0:
                    i += 1
                    continue
                cfg_i = {**cfg, 'halving_atr_override': med}
            sig, reason = get_signal_with_reason(primary, md, 'single', timeframe, strategy_type, filters, cfg_i, None,
                                                 live_price=nxt_open)
        except Exception:
            i += 1
            continue
        if sig not in ('BUY', 'SELL'):
            i += 1
            continue
        stats['signals'] += 1
        try:
            plan, _why = build_trade_plan(primary, sig, cfg_i, 'dynamic' if strategy_type == 'dynamic' else strategy_type,
                                          strategy_timeframe=timeframe, grid_levels=None, live_price=nxt_open)
        except Exception:
            plan = None
        if not plan:
            stats['plan_failed'] += 1
            i += 1
            continue
        if plan.get('tp_stages'):
            stats['with_stages'] += 1
        entry = float(plan['entry']); sl = float(plan['sl']); tp = float(plan['tp'])
        is_long = (sig == 'BUY')
        rd = abs(entry - sl)
        if rd <= 0 or entry <= 0:
            i += 1
            continue
        if entry_gate is not None:          # V3.44.127: گیت‌های BTC (ok, tag)؛ رد = این قدم بدون ورود، کندل بعد دوباره سنجیده می‌شود
            try:
                g_ok, g_tag = entry_gate(int(ts[i]), sig)
            except Exception:
                g_ok, g_tag = False, 'nodata'
            if not g_ok:
                gb = stats['gate_blocked']; gb[g_tag] = gb.get(g_tag, 0) + 1
                i += 1
                continue
        amount = (margin * leverage) / entry
        p = {'side': side_text[0] if is_long else side_text[1], 'entry_price': entry, 'sl': sl, 'sl_initial': sl,
             'tp': tp, 'risk_distance': rd}
        # --- مدیریت پوزیشن از کندل بعد از سیگنال ---
        j = i + 1
        exit_px = None; why = None; mfe_r = 0.0
        while j < n:
            h = float(df['high'].iloc[j]); l = float(df['low'].iloc[j])
            cur_sl = float(p['sl'])
            hit_tp = (h >= tp) if is_long else (l <= tp)
            hit_sl = (l <= cur_sl) if is_long else (h >= cur_sl)
            if hit_sl:                       # SL قبل از TP (محافظه‌کارانه)
                exit_px = cur_sl; why = 'TRAIL' if p.get('trail_active') else 'SL'; break
            if hit_tp:
                exit_px = tp; why = 'TP'; break
            mfe_r = max(mfe_r, ((h - entry) if is_long else (entry - l)) / rd)
            if trail_enabled and trail_fn is not None:
                best = h if is_long else l
                try:
                    act = trail_fn(p, best, trail_profile)
                except Exception:
                    act = None
                if act:
                    p['sl'] = float(act['new_sl']); p['trail_active'] = True
                    p['trail_lo'] = best; p['trail_hi'] = best
                    new_sl = float(p['sl'])
                    # بدبینانه: ترتیب داخل کندل ناشناخته است؛ اگر کندل تا SL جدید هم برگشته، خورده فرض می‌شود
                    if (l <= new_sl) if is_long else (h >= new_sl):
                        exit_px = new_sl; why = 'TRAIL'; break
            j += 1
        if exit_px is None:                  # تا پایان داده باز مانده؛ با آخرین کلوز بسته می‌شود
            j = n - 1; exit_px = float(df['close'].iloc[j]); why = 'END'
        gross = ((exit_px - entry) if is_long else (entry - exit_px)) * amount
        fee = margin * leverage * fee_rate * 2
        pnl = gross - fee
        trades.append({'open_ts': int(ts[i + 1]), 'close_ts': int(ts[min(j, n - 1)]), 'side': sig, 'entry': entry,
                       'sl': sl, 'tp': tp, 'exit': float(exit_px), 'why': why, 'pnl': float(pnl),
                       'r': float(pnl / (rd * amount)) if rd * amount else 0.0, 'mfe_r': round(mfe_r, 3),
                       'reason': (reason or '')[:120]})
        cool_until = j + 1 + cooldown_bars
        i = max(i + 1, j + 1)
    if progress:
        progress(total_steps, total_steps)
    return summarize(trades, start_balance, stats, time.time() - t0)


def summarize(trades: List[dict], start_balance: float, stats: dict, seconds: float) -> Dict:
    n = len(trades)
    pnl = np.array([t['pnl'] for t in trades], dtype=float)
    wins = int((pnl > 0).sum())
    gross_w = float(pnl[pnl > 0].sum()) if n else 0.0
    gross_l = float(-pnl[pnl < 0].sum()) if n else 0.0
    eq = start_balance + np.cumsum(pnl) if n else np.array([start_balance])
    peak = np.maximum.accumulate(np.concatenate([[start_balance], eq]))
    dd = (peak - np.concatenate([[start_balance], eq])) / peak
    return {
        'trades': n, 'wins': wins, 'win_rate': (wins / n * 100.0) if n else 0.0,
        'net': float(pnl.sum()) if n else 0.0,
        'net_pct': (float(pnl.sum()) / start_balance * 100.0) if start_balance else 0.0,
        'pf': (gross_w / gross_l) if gross_l > 0 else (float('inf') if gross_w > 0 else 0.0),
        'max_dd_pct': float(dd.max() * 100.0) if n else 0.0,
        'avg_r': float(np.mean([t['r'] for t in trades])) if n else 0.0,
        'longs': sum(1 for t in trades if t['side'] == 'BUY'), 'shorts': sum(1 for t in trades if t['side'] == 'SELL'),
        'stats': stats, 'seconds': seconds, 'trade_list': trades,
    }


def one_line(res: Dict, symbol: str, tf_label: str, start_label: str, end_label: str, start_balance: float, note: str = '') -> str:
    pf = res['pf']
    pf_txt = '∞' if pf == float('inf') else f'{pf:.2f}'
    sign = '+' if res['net'] >= 0 else '−'
    return (f"🧪 {symbol} {tf_label} | {start_label}→{end_label} | {res['trades']} معامله "
            f"({res['longs']} خرید / {res['shorts']} فروش) | وین‌ریت {res['win_rate']:.0f}٪ | "
            f"سود خالص {sign}{abs(res['net']):.1f}$ ({sign}{abs(res['net_pct']):.1f}٪ از {start_balance:.0f}$) | "
            f"بیشترین افت {res['max_dd_pct']:.1f}٪ | PF {pf_txt} | میانگین {res['avg_r']:+.2f}R" + (f" | {note}" if note else ''))
