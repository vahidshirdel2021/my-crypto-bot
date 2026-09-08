# -*- coding: utf-8 -*-
"""
signal_engine.key_level_setup.confluence
===========================================
تشخیص «سطح قوی» (Level Confluence) — طبق درخواست کاربر: وقتی دو یا چند
سطح از تایم‌فریم‌های مختلف (مثلاً P1H و PDEQ) در یک محدوده‌ی قیمتی کوچک
به هم می‌رسند، مجموعشان یک ناحیه‌ی مقاومت/حمایت به‌مراتب معتبرتر از هر
سطح به‌تنهایی می‌سازد. این ماژول این خوشه‌ها را پیدا می‌کند و به دو شکل
مصرف‌شان می‌کند:

    ۱) حساس‌تر: تلورانس برخورد به‌جای تلورانس تنگ هر سطح به‌تنهایی،
       کل بازه‌ی خوشه (+ یک بافر) را می‌پوشاند — تا برخورد با *هر*
       عضو خوشه، برخورد با کل «سطح قوی» تلقی شود.
    ۲) قوی‌تر: امتیاز اطمینان ستاپِ حاصل از این برخورد با یک ضریب
       تقویت (بر اساس مجموع وزن اهمیت لایه‌های شرکت‌کننده) افزایش
       می‌یابد — طبق همان منطق «اهمیت لایه» که هر ۵ لایه‌ی موجود
       (۱ساعته تا ماهانه) از قبل دارند.

هیچ سطح جدیدی این‌جا محاسبه نمی‌شود — فقط سطوح از پیش موجود در
LevelSet (خروجی compute_key_levels) خوشه‌بندی می‌شوند.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from signal_engine.key_level_setup.levels import LevelSet

# طبق همان اهمیت لایه‌ای که در interactions.py/setups.py استفاده می‌شود —
# اینجا هم برای وزن‌دهی به قدرت خوشه به کار می‌رود (تکرار عمدی تا این
# ماژول به ساختار داخلی ماژول‌های دیگر وابسته نباشد؛ منبع حقیقتِ خودِ
# tier اسمی هرکدام همچنان LEVEL_TIER در interactions.py است).
_TIER_WEIGHT_FOR_CONFLUENCE = {"1h": 0.25, "4h": 0.35, "daily": 0.5, "weekly": 0.75, "monthly": 1.0}

DEFAULT_CONFLUENCE_CONFIG = {
    "enabled": True,
    "proximity_atr_multiple": 0.5,  # حداکثر فاصله‌ی دو سطح (بر حسب ATR) برای این‌که «هم‌گرا» تلقی شوند
    "zone_buffer_atr_multiple": 0.1,  # بافر اضافه دور کل بازه‌ی خوشه برای تلورانس برخورد
    "max_strength_multiplier": 2.0,  # سقف ضریب تقویت اطمینان (جلوگیری از تورم بی‌حد در خوشه‌های خیلی بزرگ)
}


@dataclass
class ConfluenceZone:
    level_names: List[str]
    tiers: List[str]
    price_low: float
    price_high: float
    price_center: float
    strength: float  # مجموع وزن لایه‌های شرکت‌کننده (سقف‌خورده)

    def contains_with_buffer(self, price: float, buffer: float) -> bool:
        return (self.price_low - buffer) <= price <= (self.price_high + buffer)

    def to_dict(self) -> dict:
        return {
            "level_names": self.level_names, "tiers": self.tiers,
            "price_low": self.price_low, "price_high": self.price_high,
            "price_center": self.price_center, "strength": self.strength,
        }


def detect_level_confluence(
    level_set: LevelSet,
    atr_value: float,
    level_tier_map: Dict[str, str],
    config: Optional[dict] = None,
) -> Dict[str, ConfluenceZone]:
    """طبق منطق بالا: سطوح موجود در level_set را بر اساس نزدیکی قیمتی
    (خوشه‌بندی تک‌پیوندی ساده، sorted sweep) گروه‌بندی می‌کند.

    خروجی: دیکشنری از level_name به ConfluenceZone — *فقط* برای
    سطوحی که واقعاً بخشی از یک خوشه‌ی حداقل ۲تایی هستند؛ سطح تنها
    (بدون هم‌گرایی) در خروجی ظاهر نمی‌شود (طبق قرارداد: نبودن در این
    دیکشنری یعنی «سطح معمولی، تقویت‌نشده»).
    """
    cfg = {**DEFAULT_CONFLUENCE_CONFIG, **(config or {})}
    if not cfg["enabled"] or atr_value is None or atr_value <= 0:
        return {}

    valid = [(name, info.price) for name, info in level_set.levels.items() if info.price is not None]
    if len(valid) < 2:
        return {}

    valid.sort(key=lambda x: x[1])
    proximity = cfg["proximity_atr_multiple"] * atr_value

    clusters: List[List[tuple]] = []
    current_cluster = [valid[0]]
    for name, price in valid[1:]:
        if price - current_cluster[-1][1] <= proximity:
            current_cluster.append((name, price))
        else:
            clusters.append(current_cluster)
            current_cluster = [(name, price)]
    clusters.append(current_cluster)

    result: Dict[str, ConfluenceZone] = {}
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        names = [c[0] for c in cluster]
        prices = [c[1] for c in cluster]
        tiers = [level_tier_map.get(n, "daily") for n in names]
        strength = min(
            cfg["max_strength_multiplier"],
            sum(_TIER_WEIGHT_FOR_CONFLUENCE.get(t, 0.5) for t in tiers),
        )
        zone = ConfluenceZone(
            level_names=names, tiers=tiers,
            price_low=min(prices), price_high=max(prices),
            price_center=sum(prices) / len(prices), strength=round(strength, 3),
        )
        for n in names:
            result[n] = zone

    return result
