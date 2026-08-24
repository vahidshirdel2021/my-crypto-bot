"""V2 Adaptive Opportunity Engine.

This module is additive: V1 candidate generation and risk gates remain the
source of truth. V2 ranks already-valid opportunities, estimates evidence
confidence, and decides whether timing is NOW, PULLBACK, or CONFIRMATION.
"""

import math
import time


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def evidence_confidence(plan):
    """Confidence is intentionally separate from quality score."""
    score = float(plan.get("score", 0.0) or 0.0)
    rr = float(plan.get("rr", 0.0) or 0.0)
    regime_conf = float(plan.get("regime_confidence", 0.0) or 0.0)
    htf = abs(float(plan.get("htf_bias", 0.0) or 0.0))
    edge = float(plan.get("edge_proxy", 0.0) or 0.0)
    structural = 1.0 if plan.get("structural_target") else 0.0

    # Independent evidence, capped to avoid score inflation from one source.
    parts = [
        _clip((score - 55.0) / 45.0, 0.0, 1.0),
        _clip((rr - 1.0) / 1.5, 0.0, 1.0),
        _clip(regime_conf, 0.0, 1.0),
        _clip(htf, 0.0, 1.0),
        _clip((edge + 0.10) / 0.60, 0.0, 1.0),
        structural,
    ]
    confidence = 100.0 * (
        0.28 * parts[0] + 0.22 * parts[1] + 0.18 * parts[2]
        + 0.14 * parts[3] + 0.12 * parts[4] + 0.06 * parts[5]
    )
    return round(_clip(confidence, 0.0, 100.0), 1)


def opportunity_rank(plan):
    """Cross-symbol comparable rank for already-valid trade plans."""
    quality = float(plan.get("score", 0.0) or 0.0)
    rr = float(plan.get("rr", 0.0) or 0.0)
    conf = evidence_confidence(plan)
    directional = 2.0 if plan.get("directional_context") == "ALIGNED" else 0.0
    edge = max(-0.10, min(0.60, float(plan.get("edge_proxy", 0.0) or 0.0)))
    rank = 0.55 * quality + 10.0 * _clip(rr, 0.0, 3.0) + 0.25 * conf + 10.0 * edge + directional
    return round(rank, 2)


def smart_timing(plan, live_price=None):
    """Return TRADE_NOW, WAIT_PULLBACK or WAIT_CONFIRMATION.

    This layer never turns an invalid V1 plan into a trade. It only delays
    otherwise valid plans when timing evidence is weak.
    """
    entry = float(plan.get("entry", 0.0) or 0.0)
    sl = float(plan.get("sl", 0.0) or 0.0)
    score = float(plan.get("score", 0.0) or 0.0)
    rr = float(plan.get("rr", 0.0) or 0.0)
    confidence = evidence_confidence(plan)
    regime_conf = float(plan.get("regime_confidence", 0.0) or 0.0)

    if live_price and entry > 0 and sl != entry:
        risk_distance = abs(entry - sl)
        deviation_r = abs(float(live_price) - entry) / max(risk_distance, 1e-12)
        if deviation_r > 0.35:
            return "WAIT_PULLBACK", f"قیمت نسبت به Entry برنامه‌ریزی‌شده {deviation_r:.2f}R فاصله دارد"

    if regime_conf < 0.60 and confidence < 68:
        return "WAIT_CONFIRMATION", "کیفیت قابل قبول است اما شواهد مستقل هنوز کامل نیست"

    if score >= 78 and rr >= 1.55 and confidence >= 58:
        return "TRADE_NOW", "کیفیت، RR و Confidence برای اجرای فوری هم‌راستا هستند"

    if confidence >= 50 and score >= 70:
        return "WAIT_CONFIRMATION", "Near-Miss: ستاپ معتبر است و منتظر تأیید بعدی می‌ماند"

    return "TRADE_NOW", "Safety gates اصلی عبور شده‌اند و Timing مانع اضافی ایجاد نکرد"


def build_opportunity(symbol, side, plan, timeframe, live_price=None):
    confidence = evidence_confidence(plan)
    timing, timing_reason = smart_timing(plan, live_price=live_price)
    return {
        "symbol": symbol,
        "side": side,
        "timeframe": timeframe,
        "setup_family": plan.get("setup_family", "unknown"),
        "quality": int(round(float(plan.get("score", 0.0) or 0.0))),
        "confidence": confidence,
        "rr": round(float(plan.get("rr", 0.0) or 0.0), 3),
        "rank": opportunity_rank(plan),
        "timing": timing,
        "timing_reason": timing_reason,
        "regime": plan.get("regime"),
        "trend_state": plan.get("trend_state"),
        "volatility_state": plan.get("volatility_state"),
        "created_at": time.time(),
    }


def update_pool(session, opportunity, max_items=50):
    pool = [x for x in (session.get("opportunity_pool") or [])
            if time.time() - float(x.get("created_at", 0) or 0) < 1800]
    pool = [x for x in pool if not (
        x.get("symbol") == opportunity["symbol"] and
        x.get("side") == opportunity["side"] and
        x.get("timeframe") == opportunity["timeframe"]
    )]
    pool.append(opportunity)
    pool.sort(key=lambda x: float(x.get("rank", 0) or 0), reverse=True)
    session["opportunity_pool"] = pool[:max_items]
    session["near_miss"] = [
        x for x in pool if x.get("timing") in ("WAIT_PULLBACK", "WAIT_CONFIRMATION")
    ][:max_items]
    return session["opportunity_pool"]


def top_rank(session, opportunity):
    pool = session.get("opportunity_pool") or []
    if not pool:
        return 1
    ordered = sorted(pool, key=lambda x: float(x.get("rank", 0) or 0), reverse=True)
    for i, item in enumerate(ordered, 1):
        if (item.get("symbol"), item.get("side"), item.get("timeframe")) == (
            opportunity.get("symbol"), opportunity.get("side"), opportunity.get("timeframe")
        ):
            return i
    return len(ordered) + 1
