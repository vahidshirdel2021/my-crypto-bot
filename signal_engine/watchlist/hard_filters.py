# -*- coding: utf-8 -*-
"""
signal_engine.watchlist.hard_filters
=======================================
پیاده‌سازی بخش ۷ سند: فیلترهای سخت — «گیت» هستند نه جزء امتیاز. نمادی که
یکی از فیلترهای الزامی را رد کند، حتی با Opportunity Score بالا هم وارد
ACTIVE نمی‌شود.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from signal_engine.watchlist.models import MarketSnapshot

DEFAULT_HARD_FILTER_CONFIG = {
    "min_dollar_volume": 1_000_000.0,
    "min_volume": 0.0,
    "max_spread_pct": 0.005,  # ۰.۵٪
    "min_listing_age_days": 3.0,
    "require_valid_data": True,
}


def apply_hard_filters(
    snapshot: MarketSnapshot,
    config: Optional[dict] = None,
) -> Tuple[bool, List[str]]:
    """خروجی: (passed, failure_reasons). failure_reasons خالی یعنی از
    همه‌ی فیلترها رد شده (passed=True).

    طبق سند: فیلترهای سخت هرگز جزئی از فرمول امتیاز نیستند — این تابع
    فقط bool/دلیل برمی‌گرداند، نه یک عدد قابل‌جمع با بقیه‌ی امتیازها.
    """
    cfg = {**DEFAULT_HARD_FILTER_CONFIG, **(config or {})}
    reasons: List[str] = []

    if cfg["require_valid_data"] and not snapshot.data_valid:
        reasons.append("invalid_or_incomplete_market_data")
        # داده‌ی نامعتبر یعنی بقیه‌ی فیلدها هم قابل‌اتکا نیستند — زودتر خارج شو.
        return False, reasons

    if snapshot.dollar_volume is not None and snapshot.dollar_volume < cfg["min_dollar_volume"]:
        reasons.append(f"insufficient_dollar_volume(<{cfg['min_dollar_volume']})")

    if snapshot.volume is not None and snapshot.volume < cfg["min_volume"]:
        reasons.append(f"insufficient_volume(<{cfg['min_volume']})")

    if snapshot.spread_pct is not None and snapshot.spread_pct > cfg["max_spread_pct"]:
        reasons.append(f"excessive_spread(>{cfg['max_spread_pct']})")

    if snapshot.listing_age_days is not None and snapshot.listing_age_days < cfg["min_listing_age_days"]:
        reasons.append(f"below_min_listing_age(<{cfg['min_listing_age_days']}d)")

    return (len(reasons) == 0), reasons
