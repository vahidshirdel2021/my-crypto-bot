# -*- coding: utf-8 -*-
"""
signal_engine.watchlist_bridge
=================================
پل اتصال بین AdaptiveWatchlist (signal_engine.watchlist) و واچ‌لیست
پویای موجود در bot.py (`_refresh_dynamic_dex_watchlist`). این دو
سیستم مکمل‌اند نه رقیب:
    - واچ‌لیست DEX موجود: «کدام نمادها اصلاً در دامنه‌ی بررسی‌اند؟»
      (بر اساس رتبه‌ی مارکت‌کپ، با چسبندگی/dwell-time خودش)
    - AdaptiveWatchlist: «از بین همان نمادها، امروز چقدر عمیق/مکرر
      نگاهشان کنیم؟» (بر اساس فرصت/فوریت)

طبق سند adaptive_crypto_watchlist_v2.md، بخش ۸: ورودی‌های غنی (ساختار
تایم‌فریم بالا از SDE، فاصله تا سطح کلیدی از KLSDE) باید از موتورهای
موجود گرفته شوند، نه بازمحاسبه. در این MVP، چون scan_loop فعلی این
داده‌ها را در مرحله‌ی «تصمیم به اسکن یا نه» (پیش از اجرای واقعی موتورها)
در دسترس ندارد، فقط از داده‌ی *ارزان* موجود (حجم دلاری، که از همان
فراخوانی CoinGecko واچ‌لیست DEX رایگان به دست می‌آید) استفاده می‌شود؛
بقیه‌ی اجزای امتیاز فرصت (که ورودی ندارند) به‌صورت امن صفر می‌مانند —
دقیقاً طبق طراحی «graceful degradation» خود سند، نه یک مقدار جعلی.

`record_engine_events` به scan_symbol اجازه می‌دهد بعد از هر تحلیل عمیق
واقعی، رویدادهای واقعی موتورها (BOS/CHoCH/...) را به واچ‌لیست پس بدهد تا
چرخه‌های بعدی از ترفیع رویدادمحور واقعی بهره‌مند شوند — نه فقط حجم دلاری.
"""

from __future__ import annotations

import os
import threading
from typing import Dict, List, Optional

from signal_engine.watchlist import AdaptiveWatchlist, MarketSnapshot

_LOCK = threading.RLock()
_GLOBAL_WATCHLIST: Optional[AdaptiveWatchlist] = None
_CYCLE_COUNTER = 0

# طبق سند بخش ۱۶: نگاشت باند فرکانس به «هر چند سیکل اسکن یک‌بار» — چون
# scan_loop فعلی روی تایمر ثابت (SCAN_INTERVAL_SECONDS) کار می‌کند، نه
# زمان‌بند مستقل هر نماد، این نگاشت ساده‌ترین راه صادقانه برای اعمال
# اولویت است بدون بازنویسی کامل حلقه‌ی اسکن.
FREQUENCY_TO_CYCLE_SKIP = {
    "immediate_deep": 1,
    "high_frequency": 1,
    "normal": 2,
    "reduced": 5,
    "minimal": 15,
}


def get_global_watchlist(config: Optional[dict] = None) -> AdaptiveWatchlist:
    global _GLOBAL_WATCHLIST
    with _LOCK:
        if _GLOBAL_WATCHLIST is None:
            _GLOBAL_WATCHLIST = AdaptiveWatchlist(config)
            # طبق رفتار موجود پروژه (_leader_correlation_decision در bot.py)،
            # BTC/ETH از قبل به‌عنوان لیدر بازار با رفتار ویژه در نظر گرفته
            # می‌شوند — این‌جا هم همان دو نماد به‌صورت پیش‌فرض CORE می‌شوند.
            _GLOBAL_WATCHLIST.mark_core(["BTC", "ETH"])
        return _GLOBAL_WATCHLIST


def is_adaptive_watchlist_enabled() -> bool:
    return os.environ.get("ADAPTIVE_WATCHLIST_ENABLED", "false").lower() in ("1", "true", "yes")


def _build_cheap_snapshot(symbol: str, dollar_volume: Optional[float], time_index: int) -> MarketSnapshot:
    """طبق مستندسازی بالا: فقط از داده‌ی از پیش رایگان استفاده می‌کند.
    فیلدهای غنی (spread/atr/htf_trend/...) عمداً None می‌مانند تا اجزای
    مربوطه‌ی Opportunity Score به‌صورت امن صفر شوند، نه مقدار ساختگی.
    """
    return MarketSnapshot(
        symbol=symbol, time_index=time_index,
        dollar_volume=dollar_volume, volume=None, spread_pct=None,
        data_valid=(dollar_volume is not None),
    )


def select_symbols_for_cycle(
    symbols: List[str],
    dollar_volume_by_symbol: Optional[Dict[str, float]] = None,
    config: Optional[dict] = None,
) -> List[str]:
    """نقطه‌ی ورود اصلی برای bot.py: از بین `symbols` (خروجی واچ‌لیست DEX
    موجود)، فقط آن‌هایی که طبق زمان‌بند AdaptiveWatchlist در این سیکل
    باید اسکن شوند را برمی‌گرداند.

    طبق سند، بخش ۱۷ (مرز حیاتی): این تابع فقط تعیین می‌کند *کدام نمادها
    این سیکل اسکن شوند*، هرگز تصمیم معامله نمی‌گیرد — خروجی مستقیماً
    جایگزین لیست ورودی حلقه‌ی اسکن bot.py می‌شود، بدون تغییر در منطق
    خودِ scan_symbol.

    اگر AdaptiveWatchlist خالی/تازه باشد (نمادهای جدید، بدون تاریخچه)،
    طبق طراحی state اولیه (DORMANT با امتیاز پایین)، ممکن است در چند
    سیکل اول محافظه‌کارانه رفتار کند — این عمدی و طبق سند است (بخش ۲۰:
    «هیچ نمادی بدون حداقل یک اسکن اولیه رها نمی‌شود» را با admitted=True
    برای اولین سیکل هر نماد تضمین می‌کنیم، پایین‌تر).
    """
    global _CYCLE_COUNTER
    wl = get_global_watchlist(config)
    dv_map = dollar_volume_by_symbol or {}

    with _LOCK:
        _CYCLE_COUNTER += 1
        cycle = _CYCLE_COUNTER

    selected: List[str] = []
    for sym in symbols:
        entry = wl.get_entry(sym)
        is_first_time = entry is None

        snap = _build_cheap_snapshot(sym, dv_map.get(sym), cycle)
        wl.update_symbol(snap)

        if is_first_time:
            # طبق سند: هیچ نمادی بدون حداقل یک نگاه اولیه رها نمی‌شود.
            selected.append(sym)
            continue

        entry = wl.get_entry(sym)
        has_rich_data = any([
            entry.scores.higher_tf_structure > 0,
            entry.scores.volatility_suitability > 0,
            entry.scores.key_level_proximity > 0,
            entry.scores.early_setup_evidence > 0,
        ])
        if not has_rich_data:
            # طبق اصل «fail-open»: تا وقتی ورودی‌های غنی‌تر (ATR/روند/سطح)
            # برای این نماد در دسترس نیست، امتیاز پایین را نشانه‌ی «فرصت کم»
            # تفسیر نکن — نشانه‌ی «داده‌ی ناکافی» است. کنار گذاشتن سکوت‌آمیز
            # نمادها فقط به‌خاطر نبود داده، دقیقاً همان چیزی است که سند در
            # مورد graceful degradation هشدار می‌دهد که نباید رخ دهد.
            selected.append(sym)
            continue

        from signal_engine.watchlist.scheduler import frequency_for_attention
        freq = frequency_for_attention(entry.attention_priority, wl.config.get("scheduler"))
        skip_every = FREQUENCY_TO_CYCLE_SKIP.get(freq, 5)
        if cycle % skip_every == 0 or entry.state in ("CORE", "EVENT_HOT"):
            selected.append(sym)

    return selected


def record_deep_analysis(symbol: str, time_index: Optional[int] = None) -> None:
    """scan_symbol باید بعد از هر تحلیل عمیق واقعی (چه سیگنالی تولید شده
    باشد چه نه) این را صدا بزند تا freshness/coverage urgency درست
    محاسبه شود (طبق سند، بخش ۱۱).
    """
    wl = get_global_watchlist()
    idx = time_index if time_index is not None else _CYCLE_COUNTER
    wl.mark_deep_analysis_done(symbol, idx)


def record_engine_event(
    symbol: str, source_engine: str, native_event_type: str,
    trigger_event_id: Optional[str] = None, time_index: Optional[int] = None,
) -> None:
    """اگر scan_symbol از موتور جدید (signal_engine) استفاده می‌کند
    (پشت فلگ use_new_signal_engine)، می‌تواند رویدادهای واقعی BOS/CHoCH/
    ستاپ‌های KLSDE را از همان اجرا به واچ‌لیست پس بدهد تا ترفیع
    رویدادمحور واقعی (نه فقط حجم دلاری) فعال شود — طبق بخش ۱۳ سند.
    """
    wl = get_global_watchlist()
    idx = time_index if time_index is not None else _CYCLE_COUNTER
    wl.handle_engine_event(symbol, source_engine, native_event_type, trigger_event_id, idx)


def mark_core_symbols(symbols: List[str]) -> None:
    get_global_watchlist().mark_core(symbols)


def compute_btc_context(btc_df, timeframe: str = "15m") -> Optional[dict]:
    """طبق بخش ۴ سند اصلاحی (Architectural Addendum): «USCL باید فاز کلان
    Wyckoff بیت‌کوین (MCDE) و ساختار ۱۵ دقیقه‌ای آن (SDE) را پایش کند» —
    این تابع واقعاً همان دو موتور را روی داده‌ی خودِ BTC اجرا می‌کند
    (نه یک هیوریستیک EMA/ADX سبک‌تر مثل leader_correlation_guard موجود
    در bot.py که برای هدف دیگری طراحی شده).

    btc_df باید کندل‌های ۱۵ دقیقه‌ای BTC با تاریخچه‌ی کافی برای MCDE
    (حداقل ~۲۰۵ کندل برای EMA200) باشد — یک فراخوانی واحد، هر دو موتور
    را از همان داده تغذیه می‌کند تا برچسب تایم‌فریم رویدادها واقعاً
    درست باشد (نه یک برچسب جعلی روی داده‌ی تایم‌فریم دیگر).

    خروجی: {'macro_phase': str|None, 'structure_direction_15m': str|None}
    یا None اگر داده کافی نبود (طبق اصل fail-open: نبود btc_context یعنی
    جریمه‌ی واگرایی سیستمیک اصلاً اعمال نمی‌شود، نه این‌که حدس زده شود).
    """
    if btc_df is None or len(btc_df) < 20:
        return None

    from signal_engine.market_cycle.macro import classify_macro_cycle
    from signal_engine.swing_structure.swings import detect_swings
    from signal_engine.swing_structure.structure import detect_structure_events

    macro_phase = None
    try:
        macro_events = classify_macro_cycle(btc_df, timeframe=timeframe, symbol="BTC")
        if macro_events:
            macro_phase = macro_events[-1].phase  # آخرین فاز (چه active چه تازه closed)
    except Exception:
        macro_phase = None

    structure_direction = None
    try:
        swings = detect_swings(btc_df, timeframe=timeframe, symbol="BTC")
        structure_events = detect_structure_events(btc_df, swings, timeframe=timeframe, symbol="BTC")
        bos_events = [e for e in structure_events if e.event_type == "BOS"]
        if bos_events:
            structure_direction = bos_events[-1].direction
    except Exception:
        structure_direction = None

    if macro_phase is None and structure_direction is None:
        return None
    return {"macro_phase": macro_phase, "structure_direction_15m": structure_direction}
