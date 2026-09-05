# -*- coding: utf-8 -*-
"""Closed-candle helpers shared by live and backtest paths.

A timestamp in the bot is the candle OPEN time. A HTF candle is confirmed
only when its OPEN time + timeframe duration is <= the decision timestamp.
"""
from __future__ import annotations

import re
from typing import Optional

import pandas as pd


_TF_SECONDS = {
    "1m": 60, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
    "5min": 300, "15min": 900, "30min": 1800,
    "1hour": 3600, "4hour": 14400, "1day": 86400, "1week": 604800,
}

def timeframe_seconds(timeframe: str) -> Optional[int]:
    if timeframe in _TF_SECONDS:
        return _TF_SECONDS[timeframe]
    m = re.fullmatch(r"(\d+)\s*(m|min|h|hour|d|day|w|week)", str(timeframe or "").lower())
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    mult = {"m":60,"min":60,"h":3600,"hour":3600,"d":86400,"day":86400,"w":604800,"week":604800}[unit]
    return n * mult

def _timestamp_ms(series: pd.Series) -> pd.Series:
    ts = pd.to_numeric(series, errors="coerce")
    median = float(ts.dropna().median() or 0.0)
    return ts * 1000.0 if median < 1e12 else ts

def closed_htf_slice(htf_df: pd.DataFrame, decision_time_ms: float, timeframe: str) -> pd.DataFrame:
    """Return only HTF candles whose CLOSE TIME has passed at decision time."""
    if htf_df is None or htf_df.empty or "timestamp" not in htf_df.columns:
        return htf_df.iloc[0:0].copy() if htf_df is not None else pd.DataFrame()
    h = htf_df.copy()
    h["_open_ms"] = _timestamp_ms(h["timestamp"])
    seconds = timeframe_seconds(timeframe)
    if seconds is None:
        raise ValueError(f"Unknown timeframe for closed-candle slicing: {timeframe}")
    h["_close_ms"] = h["_open_ms"] + seconds * 1000.0
    h = h[h["_close_ms"] <= float(decision_time_ms)].copy()
    h = h.sort_values("_open_ms").reset_index(drop=True)
    return h.drop(columns=["_open_ms", "_close_ms"], errors="ignore")

def primary_decision_close_ms(df: pd.DataFrame, timeframe: str) -> Optional[float]:
    """Project convention: the last closed primary candle is df.iloc[-2]."""
    if df is None or len(df) < 2 or "timestamp" not in df.columns:
        return None
    ts = float(_timestamp_ms(pd.Series([df.iloc[-2]["timestamp"]])).iloc[0])
    seconds = timeframe_seconds(timeframe)
    if seconds is None:
        return None
    return ts + seconds * 1000.0
