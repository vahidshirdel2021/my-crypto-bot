def strategy_liquidity_sweep_5m(df, filters=None, strategy_config=None, live_price=None, timeframe="5min"):
    """
    شکار نقدینگی روی تمام سطوح کلیدی HTF شامل:
    ماهانه، هفتگی، ۴ ساعته، ۱ ساعته و روزانه همراه با نام‌گذاری ستاپ‌ها
    """
    d, pdh, pdl = _compute_prev_day_levels(df)
    if d is None:
        return None, "داده کافی نیست"
    
    # استخراج سطوح 1 ساعته، 4 ساعته، هفتگی و ماهانه از توابع ربات
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

    # تجمیع تمام سطوح همراه با تگ نام‌گذاری اختصاصی ستاپ
    key_levels = []
    if pmh is not None and pml is not None:
        key_levels.append(('PMH', pmh, 'SELL', 'SETUP Monthly'))
        key_levels.append(('PML', pml, 'BUY', 'SETUP Monthly'))
    if pwh is not None and pwl is not None:
        key_levels.append(('PWH', pwh, 'SELL', 'SETUP Weekly'))
        key_levels.append(('PWL', pwl, 'BUY', 'SETUP Weekly'))
    if p4h is not None and p4l is not None:
        key_levels.append(('P4H', p4h, 'SELL', 'SETUP 4h'))
        key_levels.append(('P4L', p4l, 'BUY', 'SETUP 4h'))
    if p1h is not None and p1l is not None:
        key_levels.append(('P1H', p1h, 'SELL', 'SETUP 1h'))
        key_levels.append(('P1L', p1l, 'BUY', 'SETUP 1h'))
    if pdh is not None and pdl is not None:
        key_levels.append(('PDH', pdh, 'SELL', 'SETUP Daily'))
        key_levels.append(('PDL', pdl, 'BUY', 'SETUP Daily'))

    def detect_at(idx):
        if idx < 0 or idx >= len(d):
            return None, None, None
        curr = d.iloc[idx]
        atr = _safe_float(curr.get("atr"), 0.0)
        if not np.isfinite(atr) or atr <= 0:
            return None, None, None
        min_sweep = atr * max(0.0, float(cfg.get("sweep_min_distance_atr", 0.10)))
        o, c, h, l = float(curr["open"]), float(curr["close"]), float(curr["high"]), float(curr["low"])

        # بررسی برخورد قیمت و تزریق نام ستاپ به دلیل سیگنال
        for level_name, level_val, expected_side, setup_tag in key_levels:
            if expected_side == 'SELL' and h >= level_val + min_sweep:
                reclaimed = (not require_reclaim) or (c < level_val)
                reversal = (not require_reversal) or (c < o)
                if reclaimed and reversal:
                    return "SELL", f"[{setup_tag}] Liquidity Sweep روی سقف {level_name} ({level_val:.6g}) + ریکلیم نزولی", atr
            
            elif expected_side == 'BUY' and l <= level_val - min_sweep:
                reclaimed = (not require_reclaim) or (c > level_val)
                reversal = (not require_reversal) or (c > o)
                if reclaimed and reversal:
                    return "BUY", f"[{setup_tag}] Liquidity Sweep روی کف {level_name} ({level_val:.6g}) + ریکلیم صعودی", atr

        return None, None, None

    latest_idx = len(d) - 2
    sig, reason, atr = detect_at(latest_idx)
    
    if sig:
        return sig, reason
        
    return None, "سطح جدیدی برای شکار نقدینگی لمس نشد"
