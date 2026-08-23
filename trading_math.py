"""
trading_math.py — pure, side-effect-free trading calculations extracted from
bot.py during the test-coverage/modularization project.

Every function here is deterministic given its inputs: no Telegram, no
exchange/network calls, no session or database access. That's what makes
them independently unit-testable (see tests/) and safe to import from
anywhere without pulling in bot.py's runtime state.

Moved as-is (behavior-preserving) — see CHANGES_THIS_SESSION.md for the
history of when/why each function was extracted and tested.
"""
import math
import hashlib
import os
import re
import logging
from datetime import timedelta

logger = logging.getLogger('trader_bot')

TAKER_FEE_PCT = max(0.0, float(os.environ.get('TAKER_FEE_PCT', '0.05')))


def _seconds_until_next_midnight(now):
    """Pure calc: seconds remaining until the next local midnight strictly
    after `now`. Extracted from _seconds_to_local_day_end so the day-boundary
    math is testable without depending on the actual wall-clock time.
    """
    day_end = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (day_end - now).total_seconds()

def _clamp_pct(value, default=0.0):
    """Pure clamp to [0, 100], used everywhere a percentage rate (platform
    fee rate, etc.) is read from env, DB, or user input. Falls back to
    `default` (also clamped) on non-numeric input instead of raising.
    """
    try:
        return min(100.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return min(100.0, max(0.0, float(default)))

def fmt(v):
    try:
        x=float(v)
        if abs(x)<.0001: return f'{x:.8f}'
        if abs(x)<1: return f'{x:.6f}'
        return f'{x:.4f}'
    except Exception as exc:
        logger.debug('fmt fallback value=%r: %s', v, exc)
        return str(v)

def market_name(symbol): return f"{symbol.upper().replace('USDT','').replace('/','')}USDT"

def ccxt_symbol(symbol): return f"{symbol.upper().replace('USDT','').replace('/','')}/USDT:USDT"

def _extract_numbers(obj, names):
    found=[]
    if isinstance(obj, dict):
        for k,v in obj.items():
            key=str(k).lower().replace('-','_')
            if key in names:
                try: found.append(float(v))
                except Exception: pass
            found.extend(_extract_numbers(v,names))
    elif isinstance(obj, list):
        for v in obj: found.extend(_extract_numbers(v,names))
    return found

def _price_matches(a,b):
    try:
        a=float(a); b=float(b); scale=max(abs(a),abs(b),1.0)
        return abs(a-b) <= max(1e-8,scale*2e-5)
    except Exception:
        return False

def _verify_protection_prices(sls, tps, expected_sl, expected_tp):
    """Pure safety-critical verification: given SL/TP price values pulled from
    exchange API responses, confirm at least one matches what we intended to
    set, within tolerance. An EMPTY list means 'nothing discoverable in this
    response to check' and is NOT itself a failure (mirrors the original
    inline behavior) — only a confirmed MISMATCH blocks the trade. This is
    the exact check standing between a real position and running with no
    real stop-loss on the exchange, so it's tested independently of any
    network/exchange call — see tests/test_execution.py.
    """
    if sls and not any(_price_matches(x, expected_sl) for x in sls):
        return False, f'SL verification mismatch: expected {expected_sl}'
    if tps and not any(_price_matches(x, expected_tp) for x in tps):
        return False, f'TP verification mismatch: expected {expected_tp}'
    return True, 'OK'

def side_long(side): return 'BUY' in str(side).upper() or 'LONG' in str(side).upper()

def _same_direction_guard_allows(session, side, now_ts):
    """Pure decision function for the correlated-exposure guard.

    Returns True iff a new entry on `side` is allowed given the session's current
    open positions and last-entry timestamps. Kept side-effect-free (no session
    mutation, no time.time() call inside) specifically so it can be unit tested
    without needing a live session, Telegram, or exchange state — see
    tests/test_risk_guards.py.
    """
    max_same_dir = int(session.get('max_same_direction_positions', 0) or 0)
    if max_same_dir > 0:
        same_dir_open = sum(
            1 for p in session.get('paper_positions', [])
            if side_long(p.get('side', '')) == side_long(side)
        )
        if same_dir_open >= max_same_dir:
            return False
    same_dir_cooldown = float(session.get('same_direction_entry_cooldown_seconds', 0) or 0)
    if same_dir_cooldown > 0:
        dir_key = 'BUY' if side_long(side) else 'SELL'
        last_dir_ts = float((session.get('last_direction_entry_ts') or {}).get(dir_key, 0))
        if now_ts - last_dir_ts < same_dir_cooldown:
            return False
    return True

def round_trip_fee_usdt(margin, leverage):
    try:
        notional = abs(float(margin)) * abs(float(leverage))
        if not math.isfinite(notional): return 0.0
        return notional * (TAKER_FEE_PCT / 100.0) * 2
    except Exception:
        return 0.0

def trailing_locked_r(entry, risk_distance, current_price, is_long):
    """
    Profit-protection ladder for an already profitable position.

    1.0R -> break-even
    1.5R -> lock +0.5R
    2.0R -> lock +1.0R
    2.5R -> lock +1.5R
    ...

    This intentionally does not alter entry/TP logic; it only protects an
    existing position after it has moved in the intended direction.
    """
    try:
        entry=float(entry); risk_distance=float(risk_distance); current_price=float(current_price)
    except Exception:
        return None
    if risk_distance<=0 or not math.isfinite(risk_distance): return None
    r=(current_price-entry)/risk_distance if is_long else (entry-current_price)/risk_distance
    if r<1.0: return None
    step=math.floor(r*2)/2.0
    return max(0.0, step-1.0)

def _compute_trailing_update(entry, risk_distance, current_sl, is_long, trailing_locked_r_current, trailing_activated, favorable_price):
    """Pure decision: given the profit-protection ladder position, should the
    stop move, and to where? Isolated from _apply_profit_protection's
    exchange call / Telegram message so the actual ladder-advance logic
    (including the first-activation-at-0R edge case) is independently
    testable.

    Returns None if no update should happen, otherwise a dict with new_sl,
    locked_r, and first_activation.
    """
    lr = trailing_locked_r(entry, risk_distance, favorable_price, is_long)
    if lr is None:
        return None
    new_sl = entry + (lr * risk_distance if is_long else -lr * risk_distance)
    is_better = (new_sl > current_sl) if is_long else (new_sl < current_sl)
    locked = float(trailing_locked_r_current or 0.0)
    # First activation is allowed at exactly 1R: 0R is a valid lock level.
    first_activation = not bool(trailing_activated)
    if not is_better or not (lr > locked or (first_activation and lr >= locked)):
        return None
    return {'new_sl': new_sl, 'locked_r': lr, 'first_activation': first_activation}

def _should_update_swing_stop(new_sl, swing_level, price, current_sl, is_long, prev_swing_level):
    """Pure decision for the swing-based trailing stop: move only if the new
    stop sits behind current price (not already breached), is strictly better
    than the current SL, and reflects an actually NEW swing (not the same
    level triggering again). Isolated from _check_swing_trailing_stop's
    kline fetch / exchange call / Telegram message for independent testing.
    """
    if is_long:
        behind_price = new_sl < price
        improved = new_sl > current_sl
    else:
        behind_price = new_sl > price
        improved = new_sl < current_sl
    if not (behind_price and improved):
        return False
    if prev_swing_level is not None and math.isclose(swing_level, prev_swing_level, rel_tol=1e-9, abs_tol=1e-9):
        return False
    return True

def _should_close_before_day_end(timeframe, seconds_to_day_end, scan_interval_seconds, no_overnight_timeframes):
    """Pure decision: is it time to force-close a no-overnight-timeframe
    position before the local day rolls over? Separated from
    _maybe_close_before_day_end's actual close_position() call/side effects.
    """
    if timeframe not in no_overnight_timeframes:
        return False
    return seconds_to_day_end <= scan_interval_seconds

def _directional_price_fraction(side, entry, price):
    """Pure fractional price move in the position's favorable direction.
    Positive means profit, negative means loss, for either Long or Short.
    """
    entry = float(entry)
    denom = max(entry, 1e-12)
    return ((float(price) - entry) / denom) if side_long(side) else ((entry - float(price)) / denom)

def _gross_pnl_usdt(margin, leverage, frac):
    """Pure gross PnL (before fees/funding) for a given directional fraction."""
    return float(margin) * float(frac) * float(leverage)

def _paper_funding_cost_usdt(margin, leverage, opened_at, now_ts, funding_rate_pct_8h):
    """Pure paper-mode funding cost accrued since open, charged per 8h interval."""
    hours = max(0.0, float(now_ts) - float(opened_at)) / 3600.0
    funding_intervals = hours / 8.0
    return float(margin) * float(leverage) * (float(funding_rate_pct_8h) / 100.0) * funding_intervals

def _risk_usdt_from_stop(entry, sl, margin, leverage):
    """Pure fallback risk_usdt derived from stop distance, used when a trade's
    risk_usdt wasn't recorded at entry time. NOTE: intentionally mirrors the
    original inline formula's behavior for entry<=0 (denominator floored at
    1e-12 rather than short-circuiting to 0) — this is a pre-existing edge
    case, not something this extraction should silently change.
    """
    entry = float(entry)
    denom = max(entry, 1e-12)
    return abs(entry - float(sl)) / denom * float(margin) * float(leverage)

def _realized_r(pnl_usdt, risk_usdt):
    """Pure realized-R calculation: PnL expressed as a multiple of planned risk.
    Returns None (not 0) when risk_usdt is missing/zero, matching how the rest
    of the codebase (and every trade-audit export) distinguishes 'no R available'
    from 'exactly breakeven'.
    """
    risk_usdt = float(risk_usdt or 0.0)
    if risk_usdt <= 0:
        return None
    return float(pnl_usdt or 0.0) / risk_usdt

def _daily_loss_limit_breached(equity, daily_start_equity, daily_loss_limit_pct):
    """Pure decision: has today's equity fallen past the configured daily loss
    limit? Kept separate from risk_guard() (which also touches the exchange,
    session, and Telegram) so the actual threshold math is independently
    testable — see tests/test_execution.py.
    """
    start = float(daily_start_equity)
    if start <= 0:
        return False, None
    limit = start * (1 - float(daily_loss_limit_pct) / 100)
    return equity <= limit, limit

def _parse_signal_reason(reason):
    """Pure regex parsing of the human-readable Persian `reason` string into
    structured fields (quality score/label, planned R:R, PDH/PDL level).

    This is inherently fragile (free-text pattern matching) — if the strategy
    layer ever changes how it phrases these fragments, extraction silently
    returns None instead of raising, and quality_score/planned_rr end up
    missing from the trade record with no visible error. Kept as its own pure
    function specifically so tests can pin the exact patterns depended on —
    see tests/test_execution.py.
    """
    quality_score = None; quality_label = None; planned_rr = None; level_suffix = None
    m_score = re.search(r'کیفیت (\d+)/100 \(([^)]+)\)', reason or '')
    if m_score:
        quality_score = int(m_score.group(1)); quality_label = m_score.group(2)
    m_rr = re.search(r'R:R ([0-9.]+)R', reason or '')
    if m_rr:
        planned_rr = float(m_rr.group(1))
    m_level = re.search(r'PD([HL])=([0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?)', reason or '')
    if m_level:
        level_suffix = f"{m_level.group(1)}:{m_level.group(2)}"
    return {
        'quality_score': quality_score,
        'quality_label': quality_label,
        'planned_rr': planned_rr,
        'level_suffix': level_suffix,
    }

def _compute_setup_id(symbol, side, timeframe, signal_price, sl, tp, reason):
    """Pure setup-identity hash used for the once-only consumption guard."""
    setup_source = f"{symbol}|{side}|{timeframe}|{signal_price:.12g}|{sl:.12g}|{tp:.12g}|{reason}"
    return hashlib.sha256(setup_source.encode('utf-8')).hexdigest()[:24]

def _risk_usdt_for_entry(entry_price, sl, margin, leverage):
    """Pure risk_usdt calc used just BEFORE a position exists (entry decision
    time). Deliberately keeps its own price<=0 guard (returns 0.0, matching
    the original inline code) rather than reusing _risk_usdt_from_stop's
    denominator-floor behavior, which is meant for an already-open position
    and would instead return a huge number for entry_price<=0.
    """
    entry_price = float(entry_price)
    if entry_price <= 0:
        return 0.0
    risk_dist = abs(entry_price - float(sl))
    return float(margin) * ((risk_dist / entry_price) * float(leverage))

def _passes_min_risk_to_fee_ratio(risk_usdt, fee_estimate, min_ratio):
    """Pure gate: reject setups whose planned risk is too small relative to
    round-trip fees to be worth taking (fees would dominate the outcome)."""
    if min_ratio <= 0:
        return True
    return float(risk_usdt) >= float(fee_estimate) * float(min_ratio)

def _is_order_filled(confirmed):
    """Pure decision: does this exchange order-status response count as filled?
    A missing/empty status is treated as filled-if-amount-present, matching
    exchanges that omit status on a fully executed market order.
    """
    confirmed = confirmed or {}
    filled = float(confirmed.get('filled') or 0)
    status = str(confirmed.get('status') or '').lower()
    return filled > 0 and (status in ('closed', 'filled') or not status)

def _capped_leverage(requested_leverage, max_leverage):
    """Pure leverage cap: never exceed what the exchange/market allows."""
    max_leverage = float(max_leverage) if max_leverage else float(requested_leverage)
    return int(max_leverage) if requested_leverage > max_leverage else int(requested_leverage)

def _meets_min_amount(amount, min_amount):
    """Pure exchange-minimum-size check for an order amount."""
    if amount <= 0:
        return False
    if min_amount and amount < min_amount:
        return False
    return True

def _leader_correlation_decision(leader_states, correlations, is_long):
    """Pure decision for the anti-correlated-crash guard: given each leader's
    (name, bearish, crash, change_1, change_3, bullish, pump) state and each
    leader's correlation to the target symbol, should a new entry on this
    side be blocked? Extracted from leader_correlation_guard() so this exact
    mechanism — intended to prevent a market-wide move from hitting many
    correlated positions at once — is independently testable without a live
    kline fetch. Returns (allowed, block_reason_key or None).
    """
    both_bearish = all(x[1] for x in leader_states) if leader_states else False
    both_bullish = all(x[5] for x in leader_states) if leader_states else False
    any_crash = any(x[2] for x in leader_states)
    any_pump = any(x[6] for x in leader_states)
    max_corr = max(abs(c) for _, c in correlations) if correlations else 0.0
    avg_positive_corr = sum(max(0.0, c) for _, c in correlations) / len(correlations) if correlations else 0.0

    if is_long:
        if both_bearish and (max_corr >= 0.40 or avg_positive_corr >= 0.55):
            return False, 'bearish_leaders_correlated'
        if any_crash and max_corr >= 0.65:
            return False, 'leader_crash_correlated'
    else:
        if both_bullish and (max_corr >= 0.40 or avg_positive_corr >= 0.55):
            return False, 'bullish_leaders_correlated'
        if any_pump and max_corr >= 0.65:
            return False, 'leader_pump_correlated'
    return True, None

def _platform_fee_amount(profit, rate_pct, min_profit_usdt):
    """Pure: platform fee charged on a trade's realized profit, or 0.0 if the
    trade isn't eligible (profit at or below the minimum threshold). Rate is
    clamped to [0, 100] regardless of what's stored, matching every other
    read/write path for platform_fee_rate_pct in this file.
    """
    profit = float(profit or 0.0)
    if profit <= float(min_profit_usdt):
        return 0.0
    rate = _clamp_pct(rate_pct)
    return round(profit * rate / 100.0, 8)

def _live_position_metrics(side, entry, live, amount, risk_usdt):
    """Pure calc behind the numbers shown on every open-position card: live
    unrealized PnL, percent return, and R-multiple. This is exactly the math
    behind the DASH card in the user-reported screenshot (R: -1.23,
    بازده: -1.30%) that first surfaced the SL-timing investigation — kept
    independently testable so this display math is never the unverified part
    of a future debugging session.
    """
    entry = float(entry or 0); live = float(live or entry or 0); amount = abs(float(amount or 0))
    is_long = side_long(side)
    pnl = (live - entry) * amount if is_long else (entry - live) * amount
    if entry > 0:
        pct = ((live - entry) / entry * 100.0) if is_long else ((entry - live) / entry * 100.0)
    else:
        pct = 0.0
    risk = float(risk_usdt or 0.0)
    r = (pnl / risk) if risk > 0 else 0.0
    return pnl, pct, r
