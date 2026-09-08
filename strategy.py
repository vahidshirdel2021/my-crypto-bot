import numpy as np

# تنظیمات پیش‌فرض استراتژی
STRATEGY_DEFAULTS = {
    "sweep_min_distance_atr": 0.10,
    "sweep_require_reclaim": True,
    "sweep_require_reversal_candle": True,
    "min_rr": 1.30,
    "sweep_risk_reward": 1.8,
    "sweep_stop_buffer_atr": 0.40,
    "min_sl_percent": 0.005,
    "max_fee_risk_ratio": 0.20,
    "max_sl_atr": 3.00,
    "min_trade_score": 58.0,
    "extend_tp_to_pdl": True
}

def _cfg(strategy_config):
    return strategy_config if isinstance(strategy_config, dict) else {}

def _safe_float(val, default=0.0):
    try:
        v = float(val)
        return v if np.isfinite(v) else default
    except Exception:
        return default

def _compute_prev_day_levels(df):
    if df is None or len(df) < 2:
        return None, None, None
    d = df.copy()
    pdh = float(d['high'].max())
    pdl = float(d['low'].min())
    return d, pdh, pdl

def _compute_prev_htf_levels(df, idx):
    # تابع فرضی استخراج سطوح HTF برای جلوگیری از خطا
    return {}

def candle_pattern_score(df, signal, regime="range", near_structure=True, max_points=10.0):
    return 0.0, ""

def strategy_liquidity_sweep_5m(df, filters=None, strategy_config=None, live_price=None, timeframe="5min"):
    """
    شکار نقدینگی روی تمام سطوح کلیدی HTF شامل:
    ماهانه، هفتگی، ۴ ساعته، ۱ ساعته و روزانه
    """
    d, pdh, pdl = _compute_prev_day_levels(df)
    if d is None:
        return None, "داده کافی نیست"
    
    htf_levels = _compute_prev_htf_levels(d, len(d) - 2)
    
    p1h = htf_levels.get("P1H")
    p1l = htf_levels.get("P1L")
    p4h = htf_levels.get("P4H")
    p4l = htf_levels.get("P4L")
    pwh = htf_levels.get("PWH")
    pwl = htf_levels.get("PWL")
    pmh = htf_levels.get("PMH")
    pml = htf_levels.get("PML")

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    require_reclaim = bool(cfg.get("sweep_require_reclaim", True))
    require_reversal = bool(cfg.get("sweep_require_reversal_candle", True))

    key_levels = []
    if pmh is not None and pml is not None:
        key_levels.append(('PMH (ماهانه)', pmh, 'SELL'))
        key_levels.append(('PML (ماهانه)', pml, 'BUY'))
    if pwh is not None and pwl is not None:
        key_levels.append(('PWH (هفتگی)', pwh, 'SELL'))
        key_levels.append(('PWL (هفتگی)', pwl, 'BUY'))
    if p4h is not None and p4l is not None:
        key_levels.append(('P4H (۴ ساعته)', p4h, 'SELL'))
        key_levels.append(('P4L (۴ ساعته)', p4l, 'BUY'))
    if p1h is not None and p1l is not None:
        key_levels.append(('P1H (۱ ساعته)', p1h, 'SELL'))
        key_levels.append(('P1L (۱ ساعته)', p1l, 'BUY'))
    if pdh is not None and pdl is not None:
        key_levels.append(('PDH (روزانه)', pdh, 'SELL'))
        key_levels.append(('PDL (روزانه)', pdl, 'BUY'))

    def detect_at(idx):
        if idx < 0 or idx >= len(d):
            return None, None, None
        curr = d.iloc[idx]
        atr = _safe_float(curr.get("atr"), 0.0)
        if not np.isfinite(atr) or atr <= 0:
            return None, None, None
        min_sweep = atr * max(0.0, float(cfg.get("sweep_min_distance_atr", 0.10)))
        o, c, h, l = float(curr["open"]), float(curr["close"]), float(curr["high"]), float(curr["low"])

        for level_name, level_val, expected_side in key_levels:
            if expected_side == 'SELL' and h >= level_val + min_sweep:
                reclaimed = (not require_reclaim) or (c < level_val)
                reversal = (not require_reversal) or (c < o)
                if reclaimed and reversal:
                    return "SELL", f"Liquidity Sweep روی سقف {level_name} ({level_val:.6g}) + ریکلیم نزولی", atr
            
            elif expected_side == 'BUY' and l <= level_val - min_sweep:
                reclaimed = (not require_reclaim) or (c > level_val)
                reversal = (not require_reversal) or (c > o)
                if reclaimed and reversal:
                    return "BUY", f"Liquidity Sweep روی کف {level_name} ({level_val:.6g}) + ریکلیم صعودی", atr

        return None, None, None

    latest_idx = len(d) - 2
    sig, reason, atr = detect_at(latest_idx)
    
    if sig:
        return sig, reason
        
    return None, "سطح جدیدی برای شکار نقدینگی لمس نشد"

def _extend_stop_to_grid(levels, sweep_extreme, naive_sl, atr, direction):
    if not levels:
        return naive_sl
    if direction == -1:
        cands = [lv['price'] for lv in levels if sweep_extreme < lv['price'] <= sweep_extreme + atr * 1.5]
        if cands:
            return max(naive_sl, min(cands) + atr * 0.15)
    else:
        cands = [lv['price'] for lv in levels if sweep_extreme - atr * 1.5 <= lv['price'] < sweep_extreme]
        if cands:
            return min(naive_sl, max(cands) - atr * 0.15)
    return naive_sl

def _cap_target_to_grid(levels, entry, risk_dist, direction, min_rr, current_target):
    if not levels:
        return current_target
    candidates = []
    for lv in levels:
        p = lv['price']
        dist = (entry - p) if direction == -1 else (p - entry)
        if dist <= 0:
            continue
        if dist / risk_dist < min_rr:
            continue
        candidates.append((dist, p))
    if not candidates:
        return current_target
    candidates.sort()
    _, nearest_price = candidates[0]
    if direction == -1 and nearest_price > current_target:
        return nearest_price
    if direction == 1 and nearest_price < current_target:
        return nearest_price
    return current_target

def build_sweep_trade_plan(df, signal, strategy_config=None, grid_levels=None, setup_index=None, live_price=None, anchor_level=None, target_level=None, continuation=False):
    if df is None or len(df) < 100 or signal not in ("BUY", "SELL"):
        return None, "داده کافی برای طراحی معامله وجود ندارد"
    d, pdh, pdl = _compute_prev_day_levels(df)
    if d is None or pdh is None or pdl is None:
        return None, "سطوح روز قبل هنوز آماده نیست"
    idx = (len(d) - 2) if setup_index is None else int(setup_index)
    if idx < 1 or idx >= len(d):
        return None, "شاخص ستاپ معتبر نیست"
    curr = d.iloc[idx]
    risk_idx = len(d) - 2 if setup_index is not None else idx
    risk_row = d.iloc[risk_idx]
    try:
        entry = float(live_price) if (setup_index is not None and live_price is not None) else float(curr["close"])
        atr = float(risk_row["atr"])
    except Exception:
        return None, "ATR یا قیمت ورود نامعتبر است"
    if not np.isfinite(entry) or entry <= 0 or not np.isfinite(atr) or atr <= 0:
        return None, "ATR یا قیمت ورود نامعتبر است"

    cfg = {**STRATEGY_DEFAULTS, **(_cfg(strategy_config) or {})}
    min_rr = float(cfg.get("min_rr", 1.30))
    target_rr = max(min_rr, float(cfg.get("sweep_risk_reward", 1.8)))
    buffer_atr = max(0.40, float(cfg.get("sweep_stop_buffer_atr", 0.40)))
    min_sl_pct = float(cfg.get("min_sl_percent", 0.005))
    max_fee_ratio = float(cfg.get("max_fee_risk_ratio", 0.20))
    max_sl_atr = max(1.5, float(cfg.get("max_sl_atr", 3.00)))
    body_ratio = _safe_float(curr.get("body_ratio"), 0)
    vr = _safe_float(curr.get("volume_ratio"), 1)

    extend_to_structure = bool(cfg.get("extend_tp_to_pdl", True))

    if signal == "SELL":
        sweep_extreme = float(curr["high"])
        sl = sweep_extreme + (atr * buffer_atr)
        sl = _extend_stop_to_grid(grid_levels, sweep_extreme, sl, atr, -1)
        if (sl - entry) / entry < min_sl_pct:
            sl = entry * (1.0 + min_sl_pct)
        risk_dist = sl - entry
        if risk_dist <= 0:
            return None, "فاصله حد ضرر معتبر نیست"
        if risk_dist > atr * max_sl_atr:
            return None, "استاپ ساختاری بیش از حد دور است؛ معامله رد شد"
        reclaim_depth = (sweep_extreme - entry) / risk_dist
        soft_tp = entry - (risk_dist * target_rr)
        tp = soft_tp
        target_ref = float(target_level) if target_level is not None else pdl
        if extend_to_structure and target_ref < entry and (entry - target_ref) / risk_dist >= min_rr:
            tp = target_ref
        elif target_ref < entry and (entry - target_ref) / risk_dist >= min_rr:
            tp = max(tp, target_ref)
        tp = _cap_target_to_grid(grid_levels, entry, risk_dist, -1, min_rr, tp)
    else:
        sweep_extreme = float(curr["low"])
        sl = sweep_extreme - (atr * buffer_atr)
        sl = _extend_stop_to_grid(grid_levels, sweep_extreme, sl, atr, 1)
        if (entry - sl) / entry < min_sl_pct:
            sl = entry * (1.0 - min_sl_pct)
        risk_dist = entry - sl
        if risk_dist <= 0:
            return None, "فاصله حد ضرر معتبر نیست"
        if risk_dist > atr * max_sl_atr:
            return None, "استاپ ساختاری بیش از حد دور است؛ معامله رد شد"
        reclaim_depth = (entry - sweep_extreme) / risk_dist
        soft_tp = entry + (risk_dist * target_rr)
        tp = soft_tp
        target_ref = float(target_level) if target_level is not None else pdh
        if extend_to_structure and target_ref > entry and (target_ref - entry) / risk_dist >= min_rr:
            tp = target_ref
        elif target_ref > entry and (target_ref - entry) / risk_dist >= min_rr:
            tp = min(tp, target_ref)
        tp = _cap_target_to_grid(grid_levels, entry, risk_dist, 1, min_rr, tp)

    risk_pct = risk_dist / entry
    est_risk_usdt = 500.0 * risk_pct
    if est_risk_usdt > 0:
        if (0.50 / est_risk_usdt) > max_fee_ratio:
            return None, f"ریسک به کارمزد کوچک است ({est_risk_usdt:.2f}$)"

    rr = abs(tp - entry) / risk_dist
    if rr < min_rr:
        return None, f"R:R کافی نیست ({rr:.2f}R < {min_rr:.2f}R)"

    reclaim_score = min(35.0, max(0.0, reclaim_depth * 35.0))
    candle_score = min(20.0, max(0.0, body_ratio * 27.0))
    volume_score = min(20.0, max(0.0, (vr - 0.8) * 25.0))
    rr_score = min(15.0, max(0.0, (rr - min_rr) * 10.0))
    pattern_df = d.iloc[:idx + 1].copy() if setup_index is not None else df
    pattern_score, pattern_name = candle_pattern_score(pattern_df, signal, regime="range", near_structure=True, max_points=10.0)
    score = int(round(max(0.0, min(100.0, reclaim_score + candle_score + volume_score + rr_score + pattern_score))))

    min_score = float(cfg.get("min_trade_score", 58.0))
    quality_label = "عالی" if score >= 85 else "خوب" if score >= 75 else "قابل قبول" if score >= min_score else "ضعیف"
    if score < min_score:
        return None, f"امتیاز کیفیت پایین است ({score}/100)"

    plan = {
        "entry": entry, "sl": float(sl), "tp": float(tp), "score": score,
        "quality_label": quality_label, "rr": float(rr),
        "pdh": float(pdh), "pdl": float(pdl), "soft_tp": float(soft_tp),
        "anchor_level": float(anchor_level) if anchor_level is not None else (float(pdh) if signal == "SELL" else float(pdl)),
        "target_level": float(target_level) if target_level is not None else (float(pdl) if signal == "SELL" else float(pdh)),
        "structural_target": bool(target_level is not None or tp == pdl or tp == pdh),
        "risk_atr_source_index": int(risk_idx),
        "setup_index": int(idx),
        "pattern": pattern_name,
        "reason": f"Liquidity Sweep | کیفیت {score}/100 ({quality_label}) | عمق ریکلیم {reclaim_depth:.2f}x ریسک | R:R {rr:.2f}R" + (f" | الگو: {pattern_name}" if pattern_name else "")
    }
    return plan, plan["reason"]
