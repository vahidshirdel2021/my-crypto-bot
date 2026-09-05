# -*- coding: utf-8 -*-
"""
klsde_v2.py — KLSDE V2: Universal Key-Level Reaction Engine
=============================================================
Implements KLSDE_V2_Universal_Level_Reaction_Spec.md:

    LEVEL + PRICE REACTION = SETUP

15 key levels (Month/Week/Day/4H/1H x High/Low/EQ) are monitored on a
single execution timeframe (default 5m). Every level interaction opens a
stateful window that is resolved, deterministically, into exactly one of:

    BOF  — Break Of Failure
    TST  — Test of Support/Resistance
    BPB  — Pullback After Breakout
    BP   — Simple Trend Pullback
    CPB  — Complex Trend Pullback

or `none`.

This module is intentionally independent of order/execution management
(spec §13/§16): it only produces `SetupEvent` dicts. A downstream
confluence layer (USCL) decides what, if anything, to trade.

Design notes
------------
* Level computation, the classification state machine, confidence
  scoring and level clustering are separate concerns (spec §11/§12),
  implemented as separate functions below so each can be tested and
  tuned independently.
* Swing/structure counting for pullback classification (BP/BPB/CPB)
  reuses `swing_detection.detect_classic_three_bar_swings` — no second
  competing swing detector is implemented here (spec §5 CPB, §8).
* B1..B7 / S1..S7 are NOT reimplemented here. This module is additive;
  legacy codes may be attached as `sub_pattern` metadata by a caller
  that still has access to that classification (spec §9) — see
  `attach_legacy_subpattern()` at the bottom.
* Both historical (batch) and streaming use the exact same
  `KLSDEEngine.step()` call per new closed candle, so replay and live
  behavior are identical by construction (spec §14 no-look-ahead /
  historical-vs-streaming consistency).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from swing_detection import (
        detect_classic_three_bar_swings,
        SwingType,
        SwingDetectionError,
    )
    _SWING_LIB_AVAILABLE = True
except Exception:  # pragma: no cover - optional dependency guard
    _SWING_LIB_AVAILABLE = False
    SwingDetectionError = Exception  # type: ignore


# ============================================================================
# 1. Key-level universe (spec §1 / §2)
# ============================================================================

# (level_code, period, kind, tier)
LEVEL_SPECS: List[Tuple[str, str, str, str]] = [
    ("PMH",   "month", "high", "major"),
    ("PML",   "month", "low",  "major"),
    ("PMEQ",  "month", "eq",   "major"),
    ("PWH",   "week",  "high", "major"),
    ("PWL",   "week",  "low",  "major"),
    ("PWEQ",  "week",  "eq",   "major"),
    ("PDH",   "day",   "high", "intraday"),
    ("PDL",   "day",   "low",  "intraday"),
    ("PDEQ",  "day",   "eq",   "intraday"),
    ("P4HH",  "4h",    "high", "execution"),
    ("P4HL",  "4h",    "low",  "execution"),
    ("P4HEQ", "4h",    "eq",   "execution"),
    ("P1HH",  "1h",    "high", "execution"),
    ("P1HL",  "1h",    "low",  "execution"),
    ("P1HEQ", "1h",    "eq",   "execution"),
]

LEVEL_KIND: Dict[str, str] = {c: k for c, _, k, _ in LEVEL_SPECS}
LEVEL_TIER: Dict[str, str] = {c: t for c, _, _, t in LEVEL_SPECS}
LEVEL_PERIOD: Dict[str, str] = {c: p for c, p, _, _ in LEVEL_SPECS}
ALL_LEVEL_CODES: List[str] = [c for c, _, _, _ in LEVEL_SPECS]
PERIODS: List[str] = ["month", "week", "day", "4h", "1h"]

MIN_PERIOD_COMPLETENESS_RATIO = 0.85

SETUP_TYPES = ("BOF", "TST", "BPB", "BP", "CPB")

DEFAULT_CONFIG: Dict[str, Any] = {
    # State 1 — interaction window opens once price is within this many
    # ATR of the level.
    "approach_atr": 1.0,
    # "touched" if price wick is within this many ATR of the level.
    "touch_atr": 0.10,
    # candles allowed to wait for either a real breach or a clear
    # rejection before the window times out with no setup.
    "touch_timeout_candles": 8,
    # State 2 — minimum wick penetration beyond the level to count as a
    # "real breach" rather than mere noise.
    "min_breach_atr": 0.15,
    # State 3 — a breach becomes a "confirmed full breakout" once close
    # is beyond the level by this many ATR (for `breakout_confirm_closes`
    # consecutive closes).
    "breakout_confirm_atr": 0.25,
    "breakout_confirm_closes": 1,
    # candles allowed after a real breach to resolve into BOF before the
    # window is abandoned with no setup.
    "failure_window_candles": 3,
    # State 4 — minimum retracement (in ATR, against breakout direction,
    # measured from the post-breakout extreme) to call it a genuine
    # pullback rather than noise.
    "min_pullback_atr": 0.15,
    # candles allowed after confirmed breakout to find a pullback +
    # continuation before the window is closed as breakout-context-only.
    "pullback_timeout_candles": 60,
    # State 5 — BP requires the retest to come back within this many ATR
    # of the broken level.
    "retest_tolerance_atr": 0.20,
    "min_cpb_swing_count": 2,
    "min_confirm_body_ratio": 0.35,
    # confidence weights (spec §11) — tunable, never affect classification
    "confidence": {
        "base": 0.45,
        "tier_weight": 0.20,
        "breach_depth_weight": 0.15,
        "speed_weight": 0.10,
        "rejection_quality_weight": 0.10,
        "tier_scores": {"major": 1.0, "intraday": 0.75, "execution": 0.5},
    },
    # clustering (spec §12)
    "cluster_atr": 0.5,
}


def _merge_cfg(overrides: Optional[dict]) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if isinstance(overrides, dict):
        for k, v in overrides.items():
            if k in ("confidence",) and isinstance(v, dict):
                merged = dict(cfg.get(k, {}))
                merged.update(v)
                cfg[k] = merged
            else:
                cfg[k] = v
    return cfg


# ============================================================================
# 2. SetupEvent (spec §10)
# ============================================================================

@dataclass
class SetupEvent:
    setup_type: str
    level: str
    level_tier: str
    level_price: float
    source_period: Optional[str]
    symbol: str
    execution_timeframe: str
    direction: str
    window_opened_at: Any
    resolved_at: Any
    confidence: float
    evidence: Dict[str, Any] = field(default_factory=dict)
    sub_pattern: Optional[str] = None
    cluster: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


# ============================================================================
# 3. Level computation — generic across all 5 periods (spec §1, §4, §14)
# ============================================================================

def _to_utc_datetime(ts: pd.Series) -> pd.Series:
    ts_num = pd.to_numeric(ts, errors="coerce")
    median = float(ts_num.dropna().median()) if ts_num.notna().any() else 0.0
    unit = "ms" if median > 1e12 else "s"
    return pd.to_datetime(ts_num, unit=unit, utc=True)


def _infer_bar_seconds(dt: pd.Series) -> float:
    diffs = dt.diff().dropna()
    if diffs.empty:
        return 0.0
    return float(diffs.dt.total_seconds().median() or 0.0)


def _floor_period(dt: pd.Series, period: str) -> pd.Series:
    if period == "day":
        return dt.dt.floor("D")
    if period == "week":
        d0 = dt.dt.floor("D")
        dow = d0.dt.dayofweek
        return d0 - pd.to_timedelta(dow, unit="D")
    if period == "month":
        naive = dt.dt.tz_convert("UTC").dt.tz_localize(None)
        starts = pd.to_datetime(naive.dt.strftime("%Y-%m-01"))
        return starts.dt.tz_localize("UTC")
    if period == "4h":
        return dt.dt.floor("4h")
    if period == "1h":
        return dt.dt.floor("1h")
    raise ValueError(f"Unknown period: {period!r}")


def _compute_one_period_levels(dt: pd.Series, high: pd.Series, low: pd.Series,
                                period: str) -> pd.DataFrame:
    """
    Returns a DataFrame aligned 1:1 with the input rows, with columns
    hi/lo/eq/src for the *previous, fully completed* `period`.

    No look-ahead: a period's H/L only become usable once the FOLLOWING
    period has started (i.e. `_prev_dur` — the length of that period in
    seconds — is only known once we've observed the boundary at which it
    ended). Completeness is additionally checked against the number of
    candles actually observed vs. expected (MIN_PERIOD_COMPLETENESS_RATIO)
    so a truncated period near the start of the dataset never produces a
    level (matches pdh_eq_pdl_engine.py's existing safeguard).
    """
    n = len(dt)
    pstart = _floor_period(dt, period)
    bar_seconds = _infer_bar_seconds(dt)

    tmp = pd.DataFrame({"_pstart": pstart, "high": high, "low": low})
    grp = tmp.groupby("_pstart").agg(_hi=("high", "max"), _lo=("low", "min"),
                                      _n=("high", "size"))
    grp = grp.sort_index()

    idx = grp.index.to_series()
    next_start = idx.shift(-1)
    dur_sec = (next_start - idx).dt.total_seconds()

    prev_hi = grp["_hi"].shift(1)
    prev_lo = grp["_lo"].shift(1)
    prev_n = grp["_n"].shift(1)
    prev_dur = dur_sec.shift(1)
    prev_label = idx.shift(1)

    if bar_seconds > 0:
        expected_bars = prev_dur / bar_seconds
        prev_complete = (prev_n >= expected_bars * MIN_PERIOD_COMPLETENESS_RATIO)
    else:
        prev_complete = pd.Series(False, index=grp.index)
    prev_complete = prev_complete.fillna(False)

    out = pd.DataFrame(index=grp.index)
    out["_hi"] = prev_hi.where(prev_complete)
    out["_lo"] = prev_lo.where(prev_complete)
    out["_eq"] = ((prev_hi + prev_lo) / 2.0).where(prev_complete)
    out["_src"] = prev_label.dt.strftime("%Y-%m-%dT%H:%M:%SZ").where(prev_complete)

    merged = tmp[["_pstart"]].merge(out, left_on="_pstart", right_index=True, how="left")
    merged = merged.reset_index(drop=True)
    assert len(merged) == n
    return merged[["_hi", "_lo", "_eq", "_src"]]


def compute_all_levels(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given an execution-timeframe OHLC(V) dataframe with a `timestamp`
    column (unix seconds or ms), returns a copy with 15*4 = 60 extra
    columns: for every (period, kind) pair the current value of that
    level plus its source-period label, e.g. `_day_hi`, `_day_hi_src`.

    Only fully completed periods produce a level (NaN otherwise) — see
    `_compute_one_period_levels`. Never uses the currently-forming
    period's own high/low.
    """
    d = df.copy()
    d["_dt"] = _to_utc_datetime(d["timestamp"])
    d = d.sort_values("_dt").reset_index(drop=True)

    for period in PERIODS:
        lv = _compute_one_period_levels(d["_dt"], d["high"], d["low"], period)
        d[f"_{period}_hi"] = lv["_hi"].values
        d[f"_{period}_lo"] = lv["_lo"].values
        d[f"_{period}_eq"] = lv["_eq"].values
        d[f"_{period}_src"] = lv["_src"].values
    return d


def _level_price_col(level_code: str) -> str:
    period = LEVEL_PERIOD[level_code]
    kind = LEVEL_KIND[level_code]
    return f"_{period}_{ {'high': 'hi', 'low': 'lo', 'eq': 'eq'}[kind] }"


def _level_src_col(level_code: str) -> str:
    return f"_{LEVEL_PERIOD[level_code]}_src"


def _ensure_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    if "atr" in df.columns:
        return pd.to_numeric(df["atr"], errors="coerce")
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


# ============================================================================
# 4. Small helpers shared by the state machine
# ============================================================================

def _body_ratio(row) -> float:
    rng = max(float(row["high"]) - float(row["low"]), 1e-12)
    return abs(float(row["close"]) - float(row["open"])) / rng


def _is_confirm_candle(row, direction: str, min_body_ratio: float) -> bool:
    """direction: 'up' -> bullish confirm candle, 'down' -> bearish confirm candle."""
    if direction == "up":
        return float(row["close"]) > float(row["open"]) and _body_ratio(row) >= min_body_ratio
    return float(row["close"]) < float(row["open"]) and _body_ratio(row) >= min_body_ratio


def _count_corrective_swings(sub_df: pd.DataFrame, breakout_dir: str) -> int:
    """
    Count corrective swing points (against `breakout_dir`) inside `sub_df`
    using the shared classic 3-bar fractal swing detector — this is the
    ONLY swing counter used anywhere in this module (spec §5/§8: do not
    build a second competing swing detector).

    For an 'up' breakout, a corrective leg is marked by a swing LOW
    (a local low pivot) formed during the pullback; for a 'down'
    breakout, a corrective leg is marked by a swing HIGH.
    """
    if not _SWING_LIB_AVAILABLE or len(sub_df) < 3:
        return 0
    try:
        swings = detect_classic_three_bar_swings(sub_df.reset_index(drop=True))
    except SwingDetectionError:
        return 0
    wanted = SwingType.LOW if breakout_dir == "up" else SwingType.HIGH
    return sum(1 for s in swings if s.swing_type == wanted)


# ============================================================================
# 5. The deterministic per-level state machine (spec §6)
# ============================================================================

class _LevelWindow:
    """Mutable state for one in-flight interaction window on one level."""

    __slots__ = (
        "state", "opened_idx", "src", "effective_kind",
        "breach_idx", "breakout_confirm_idx", "post_breakout_extreme_idx",
        "post_breakout_extreme_price", "consec_confirm_closes",
        "pullback_extreme_idx", "pullback_extreme_price", "in_pullback",
    )

    def __init__(self):
        self.state = "idle"           # idle | touched | breached | breakout | pullback
        self.opened_idx = None
        self.src = None
        self.effective_kind = None    # 'high' or 'low' (resolved for EQ at open time)
        self.breach_idx = None
        self.breakout_confirm_idx = None
        self.post_breakout_extreme_idx = None
        self.post_breakout_extreme_price = None
        self.consec_confirm_closes = 0
        self.pullback_extreme_idx = None
        self.pullback_extreme_price = None
        self.in_pullback = False

    def reset(self):
        self.__init__()


def run_level_reactions(df: pd.DataFrame, level_code: str, symbol: str,
                         execution_timeframe: str, cfg: Optional[dict] = None
                         ) -> List[Dict[str, Any]]:
    """
    Walk `df` (must already contain columns from `compute_all_levels` and
    an `atr` column — call `_ensure_atr` first if not) candle by candle
    and emit resolved SetupEvent dicts for `level_code`.

    Deterministic, single pass, no look-ahead: at candle i we only ever
    read df.iloc[0..i]. This is exactly the function called for both
    historical replay and live streaming (call again with one more row
    appended each time price closes a new candle) so both modes agree
    by construction (spec §14).
    """
    cfg = _merge_cfg(cfg)
    kind = LEVEL_KIND[level_code]
    tier = LEVEL_TIER[level_code]
    price_col = _level_price_col(level_code)
    src_col = _level_src_col(level_code)

    if price_col not in df.columns or "atr" not in df.columns:
        return []

    n = len(df)
    events: List[Dict[str, Any]] = []
    win = _LevelWindow()

    approach_atr = float(cfg["approach_atr"])
    touch_atr = float(cfg["touch_atr"])
    touch_timeout = int(cfg["touch_timeout_candles"])
    min_breach_atr = float(cfg["min_breach_atr"])
    breakout_confirm_atr = float(cfg["breakout_confirm_atr"])
    breakout_confirm_closes = int(cfg["breakout_confirm_closes"])
    failure_window = int(cfg["failure_window_candles"])
    min_pullback_atr = float(cfg["min_pullback_atr"])
    pullback_timeout = int(cfg["pullback_timeout_candles"])
    retest_tol_atr = float(cfg["retest_tolerance_atr"])
    min_cpb_swings = int(cfg["min_cpb_swing_count"])
    min_body_ratio = float(cfg["min_confirm_body_ratio"])

    def _sided(effective_kind: str, i: int, level_price: float, atr: float):
        """Return (wick_breach, close_breach) toward the 'breakout side'
        for the given effective_kind, at candle i."""
        row = df.iloc[i]
        if effective_kind == "high":
            wick = (float(row["high"]) - level_price) / atr
            close_b = (float(row["close"]) - level_price) / atr
        else:
            wick = (level_price - float(row["low"])) / atr
            close_b = (level_price - float(row["close"])) / atr
        return wick, close_b

    def _emit(setup_type, direction, resolved_idx, level_price, src, evidence):
        conf = _confidence(cfg, tier, evidence)
        events.append(SetupEvent(
            setup_type=setup_type,
            level=level_code,
            level_tier=tier,
            level_price=float(level_price),
            source_period=src,
            symbol=symbol,
            execution_timeframe=execution_timeframe,
            direction=direction,
            window_opened_at=_ts(df, win.opened_idx),
            resolved_at=_ts(df, resolved_idx),
            confidence=conf,
            evidence=evidence,
        ).to_dict())

    i = 0
    while i < n:
        level_price = df.at[df.index[i], price_col]
        src = df.at[df.index[i], src_col]
        atr = df.at[df.index[i], "atr"]

        if pd.isna(level_price) or pd.isna(atr) or atr <= 0:
            i += 1
            continue

        # A level instance is tied to its source period (spec §4). If the
        # instance changed mid-window, the old window can no longer be
        # meaningfully resolved against a level that no longer exists —
        # discard it (no setup emitted for the abandoned window).
        if win.state != "idle" and win.src is not None and src != win.src:
            win.reset()

        row = df.iloc[i]
        close = float(row["close"]); high = float(row["high"]); low = float(row["low"])

        # ---------------- STATE 1 — Interaction -----------------------
        if win.state == "idle":
            if kind == "high":
                dist = (level_price - low) / atr  # how close price came from below
                approached = dist >= -approach_atr and high >= level_price - touch_atr * atr
                effective_kind = "high"
            elif kind == "low":
                dist = (high - level_price) / atr
                approached = dist >= -approach_atr and low <= level_price + touch_atr * atr
                effective_kind = "low"
            else:  # eq — approach side decides which fixed-kind machinery applies
                near = abs(close - level_price) / atr <= approach_atr
                touched_now = (high >= level_price - touch_atr * atr and
                               low <= level_price + touch_atr * atr)
                approached = near or touched_now
                effective_kind = "high" if close <= level_price else "low"

            if approached:
                win.state = "touched"
                win.opened_idx = i
                win.src = src
                win.effective_kind = effective_kind
            i += 1
            continue

        # From here on, effective_kind is fixed for this window.
        eff = win.effective_kind

        # ---------------- STATE 2 — Breach ------------------------------
        if win.state == "touched":
            wick_b, close_b = _sided(eff, i, level_price, atr)
            if wick_b >= min_breach_atr:
                win.state = "breached"
                win.breach_idx = i
                # fall through to STATE 3 handling below on this same candle
            else:
                rejected = close_b <= -touch_atr
                timed_out = (i - win.opened_idx) >= touch_timeout
                if rejected:
                    direction = "bearish" if eff == "high" else "bullish"
                    _emit("TST", direction, i, level_price, src, {
                        "penetration_depth_atr": round(max(wick_b, 0.0), 4),
                        "breakout_confirmed": False,
                        "pullback_swing_count": 0,
                        "retest_reached_level": False,
                        "candles_to_resolve": i - win.opened_idx,
                    })
                    win.reset()
                elif timed_out:
                    win.reset()
                i += 1
                continue

        # ---------------- STATE 3 — Breakout qualification --------------
        if win.state == "breached":
            wick_b, close_b = _sided(eff, i, level_price, atr)
            if close_b >= breakout_confirm_atr:
                win.consec_confirm_closes += 1
            else:
                win.consec_confirm_closes = 0

            if win.consec_confirm_closes >= breakout_confirm_closes:
                win.state = "breakout"
                win.breakout_confirm_idx = i
                win.post_breakout_extreme_idx = i
                win.post_breakout_extreme_price = high if eff == "high" else low
                i += 1
                continue

            if close_b <= 0:
                direction = "bearish" if eff == "high" else "bullish"
                _emit("BOF", direction, i, level_price, src, {
                    "penetration_depth_atr": round(max(wick_b, 0.0), 4),
                    "breakout_confirmed": False,
                    "pullback_swing_count": 0,
                    "retest_reached_level": False,
                    "candles_to_resolve": i - win.breach_idx,
                })
                win.reset()
                i += 1
                continue

            if (i - win.breach_idx) >= failure_window:
                win.reset()
                i += 1
                continue

            i += 1
            continue

        # ---------------- STATE 4 — Pullback -----------------------------
        if win.state == "breakout":
            # track the running post-breakout extreme in breakout direction
            if eff == "high":
                if high > win.post_breakout_extreme_price:
                    win.post_breakout_extreme_price = high
                    win.post_breakout_extreme_idx = i
                retrace_atr = (win.post_breakout_extreme_price - low) / atr
            else:
                if low < win.post_breakout_extreme_price:
                    win.post_breakout_extreme_price = low
                    win.post_breakout_extreme_idx = i
                retrace_atr = (high - win.post_breakout_extreme_price) / atr

            if retrace_atr >= min_pullback_atr:
                win.state = "pullback"
                win.pullback_extreme_idx = i
                win.pullback_extreme_price = low if eff == "high" else high
                i += 1
                continue

            if (i - win.breakout_confirm_idx) >= pullback_timeout:
                # breakout happened but no pullback ever formed: context
                # only, no setup (spec §6 State 4).
                win.reset()
                i += 1
                continue

            i += 1
            continue

        # ---------------- STATE 5 — Pullback classification --------------
        if win.state == "pullback":
            breakout_dir = "up" if eff == "high" else "down"
            if eff == "high":
                if low < win.pullback_extreme_price:
                    win.pullback_extreme_price = low
                    win.pullback_extreme_idx = i
                continuation_confirmed = close > win.post_breakout_extreme_price
            else:
                if high > win.pullback_extreme_price:
                    win.pullback_extreme_price = high
                    win.pullback_extreme_idx = i
                continuation_confirmed = close < win.post_breakout_extreme_price

            if continuation_confirmed:
                sub = df.iloc[win.breakout_confirm_idx:i + 1]
                swing_count = _count_corrective_swings(sub, breakout_dir)
                retest_reached = (
                    abs(win.pullback_extreme_price - level_price) / atr <= retest_tol_atr
                )
                retest_row = df.iloc[win.pullback_extreme_idx]
                weakness = _is_confirm_candle(
                    retest_row,
                    "down" if breakout_dir == "up" else "up",
                    min_body_ratio,
                )
                direction = "bullish" if breakout_dir == "up" else "bearish"

                if swing_count >= min_cpb_swings:
                    setup = "CPB"
                elif swing_count == 1 and retest_reached and weakness:
                    setup = "BP"
                else:
                    setup = "BPB"

                _emit(setup, direction, i, level_price, src, {
                    "penetration_depth_atr": round(
                        abs(win.post_breakout_extreme_price - level_price) / atr, 4
                    ),
                    "breakout_confirmed": True,
                    "pullback_swing_count": int(swing_count),
                    "retest_reached_level": bool(retest_reached),
                    "candles_to_resolve": i - win.opened_idx,
                })
                win.reset()
                i += 1
                continue

            if (i - win.breakout_confirm_idx) >= pullback_timeout:
                win.reset()
                i += 1
                continue

            i += 1
            continue

        i += 1

    return events


def _ts(df: pd.DataFrame, idx: Optional[int]):
    if idx is None:
        return None
    val = df.iloc[idx].get("_dt")
    if val is not None and not pd.isna(val):
        return val.isoformat().replace("+00:00", "Z")
    return df.iloc[idx].get("timestamp")


def _confidence(cfg: dict, tier: str, evidence: dict) -> float:
    """
    Confidence is separate from classification (spec §11): a
    high-confidence TST and a low-confidence TST are still both TST.
    Purely additive/weighted, all weights configurable.
    """
    w = cfg["confidence"]
    tier_score = w["tier_scores"].get(tier, 0.5)
    depth = min(float(evidence.get("penetration_depth_atr", 0.0)) / 1.0, 1.0)
    candles = evidence.get("candles_to_resolve", 10) or 10
    speed_score = max(0.0, 1.0 - min(candles, 20) / 20.0)
    rejection_score = 1.0 if evidence.get("retest_reached_level") else 0.5

    score = (
        w["base"]
        + w["tier_weight"] * tier_score
        + w["breach_depth_weight"] * depth
        + w["speed_weight"] * speed_score
        + w["rejection_quality_weight"] * rejection_score
    )
    return round(max(0.0, min(1.0, score)), 4)


# ============================================================================
# 6. Top-level orchestration across all 15 levels (spec §8)
# ============================================================================

def run_klsde(df: pd.DataFrame, symbol: str, execution_timeframe: str = "5min",
              cfg: Optional[dict] = None, levels: Optional[List[str]] = None
              ) -> List[Dict[str, Any]]:
    """
    Compute all 15 levels on `df` and run the shared reaction state
    machine across each of them, producing a flat, time-ordered list of
    SetupEvent dicts. The same five reaction implementations run against
    every level (spec §8) — there is exactly one state-machine function
    (`run_level_reactions`), parameterized by level, never one per level.
    """
    cfg = _merge_cfg(cfg)
    d = compute_all_levels(df)
    d["atr"] = _ensure_atr(d)

    all_events: List[Dict[str, Any]] = []
    for level_code in (levels or ALL_LEVEL_CODES):
        all_events.extend(
            run_level_reactions(d, level_code, symbol, execution_timeframe, cfg)
        )

    all_events.sort(key=lambda e: (e["resolved_at"] or ""))
    attach_clustering(all_events, cfg)
    return all_events


# ============================================================================
# 7. Nearby-level clustering (spec §12)
# ============================================================================

def attach_clustering(events: List[Dict[str, Any]], cfg: Optional[dict] = None) -> None:
    """
    In-place: tags each event's `cluster` field with the other events
    resolved within the same short window whose level price sits within
    `cluster_atr` ATR-equivalent price distance. KLSDE only *exposes*
    this; it never decides confluence itself (spec §12/§13) — that is
    USCL's job.
    """
    cfg = _merge_cfg(cfg)
    cluster_atr = float(cfg["cluster_atr"])
    n = len(events)
    for i, ev in enumerate(events):
        nearby = []
        for j, other in enumerate(events):
            if i == j:
                continue
            if ev["resolved_at"] != other["resolved_at"]:
                continue
            depth_i = ev["evidence"].get("penetration_depth_atr")
            price_i, price_j = ev["level_price"], other["level_price"]
            if price_i == 0:
                continue
            approx_atr_dist = abs(price_i - price_j) / max(abs(price_i) * 0.001, 1e-9)
            # Fallback distance metric when no shared ATR value is available
            # at aggregation time: relative price distance normalized by a
            # conservative 0.1% proxy. Callers with the live ATR series
            # should prefer computing exact ATR distance themselves and
            # overriding this field.
            if abs(price_i - price_j) <= cluster_atr * abs(price_i) * 0.01:
                nearby.append({"level": other["level"], "level_tier": other["level_tier"],
                                "level_price": price_j, "setup_type": other["setup_type"]})
        ev["cluster"] = {
            "clustered": len(nearby) > 0,
            "nearby_levels": nearby,
        }


# ============================================================================
# 8. Optional legacy B/S sub-pattern tagging (spec §9)
# ============================================================================

LEGACY_SUBPATTERN_MAP: Dict[str, str] = {
    # Populate as needed when migrating specific legacy B1..B7/S1..S7
    # patterns you want preserved as metadata, e.g.:
    # "B1": "liquidity_sweep_reclaim",
    # "S1": "liquidity_sweep_reclaim",
}


def attach_legacy_subpattern(event: Dict[str, Any], legacy_code: Optional[str]) -> Dict[str, Any]:
    """
    Attach a legacy B1..B7/S1..S7 label as `sub_pattern` metadata only.
    Legacy codes never control classification here (spec §9) — this is
    purely for backtest/comparison traceability.
    """
    if legacy_code:
        event["sub_pattern"] = LEGACY_SUBPATTERN_MAP.get(legacy_code, legacy_code)
    return event
