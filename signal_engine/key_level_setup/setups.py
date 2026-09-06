# -*- coding: utf-8 -*-
"""
KLSDE setup classifier — V18

The classifier keeps the five primary YTC-style setup families distinct:

  S/R interaction setups:
    TST  = test of support/resistance expected to hold
    BOF  = breakout failure back through the S/R area
    BPB  = breakout, acceptance beyond S/R, weak pullback, continuation

  Trend setups:
    PB   = simple single-leg pullback within a trend
    CPB  = complex multi-swing OR extended-duration pullback within a trend

B5/S5 remain first-class project-specific setups and are evaluated before
BPB when a clean breakout -> retest -> directional confirmation is present.

The source material supports the behavioral definitions above; it does not
specify universal numeric ATR/body thresholds. Therefore all numeric
thresholds below are explicit, configurable engineering approximations and
are recorded in evidence rather than being presented as part of the source
method itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Sequence

import numpy as np
import pandas as pd

from signal_engine.common.candle_geometry import compute_candle_geometry
from signal_engine.key_level_setup.interactions import InteractionWindow
from signal_engine.swing_structure.swings import detect_swings, SwingPoint
from signal_engine.swing_structure.structure import detect_structure_events
from signal_engine.common.trend_context import trend_from_swings

SetupType = Literal["BOF", "TST", "B5", "BPB", "BP", "CPB", "S5"]
Direction = Literal["bullish", "bearish"]

DEFAULT_SETUP_CONFIG = {
    # These are engineering thresholds, not claims from the source material.
    "min_breach_atr_multiple": 0.15,
    "full_breakout_atr_multiple": 0.50,
    "full_breakout_confirm_bars": 2,
    "bof_max_bars_to_fail": 4,
    "tst_max_bars_to_reject": 4,
    "pullback_min_retrace_atr": 0.30,
    "resumption_min_atr": 0.20,
    "weakness_body_ratio_factor": 0.65,
    "weakness_max_range_ratio": 0.85,
    "weakness_max_volume_ratio": 1.15,
    "bpb_max_pullback_atr": 0.90,
    "trend_min_swings": 2,
    "cpb_min_pullback_swings": 3,
    "b5_retest_min_close_pen_atr": 0.0,
    "b5_retest_max_close_pen_atr": 0.20,
    "cpb_min_duration_bars": 8,
    "pb_max_duration_bars": 10,
    "trend_break_buffer_atr": 0.10,
    "sr_zone_atr": 0.20,
    # B5/S5 structural quality: BOS/HL-LH are evidence by default, not hard gates.
    "b5_require_bos": False,
    "b5_require_hl_lh": False,
    "b5_structure_bonus": 0.06,
}


@dataclass
class SetupEvent:
    id: str
    setup_type: SetupType
    level_name: str
    level_price: float
    symbol: str
    timeframe: str
    direction: Direction
    window_opened_at_index: int
    resolved_at_index: int
    confidence: float
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": f"{self.id}", "setup_type": self.setup_type, "level_name": self.level_name,
            "level_price": self.level_price, "symbol": self.symbol, "timeframe": self.timeframe,
            "direction": self.direction, "window_opened_at_index": self.window_opened_at_index,
            "resolved_at_index": self.resolved_at_index, "confidence": self.confidence,
            "evidence": self.evidence,
        }


_TIER_CONFIDENCE_WEIGHT = {"1h": 0.25, "4h": 0.35, "daily": 0.5, "weekly": 0.75, "monthly": 1.0}


def _direction_from_approach(approach_direction: str, is_continuation: bool) -> Direction:
    resistance_touch = approach_direction == "from_below"
    if is_continuation:
        return "bullish" if resistance_touch else "bearish"
    return "bearish" if resistance_touch else "bullish"


def _sorted_indices(window: InteractionWindow) -> List[int]:
    return sorted(set(int(i) for i in window.candle_indices))


def _atr_at(df: pd.DataFrame, idx: int) -> float:
    if "atr" in df.columns and pd.notna(df["atr"].iloc[idx]):
        return max(float(df["atr"].iloc[idx]), 1e-12)
    # Local range fallback; used only for classifier geometry.
    r = abs(float(df["high"].iloc[idx]) - float(df["low"].iloc[idx]))
    return max(r, 1e-12)


def _signed_penetration(window: InteractionWindow, idx: int) -> float:
    return float(window.penetration_depth_atr_by_index.get(idx, 0.0))


def _find_first_sustained_breakout(window: InteractionWindow, full_breakout_atr_multiple: float, confirm_bars: int) -> Optional[int]:
    indices = _sorted_indices(window)
    run = 0
    for pos, idx in enumerate(indices):
        pen = _signed_penetration(window, idx)
        if pen >= full_breakout_atr_multiple:
            run += 1
            if run >= confirm_bars:
                return indices[pos - confirm_bars + 1]
        else:
            run = 0
    return None


def _find_bof_failure_index(window: InteractionWindow, max_bars_to_fail: int, zone_atr: float) -> Optional[int]:
    """BOF requires breach, then a return across the S/R area.

    The interaction engine stores close-based penetration. We additionally
    require a close back through the level-zone, not merely a wick back inside.
    """
    indices = _sorted_indices(window)
    if not indices:
        return None
    breach_positions = [p for p, i in enumerate(indices) if _signed_penetration(window, i) >= 0]
    if not breach_positions:
        return None
    peak_pos = max(breach_positions, key=lambda p: _signed_penetration(window, indices[p]))
    peak_pen = _signed_penetration(window, indices[peak_pos])
    if peak_pen <= 0:
        return None
    for offset in range(1, max_bars_to_fail + 1):
        pos = peak_pos + offset
        if pos >= len(indices):
            break
        pen = _signed_penetration(window, indices[pos])
        if pen <= -zone_atr:
            return indices[pos]
    return None


def _find_reversal_index_for_tst(window: InteractionWindow, max_bars_to_reject: int, zone_atr: float) -> Optional[int]:
    indices = _sorted_indices(window)
    for offset in range(1, min(max_bars_to_reject, len(indices) - 1) + 1):
        idx = indices[offset]
        if _signed_penetration(window, idx) <= -zone_atr:
            return idx
    return None


def _confirmed_swings(df: pd.DataFrame, timeframe: str, through_index: int) -> List[SwingPoint]:
    if through_index < 0 or len(df) < 5:
        return []
    swings = detect_swings(df.reset_index(drop=True), timeframe=timeframe)
    return [
        s for s in swings
        if s.status == "confirmed"
        and s.confirmed_at_index is not None
        and int(s.confirmed_at_index) <= int(through_index)
        and int(s.candle_index) <= int(through_index)
    ]


def _trend_at(df: pd.DataFrame, timeframe: str, through_index: int):
    swings = _confirmed_swings(df, timeframe, through_index)
    highs = sorted([s for s in swings if s.type == "swing_high"], key=lambda s: s.candle_index)
    lows = sorted([s for s in swings if s.type == "swing_low"], key=lambda s: s.candle_index)
    prices = [s.price for s in sorted(swings, key=lambda s: s.candle_index)]
    types = ["high" if s.type == "swing_high" else "low" for s in sorted(swings, key=lambda s: s.candle_index)]
    ctx = trend_from_swings(prices, types) if len(prices) >= 4 else None
    return ctx, highs, lows, swings


def _candle_strength(df: pd.DataFrame, start: int, end: int, direction: Direction) -> dict:
    """Estimate relative strength/weakness using price geometry and volume.

    This is deliberately descriptive: the source defines weakness behaviorally,
    not by a single universal numeric formula.
    """
    if end < start:
        return {"weak": False, "body_ratio": None, "range_ratio": None, "volume_ratio": None}
    seg = df.iloc[start:end + 1]
    ranges = (seg["high"].astype(float) - seg["low"].astype(float)).clip(lower=0)
    bodies = (seg["close"].astype(float) - seg["open"].astype(float)).abs()
    body_ratio = float(bodies.mean() / max(ranges.mean(), 1e-12))
    range_ratio = float(ranges.mean() / max(float(ranges.iloc[0]), 1e-12))
    volume_ratio = None
    if "volume" in df.columns and len(seg) > 0:
        before = df["volume"].iloc[max(0, start - 20):start].astype(float)
        if len(before) >= 5:
            volume_ratio = float(seg["volume"].astype(float).mean() / max(float(before.mean()), 1e-12))
    return {"weak": False, "body_ratio": round(body_ratio, 4), "range_ratio": round(range_ratio, 4),
            "volume_ratio": None if volume_ratio is None else round(volume_ratio, 4)}


def _pullback_geometry(df: pd.DataFrame, breakout_index: int, trough_index: int, resumption_index: int,
                       direction: Direction, cfg: dict) -> dict:
    """Return objective evidence for whether the pullback looks weak."""
    if trough_index <= breakout_index:
        return {"weak": False}
    b = df.iloc[breakout_index]
    pull = df.iloc[breakout_index:trough_index + 1]
    b_range = max(float(b["high"] - b["low"]), 1e-12)
    p_range = float((pull["high"] - pull["low"]).abs().mean())
    b_body = abs(float(b["close"] - b["open"])) / b_range
    p_body = float((pull["close"] - pull["open"]).abs().mean()) / max(p_range, 1e-12)
    range_ratio = p_range / b_range
    # Pullback should not display stronger average range/body than the breakout.
    weak_body = p_body <= max(float(cfg["weakness_body_ratio_factor"]), b_body * 1.25)
    weak_range = range_ratio <= float(cfg["weakness_max_range_ratio"])
    volume_ratio = None
    weak_volume = True
    if "volume" in df.columns:
        pre = df["volume"].iloc[max(0, breakout_index - 20):breakout_index].astype(float)
        if len(pre) >= 5:
            volume_ratio = float(pull["volume"].astype(float).mean() / max(float(pre.mean()), 1e-12))
            weak_volume = volume_ratio <= float(cfg["weakness_max_volume_ratio"])
    # A small directional rejection on the resumption candle strengthens the case.
    c = df.iloc[resumption_index]
    directional = float(c["close"]) > float(c["open"]) if direction == "bullish" else float(c["close"]) < float(c["open"])
    weak = bool(weak_body and weak_range and weak_volume and directional)
    return {
        "weak": weak,
        "breakout_body_ratio": round(b_body, 4),
        "pullback_body_ratio": round(p_body, 4),
        "pullback_to_breakout_range_ratio": round(range_ratio, 4),
        "pullback_volume_ratio": None if volume_ratio is None else round(volume_ratio, 4),
        "directional_resumption": directional,
    }


def _trend_pullback_classification(
    df: pd.DataFrame, timeframe: str, start_index: int, trough_index: int, resumption_index: int,
    direction: Direction, cfg: dict,
) -> tuple[Optional[str], dict]:
    """Classify PB vs CPB only inside a confirmed trend.

    PB = one counter-trend leg and no violation of the prior trend swing.
    CPB = multiple counter-trend swing legs OR an extended pullback duration.
    """
    ctx, highs, lows, swings = _trend_at(df, timeframe, start_index)
    expected = "uptrend" if direction == "bullish" else "downtrend"
    evidence = {"trend": None, "trend_strength": 0.0, "pullback_swings": 0, "pullback_duration_bars": max(0, resumption_index - start_index)}
    if ctx is None or ctx.trend != expected:
        return None, evidence
    evidence["trend"] = ctx.trend
    evidence["trend_strength"] = round(float(ctx.strength), 4)

    # Count confirmed swings formed during the retracement, but only those
    # representing counter-trend pivots. A PB has at most one such pivot.
    pullback_swings = [
        s for s in swings
        if start_index <= s.candle_index <= trough_index
        and s.confirmed_at_index is not None and s.confirmed_at_index <= resumption_index
    ]
    if direction == "bullish":
        counter = [s for s in pullback_swings if s.type == "swing_low"]
        prior_lows = [s for s in lows if s.candle_index < start_index]
        violation = bool(prior_lows and counter and min(s.price for s in counter) < prior_lows[-1].price - cfg["trend_break_buffer_atr"] * _atr_at(df, trough_index))
        continuation = float(df["close"].iloc[resumption_index]) > float(df["high"].iloc[start_index])
    else:
        counter = [s for s in pullback_swings if s.type == "swing_high"]
        prior_highs = [s for s in highs if s.candle_index < start_index]
        violation = bool(prior_highs and counter and max(s.price for s in counter) > prior_highs[-1].price + cfg["trend_break_buffer_atr"] * _atr_at(df, trough_index))
        continuation = float(df["close"].iloc[resumption_index]) < float(df["low"].iloc[start_index])

    count = len(counter)
    duration = resumption_index - start_index
    evidence["pullback_swings"] = count
    evidence["trend_swing_violation"] = violation
    evidence["continuation_after_pullback"] = continuation
    if not continuation or violation:
        return None, evidence

    if count >= int(cfg["cpb_min_pullback_swings"]) or duration >= int(cfg["cpb_min_duration_bars"]):
        return "CPB", evidence
    if count <= 1 and duration <= int(cfg["pb_max_duration_bars"]):
        return "PB", evidence
    return "CPB", evidence


def _b5_structure_evidence(df: pd.DataFrame, timeframe: str, symbol: str, direction: Direction,
                           breakout_index: int, retest_index: int, resumption_index: int) -> dict:
    out = {
        "bos_confirmed": False, "bos_index": None, "bos_broken_swing_price": None,
        "structure_hl_lh_confirmed": False, "structure_swing_price": None,
        "structure_prev_swing_price": None,
    }
    try:
        if breakout_index < 0 or retest_index <= breakout_index or resumption_index <= retest_index:
            return out
        swings = detect_swings(df.reset_index(drop=True), timeframe=timeframe)
        events = detect_structure_events(df.reset_index(drop=True), swings, timeframe=timeframe, symbol=symbol)
        want = "bullish" if direction == "bullish" else "bearish"
        bos = [e for e in events if e.event_type == "BOS" and e.direction == want
               and breakout_index <= e.trigger_index <= resumption_index]
        if bos:
            e = min(bos, key=lambda x: x.trigger_index)
            out["bos_confirmed"] = True
            out["bos_index"] = int(e.trigger_index)
            out["bos_broken_swing_price"] = float(e.evidence.get("broken_price")) if e.evidence.get("broken_price") is not None else None
        confirmed = [s for s in swings if s.status == "confirmed" and s.confirmed_at_index is not None and s.confirmed_at_index <= resumption_index]
        if direction == "bullish":
            prior = sorted([s for s in confirmed if s.type == "swing_low" and s.candle_index < breakout_index], key=lambda x: x.candle_index)
            retest_lows = sorted([s for s in confirmed if s.type == "swing_low" and breakout_index <= s.candle_index <= retest_index], key=lambda x: x.candle_index)
            if prior and retest_lows and retest_lows[-1].price > prior[-1].price:
                out["structure_hl_lh_confirmed"] = True
                out["structure_swing_price"] = float(retest_lows[-1].price)
                out["structure_prev_swing_price"] = float(prior[-1].price)
        else:
            prior = sorted([s for s in confirmed if s.type == "swing_high" and s.candle_index < breakout_index], key=lambda x: x.candle_index)
            retest_highs = sorted([s for s in confirmed if s.type == "swing_high" and breakout_index <= s.candle_index <= retest_index], key=lambda x: x.candle_index)
            if prior and retest_highs and retest_highs[-1].price < prior[-1].price:
                out["structure_hl_lh_confirmed"] = True
                out["structure_swing_price"] = float(retest_highs[-1].price)
                out["structure_prev_swing_price"] = float(prior[-1].price)
    except Exception:
        return out
    return out


def _event(window, timeframe, direction, setup_type, resolved_idx, confidence, evidence):
    return SetupEvent(
        id=f"setup_{timeframe}_{window.id}", setup_type=setup_type, level_name=window.level_name,
        level_price=window.level_price, symbol=window.symbol, timeframe=timeframe, direction=direction,
        window_opened_at_index=window.open_index, resolved_at_index=int(resolved_idx),
        confidence=round(float(min(1.0, confidence)), 3), evidence=evidence,
    )


def classify_setup(window: InteractionWindow, df: pd.DataFrame, timeframe: str, config: Optional[dict] = None) -> Optional[SetupEvent]:
    cfg = {**DEFAULT_SETUP_CONFIG, **(config or {})}
    d = df.reset_index(drop=True).copy()
    tier_weight = _TIER_CONFIDENCE_WEIGHT.get(window.level_tier, 0.5)
    if getattr(window, "is_confluent", False) and window.confluence_strength > 0:
        tier_weight = min(1.0, tier_weight + 0.15 * window.confluence_strength)
    indices = _sorted_indices(window)
    if len(indices) < 2:
        return None

    zone_atr = float(cfg["sr_zone_atr"])

    # ------------------------------------------------------------------
    # 1) TST — test of S/R expected to hold.
    # ------------------------------------------------------------------
    if window.max_penetration_atr < cfg["min_breach_atr_multiple"]:
        reversal_idx = _find_reversal_index_for_tst(window, cfg["tst_max_bars_to_reject"], zone_atr)
        if reversal_idx is None:
            return None
        direction = _direction_from_approach(window.approach_direction, False)
        evidence = {
            "definition": "TST: test of support/resistance expected to hold",
            "max_penetration_atr": round(window.max_penetration_atr, 4),
            "reversal_index": reversal_idx,
            "sr_area_hold": True,
            "level_tier": window.level_tier,
            "is_confluent": window.is_confluent,
            "confluent_with": window.confluent_with,
            "confluence_strength": window.confluence_strength,
            "engineering_thresholds": {"min_breach_atr_multiple": cfg["min_breach_atr_multiple"], "sr_zone_atr": zone_atr},
        }
        conf = 0.52 + 0.18 * tier_weight + 0.10 * min(1.0, abs(window.max_penetration_atr) / max(cfg["min_breach_atr_multiple"], 1e-9))
        return _event(window, timeframe, direction, "TST", reversal_idx, conf, evidence)

    # ------------------------------------------------------------------
    # 2) BOF — breach, failure, return through the S/R area.
    # ------------------------------------------------------------------
    # BOF has precedence over continuation setups. A failed breakout may
    # briefly exceed even a strong-breakout threshold before reversing; what
    # matters is the completed failure back through the S/R area.
    fail_idx = _find_bof_failure_index(window, cfg["bof_max_bars_to_fail"], zone_atr)
    if fail_idx is not None:
        direction = _direction_from_approach(window.approach_direction, False)
        peak_idx = max(indices, key=lambda i: _signed_penetration(window, i))
        post = d.iloc[peak_idx:fail_idx + 1]
        move = float(post["close"].iloc[-1] - post["close"].iloc[0])
        expected = -1 if direction == "bearish" else 1
        directional_failure = move * expected > 0
        if directional_failure:
            evidence = {
                "definition": "BOF: breakout/breach of S/R followed by failure and reversal back through the area",
                "max_penetration_atr": round(window.max_penetration_atr, 4),
                "breakout_failure_index": fail_idx,
                "breach_peak_index": peak_idx,
                "returned_through_sr_area": True,
                "directional_failure": True,
                "level_tier": window.level_tier,
                "engineering_thresholds": {"min_breach_atr_multiple": cfg["min_breach_atr_multiple"], "bof_max_bars_to_fail": cfg["bof_max_bars_to_fail"], "sr_zone_atr": zone_atr},
            }
            conf = 0.58 + 0.16 * tier_weight + 0.10 * min(1.0, window.max_penetration_atr / max(cfg["min_breach_atr_multiple"], 1e-9))
            return _event(window, timeframe, direction, "BOF", fail_idx, conf, evidence)

    # ------------------------------------------------------------------
    # 3) Confirmed breakout. First look for a project-specific B5/S5.
    # ------------------------------------------------------------------
    # The source definition is behavioral (price breaches/accepts the area),
    # not a universal requirement for N consecutive closes. We therefore use
    # the first meaningful close beyond the engineering breakout threshold.
    breakout_confirm_index = next(
        (i for i in indices if _signed_penetration(window, i) >= cfg["full_breakout_atr_multiple"]),
        None,
    )
    if breakout_confirm_index is None:
        return None
    direction = _direction_from_approach(window.approach_direction, True)
    after = [i for i in indices if i > breakout_confirm_index]
    if not after:
        return None
    pen_at_confirm = _signed_penetration(window, breakout_confirm_index)
    trough_index = min(after, key=lambda i: _signed_penetration(window, i))
    trough_pen = _signed_penetration(window, trough_index)
    pullback_occurred = (pen_at_confirm - trough_pen) >= cfg["pullback_min_retrace_atr"]
    if not pullback_occurred:
        return None
    after_trough = [i for i in after if i > trough_index]
    resumption_candidates = [
        i for i in after_trough
        if _signed_penetration(window, i) >= trough_pen + cfg["resumption_min_atr"]
    ]
    if not resumption_candidates:
        return None
    resumption_index = resumption_candidates[0]

    # B5/S5 image definition: retest the broken level/area without a close
    # back through it.  A wick may probe the zone, but the retest close must
    # remain on the breakout side of the level.
    b5_retest_in_zone = (
        float(cfg.get("b5_retest_min_close_pen_atr", 0.0))
        <= trough_pen
        <= float(cfg.get("b5_retest_max_close_pen_atr", 0.20))
    )
    pullback_reached_level = b5_retest_in_zone
    try:
        breakout_candle = d.iloc[breakout_confirm_index]
        trough_candle = d.iloc[trough_index]
        confirm_candle = d.iloc[resumption_index]
        bg = compute_candle_geometry(breakout_candle["open"], breakout_candle["high"], breakout_candle["low"], breakout_candle["close"])
        tg = compute_candle_geometry(trough_candle["open"], trough_candle["high"], trough_candle["low"], trough_candle["close"])
        cg = compute_candle_geometry(confirm_candle["open"], confirm_candle["high"], confirm_candle["low"], confirm_candle["close"])
        weakness_signal = bool(
            pd.notna(tg.body_to_range_ratio)
            and pd.notna(bg.body_to_range_ratio)
            and float(tg.body_to_range_ratio) <= cfg["weakness_body_ratio_factor"] * max(float(bg.body_to_range_ratio), 0.05)
        )
        b5_confirmation_body_ratio = float(cg.body_to_range_ratio) if pd.notna(cg.body_to_range_ratio) else None
        body_direction_ok = bool(float(confirm_candle["close"]) > float(confirm_candle["open"]) if direction == "bullish" else float(confirm_candle["close"]) < float(confirm_candle["open"]))
        b5_confirmation = bool(body_direction_ok and (b5_confirmation_body_ratio or 0.0) >= 0.45)
    except Exception:
        weakness_signal = False
        b5_confirmation = False
        b5_confirmation_body_ratio = None

    pullback_evidence = _pullback_geometry(d, breakout_confirm_index, trough_index, resumption_index, direction, cfg)
    swing_count_raw = len(_confirmed_swings(d, timeframe, trough_index))
    # Count only counter-trend pivots inside the pullback for auditability.
    trend_setup, trend_evidence = _trend_pullback_classification(
        d, timeframe, breakout_confirm_index, trough_index, resumption_index, direction, cfg
    )

    b5_variant = bool(pullback_reached_level and b5_confirmation)
    structure = _b5_structure_evidence(
        d, timeframe, window.symbol, direction, breakout_confirm_index, trough_index, resumption_index
    ) if b5_variant else {"bos_confirmed": False, "bos_index": None, "bos_broken_swing_price": None,
                          "structure_hl_lh_confirmed": False, "structure_swing_price": None, "structure_prev_swing_price": None}
    structure_ready = bool(structure["bos_confirmed"] and structure["structure_hl_lh_confirmed"])
    structure_gate_ok = (not cfg.get("b5_require_bos", False) or structure["bos_confirmed"]) and (not cfg.get("b5_require_hl_lh", False) or structure["structure_hl_lh_confirmed"])
    if b5_variant and not structure_gate_ok:
        b5_variant = False

    # BPB requires acceptance beyond the breakout area AND a weak pullback.
    # A retest into the old level with strong counter-pressure is not BPB.
    breakout_side_hold = trough_pen > -zone_atr
    bpb_valid = bool(pullback_evidence.get("weak") and breakout_side_hold and not pullback_reached_level)

    evidence = {
        "definition": {
            "B5_S5": "project-specific breakout -> retest -> directional confirmation",
            "BPB": "breakout -> acceptance beyond S/R -> weak pullback -> continuation",
            "PB": "single-leg pullback within an established trend",
            "CPB": "multi-swing OR extended-duration pullback within an established trend",
        },
        "penetration_depth_atr": round(pen_at_confirm, 4),
        "full_breakout_confirmed": True,
        "breakout_confirm_index": breakout_confirm_index,
        "retest_swing_index": trough_index,
        "resumption_index": resumption_index,
        "pullback_reached_level": pullback_reached_level,
        "weakness_signal": weakness_signal,
        "pullback_geometry": pullback_evidence,
        "breakout_side_hold": breakout_side_hold,
        "bpb_valid": bpb_valid,
        "trend_classification": trend_setup,
        "trend_evidence": trend_evidence,
        "confirmed_swings_visible_through_trough": swing_count_raw,
        "b5_variant": b5_variant,
        "b5_confirmation": b5_confirmation,
        "b5_confirmation_body_ratio": round(b5_confirmation_body_ratio, 4) if b5_confirmation_body_ratio is not None else None,
        "bos_confirmed": structure["bos_confirmed"],
        "bos_index": structure["bos_index"],
        "bos_broken_swing_price": structure["bos_broken_swing_price"],
        "structure_hl_lh_confirmed": structure["structure_hl_lh_confirmed"],
        "structure_swing_price": structure["structure_swing_price"],
        "structure_prev_swing_price": structure["structure_prev_swing_price"],
        "b5_structure_ready": structure_ready,
        "level_significance_tier": window.level_tier,
        "is_confluent": window.is_confluent,
        "confluent_with": window.confluent_with,
        "confluence_strength": window.confluence_strength,
        "engineering_thresholds": {
            "full_breakout_atr_multiple": cfg["full_breakout_atr_multiple"],
            "full_breakout_confirm_bars": cfg["full_breakout_confirm_bars"],
            "pullback_min_retrace_atr": cfg["pullback_min_retrace_atr"],
            "resumption_min_atr": cfg["resumption_min_atr"],
            "cpb_min_pullback_swings": cfg["cpb_min_pullback_swings"],
            "cpb_min_duration_bars": cfg["cpb_min_duration_bars"],
            "b5_retest_min_close_pen_atr": cfg.get("b5_retest_min_close_pen_atr", 0.0),
            "b5_retest_max_close_pen_atr": cfg.get("b5_retest_max_close_pen_atr", 0.20),
        },
    }

    if b5_variant:
        setup_type: SetupType = "B5" if direction == "bullish" else "S5"
    elif bpb_valid:
        setup_type = "BPB"
    elif trend_setup in ("PB", "CPB"):
        setup_type = trend_setup  # type: ignore[assignment]
    else:
        # A confirmed breakout without the required weak-pullback/within-trend
        # structure is deliberately rejected instead of being mislabeled.
        return None

    base_conf = {"B5": 0.72, "S5": 0.72, "BPB": 0.64, "PB": 0.62, "CPB": 0.66}[setup_type]
    confidence = base_conf + 0.16 * tier_weight
    if pullback_evidence.get("weak"):
        confidence += 0.08
    if structure_ready and b5_variant:
        confidence += float(cfg.get("b5_structure_bonus", 0.06))
    return _event(window, timeframe, direction, setup_type, resumption_index, confidence, evidence)



def classify_trend_setups(
    df: pd.DataFrame, timeframe: str, symbol: str = "", config: Optional[dict] = None,
) -> List[SetupEvent]:
    """Detect PB/CPB as genuine trend setups.

    PB/CPB are not breakout-at-level variants. A setup is emitted only after
    a confirmed trend swing, a counter-trend pullback, and a continuation
    through the prior trend swing. PB is single-leg/short-duration; CPB is
    multi-swing or extended-duration. All decisions are bounded by swing
    confirmation and the resolution candle.
    """
    cfg = {**DEFAULT_SETUP_CONFIG, **(config or {})}
    d = df.reset_index(drop=True)
    if len(d) < 20:
        return []
    swings = detect_swings(d, timeframe=timeframe, symbol=symbol)
    confirmed = sorted(
        [s for s in swings if s.status == "confirmed" and s.confirmed_at_index is not None],
        key=lambda s: s.candle_index,
    )
    events: List[SetupEvent] = []

    for anchor in confirmed:
        anchor_confirm = int(anchor.confirmed_at_index)
        prior_visible = [s for s in confirmed if int(s.confirmed_at_index) <= anchor_confirm]
        if len(prior_visible) < 4:
            continue
        prices = [s.price for s in prior_visible]
        types = ["high" if s.type == "swing_high" else "low" for s in prior_visible]
        ctx = trend_from_swings(prices, types)
        if anchor.type == "swing_high" and ctx.trend != "uptrend":
            continue
        if anchor.type == "swing_low" and ctx.trend != "downtrend":
            continue

        direction: Direction = "bullish" if anchor.type == "swing_high" else "bearish"
        pull_type = "swing_low" if direction == "bullish" else "swing_high"
        prior_opposite = [
            s for s in prior_visible
            if s.type == pull_type and s.candle_index < anchor.candle_index
        ]
        if not prior_opposite:
            continue
        trend_boundary = float(prior_opposite[-1].price)

        future = [s for s in confirmed if s.candle_index > anchor.candle_index and s.type == pull_type]
        pb_swing = None
        resumption_index = None
        for candidate in future:
            ci = int(candidate.confirmed_at_index)
            if ci <= anchor_confirm:
                continue
            atr = _atr_at(d, candidate.candle_index)
            if direction == "bullish" and candidate.price < trend_boundary - cfg["trend_break_buffer_atr"] * atr:
                continue
            if direction == "bearish" and candidate.price > trend_boundary + cfg["trend_break_buffer_atr"] * atr:
                continue
            if direction == "bullish":
                resumes = [i for i in range(ci, len(d)) if float(d["close"].iloc[i]) > float(anchor.price)]
            else:
                resumes = [i for i in range(ci, len(d)) if float(d["close"].iloc[i]) < float(anchor.price)]
            if not resumes:
                continue
            r = resumes[0]
            boundary_atr = cfg["trend_break_buffer_atr"] * atr
            segment = d.iloc[anchor.candle_index:r + 1]
            if direction == "bullish" and float(segment["low"].min()) < trend_boundary - boundary_atr:
                continue
            if direction == "bearish" and float(segment["high"].max()) > trend_boundary + boundary_atr:
                continue
            pb_swing, resumption_index = candidate, r
            break

        if pb_swing is None or resumption_index is None:
            continue

        # Count the swing legs that actually formed during the entire
        # retracement, not just up to the first counter-trend pivot. This is
        # what distinguishes a true multi-swing CPB from a simple PB.
        pullback_swings = [
            s for s in confirmed
            if anchor.candle_index < s.candle_index < resumption_index
            and int(s.confirmed_at_index) <= resumption_index
        ]
        retrace_swing_count = len(pullback_swings)
        counter_count = len([s for s in pullback_swings if s.type == pull_type])
        duration = int(resumption_index - anchor_confirm)
        is_cpb = retrace_swing_count >= int(cfg["cpb_min_pullback_swings"]) or duration >= int(cfg["cpb_min_duration_bars"])
        setup_type: SetupType = "CPB" if is_cpb else "PB"

        evidence = {
            "definition": "CPB: complex multi-swing or extended-duration pullback within trend" if is_cpb else "PB: simple single-leg pullback within trend",
            "trend": "uptrend" if direction == "bullish" else "downtrend",
            "trend_strength": round(float(ctx.strength), 4),
            "trend_anchor_swing_index": int(anchor.candle_index),
            "trend_anchor_confirmed_at_index": anchor_confirm,
            "pullback_swing_index": int(pb_swing.candle_index),
            "pullback_swing_confirmed_at_index": int(pb_swing.confirmed_at_index),
            "pullback_swing_count": int(retrace_swing_count),
            "counter_trend_pullback_pivots": int(counter_count),
            "pullback_duration_bars": duration,
            "trend_boundary_price": trend_boundary,
            "trend_pullback_stop_price": float(pb_swing.price),
            "continuation_index": int(resumption_index),
            "lookahead_safe": True,
            "engineering_thresholds": {
                "cpb_min_pullback_swings": cfg["cpb_min_pullback_swings"],
                "cpb_min_duration_bars": cfg["cpb_min_duration_bars"],
            "b5_retest_min_close_pen_atr": cfg.get("b5_retest_min_close_pen_atr", 0.0),
            "b5_retest_max_close_pen_atr": cfg.get("b5_retest_max_close_pen_atr", 0.20),
            },
        }
        conf = (0.66 if is_cpb else 0.60) + 0.14 * float(ctx.strength)
        events.append(SetupEvent(
            id=f"trend_setup_{timeframe}_{anchor.candle_index}_{resumption_index}",
            setup_type=setup_type,
            level_name="TREND_SWING_H" if direction == "bullish" else "TREND_SWING_L",
            level_price=float(anchor.price), symbol=symbol, timeframe=timeframe,
            direction=direction, window_opened_at_index=anchor_confirm,
            resolved_at_index=int(resumption_index), confidence=round(min(1.0, conf), 3), evidence=evidence,
        ))

    dedup = {}
    for e in events:
        key = (e.setup_type, e.direction, e.resolved_at_index)
        if key not in dedup or e.confidence > dedup[key].confidence:
            dedup[key] = e
    return sorted(dedup.values(), key=lambda e: e.resolved_at_index)


def classify_all(windows: List[InteractionWindow], df: pd.DataFrame, timeframe: str, config: Optional[dict] = None, symbol: str = "") -> List[SetupEvent]:
    events: List[SetupEvent] = []
    for w in windows:
        ev = classify_setup(w, df, timeframe, config)
        if ev is not None:
            events.append(ev)
    events.extend(classify_trend_setups(df, timeframe, symbol=(symbol or (windows[0].symbol if windows else "")), config=config))
    return sorted(events, key=lambda e: (e.resolved_at_index, e.id))
