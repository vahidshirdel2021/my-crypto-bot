# -*- coding: utf-8 -*-
"""
signal_engine.swing_structure.swings
======================================
Swing detection with a strict no-lookahead confirmation boundary and a
second, explicit swing-quality layer.

Important distinction:
- ``confirmed`` means the fractal has completed its k-bar confirmation.
- ``significant`` means the confirmed swing also has enough structural
  prominence/reversal evidence to be treated as a meaningful swing rather
  than ordinary market noise.

Quality is calculated only from information available no later than
``confirmed_at_index``. No future candles after the confirmation boundary
are used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import numpy as np
import pandas as pd

from signal_engine.common.atr import compute_atr

SwingType = Literal["swing_high", "swing_low"]
SwingStatus = Literal["pending", "confirmed", "invalidated"]
SwingQuality = Literal["weak", "confirmed", "significant"]


@dataclass
class SwingPoint:
    id: str
    timeframe: str
    symbol: str
    type: SwingType
    price: float
    candle_index: int
    confirmed_at_index: Optional[int] = None
    confirmation_lag_bars: Optional[int] = None
    magnitude_atr: Optional[float] = None
    status: SwingStatus = "pending"
    invalidated_at_index: Optional[int] = None
    quality_score: Optional[float] = None
    quality_label: SwingQuality = "weak"
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timeframe": self.timeframe,
            "symbol": self.symbol,
            "type": self.type,
            "price": self.price,
            "candle_index": self.candle_index,
            "confirmed_at_index": self.confirmed_at_index,
            "confirmation_lag_bars": self.confirmation_lag_bars,
            "magnitude_atr": self.magnitude_atr,
            "status": self.status,
            "invalidated": self.status == "invalidated",
            "quality_score": self.quality_score,
            "quality_label": self.quality_label,
            "evidence": self.evidence,
        }


DEFAULT_SWING_CONFIG = {
    "5m": dict(fractal_k=3, atr_period=14, min_swing_atr_multiple=1.2,
               min_retrace_pct=0.20, volume_percentile_floor=30),
    "15m": dict(fractal_k=2, atr_period=14, min_swing_atr_multiple=1.0,
                min_retrace_pct=0.20, volume_percentile_floor=30),
}
_GENERIC_FALLBACK_CONFIG = dict(fractal_k=2, atr_period=14, min_swing_atr_multiple=1.0,
                                 min_retrace_pct=0.20, volume_percentile_floor=30)

# Quality layer. These are intentionally configurable rather than hard-coded
# into the KLSDE strategy, so the swing engine can be tuned independently.
QUALITY_DEFAULTS = {
    "quality_significant_threshold": 70.0,
    "quality_confirmed_threshold": 45.0,
    "quality_min_spacing_bars": 2,
    "quality_prominence_atr": 0.60,
    "quality_strong_prominence_atr": 1.50,
    "quality_reversal_atr": 0.50,
    "quality_strong_reversal_atr": 1.20,
    "quality_volume_bonus_threshold": 60.0,
}


def _cfg_for(timeframe: str, overrides: Optional[dict] = None) -> dict:
    base = dict(DEFAULT_SWING_CONFIG.get(timeframe, _GENERIC_FALLBACK_CONFIG))
    base.update(QUALITY_DEFAULTS)
    if overrides:
        base.update(overrides)
    return base


def _raw_fractal_candidates(df: pd.DataFrame, k: int) -> List[dict]:
    """Raw local extrema. The right-hand k bars are the confirmation horizon."""
    n = len(df)
    candidates: List[dict] = []
    if n < (2 * k + 1):
        return candidates

    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    for i in range(k, n - k):
        window_h = highs[i - k: i + k + 1]
        window_l = lows[i - k: i + k + 1]
        if highs[i] == window_h.max():
            candidates.append({"type": "swing_high", "index": i, "price": float(highs[i])})
        if lows[i] == window_l.min():
            candidates.append({"type": "swing_low", "index": i, "price": float(lows[i])})
    return candidates


def _volume_ok(df: pd.DataFrame, idx: int, floor_percentile: float, magnitude_atr: float,
               strong_move_atr_threshold: float = 2.0) -> bool:
    if "volume" not in df.columns:
        return True
    if magnitude_atr >= strong_move_atr_threshold:
        return True
    window = df["volume"].iloc[max(0, idx - 20): idx + 1]
    if len(window) < 5:
        return True
    threshold = np.percentile(window.to_numpy(dtype=float), floor_percentile)
    return bool(df["volume"].iloc[idx] >= threshold)


def _safe_float(x: float, default: float = 0.0) -> float:
    try:
        v = float(x)
        return default if not np.isfinite(v) else v
    except Exception:
        return default


def _swing_quality(
    df: pd.DataFrame,
    idx: int,
    confirm_index: int,
    cand_type: SwingType,
    price: float,
    atr_series: pd.Series,
    cfg: dict,
    prior_opposite_price: Optional[float],
) -> tuple[float, SwingQuality, dict]:
    """Score a swing using only candles <= confirm_index.

    Components:
      - local prominence versus the k-bar neighborhood
      - reversal excursion visible by confirmation time
      - volume confirmation
      - minimum spacing from the previous opposite swing
      - optional prior-leg magnitude

    No post-confirmation candle participates in this calculation.
    """
    k = int(cfg["fractal_k"])
    atr = _safe_float(atr_series.iloc[idx], 0.0)
    if atr <= 0:
        return 0.0, "weak", {"quality_reason": "invalid_atr"}

    left = max(0, idx - k)
    right = min(confirm_index, len(df) - 1)
    local_high = _safe_float(df["high"].iloc[left:right + 1].max())
    local_low = _safe_float(df["low"].iloc[left:right + 1].min())

    if cand_type == "swing_high":
        prominence_price = max(0.0, price - local_low)
        reversal_price = max(0.0, price - _safe_float(df["low"].iloc[idx:right + 1].min()))
    else:
        prominence_price = max(0.0, local_high - price)
        reversal_price = max(0.0, _safe_float(df["high"].iloc[idx:right + 1].max()) - price)

    prominence_atr = prominence_price / atr
    reversal_atr = reversal_price / atr

    p_score = min(35.0, 35.0 * prominence_atr / max(float(cfg["quality_strong_prominence_atr"]), 1e-9))
    r_score = min(35.0, 35.0 * reversal_atr / max(float(cfg["quality_strong_reversal_atr"]), 1e-9))

    volume_score = 0.0
    volume_pct = None
    if "volume" in df.columns:
        window = df["volume"].iloc[max(0, idx - 20): idx + 1].to_numpy(dtype=float)
        if len(window) >= 5:
            volume_pct = float((window <= _safe_float(df["volume"].iloc[idx])).mean() * 100.0)
            volume_score = 10.0 if volume_pct >= float(cfg["quality_volume_bonus_threshold"]) else 0.0
    else:
        # Missing volume should be neutral, not punitive.
        volume_score = 5.0

    spacing_score = 5.0
    if prior_opposite_price is not None:
        leg_atr = abs(price - prior_opposite_price) / atr
        spacing_score = 10.0 if leg_atr >= float(cfg["min_swing_atr_multiple"]) else 2.0
    else:
        leg_atr = None

    raw_score = p_score + r_score + volume_score + spacing_score
    score = round(min(100.0, raw_score), 1)
    if score >= float(cfg["quality_significant_threshold"]):
        label: SwingQuality = "significant"
    elif score >= float(cfg["quality_confirmed_threshold"]):
        label = "confirmed"
    else:
        label = "weak"

    evidence = {
        "quality_score": score,
        "quality_label": label,
        "prominence_atr": round(prominence_atr, 3),
        "reversal_excursion_atr": round(reversal_atr, 3),
        "volume_percentile": None if volume_pct is None else round(volume_pct, 1),
        "prior_leg_atr": None if leg_atr is None else round(leg_atr, 3),
        "quality_calculated_through_index": int(confirm_index),
        "quality_lookahead_safe": True,
    }
    return score, label, evidence


def _filter_and_confirm(df: pd.DataFrame, candidates: List[dict], cfg: dict,
                        timeframe: str, symbol: str) -> List[SwingPoint]:
    atr_period = cfg["atr_period"]
    k = cfg["fractal_k"]
    min_atr_mult = cfg["min_swing_atr_multiple"]
    min_retrace = cfg["min_retrace_pct"]
    vol_floor = cfg["volume_percentile_floor"]

    d = compute_atr(df, period=atr_period)
    atr_series = d["atr"]
    swings: List[SwingPoint] = []
    last_confirmed_opposite: Optional[dict] = None
    candidates_sorted = sorted(candidates, key=lambda c: c["index"])

    for cand in candidates_sorted:
        idx = cand["index"]
        confirm_index = idx + k
        # A candidate is not a confirmed swing until the full k-bar horizon exists.
        if confirm_index >= len(df):
            continue
        atr_val = atr_series.iloc[idx]
        if pd.isna(atr_val) or atr_val <= 0:
            continue

        if last_confirmed_opposite is not None:
            move = abs(cand["price"] - last_confirmed_opposite["price"])
            magnitude_atr = move / atr_val
        else:
            magnitude_atr = float("inf")

        if magnitude_atr < min_atr_mult:
            continue
        if not _volume_ok(df, idx, vol_floor,
                          magnitude_atr if np.isfinite(magnitude_atr) else 999.0):
            continue

        score, label, quality_evidence = _swing_quality(
            df, idx, confirm_index, cand["type"], cand["price"], atr_series, cfg,
            None if last_confirmed_opposite is None else last_confirmed_opposite["price"],
        )

        sw_id = f"swing_{timeframe}_{idx:06d}"
        evidence = {
            "fractal_k": k,
            "atr_at_swing": float(atr_val),
            **quality_evidence,
        }
        sw = SwingPoint(
            id=sw_id, timeframe=timeframe, symbol=symbol,
            type=cand["type"], price=cand["price"], candle_index=idx,
            confirmed_at_index=confirm_index,
            confirmation_lag_bars=confirm_index - idx,
            magnitude_atr=None if not np.isfinite(magnitude_atr) else round(float(magnitude_atr), 3),
            status="confirmed",
            quality_score=score,
            quality_label=label,
            evidence=evidence,
        )
        swings.append(sw)
        last_confirmed_opposite = cand

    return _apply_retrace_filter(df, swings, min_retrace)


def _apply_retrace_filter(df: pd.DataFrame, swings: List[SwingPoint], min_retrace_pct: float) -> List[SwingPoint]:
    """Suppress same-direction swing spam while preserving quality metadata."""
    if not swings:
        return swings
    swings_sorted = sorted(swings, key=lambda s: s.candle_index)
    kept: List[SwingPoint] = []
    for sw in swings_sorted:
        if kept and kept[-1].type == sw.type:
            prev = kept[-1]
            if sw.type == "swing_high":
                if sw.price >= prev.price:
                    kept[-1] = sw
            else:
                if sw.price <= prev.price:
                    kept[-1] = sw
            continue
        kept.append(sw)
    return kept


def detect_swings(df: pd.DataFrame, timeframe: str, symbol: str = "",
                  config_overrides: Optional[dict] = None) -> List[SwingPoint]:
    """Detect confirmed swings and attach a lookahead-safe quality score.

    ``status=confirmed`` only means the fractal confirmation completed.
    Consumers that need structurally important swings should select
    ``quality_label == 'significant'`` (or a configured score threshold).
    """
    if df is None or df.empty:
        return []
    cfg = _cfg_for(timeframe, config_overrides)
    df_reset = df.reset_index(drop=True)
    candidates = _raw_fractal_candidates(df_reset, cfg["fractal_k"])
    return _filter_and_confirm(df_reset, candidates, cfg, timeframe, symbol)


def select_significant_swings(swings: List[SwingPoint], min_score: float = 70.0) -> List[SwingPoint]:
    """Return only confirmed, meaningful swings; never returns pending/invalidated points."""
    return [
        s for s in swings
        if s.status == "confirmed"
        and s.quality_score is not None
        and float(s.quality_score) >= float(min_score)
    ]


def swings_as_arrays(swings: List[SwingPoint]):
    """Convert SwingPoint objects to parallel price/type arrays."""
    ordered = sorted(swings, key=lambda s: s.candle_index)
    prices = [s.price for s in ordered]
    types = ["high" if s.type == "swing_high" else "low" for s in ordered]
    return prices, types
