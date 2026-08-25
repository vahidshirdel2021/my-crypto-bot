# -*- coding: utf-8 -*-
"""
V3 Professional Backtester for Trading Bot Strategy V2
=======================================================

Features
--------
- Reuses strategy.py V2 regime/setup engine (no duplicate signal logic).
- Historical CSV or CoinEx/ccxt OHLCV source.
- Long / short / both.
- Position sizing from risk-per-trade and structural SL.
- Fees, configurable slippage and optional funding cost.
- One position per symbol; portfolio-level max open positions.
- Conservative OHLC ambiguity handling (SL wins if SL+TP hit in same candle).
- Dynamic trailing and V2 weakness exit.
- Equity curve, drawdown, monthly returns, daily P&L.
- Profit Factor, Expectancy, Sharpe, Sortino, Calmar, SQN, VaR/CVaR,
  max consecutive wins/losses, exposure, turnover, MAE/MFE, R-multiple stats.
- Regime / setup-family / side attribution.
- Bootstrap confidence intervals for expectancy and max drawdown.
- Walk-forward evaluation with train/test windows. Training is used only to
  calibrate optional empirical win-rate/expectancy thresholds; the default
  mode is strict OOS and does not tune the strategy.
- Optional empirical edge calibration from the training set.
- JSON/CSV/PNG report bundle.

Important
---------
This is a research backtester, not an execution engine. Results are estimates.
The V2 `edge_proxy` remains a heuristic unless `--calibrate-edge` is enabled
inside a walk-forward run, in which case calibration uses TRAIN trades only.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from strategy import (
    calculate_indicators,
    evaluate_trend_weakness,
    detect_market_regime,
    _select_v2_setup,
    FILTER_DEFAULTS,
    STRATEGY_DEFAULTS,
    TIMEFRAME_PARAM_ADJUST,
    get_v2_config,
    compute_log_grid_levels,
)

PAPER_CONSERVATIVE_OHLC = True
CCXT_TO_STRATEGY_TF = {'5m': '5min', '15m': '15min', '1h': '1hour', '4h': '4hour'}
POSITION_MANAGEMENT_TIMEFRAME_MAP = {'5m':'1m','15m':'5m','1h':'15m','4h':'1h'}


@dataclass
class BacktestConfig:
    initial_balance: float = 10_000.0
    risk_per_trade: float = 0.005
    max_daily_loss: float = 0.03
    max_open_positions: int = 1  # single-symbol engine: more than one is not simulated
    leverage: float = 5.0
    taker_fee_pct: float = 0.05
    slippage_bps: float = 2.0
    funding_rate_8h: float = 0.01
    funding_enabled: bool = True
    use_trailing: bool = True
    conservative_ohlc: bool = True
    allow_same_bar_entry: bool = False
    cooldown_bars: int = 0
    min_bars: int = 70


@dataclass
class Position:
    symbol: str
    side: str
    entry_time: int
    entry_idx: int
    entry: float
    sl_initial: float
    sl_current: float
    tp: float
    risk_distance: float
    qty: float
    notional_entry: float
    margin: float
    fee_entry: float
    score: float
    planned_rr: float
    regime: str
    setup_family: str
    edge_proxy: float
    model_win_proxy: float
    reason: str
    best_favorable_r: float = 0.0
    worst_adverse_r: float = 0.0
    locked_r: float = 0.0
    trailing_activated: bool = False
    funding_paid: float = 0.0


# ---------------------------- data -----------------------------------------

def fetch_ohlcv_coinex(symbol, timeframe, start, end, market_type='swap') -> pd.DataFrame:
    import ccxt
    ex = ccxt.coinex({'enableRateLimit': True, 'timeout': 30000, 'options': {'defaultType': market_type}})
    ex.has['fetchCurrencies'] = False
    for attempt in range(5):
        try:
            ex.load_markets()
            break
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2 + attempt)
    since = ex.parse8601(start + 'T00:00:00Z')
    until = ex.parse8601(end + 'T00:00:00Z')
    rows, cursor = [], since
    while cursor < until:
        batch = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=cursor, limit=1000)
        if not batch:
            break
        rows.extend(batch)
        last = batch[-1][0]
        if len(batch) < 1000 or last >= until:
            break
        cursor = last + 1
        time.sleep(max(ex.rateLimit / 1000.0, 0.05))
    if not rows:
        raise RuntimeError(f'No OHLCV returned for {symbol}')
    df = pd.DataFrame(rows, columns=['ts','open','high','low','close','volume'])
    return normalize_ohlcv(df, start, end)


def normalize_ohlcv(df: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    d = df.copy()
    rename = {c: c.lower() for c in d.columns}
    d.rename(columns=rename, inplace=True)
    if 'timestamp' in d.columns and 'ts' not in d.columns:
        if np.issubdtype(d['timestamp'].dtype, np.datetime64):
            d['ts'] = d['timestamp'].astype('int64') // 10**6
        else:
            d['ts'] = pd.to_numeric(d['timestamp'], errors='coerce')
    if 'ts' not in d.columns:
        raise ValueError('CSV needs ts/timestamp column')
    for c in ['open','high','low','close','volume']:
        if c not in d.columns:
            raise ValueError(f'CSV missing {c}')
        d[c] = pd.to_numeric(d[c], errors='coerce')
    d['ts'] = pd.to_numeric(d['ts'], errors='coerce').astype('Int64')
    d = d.dropna(subset=['ts','open','high','low','close']).copy()
    d['ts'] = d['ts'].astype('int64')
    if d['ts'].median() < 10**12:
        d['ts'] *= 1000
    d = d.drop_duplicates('ts').sort_values('ts').reset_index(drop=True)
    if start:
        lo = int(pd.Timestamp(start, tz='UTC').timestamp() * 1000)
        d = d[d.ts >= lo]
    if end:
        hi = int(pd.Timestamp(end, tz='UTC').timestamp() * 1000)
        d = d[d.ts < hi]
    d['timestamp'] = d['ts']
    return d.reset_index(drop=True)


def load_source(symbol: str, timeframe: str, start: str, end: str, csv: Optional[str]) -> pd.DataFrame:
    if csv:
        return normalize_ohlcv(pd.read_csv(csv), start, end)
    return fetch_ohlcv_coinex(symbol, timeframe, start, end)

def management_timeframe(timeframe: str) -> str:
    return POSITION_MANAGEMENT_TIMEFRAME_MAP.get(timeframe, timeframe)



# ---------------------------- mechanics ------------------------------------

def apply_slippage(price: float, side: str, is_entry: bool, bps: float) -> float:
    x = float(bps) / 10_000.0
    if side == 'LONG':
        return price * (1 + x) if is_entry else price * (1 - x)
    return price * (1 - x) if is_entry else price * (1 + x)


def locked_r(entry, risk_distance, price, is_long):
    if risk_distance <= 0:
        return None
    r = (price-entry)/risk_distance if is_long else (entry-price)/risk_distance
    if r < 1.0:
        return None
    step = math.floor(r * 2) / 2.0
    return max(0.0, step - 1.0)


def bars_per_8h(timeframe: str) -> float:
    mins = {'5m':5, '15m':15, '1h':60, '4h':240, '1d':1440}.get(timeframe, 60)
    return max(1.0, 480 / mins)


def funding_cost(notional: float, holding_bars: int, timeframe: str, rate_8h_pct: float) -> float:
    if notional <= 0 or rate_8h_pct == 0:
        return 0.0
    periods = holding_bars / bars_per_8h(timeframe)
    return abs(notional) * (rate_8h_pct / 100.0) * periods


def mark_to_market_pnl(pos: Position, price: float) -> float:
    return pos.qty * (price - pos.entry) if pos.side == 'LONG' else pos.qty * (pos.entry - price)


def position_size(balance: float, entry: float, sl: float, risk_pct: float, leverage: float) -> Tuple[float,float,float]:
    dist = abs(entry-sl)
    if entry <= 0 or dist <= 0 or risk_pct <= 0:
        return 0.0, 0.0, 0.0
    risk_usdt = balance * risk_pct
    qty = risk_usdt / dist
    notional = qty * entry
    margin = notional / max(leverage, 1e-9)
    return qty, notional, margin


def close_position(pos: Position, exit_price: float, exit_time: int, reason: str, cfg: BacktestConfig, bars_held: int, timeframe: str) -> Dict:
    px = apply_slippage(exit_price, pos.side, False, cfg.slippage_bps)
    gross = mark_to_market_pnl(pos, px)
    fee_exit = abs(pos.qty * px) * cfg.taker_fee_pct / 100.0
    fund = funding_cost(abs(pos.qty * pos.entry), bars_held, timeframe, cfg.funding_rate_8h) if cfg.funding_enabled else 0.0
    total_fee = pos.fee_entry + fee_exit
    net = gross - total_fee - fund
    risk_usdt = pos.risk_distance * pos.qty
    realized_r = net / risk_usdt if risk_usdt else 0.0
    return {
        'symbol': pos.symbol, 'side': pos.side,
        'entry_time': pos.entry_time, 'exit_time': exit_time,
        'entry': pos.entry, 'exit': px,
        'sl_initial': pos.sl_initial, 'sl_final': pos.sl_current, 'tp': pos.tp,
        'qty': pos.qty, 'notional_entry': pos.notional_entry, 'margin': pos.margin,
        'fee_entry': pos.fee_entry, 'fee_exit': fee_exit,
        'funding': fund, 'pnl_gross': gross, 'pnl_net': net,
        'realized_r': realized_r, 'planned_rr': pos.planned_rr,
        'score': pos.score, 'regime': pos.regime, 'setup_family': pos.setup_family,
        'edge_proxy': pos.edge_proxy, 'model_win_proxy': pos.model_win_proxy,
        'exit_reason': reason, 'bars_held': bars_held,
        'mae_r': pos.worst_adverse_r, 'mfe_r': pos.best_favorable_r,
        'locked_r': pos.locked_r, 'trailing_activated': pos.trailing_activated,
        'reason': pos.reason,
    }


def build_htf_data(primary: pd.DataFrame, timeframe: str) -> Dict[str,pd.DataFrame]:
    # Resample from the same historical source. This avoids future data: each
    # HTF candle is only used after its close because strategy.py reads iloc[-2].
    freq = {'5m':'5min','15m':'15min','1h':'1h','4h':'4h'}.get(timeframe)
    if not freq:
        return {}
    d = primary.copy()
    d.index = pd.to_datetime(d['ts'], unit='ms', utc=True)
    out = {}
    for key, rule in [('15m','15min'),('1h','1h'),('4h','4h'),('1d','1D')]:
        if rule == freq:
            r = d.resample(rule, label='right', closed='right').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum','ts':'last'}).dropna().reset_index(drop=True)
        else:
            r = d.resample(rule, label='right', closed='right').agg({'open':'first','high':'max','low':'min','close':'last','volume':'sum','ts':'last'}).dropna().reset_index(drop=True)
        if len(r) >= 65:
            out[key] = calculate_indicators(r)
    return out


# ---------------------------- single run -----------------------------------

def run_single(df: pd.DataFrame, symbol: str, timeframe: str, start: str, end: str,
               cfg: BacktestConfig, side_filter='both', strategy_config=None,
               calibrator=None, management_df: Optional[pd.DataFrame]=None) -> Tuple[List[Dict], pd.DataFrame]:
    ind = calculate_indicators(df)
    if len(ind) < cfg.min_bars:
        return [], pd.DataFrame()
    strategy_tf = CCXT_TO_STRATEGY_TF.get(timeframe, '1hour')
    filters = dict(FILTER_DEFAULTS)
    scfg = get_v2_config(strategy_config)
    trades: List[Dict] = []
    equity_rows = []
    balance = cfg.initial_balance
    peak = balance
    daily_start = None
    daily_start_balance = balance
    daily_realized = 0.0
    pos: Optional[Position] = None
    cooldown_until = -1
    htf = build_htf_data(df, timeframe)
    mgmt_tf=management_timeframe(timeframe)
    mgmt_ind=calculate_indicators(management_df) if management_df is not None and not management_df.empty else ind
    n = len(ind)
    i = cfg.min_bars - 1

    while i < n - 1:
        row = ind.iloc[i]
        ts = int(row.ts)
        day = pd.Timestamp(ts, unit='ms', tz='UTC').date()
        if daily_start != day:
            daily_start, daily_realized, daily_start_balance = day, 0.0, balance

        # If a position exists, manage the completed candle first.
        if pos is not None:
            high, low, close = map(float, (row.high, row.low, row.close))
            is_long = pos.side == 'LONG'
            hit_tp = high >= pos.tp if is_long else low <= pos.tp
            hit_sl = low <= pos.sl_current if is_long else high >= pos.sl_current
            exit_px = None
            reason = None
            if hit_tp and hit_sl and cfg.conservative_ohlc:
                exit_px, reason = pos.sl_current, 'SL_SAME_BAR'
            elif hit_tp:
                exit_px, reason = pos.tp, 'TP'
            elif hit_sl:
                exit_px, reason = pos.sl_current, 'SL'
            else:
                # MFE/MAE use intrabar extremes, conservative enough for research.
                r_high = ((high-pos.entry)/pos.risk_distance if is_long else (pos.entry-low)/pos.risk_distance)
                r_low = ((low-pos.entry)/pos.risk_distance if is_long else (pos.entry-high)/pos.risk_distance)
                pos.best_favorable_r = max(pos.best_favorable_r, r_high)
                pos.worst_adverse_r = min(pos.worst_adverse_r, r_low)
                if cfg.use_trailing:
                    lr = locked_r(pos.entry, pos.risk_distance, close, is_long)
                    if lr is not None and lr > pos.locked_r:
                        ns = pos.entry + lr*pos.risk_distance if is_long else pos.entry - lr*pos.risk_distance
                        if (ns > pos.sl_current if is_long else ns < pos.sl_current):
                            pos.sl_current, pos.locked_r, pos.trailing_activated = ns, lr, True
                current_r = ((close-pos.entry)/pos.risk_distance if is_long else (pos.entry-close)/pos.risk_distance)
                if current_r >= float(scfg.get('weakness_exit_min_r',0.8)) or current_r <= float(scfg.get('early_loss_weakness_exit_min_r', -0.10)):
                    mg=mgmt_ind[mgmt_ind.ts <= ts]
                    if len(mg) >= 60:
                        weak, ws, _ = evaluate_trend_weakness(mg, 'BUY' if is_long else 'SELL', scfg)
                        min_weak_r = max(1.0, float(scfg.get('weakness_exit_min_r',1.0)))
                        if current_r >= min_weak_r and weak:
                            exit_px, reason = close, 'WEAKNESS_EXIT'
                        elif bool(scfg.get('early_loss_weakness_exit_enabled', True)) and current_r <= float(scfg.get('early_loss_weakness_exit_min_r', -0.10)) and ws >= float(scfg.get('early_loss_weakness_exit_score', 45.0)):
                            exit_px, reason = close, 'SMART_LOSS_CUT'
            if exit_px is not None:
                tr = close_position(pos, exit_px, ts, reason, cfg, i-pos.entry_idx, timeframe)
                balance += tr['pnl_net']
                daily_realized += tr['pnl_net']
                peak = max(peak, balance)
                trades.append(tr)
                cooldown_until = i + cfg.cooldown_bars
                pos = None
                equity_rows.append({'ts':ts,'balance':balance,'drawdown':balance/peak-1,'open_pnl':0.0,'equity':balance})
                i += 1
                continue

            open_pnl = mark_to_market_pnl(pos, float(row.close))
            equity = balance + open_pnl
            peak = max(peak, equity)
            equity_rows.append({'ts':ts,'balance':balance,'drawdown':equity/peak-1,'open_pnl':open_pnl,'equity':equity})
            i += 1
            continue

        # Portfolio guard is single-symbol in this function. Daily guard is real-money-like.
        if daily_realized <= -daily_start_balance * cfg.max_daily_loss or i <= cooldown_until:
            equity_rows.append({'ts':ts,'balance':balance,'drawdown':balance/peak-1,'open_pnl':0.0,'equity':balance})
            i += 1
            continue

        window = ind.iloc[:i+1].copy()
        # IMPORTANT: build HTF features only from data available at this decision time.
        # Reusing full-history HTF frames here would leak future candles into the signal.
        htf = build_htf_data(window, timeframe)
        grid_lookback = int(scfg.get('grid_lookback_candles', 500))
        grid = compute_log_grid_levels(window, lookback=grid_lookback) if timeframe in ('5m','15m') else None
        sig, plan, reason = _select_v2_setup(window, htf, strategy_tf, filters, scfg, grid_levels=grid)
        if sig not in ('BUY','SELL') or plan is None:
            equity_rows.append({'ts':ts,'balance':balance,'drawdown':balance/peak-1,'open_pnl':0.0,'equity':balance})
            i += 1
            continue
        if side_filter == 'long' and sig != 'BUY' or side_filter == 'short' and sig != 'SELL':
            i += 1
            continue
        if calibrator:
            sb = int(float(plan.get('score', 0)) // 5 * 5)
            empirical_r = calibrator.get(sb)
            if empirical_r is not None and empirical_r <= 0:
                i += 1
                continue

        raw_entry, sl, tp = float(plan['entry']), float(plan['sl']), float(plan['tp'])
        side = 'LONG' if sig == 'BUY' else 'SHORT'
        entry = apply_slippage(raw_entry, side, True, cfg.slippage_bps)
        dist = abs(entry-sl)
        target_risk_usdt = balance * cfg.risk_per_trade
        qty_by_risk, _, _ = position_size(balance, entry, sl, cfg.risk_per_trade, cfg.leverage)
        max_margin = balance * 0.5
        qty_by_margin = (max_margin * cfg.leverage) / entry
        qty = min(qty_by_risk, qty_by_margin)
        notional = qty * entry
        margin = notional / max(cfg.leverage, 1e-9)
        if qty <= 0 or notional <= 0:
            i += 1
            continue
        actual_risk_usdt = dist * qty
        fee_entry = abs(qty*entry) * cfg.taker_fee_pct/100.0
        pos = Position(symbol, side, ts, i, entry, sl, sl, tp, dist, qty, qty*entry, margin,
                       fee_entry, float(plan.get('score',0)), float(plan.get('rr',0)),
                       str(plan.get('regime','UNKNOWN')), str(plan.get('setup_family','UNKNOWN')),
                       float(plan.get('edge_proxy',0)), float(plan.get('model_win_proxy',0)), reason)
        # Entry is next bar by default. The position begins now only for accounting;
        # exits are checked from the following candle, matching signal-at-close semantics.
        equity_rows.append({'ts':ts,'balance':balance,'drawdown':balance/peak-1,'open_pnl':0.0,'equity':balance})
        i += 1

    if pos is not None:
        last = ind.iloc[-1]
        tr = close_position(pos, float(last.close), int(last.ts), 'END_OF_DATA', cfg, n-1-pos.entry_idx, timeframe)
        trades.append(tr)
        balance += tr['pnl_net']
        equity_rows.append({'ts':int(last.ts),'balance':balance,'drawdown':balance/peak-1,'open_pnl':0.0,'equity':balance})
    eq = pd.DataFrame(equity_rows).drop_duplicates('ts').sort_values('ts') if equity_rows else pd.DataFrame()
    return trades, eq


# ---------------------------- metrics --------------------------------------

def _max_consecutive(vals, positive=True):
    best = cur = 0
    for x in vals:
        ok = x > 0 if positive else x <= 0
        cur = cur+1 if ok else 0
        best = max(best, cur)
    return best


def bootstrap_ci(values, statistic=np.mean, n=3000, seed=42, alpha=0.05):
    a = np.asarray(values, dtype=float)
    a = a[np.isfinite(a)]
    if len(a) < 2:
        return [None,None]
    rng = np.random.default_rng(seed)
    samples = rng.choice(a, size=(n, len(a)), replace=True)
    stats = statistic(samples, axis=1)
    return [float(np.quantile(stats, alpha/2)), float(np.quantile(stats, 1-alpha/2))]


def max_drawdown(equity: pd.Series):
    if equity.empty: return 0.0, 0.0
    peak = equity.cummax()
    dd = equity/peak - 1
    return float(dd.min()), float((equity-peak).min())


def compute_metrics(trades: List[Dict], equity: pd.DataFrame, initial: float, timeframe='15m') -> Dict:
    if not trades:
        return {'trades':0,'initial_balance':initial,'net_pnl':0.0,'return_pct':0.0}
    t = pd.DataFrame(trades)
    pnl = t.pnl_net.astype(float)
    wins, losses = pnl[pnl>0], pnl[pnl<=0]
    gross_win, gross_loss = wins.sum(), abs(losses.sum())
    pf = gross_win/gross_loss if gross_loss>0 else float('inf')
    r = t.realized_r.astype(float)
    eq = equity.copy()
    if not eq.empty:
        eq['dt'] = pd.to_datetime(eq.ts, unit='ms', utc=True)
        dd_pct, dd_abs = max_drawdown(eq.equity)
        daily = eq.set_index('dt').equity.resample('1D').last().pct_change().dropna()
    else:
        dd_pct, dd_abs, daily = 0.0, 0.0, pd.Series(dtype=float)
    periods_year = 365.25 * 24 * 60 / {'5m':5,'15m':15,'1h':60,'4h':240,'1d':1440}.get(timeframe,60)
    sharpe = float(daily.mean()/daily.std(ddof=1)*math.sqrt(365)) if len(daily)>1 and daily.std(ddof=1)>0 else 0.0
    downside = daily[daily<0].std(ddof=1) if len(daily)>1 else np.nan
    sortino = float(daily.mean()/downside*math.sqrt(365)) if np.isfinite(downside) and downside>0 else 0.0
    total_days = max((eq.dt.iloc[-1]-eq.dt.iloc[0]).total_seconds()/86400, 1/24) if not eq.empty else 1
    years = total_days/365.25
    final = initial + pnl.sum()
    cagr = (final/initial)**(1/years)-1 if final>0 else -1.0
    calmar = cagr/abs(dd_pct) if dd_pct<0 else 0.0
    q05 = float(np.quantile(r,0.05)) if len(r) else 0
    cvar = float(r[r<=q05].mean()) if (r<=q05).any() else q05
    expectancy = float(r.mean())
    sqn = float(np.sqrt(len(r))*r.mean()/r.std(ddof=1)) if len(r)>1 and r.std(ddof=1)>0 else 0.0
    exposure = 0.0
    if not eq.empty and 'open_pnl' in eq:
        # Approximation: each trade's holding time / total sample.
        exposure = float(t.bars_held.sum()/max(len(eq),1)*100)
    return {
        'trades': int(len(t)),
        'wins': int((pnl>0).sum()), 'losses': int((pnl<=0).sum()),
        'win_rate_pct': float((pnl>0).mean()*100),
        'net_pnl': float(pnl.sum()), 'return_pct': float((final/initial-1)*100),
        'final_balance': float(final), 'profit_factor': float(pf),
        'gross_profit': float(gross_win), 'gross_loss': float(-gross_loss),
        'expectancy_r': expectancy, 'avg_win_r': float(t.loc[pnl>0,'realized_r'].mean()) if (pnl>0).any() else 0.0,
        'avg_loss_r': float(t.loc[pnl<=0,'realized_r'].mean()) if (pnl<=0).any() else 0.0,
        'median_r': float(r.median()), 'sqn': sqn,
        'max_drawdown_pct': float(dd_pct*100), 'max_drawdown_usdt': float(dd_abs),
        'sharpe_daily': sharpe, 'sortino_daily': sortino, 'cagr_pct': float(cagr*100), 'calmar': calmar,
        'var_95_r': q05, 'cvar_95_r': cvar,
        'max_consecutive_wins': _max_consecutive(pnl.tolist(), True),
        'max_consecutive_losses': _max_consecutive(pnl.tolist(), False),
        'avg_bars_held': float(t.bars_held.mean()), 'median_bars_held': float(t.bars_held.median()),
        'exposure_pct_approx': exposure,
        'avg_mfe_r': float(t.mfe_r.mean()), 'avg_mae_r': float(t.mae_r.mean()),
        'trailing_rate_pct': float(t.trailing_activated.mean()*100),
        'fee_total': float(t.fee_entry.sum()+t.fee_exit.sum()), 'funding_total': float(t.funding.sum()),
        'expectancy_r_bootstrap_ci95': bootstrap_ci(r),
        'win_rate_bootstrap_ci95': bootstrap_ci((pnl>0).astype(float), statistic=np.mean),
    }


def group_metrics(trades: List[Dict], key: str) -> pd.DataFrame:
    if not trades: return pd.DataFrame()
    rows=[]
    df=pd.DataFrame(trades)
    for name,g in df.groupby(key, dropna=False):
        pnl=g.pnl_net
        loss=abs(pnl[pnl<=0].sum()); win=pnl[pnl>0].sum()
        rows.append({key:name,'trades':len(g),'win_rate_pct':(pnl>0).mean()*100,
                     'profit_factor':win/loss if loss else float('inf'),
                     'net_pnl':pnl.sum(),'expectancy_r':g.realized_r.mean(),
                     'avg_score':g.score.mean(),'avg_rr':g.planned_rr.mean()})
    return pd.DataFrame(rows).sort_values('net_pnl',ascending=False)


# ---------------------------- walk forward ---------------------------------

def walk_forward(df: pd.DataFrame, symbol, timeframe, start, end, cfg, train_days=60, test_days=30,
                 calibrate_edge=False, side='both', strategy_config=None, management_df=None) -> Tuple[List[Dict], pd.DataFrame]:
    d=df.copy(); d['dt']=pd.to_datetime(d.ts,unit='ms',utc=True)
    start_dt=pd.Timestamp(start,tz='UTC'); end_dt=pd.Timestamp(end,tz='UTC')
    cursor=start_dt + pd.Timedelta(days=train_days)
    all_trades=[]; folds=[]
    while cursor < end_dt:
        train_start=cursor-pd.Timedelta(days=train_days); test_end=min(cursor+pd.Timedelta(days=test_days),end_dt)
        train=d[(d.dt>=train_start)&(d.dt<cursor)].drop(columns='dt')
        test=d[(d.dt>=cursor)&(d.dt<test_end)].drop(columns='dt')
        mtrain = management_df[(pd.to_datetime(management_df.ts,unit='ms',utc=True)>=train_start)&(pd.to_datetime(management_df.ts,unit='ms',utc=True)<cursor)] if management_df is not None else None
        mtest = management_df[(pd.to_datetime(management_df.ts,unit='ms',utc=True)>=cursor)&(pd.to_datetime(management_df.ts,unit='ms',utc=True)<test_end)] if management_df is not None else None
        if len(train)<cfg.min_bars or len(test)<cfg.min_bars//2:
            cursor=test_end; continue
        calibrator=None
        if calibrate_edge:
            # Training-only calibration: map V2 score to empirical win rate using bins.
            tr,_=run_single(train,symbol,timeframe,str(train_start.date()),str(cursor.date()),cfg,side,strategy_config,management_df=mtrain)
            if tr:
                td=pd.DataFrame(tr); td['score_bin']=(td.score//5*5).clip(0,100)
                calibrator=td.groupby('score_bin').realized_r.mean().to_dict()
        te,eq=run_single(test,symbol,timeframe,str(cursor.date()),str(test_end.date()),cfg,side,strategy_config,calibrator,management_df=mtest)
        for x in te: x['wf_fold_start']=cursor.isoformat(); x['wf_fold_end']=test_end.isoformat()
        all_trades.extend(te)
        folds.append({'fold':len(folds)+1,'train_start':train_start.isoformat(),'train_end':cursor.isoformat(),
                      'test_start':cursor.isoformat(),'test_end':test_end.isoformat(),'test_trades':len(te),
                      'test_net_pnl':float(sum(x['pnl_net'] for x in te))})
        cursor=test_end
    return all_trades,pd.DataFrame(folds)


# ---------------------------- reports ---------------------------------------

def save_report(outdir, trades, equity, metrics, symbol, timeframe, start, end, folds=None):
    os.makedirs(outdir,exist_ok=True)
    t=pd.DataFrame(trades)
    if not t.empty:
        t.to_csv(os.path.join(outdir,'trades.csv'),index=False)
        group_metrics(trades,'regime').to_csv(os.path.join(outdir,'by_regime.csv'),index=False)
        group_metrics(trades,'setup_family').to_csv(os.path.join(outdir,'by_setup.csv'),index=False)
        group_metrics(trades,'side').to_csv(os.path.join(outdir,'by_side.csv'),index=False)
        t['exit_dt']=pd.to_datetime(t.exit_time,unit='ms',utc=True)
        monthly=t.set_index('exit_dt').pnl_net.resample('ME').sum().reset_index()
        monthly['month']=monthly.exit_dt.dt.strftime('%Y-%m'); monthly.drop(columns='exit_dt').to_csv(os.path.join(outdir,'monthly_pnl.csv'),index=False)
    if not equity.empty:
        equity.to_csv(os.path.join(outdir,'equity_curve.csv'),index=False)
    if folds is not None and not folds.empty: folds.to_csv(os.path.join(outdir,'walk_forward_folds.csv'),index=False)
    report={'metadata':{'symbol':symbol,'timeframe':timeframe,'start':start,'end':end,'generated_utc':pd.Timestamp.utcnow().isoformat()},'metrics':metrics}
    with open(os.path.join(outdir,'report.json'),'w',encoding='utf-8') as f: json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
    try:
        import matplotlib.pyplot as plt
        if not equity.empty:
            plt.figure(figsize=(12,5)); plt.plot(pd.to_datetime(equity.ts,unit='ms',utc=True),equity.equity); plt.title('V3 Equity Curve'); plt.xlabel('Time'); plt.ylabel('Equity'); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(os.path.join(outdir,'equity_curve.png'),dpi=150); plt.close()
            plt.figure(figsize=(12,4)); plt.plot(pd.to_datetime(equity.ts,unit='ms',utc=True),equity.drawdown*100); plt.title('Drawdown %'); plt.xlabel('Time'); plt.ylabel('Drawdown %'); plt.grid(alpha=.2); plt.tight_layout(); plt.savefig(os.path.join(outdir,'drawdown.png'),dpi=150); plt.close()
    except Exception as e:
        with open(os.path.join(outdir,'plot_warning.txt'),'w') as f: f.write(str(e))


def main():
    ap=argparse.ArgumentParser(description='V3 Professional Backtester for Strategy V2')
    ap.add_argument('--symbol',default='BTC/USDT:USDT'); ap.add_argument('--timeframe',default='15m',choices=['5m','15m','1h','4h','1d'])
    ap.add_argument('--start',required=True); ap.add_argument('--end',required=True); ap.add_argument('--csv',default=None)
    ap.add_argument('--management-csv',default=None,help='CSV تایم‌فریم مدیریت؛ برای شبیه‌سازی دقیق مدیریت سریع در حالت CSV')
    ap.add_argument('--side',default='both',choices=['long','short','both']); ap.add_argument('--outdir',default='v3_report')
    ap.add_argument('--initial',type=float,default=10000); ap.add_argument('--risk',type=float,default=.005)
    ap.add_argument('--daily-loss',type=float,default=.03); ap.add_argument('--leverage',type=float,default=5)
    ap.add_argument('--fee',type=float,default=.05,help='taker fee percent per side'); ap.add_argument('--slippage-bps',type=float,default=2)
    ap.add_argument('--funding-rate',type=float,default=.01,help='funding percent per 8h'); ap.add_argument('--no-funding',action='store_true')
    ap.add_argument('--no-trailing',action='store_true'); ap.add_argument('--no-conservative-ohlc',action='store_true')
    ap.add_argument('--walk-forward',action='store_true'); ap.add_argument('--train-days',type=int,default=90); ap.add_argument('--test-days',type=int,default=30)
    ap.add_argument('--calibrate-edge',action='store_true',help='training-only empirical calibration diagnostics')
    args=ap.parse_args()
    cfg=BacktestConfig(initial_balance=args.initial,risk_per_trade=args.risk,max_daily_loss=args.daily_loss,leverage=args.leverage,
                       taker_fee_pct=args.fee,slippage_bps=args.slippage_bps,funding_rate_8h=args.funding_rate,
                       funding_enabled=not args.no_funding,use_trailing=not args.no_trailing,
                       conservative_ohlc=not args.no_conservative_ohlc)
    print(f'Loading {args.symbol} {args.timeframe}: {args.start} -> {args.end}')
    df=load_source(args.symbol,args.timeframe,args.start,args.end,args.csv)
    mgmt_tf=management_timeframe(args.timeframe)
    if args.management_csv:
        management_df=normalize_ohlcv(pd.read_csv(args.management_csv),args.start,args.end)
    elif args.csv:
        management_df=None
        print(f'⚠️ CSV مدیریت سریع ارائه نشده؛ برای {args.timeframe}→{mgmt_tf} خروج ضعف با تایم‌فریم اصلی تقریب زده می‌شود.')
    else:
        print(f'Loading management timeframe {mgmt_tf} ...')
        management_df=fetch_ohlcv_coinex(args.symbol,mgmt_tf,args.start,args.end)
    if args.walk_forward:
        trades,folds=walk_forward(df,args.symbol,args.timeframe,args.start,args.end,cfg,args.train_days,args.test_days,args.calibrate_edge,args.side,management_df=management_df)
        # OOS equity curve is reconstructed from trade PnL.
        if trades:
            tt=pd.DataFrame(trades); tt['exit_dt']=pd.to_datetime(tt.exit_time,unit='ms',utc=True); tt=tt.sort_values('exit_time'); tt['equity']=cfg.initial_balance+tt.pnl_net.cumsum(); tt['peak']=tt.equity.cummax(); tt['drawdown']=tt.equity/tt.peak-1; eq=tt[['exit_time','equity','drawdown']].rename(columns={'exit_time':'ts'}); eq['balance']=eq.equity; eq['open_pnl']=0.0
        else: eq=pd.DataFrame()
    else:
        trades,eq=run_single(df,args.symbol,args.timeframe,args.start,args.end,cfg,args.side,management_df=management_df)
        folds=None
    metrics=compute_metrics(trades,eq,cfg.initial_balance,args.timeframe)
    save_report(args.outdir,trades,eq,metrics,args.symbol,args.timeframe,args.start,args.end,folds)
    print(json.dumps(metrics,ensure_ascii=False,indent=2,default=str))
    print(f'Report saved to {args.outdir}/')

if __name__=='__main__': main()
