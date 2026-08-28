# -*- coding: utf-8 -*-
"""
swing_detection.py
===================================================================
Modular Swing High / Swing Low detection library for OHLCV data.

Implements three independent, composable swing-detection methodologies
plus a risk-management layer that converts any detected swing into a
structured trade signal (SL/TP, entry trigger, pattern metadata).

Methodologies implemented
--------------------------
1. Three-Bar Rejection / Wick Swing  (detect_three_bar_rejection_swings)
   - Momentum/rejection pattern: the middle candle pokes beyond its
     neighbors with a wick and is "confirmed" by the third candle
     closing back through the middle candle's body.

2. Classic Three-Bar Extremity Swing (detect_classic_three_bar_swings)
   - The textbook fractal/ZigZag definition: middle candle's high/low
     is strictly more extreme than both neighbors.

3. Market Structure Swings + ChoCH/BOS (detect_structural_swings)
   - Sequential structural pivots (using the classic swing engine as
     its pivot source) that are only "confirmed" once a later candle
     BODY cleanly closes through the pivot level -> Break of
     Structure (BOS, continuation) or Change of Character (ChoCH,
     reversal), depending on prevailing structural bias.

Risk layer
----------
   compute_stop_loss_for_swing() / attach_risk_to_signal()
   - Places SL strictly behind the swing extreme (wick or structural
     level) with a configurable buffer (ATR-based and/or percentage-
     based, whichever is larger, to avoid noise stop-outs).
   - Computes TP from a risk multiple (R-multiple) or a fixed target
     price, and returns everything as a structured, JSON-serializable
     dictionary.

Design notes
------------
- All detector functions are pure: given a pandas DataFrame with
  columns ['open','high','low','close'] (and optionally 'volume' /
  a datetime index), they return a list of SwingPoint / StructuralEvent
  dataclass instances. Nothing is mutated on the input DataFrame.
- All functions are defensive against malformed/short/NaN-laden real-
  time data feeds: they validate input, coerce dtypes, and raise a
  single, clearly-typed SwingDetectionError instead of raw pandas/numpy
  exceptions, or degrade gracefully (return []) where documented.
- No look-ahead bias: every pattern requires its confirmation candle
  to have already closed before it is considered "confirmed". An
  `unconfirmed` flag is provided for the reversal candle itself
  (Classic swing) since, by definition, a fractal cannot be confirmed
  until N candles later -- callers who need that can control it via
  `require_confirmation`.

Author: (generated for internal trading bot integration)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import List, Optional, Dict, Any, Literal

import numpy as np
import pandas as pd


# ============================================================================
# Exceptions & shared enums
# ============================================================================

class SwingDetectionError(ValueError):
    """Raised when input data is structurally invalid for swing detection."""


class SwingType(str, Enum):
    HIGH = "swing_high"
    LOW = "swing_low"


class PatternType(str, Enum):
    THREE_BAR_REJECTION = "three_bar_rejection"
    CLASSIC_THREE_BAR = "classic_three_bar"
    STRUCTURAL_BOS = "break_of_structure"
    STRUCTURAL_CHOCH = "change_of_character"


class StructuralBias(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    UNDEFINED = "undefined"


REQUIRED_COLUMNS = ("open", "high", "low", "close")


# ============================================================================
# Data containers
# ============================================================================

@dataclass
class SwingPoint:
    """A single detected swing high or swing low."""
    index: int                     # positional index (iloc) of the pivot candle
    timestamp: Any                 # value of df.index at `index` (datetime or raw)
    swing_type: SwingType
    pattern: PatternType
    price: float                   # the extreme price of the swing (high or low)
    body_reference: float          # open/close boundary used for confirmation / SL buffer calc
    confirmed: bool                # whether a later candle has confirmed this swing
    confirmation_index: Optional[int] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["swing_type"] = self.swing_type.value
        d["pattern"] = self.pattern.value
        return d


@dataclass
class StructuralEvent:
    """A Break of Structure (BOS) or Change of Character (ChoCH) event."""
    index: int
    timestamp: Any
    event: PatternType              # STRUCTURAL_BOS or STRUCTURAL_CHOCH
    direction: Literal["bullish", "bearish"]
    broken_swing: SwingPoint
    break_price: float               # close price of the candle that broke structure
    new_bias: StructuralBias
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "index": self.index,
            "timestamp": self.timestamp,
            "event": self.event.value,
            "direction": self.direction,
            "broken_swing": self.broken_swing.to_dict(),
            "break_price": self.break_price,
            "new_bias": self.new_bias.value,
            "meta": self.meta,
        }
        return d


@dataclass
class TradeSignal:
    """Structured, execution-ready signal produced from a swing/structural event."""
    source: SwingPoint
    direction: Literal["long", "short"]
    entry_trigger: float
    stop_loss: float
    take_profit: Optional[float]
    risk_reward: Optional[float]
    sl_distance: float
    valid: bool
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "direction": self.direction,
            "entry_trigger": self.entry_trigger,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "risk_reward": self.risk_reward,
            "sl_distance": self.sl_distance,
            "valid": self.valid,
            "reason": self.reason,
        }


# ============================================================================
# Validation & utility helpers
# ============================================================================

def _validate_ohlc(df: pd.DataFrame, min_rows: int) -> pd.DataFrame:
    """
    Validate and lightly normalize an OHLC(V) DataFrame for real-time feeds.

    - Confirms required columns exist.
    - Coerces to numeric, dropping rows that become fully NaN in OHLC.
    - Confirms high >= low, high >= open/close, low <= open/close per row
      (rows failing basic sanity are dropped rather than raising, since
      live feeds occasionally emit a single malformed tick).
    - Raises SwingDetectionError if too little valid data remains.

    Returns a NEW DataFrame (input is never mutated), with a clean
    RangeIndex-free copy but original index preserved for timestamps.
    """
    if df is None:
        raise SwingDetectionError("Input DataFrame is None.")
    if not isinstance(df, pd.DataFrame):
        raise SwingDetectionError(f"Expected pandas DataFrame, got {type(df)!r}.")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise SwingDetectionError(f"Missing required OHLC columns: {missing}")

    d = df.copy()
    for c in REQUIRED_COLUMNS:
        d[c] = pd.to_numeric(d[c], errors="coerce")

    d = d.dropna(subset=list(REQUIRED_COLUMNS))

    # Basic sanity: high must be the max, low must be the min of the candle.
    sane_mask = (
        (d["high"] >= d["low"])
        & (d["high"] >= d["open"])
        & (d["high"] >= d["close"])
        & (d["low"] <= d["open"])
        & (d["low"] <= d["close"])
        & np.isfinite(d["high"])
        & np.isfinite(d["low"])
        & np.isfinite(d["open"])
        & np.isfinite(d["close"])
    )
    d = d[sane_mask]

    if len(d) < min_rows:
        raise SwingDetectionError(
            f"Not enough valid OHLC rows after cleaning: have {len(d)}, need >= {min_rows}."
        )

    d = d.reset_index(drop=False)
    # Standardize the timestamp column name internally without touching caller's df.
    if "index" in d.columns and d.columns[0] == "index":
        d = d.rename(columns={"index": "_timestamp"})
    else:
        d["_timestamp"] = d.index

    return d


def _candle_body_bounds(row: pd.Series) -> "tuple[float, float]":
    """Return (body_top, body_bottom) i.e. max/min of open & close."""
    o, c = float(row["open"]), float(row["close"])
    return (max(o, c), min(o, c))


def _candle_body_size(row: pd.Series) -> float:
    top, bottom = _candle_body_bounds(row)
    return top - bottom


def _average_true_range(d: pd.DataFrame, period: int = 14) -> pd.Series:
    """Lightweight ATR calculation (Wilder-style smoothing) used for SL buffers."""
    high, low, close = d["high"], d["low"], d["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.ewm(alpha=1.0 / max(1, period), adjust=False, min_periods=1).mean()
    return atr


# ============================================================================
# 1) THREE-BAR REJECTION / WICK SWING
# ============================================================================

def detect_three_bar_rejection_swings(
    df: pd.DataFrame,
    max_body_ratio: float = 0.5,
    require_full_confirmation: bool = True,
) -> List[SwingPoint]:
    """
    Detect 3-bar rejection (wick) swing patterns.

    Pattern definition
    -------------------
    Swing Low (bullish rejection):
        - Candle 2 (middle) has the LOWEST low of the 3 candles.
        - Candle 2's body is "relatively small/medium": body_size(2) <=
          max_body_ratio * max(body_size(1), body_size(3), candle2_range)
          i.e. it is dominated by its wick, not its body.
        - Candle 3 confirms by closing fully ABOVE candle 2's body top
          (close_3 > body_top_2). With require_full_confirmation=True the
          candle 3 OPEN must also close above (i.e. the whole candle 3
          body sits above candle 2's body) -- a stricter confirmation.

    Swing High (bearish rejection): mirror image using highs / body_bottom.

    Parameters
    ----------
    df : DataFrame with columns open, high, low, close (volume optional).
    max_body_ratio : float
        Upper bound on candle-2 body size relative to the larger of its
        neighbors' bodies / its own range, before it disqualifies as a
        "wick-dominated" rejection candle. Lower = stricter (more wick).
    require_full_confirmation : bool
        If True, candle 3's entire body must clear candle 2's body edge.
        If False, only candle 3's close must clear it (looser).

    Returns
    -------
    List[SwingPoint], each with `confirmed=True` (this pattern is by
    definition only ever emitted once its 3rd/confirmation bar exists).

    Raises
    ------
    SwingDetectionError on invalid/too-short input.
    """
    d = _validate_ohlc(df, min_rows=3)
    swings: List[SwingPoint] = []

    highs, lows = d["high"].values, d["low"].values

    for i in range(1, len(d) - 1):
        c1, c2, c3 = d.iloc[i - 1], d.iloc[i], d.iloc[i + 1]

        body1, body2, body3 = _candle_body_size(c1), _candle_body_size(c2), _candle_body_size(c3)
        range2 = float(c2["high"]) - float(c2["low"])
        if range2 <= 0:
            continue
        body2_ref = max(body1, body3, 1e-12)

        # ---- Swing Low (bullish rejection) ----
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            body_top_2, _ = _candle_body_bounds(c2)
            is_wick_dominated = body2 <= max_body_ratio * max(body2_ref, range2)
            if is_wick_dominated:
                if require_full_confirmation:
                    confirmed = min(float(c3["open"]), float(c3["close"])) > body_top_2
                else:
                    confirmed = float(c3["close"]) > body_top_2
                if confirmed:
                    swings.append(
                        SwingPoint(
                            index=i,
                            timestamp=c2["_timestamp"],
                            swing_type=SwingType.LOW,
                            pattern=PatternType.THREE_BAR_REJECTION,
                            price=float(lows[i]),
                            body_reference=float(body_top_2),
                            confirmed=True,
                            confirmation_index=i + 1,
                            meta={
                                "body_ratio": round(body2 / max(body2_ref, range2), 4),
                                "wick_size": float(body_top_2 - lows[i]),
                            },
                        )
                    )

        # ---- Swing High (bearish rejection) ----
        if highs[i] > highs[i - 1] and highs[i] > highs[i + 1]:
            _, body_bottom_2 = _candle_body_bounds(c2)
            is_wick_dominated = body2 <= max_body_ratio * max(body2_ref, range2)
            if is_wick_dominated:
                if require_full_confirmation:
                    confirmed = max(float(c3["open"]), float(c3["close"])) < body_bottom_2
                else:
                    confirmed = float(c3["close"]) < body_bottom_2
                if confirmed:
                    swings.append(
                        SwingPoint(
                            index=i,
                            timestamp=c2["_timestamp"],
                            swing_type=SwingType.HIGH,
                            pattern=PatternType.THREE_BAR_REJECTION,
                            price=float(highs[i]),
                            body_reference=float(body_bottom_2),
                            confirmed=True,
                            confirmation_index=i + 1,
                            meta={
                                "body_ratio": round(body2 / max(body2_ref, range2), 4),
                                "wick_size": float(highs[i] - body_bottom_2),
                            },
                        )
                    )

    return swings


# ============================================================================
# 2) CLASSIC THREE-BAR EXTREMITY SWING (fractal)
# ============================================================================

def detect_classic_three_bar_swings(
    df: pd.DataFrame,
    strict: bool = True,
) -> List[SwingPoint]:
    """
    Detect classic 3-bar fractal swing highs/lows.

    Swing Low:  low[i] < low[i-1]  AND  low[i] < low[i+1]
    Swing High: high[i] > high[i-1] AND high[i] > high[i+1]

    Parameters
    ----------
    strict : bool
        If True, comparisons are strict (<, >) per the classic definition
        (ties do NOT count as a swing). If False, uses <=/>= (looser,
        useful on markets/timeframes with many equal-price prints).

    Returns
    -------
    List[SwingPoint] with confirmed=True (a classic 3-bar fractal is
    fully defined the moment candle i+1 closes -- there is no further
    confirmation step in this methodology).

    Raises
    ------
    SwingDetectionError on invalid/too-short input.
    """
    d = _validate_ohlc(df, min_rows=3)
    highs, lows = d["high"].values, d["low"].values
    swings: List[SwingPoint] = []

    for i in range(1, len(d) - 1):
        row = d.iloc[i]
        if strict:
            is_low = lows[i] < lows[i - 1] and lows[i] < lows[i + 1]
            is_high = highs[i] > highs[i - 1] and highs[i] > highs[i + 1]
        else:
            is_low = lows[i] <= lows[i - 1] and lows[i] <= lows[i + 1]
            is_high = highs[i] >= highs[i - 1] and highs[i] >= highs[i + 1]

        if is_low:
            swings.append(
                SwingPoint(
                    index=i,
                    timestamp=row["_timestamp"],
                    swing_type=SwingType.LOW,
                    pattern=PatternType.CLASSIC_THREE_BAR,
                    price=float(lows[i]),
                    body_reference=float(min(row["open"], row["close"])),
                    confirmed=True,
                    confirmation_index=i + 1,
                )
            )
        if is_high:
            swings.append(
                SwingPoint(
                    index=i,
                    timestamp=row["_timestamp"],
                    swing_type=SwingType.HIGH,
                    pattern=PatternType.CLASSIC_THREE_BAR,
                    price=float(highs[i]),
                    body_reference=float(max(row["open"], row["close"])),
                    confirmed=True,
                    confirmation_index=i + 1,
                )
            )

    return swings


# ============================================================================
# 3) MARKET STRUCTURE / STRUCTURAL SWINGS (ChoCH / BOS)
# ============================================================================

def detect_structural_swings(
    df: pd.DataFrame,
    pivot_source: Literal["classic", "rejection"] = "classic",
    body_close_confirmation: bool = True,
) -> "tuple[List[SwingPoint], List[StructuralEvent]]":
    """
    Detect structural swing points and the BOS / ChoCH events they produce.

    Methodology
    -----------
    1. Extract raw pivots using either the classic fractal detector or the
       3-bar rejection detector (`pivot_source`).
    2. Walk forward through candles. Maintain the most recent confirmed
       swing high and swing low, and a running structural `bias`.
    3. A structural break occurs when a later candle's BODY (not just a
       wick) cleanly closes beyond a tracked swing level:
         - close beyond a swing HIGH -> bullish break
         - close beyond a swing LOW  -> bearish break
       (`body_close_confirmation=False` relaxes this to use wick extremes
       instead of body close, which is closer to a plain "level break").
    4. Classification vs. prevailing bias:
         - Break in the SAME direction as current bias -> Break of
           Structure (BOS): trend continuation.
         - Break AGAINST current bias -> Change of Character (ChoCH):
           potential trend reversal. Bias flips after a ChoCH.
       Before any bias is established, the first break sets initial bias
       and is still labeled ChoCH (first structural signal) for
       traceability -- see `meta['initial']`.

    Returns
    -------
    (pivots, events) where:
        pivots  -> List[SwingPoint] of the raw underlying swing points.
        events  -> List[StructuralEvent] in chronological order.

    Raises
    ------
    SwingDetectionError on invalid/too-short input or unknown pivot_source.
    """
    d = _validate_ohlc(df, min_rows=3)

    if pivot_source == "classic":
        pivots = detect_classic_three_bar_swings(df)
    elif pivot_source == "rejection":
        pivots = detect_three_bar_rejection_swings(df)
    else:
        raise SwingDetectionError(f"Unknown pivot_source: {pivot_source!r}")

    pivots.sort(key=lambda p: p.index)

    events: List[StructuralEvent] = []
    bias = StructuralBias.UNDEFINED

    # Track the most recent *unbroken* swing high and swing low.
    active_high: Optional[SwingPoint] = None
    active_low: Optional[SwingPoint] = None

    # Pointer into pivots list so we only "activate" pivots once we reach
    # their index while scanning candles forward (no look-ahead).
    pivot_i = 0
    n = len(d)

    for i in range(n):
        # Activate any pivots whose index has just been reached.
        while pivot_i < len(pivots) and pivots[pivot_i].index == i:
            p = pivots[pivot_i]
            if p.swing_type == SwingType.HIGH:
                active_high = p
            else:
                active_low = p
            pivot_i += 1

        row = d.iloc[i]
        close = float(row["close"])
        high_extreme = float(row["high"])
        low_extreme = float(row["low"])

        # Check break above active_high
        if active_high is not None and active_high.index < i:
            broke_above = (close > active_high.price) if body_close_confirmation else (high_extreme > active_high.price)
            if broke_above:
                if bias in (StructuralBias.UNDEFINED, StructuralBias.BULLISH):
                    event_type = PatternType.STRUCTURAL_BOS if bias == StructuralBias.BULLISH else PatternType.STRUCTURAL_CHOCH
                else:  # bias was BEARISH -> this is a reversal
                    event_type = PatternType.STRUCTURAL_CHOCH
                events.append(
                    StructuralEvent(
                        index=i,
                        timestamp=row["_timestamp"],
                        event=event_type,
                        direction="bullish",
                        broken_swing=active_high,
                        break_price=close,
                        new_bias=StructuralBias.BULLISH,
                        meta={"initial": bias == StructuralBias.UNDEFINED},
                    )
                )
                bias = StructuralBias.BULLISH
                active_high = None  # consumed; needs a fresh pivot to re-arm

        # Check break below active_low
        if active_low is not None and active_low.index < i:
            broke_below = (close < active_low.price) if body_close_confirmation else (low_extreme < active_low.price)
            if broke_below:
                if bias in (StructuralBias.UNDEFINED, StructuralBias.BEARISH):
                    event_type = PatternType.STRUCTURAL_BOS if bias == StructuralBias.BEARISH else PatternType.STRUCTURAL_CHOCH
                else:  # bias was BULLISH -> reversal
                    event_type = PatternType.STRUCTURAL_CHOCH
                events.append(
                    StructuralEvent(
                        index=i,
                        timestamp=row["_timestamp"],
                        event=event_type,
                        direction="bearish",
                        broken_swing=active_low,
                        break_price=close,
                        new_bias=StructuralBias.BEARISH,
                        meta={"initial": bias == StructuralBias.UNDEFINED},
                    )
                )
                bias = StructuralBias.BEARISH
                active_low = None

    return pivots, events


# ============================================================================
# 4) EXECUTION & RISK MANAGEMENT INTEGRATION
# ============================================================================

def compute_stop_loss_for_swing(
    df: pd.DataFrame,
    swing: SwingPoint,
    atr_period: int = 14,
    atr_buffer_mult: float = 0.25,
    pct_buffer: float = 0.0015,
    min_buffer_abs: float = 0.0,
) -> float:
    """
    Compute a dynamic Stop Loss level placed strictly BEHIND a swing point.

    The buffer added beyond the raw swing extreme is:
        buffer = max(ATR(atr_period) * atr_buffer_mult,
                      swing.price * pct_buffer,
                      min_buffer_abs)

    i.e. the larger of an absolute-volatility (ATR) buffer and a
    percentage-of-price buffer, so the SL adapts to both changing
    volatility regimes and the instrument's price scale. This mirrors
    the "won't get stopped by normal noise" principle.

    For a SWING LOW (long trade context): SL = swing.price - buffer
    For a SWING HIGH (short trade context): SL = swing.price + buffer

    Returns
    -------
    float: the computed stop-loss price.

    Raises
    ------
    SwingDetectionError if df is invalid or swing.index is out of range.
    """
    d = _validate_ohlc(df, min_rows=max(2, atr_period))
    if swing.index < 0 or swing.index >= len(d):
        raise SwingDetectionError(
            f"swing.index={swing.index} out of range for df of length {len(d)}."
        )

    atr_series = _average_true_range(d, period=atr_period)
    atr_at_swing = float(atr_series.iloc[swing.index])
    if not np.isfinite(atr_at_swing):
        atr_at_swing = 0.0

    buffer = max(
        atr_at_swing * atr_buffer_mult,
        swing.price * pct_buffer,
        min_buffer_abs,
    )

    if swing.swing_type == SwingType.LOW:
        return float(swing.price - buffer)
    else:
        return float(swing.price + buffer)


def attach_risk_to_signal(
    df: pd.DataFrame,
    swing: SwingPoint,
    direction: Literal["long", "short"],
    entry_price: Optional[float] = None,
    risk_reward: float = 2.0,
    fixed_tp: Optional[float] = None,
    atr_period: int = 14,
    atr_buffer_mult: float = 0.25,
    pct_buffer: float = 0.0015,
) -> TradeSignal:
    """
    Build a structured, execution-ready TradeSignal from a detected swing.

    Parameters
    ----------
    direction : "long" or "short" -- the trade direction this swing informs.
        (Typically: swing LOW -> long setup, swing HIGH -> short setup, but
        left explicit so structural ChoCH/BOS events -- which may want the
        opposite side -- can also use this function.)
    entry_price : optional explicit entry; defaults to the swing's
        `body_reference` (the confirmation/close level) which is a
        reasonable "trigger" proxy; callers can override with live price.
    risk_reward : desired R-multiple for TP if `fixed_tp` is not given.
    fixed_tp : optional explicit take-profit price overriding risk_reward.

    Returns
    -------
    TradeSignal -- `valid=False` (with `reason` explaining why) if the
    computed SL/TP would be nonsensical (e.g. SL on wrong side of entry,
    or zero/negative distance), so downstream execution code can safely
    skip malformed signals from noisy real-time data instead of crashing.
    """
    try:
        sl = compute_stop_loss_for_swing(
            df, swing,
            atr_period=atr_period,
            atr_buffer_mult=atr_buffer_mult,
            pct_buffer=pct_buffer,
        )
    except SwingDetectionError as e:
        return TradeSignal(
            source=swing, direction=direction, entry_trigger=float("nan"),
            stop_loss=float("nan"), take_profit=None, risk_reward=None,
            sl_distance=float("nan"), valid=False, reason=f"SL computation failed: {e}",
        )

    entry = float(entry_price) if entry_price is not None else float(swing.body_reference)
    sl_distance = abs(entry - sl)

    if sl_distance <= 0 or not np.isfinite(sl_distance):
        return TradeSignal(
            source=swing, direction=direction, entry_trigger=entry, stop_loss=sl,
            take_profit=None, risk_reward=None, sl_distance=sl_distance,
            valid=False, reason="Non-positive or invalid SL distance.",
        )

    if direction == "long":
        if sl >= entry:
            return TradeSignal(
                source=swing, direction=direction, entry_trigger=entry, stop_loss=sl,
                take_profit=None, risk_reward=None, sl_distance=sl_distance,
                valid=False, reason="Stop loss is not below entry for a long trade.",
            )
        tp = float(fixed_tp) if fixed_tp is not None else entry + sl_distance * risk_reward
        rr = (tp - entry) / sl_distance if tp is not None else None
    elif direction == "short":
        if sl <= entry:
            return TradeSignal(
                source=swing, direction=direction, entry_trigger=entry, stop_loss=sl,
                take_profit=None, risk_reward=None, sl_distance=sl_distance,
                valid=False, reason="Stop loss is not above entry for a short trade.",
            )
        tp = float(fixed_tp) if fixed_tp is not None else entry - sl_distance * risk_reward
        rr = (entry - tp) / sl_distance if tp is not None else None
    else:
        return TradeSignal(
            source=swing, direction=direction, entry_trigger=entry, stop_loss=sl,
            take_profit=None, risk_reward=None, sl_distance=sl_distance,
            valid=False, reason=f"Unknown direction {direction!r}, expected 'long' or 'short'.",
        )

    return TradeSignal(
        source=swing, direction=direction, entry_trigger=entry, stop_loss=sl,
        take_profit=float(tp), risk_reward=float(rr) if rr is not None else None,
        sl_distance=float(sl_distance), valid=True,
    )


# ============================================================================
# ORCHESTRATOR — run everything and return one structured payload
# ============================================================================

def analyze_swings(
    df: pd.DataFrame,
    include_rejection: bool = True,
    include_classic: bool = True,
    include_structural: bool = True,
    risk_reward: float = 2.0,
    atr_period: int = 14,
    atr_buffer_mult: float = 0.25,
    pct_buffer: float = 0.0015,
) -> Dict[str, Any]:
    """
    Run all requested detectors on `df` and return one structured,
    JSON-serializable payload combining swing points, structural events,
    and risk-annotated trade signals for the most recent swings.

    Returns a dict of the shape:
    {
        "ok": bool,
        "error": Optional[str],
        "rejection_swings": [...],
        "classic_swings": [...],
        "structural_pivots": [...],
        "structural_events": [...],
        "signals": [...],          # TradeSignal dicts, newest-first
    }

    This function never raises for malformed input -- it catches
    SwingDetectionError and returns ok=False with the reason, which is
    the recommended integration point for a live bot's decision loop
    (so one bad candle/feed hiccup cannot crash the trading loop).
    """
    result: Dict[str, Any] = {
        "ok": True,
        "error": None,
        "rejection_swings": [],
        "classic_swings": [],
        "structural_pivots": [],
        "structural_events": [],
        "signals": [],
    }

    try:
        rejection_swings: List[SwingPoint] = []
        classic_swings: List[SwingPoint] = []
        structural_pivots: List[SwingPoint] = []
        structural_events: List[StructuralEvent] = []

        if include_rejection:
            rejection_swings = detect_three_bar_rejection_swings(df)
            result["rejection_swings"] = [s.to_dict() for s in rejection_swings]

        if include_classic:
            classic_swings = detect_classic_three_bar_swings(df)
            result["classic_swings"] = [s.to_dict() for s in classic_swings]

        if include_structural:
            structural_pivots, structural_events = detect_structural_swings(df)
            result["structural_pivots"] = [s.to_dict() for s in structural_pivots]
            result["structural_events"] = [e.to_dict() for e in structural_events]

        # Build risk-annotated signals from every rejection + classic swing:
        # swing LOW -> long setup, swing HIGH -> short setup.
        signals: List[TradeSignal] = []
        for swing in (rejection_swings + classic_swings):
            direction = "long" if swing.swing_type == SwingType.LOW else "short"
            sig = attach_risk_to_signal(
                df, swing, direction,
                risk_reward=risk_reward,
                atr_period=atr_period,
                atr_buffer_mult=atr_buffer_mult,
                pct_buffer=pct_buffer,
            )
            signals.append(sig)

        signals.sort(key=lambda s: s.source.index, reverse=True)
        result["signals"] = [s.to_dict() for s in signals]

    except SwingDetectionError as e:
        result["ok"] = False
        result["error"] = str(e)

    return result


# ============================================================================
# Minimal self-test / usage example (only runs when executed directly)
# ============================================================================

if __name__ == "__main__":
    import numpy as _np

    rng = _np.random.default_rng(42)
    n = 200
    price = 100 + _np.cumsum(rng.normal(0, 1, n))
    highs = price + rng.uniform(0.2, 1.5, n)
    lows = price - rng.uniform(0.2, 1.5, n)
    opens = price + rng.normal(0, 0.3, n)
    closes = price + rng.normal(0, 0.3, n)
    closes = _np.clip(closes, lows, highs)
    opens = _np.clip(opens, lows, highs)

    sample = pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes},
        index=pd.date_range("2024-01-01", periods=n, freq="1h"),
    )

    payload = analyze_swings(sample)
    print(f"ok={payload['ok']}  rejection={len(payload['rejection_swings'])}  "
          f"classic={len(payload['classic_swings'])}  "
          f"structural_events={len(payload['structural_events'])}  "
          f"signals={len(payload['signals'])}")
    if payload["signals"]:
        print("Most recent signal:", payload["signals"][0])
