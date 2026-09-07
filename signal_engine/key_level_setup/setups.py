# -*- coding: utf-8 -*-
"""
signal_engine.key_level_setup.setups
=======================================
پیاده‌سازی خط‌به‌خط بخش‌های ۵ و ۶ سند KLSDE: درخت تصمیم‌گیری ترتیبی که هر
پنجره‌ی برخورد (InteractionWindow) را به دقیقاً یکی از پنج ستاپ اصلی سند
(BOF/TST/BPB/BP/CPB) یا «هیچ‌کدام» تبدیل می‌کند.

طبق تأکید صریح سند (بخش ۶، آخر): این پنج ستاپ برداشت‌های متقابلاً
منحصربه‌فرد از یک برخورد هستند — این ماژول عمداً یک state machine
صریح و ترتیبی است، نه یک سیستم امتیازدهی/رأی‌گیری موازی مثل بقیه‌ی
موتورهای پروژه.

BRT (طبق درخواست صریح کاربر، خارج از تاکسونومی اصلی سند): پورت مستقل
ستاپ «بریک‌اند‌ریتست» B5/S5 موتور قدیم (`pdh_eq_pdl_engine.py`) با
همان منطق خودش — نه یک زیرمجموعه‌ی BPB/BP/CPB. چون فقط به «شکست
تأییدشده + ری‌تست تمیز بدون عبور معکوس قاطع» نیاز دارد (نه لزوماً
از‌سرگیری کامل بعدی مثل BPB/BP/CPB)، در درخت تصمیم دقیقاً همان لحظه‌ای
حل می‌شود که شرط سبک‌ترش برآورده شود؛ هیچ اولویت دستی‌ای بین BRT و
بقیه‌ی ستاپ‌ها وجود ندارد — کدام‌یک زودتر توسط رفتار واقعی قیمت
برآورده شود، همان انتخاب می‌شود (دقیقاً طبق خواسته‌ی کاربر).

نکته‌ی صداقت مهندسی: تشخیص «چند موج اصلاحی در پولبک» و «سیگنال ضعف در
نقطه‌ی برگشت» با ابزارهای موجود پروژه (swing_structure و
candle_geometry) پیاده شده‌اند؛ این‌ها تقریب‌های معقول و مستندی از
تعاریف سند هستند، نه پیاده‌سازی‌های «کامل» CPDE/جریان زنده‌ی BOS که در
سند به‌عنوان یکپارچگی نهایی (بخش ۱۰) توصیه شده و بعداً که آن موتورها
ساخته شدند، این تقریب‌ها با فراخوانی مستقیم آن‌ها جایگزین خواهند شد.
BRT هم به همین ترتیب: مثل بقیه‌ی این فایل، فقط از penetration بر مبنای
close (نه لمس high/low خام مثل موتور قدیم) استفاده می‌کند، تا با بقیه‌ی
این ماژول یک‌دست بماند — یک تقریب مستند، نه بازتولید عین‌به‌عین منطق قدیم.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

import pandas as pd

from signal_engine.common.candle_geometry import compute_candle_geometry
from signal_engine.key_level_setup.interactions import InteractionWindow
from signal_engine.swing_structure.swings import detect_swings

SetupType = Literal["BOF", "TST", "BPB", "BP", "CPB", "BRT"]
Direction = Literal["bullish", "bearish"]

DEFAULT_SETUP_CONFIG = {
    "min_breach_atr_multiple": 0.15,
    "full_breakout_atr_multiple": 0.5,
    "full_breakout_confirm_bars": 2,
    "bof_max_bars_to_fail": 3,
    "tst_max_bars_to_reject": 3,
    "pullback_min_retrace_atr": 0.3,
    "resumption_min_atr": 0.2,
    "weakness_body_ratio_factor": 0.5,  # بدنه‌ی کندل رد کردن باید حداکثر نصف بدنه‌ی کندل شکست باشد
    # BRT (بریک‌اند‌ریتست، پورت‌شده از B5/S5 موتور قدیم): چقدر نزدیکیِ
    # (بر حسب ATR) به سطح هم برای «لمس ری‌تست» و هم برای «سقفِ نگه‌داشتن»
    # کافی است — دقیقاً مثل موتور قدیم که یک `tol` مشترک برای هر دو چک
    # داشت (خط ۹۶۷/۹۶۸ و ۱۰۴۷/۱۰۴۸ pdh_eq_pdl_engine.py).
    "retest_tolerance_atr": 0.15,
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
            "id": self.id, "setup_type": self.setup_type, "level_name": self.level_name,
            "level_price": self.level_price, "symbol": self.symbol, "timeframe": self.timeframe,
            "direction": self.direction, "window_opened_at_index": self.window_opened_at_index,
            "resolved_at_index": self.resolved_at_index, "confidence": self.confidence,
            "evidence": self.evidence,
        }


_TIER_CONFIDENCE_WEIGHT = {"1h": 0.25, "4h": 0.35, "daily": 0.5, "weekly": 0.75, "monthly": 1.0}


def _direction_from_approach(approach_direction: str, is_continuation: bool) -> Direction:
    """اگر سطح از پایین لمس شده (نقش مقاومت) و ادامه/شکست رخ دهد → صعودی.
    اگر از پایین لمس شده و شکست *ناکام* بماند (BOF/TST) → نزولی (فِید).
    و برعکس برای لمس از بالا. طبق سند، بخش ۵.۱ و ۵.۲.
    """
    resistance_touch = approach_direction == "from_below"
    if is_continuation:
        return "bullish" if resistance_touch else "bearish"
    return "bearish" if resistance_touch else "bullish"


def _find_first_sustained_breakout(
    window: InteractionWindow, full_breakout_atr_multiple: float, confirm_bars: int
) -> Optional[int]:
    """اولین ایندکسی که در آن، `confirm_bars` کندل متوالی همگی
    penetration_depth_atr ≥ full_breakout_atr_multiple دارند — یعنی
    شکست واقعی (نه صرفاً یک سایه‌ی گذرا) رخ داده. طبق سند بخش ۵.۳.

    نکته‌ی اصلاح: نسخه‌ی قبلی برای پیدا کردن موقعیت شروع رشته از
    ``indices.index(idx)`` داخل حلقه استفاده می‌کرد که یک جست‌وجوی
    O(n) تکراری روی هر عنصر است (یعنی کل تابع O(n²)). این‌جا موقعیت را
    مستقیماً از ``enumerate`` می‌گیریم — همان نتیجه، بدون جست‌وجوی اضافه.
    """
    indices = sorted(window.candle_indices)
    run = 0
    for pos, idx in enumerate(indices):
        pen = window.penetration_depth_atr_by_index.get(idx, float("-inf"))
        if pen >= full_breakout_atr_multiple:
            run += 1
            if run >= confirm_bars:
                return indices[pos - confirm_bars + 1]
        else:
            run = 0
    return None


def _find_break_retest_hold(
    window: InteractionWindow, breakout_confirm_index: int, retest_tolerance_atr: float
) -> Optional[int]:
    """پورت مستقیمِ منطق B5/S5 موتور قدیم (بریک‌اند‌ریتست): بعد از شکست
    تأییدشده، اولین کندلی را برمی‌گرداند که penetration دوباره به بازه‌ی
    نزدیک سطح (±retest_tolerance_atr) برگشته — *به‌شرطی که* هیچ کندل
    قبلِ آن (از لحظه‌ی تأیید شکست تا همین‌جا) به‌طور قاطع از سطح عبور
    معکوس نکرده باشد (یعنی هرگز پایین‌تر از -retest_tolerance_atr
    نرفته). این دقیقاً معادل ترکیب دو شرط موتور قدیم است: `retested`
    (لمس دوباره‌ی سطح) + `min_close_after >= level*(1-tol)` (نگه‌داشتن
    پیوسته)، اما به‌صورت یک پیمایش ترتیبی/علّی به‌جای دو محاسبه‌ی جدا
    روی کل بازه.

    اگر هرگز چنین لمسی رخ ندهد (یا قبل از رسیدن به آن، نگه‌داشتن نقض
    شود)، None برمی‌گرداند — یعنی این پنجره برای BRT واجد شرایط نیست و
    به مرحله‌ی بعدی (پولبک/از‌سرگیری عمومی) واگذار می‌شود.
    """
    for i in sorted(window.candle_indices):
        if i <= breakout_confirm_index:
            continue
        pen = window.penetration_depth_atr_by_index.get(i, float("-inf"))
        # ترتیب چک‌ها مهم است: عبور معکوس قاطع باید *قبل* از چک لمس
        # ری‌تست بررسی شود، چون بازه‌ی pen <= tol شامل مقادیر خیلی
        # منفی‌تر از -tol هم می‌شود؛ اگر ترتیب برعکس بود، شرط دوم هرگز
        # اجرا نمی‌شد (کد مرده).
        if pen < -retest_tolerance_atr:
            return None
        if pen <= retest_tolerance_atr:
            return i
    return None


def _find_bof_failure_index(window: InteractionWindow, max_bars_to_fail: int) -> Optional[int]:
    """بعد از نقطه‌ی حداکثر نفوذ (که هنوز به سطح «شکست پایدار» نرسیده)،
    اولین کندلی که penetration منفی می‌شود (بازگشت کامل به سمت اصلی) را
    برمی‌گرداند — طبق سند بخش ۵.۱.
    """
    indices = sorted(window.candle_indices)
    peak_pos = max(
        range(len(indices)),
        key=lambda p: window.penetration_depth_atr_by_index.get(indices[p], float("-inf")),
    )
    for offset in range(1, max_bars_to_fail + 1):
        pos = peak_pos + offset
        if pos >= len(indices):
            break
        idx = indices[pos]
        if window.penetration_depth_atr_by_index.get(idx, 0.0) < 0:
            return idx
    return None


def _find_reversal_index_for_tst(window: InteractionWindow, max_bars_to_reject: int) -> Optional[int]:
    """برای TST: اولین کندل بعد از باز شدن پنجره که penetration به‌وضوح
    منفی (بازگشت از سطح، بدون این‌که هرگز عبور معناداری رخ داده باشد)
    می‌شود.
    """
    # نکته‌ی اصلاح: نسخه‌ی قبلی یک شاخه‌ی ``idx is None`` داشت که با توجه
    # به سقف بازه‌ی range (که همیشه offset < len(indices) را تضمین
    # می‌کرد) هرگز قابل اجرا نبود — کد مرده که فقط خوانایی را کم می‌کرد.
    indices = sorted(window.candle_indices)
    max_offset = min(max_bars_to_reject, len(indices) - 1)
    for offset in range(1, max_offset + 1):
        idx = indices[offset]
        if window.penetration_depth_atr_by_index.get(idx, 0.0) < 0:
            return idx
    return None


def _count_pullback_swings(df: pd.DataFrame, start_index: int, end_index: int, timeframe: str) -> int:
    """طبق سند بخش ۵.۵: تعداد سوئینگ‌های تأییدشده در بازه‌ی پولبک را از
    همان موتور سوئینگ پروژه می‌گیریم، نه یک شمارنده‌ی جداگانه.

    نکته‌ی اصلاح: نسخه‌ی قبلی یک نگهبان ثابت (`< 5`) داشت که با حداقل
    طول واقعیِ لازم برای تشخیص سوئینگ ناهم‌خوان بود — آن حداقل به
    fractal_k هر تایم‌فریم بستگی دارد (۵m: k=3 → حداقل ۷ کندل، ۱۵m:
    k=2 → حداقل ۵ کندل؛ `_raw_fractal_candidates` در swings.py). یعنی
    عدد «۵» برای ۵m به‌سادگی کافی نبود و بی‌سروصدا همیشه ۰ برمی‌گرداند،
    بدون این‌که این خطا در جایی مشخص باشد. چون detect_swings خودش از
    قبل به‌درستی و آگاه از تایم‌فریم این حداقل را چک می‌کند (و برای
    داده‌ی ناکافی با امنیت [] برمی‌گرداند)، نگهبانِ تکراری و
    ناهم‌خوان این‌جا حذف شد؛ فقط یک چک منطقی حداقلی (بازه‌ی معتبر)
    باقی می‌ماند.
    """
    if end_index <= start_index:
        return 0
    sub = df.iloc[start_index: end_index + 1].reset_index(drop=True)
    swings = detect_swings(sub, timeframe=timeframe)
    return len(swings)


def classify_setup(
    window: InteractionWindow,
    df: pd.DataFrame,
    timeframe: str,
    config: Optional[dict] = None,
) -> Optional[SetupEvent]:
    """پیاده‌سازی دقیق درخت تصمیم‌گیری بخش ۶ سند. خروجی: SetupEvent یا
    None (یعنی این برخورد به هیچ‌کدام از پنج ستاپ حل نشد).
    """
    cfg = {**DEFAULT_SETUP_CONFIG, **(config or {})}
    tier_weight = _TIER_CONFIDENCE_WEIGHT.get(window.level_tier, 0.5)
    # طبق درخواست کاربر: اگر این سطح بخشی از یک «سطح قوی» (هم‌گرایی چند
    # لایه) باشد، وزن اهمیت با قدرت خوشه (confluence_strength، از قبل در
    # interactions.py محاسبه و سقف‌خورده) تقویت می‌شود — یک برخورد با
    # محل تلاقی مثلاً P1H و PDEQ باید از برخورد با هرکدام به‌تنهایی
    # معتبرتر باشد.
    if getattr(window, "is_confluent", False) and window.confluence_strength > 0:
        tier_weight = min(1.0, tier_weight + 0.15 * window.confluence_strength)

    # ------------------------------------------------------------------
    # مرحله ۱: آیا اصلاً شکست معنادار رخ داد؟
    # ------------------------------------------------------------------
    if window.max_penetration_atr < cfg["min_breach_atr_multiple"]:
        reversal_idx = _find_reversal_index_for_tst(window, cfg["tst_max_bars_to_reject"])
        if reversal_idx is None:
            return None  # نه شکست، نه بازگشت واضح → بدون نتیجه (unresolved_timeout از قبل ثبت شده)
        direction = _direction_from_approach(window.approach_direction, is_continuation=False)
        cleanliness = max(0.0, 1.0 - (window.max_penetration_atr / max(cfg["min_breach_atr_multiple"], 1e-9)))
        confidence = min(1.0, 0.4 + 0.3 * cleanliness + 0.3 * tier_weight)
        return SetupEvent(
            id=f"setup_{timeframe}_{window.id}", setup_type="TST", level_name=window.level_name,
            level_price=window.level_price, symbol=window.symbol, timeframe=timeframe, direction=direction,
            window_opened_at_index=window.open_index, resolved_at_index=reversal_idx, confidence=round(confidence, 3),
            evidence={"max_penetration_atr": window.max_penetration_atr, "level_tier": window.level_tier, "is_confluent": window.is_confluent, "confluent_with": window.confluent_with, "confluence_strength": window.confluence_strength},
        )

    # ------------------------------------------------------------------
    # مرحله ۲: آیا شکست پایدار بود (full breakout) یا شکست ناکام (BOF)؟
    # ------------------------------------------------------------------
    breakout_confirm_index = _find_first_sustained_breakout(
        window, cfg["full_breakout_atr_multiple"], cfg["full_breakout_confirm_bars"]
    )
    if breakout_confirm_index is None:
        fail_idx = _find_bof_failure_index(window, cfg["bof_max_bars_to_fail"])
        if fail_idx is None:
            return None  # نه پایدار شد، نه به‌وضوح شکست خورد (هنوز مبهم) → بدون نتیجه
        direction = _direction_from_approach(window.approach_direction, is_continuation=False)
        confidence = min(1.0, 0.5 + 0.2 * min(window.max_penetration_atr / max(cfg["min_breach_atr_multiple"], 1e-9), 2.0) / 2.0 + 0.3 * tier_weight)
        return SetupEvent(
            id=f"setup_{timeframe}_{window.id}", setup_type="BOF", level_name=window.level_name,
            level_price=window.level_price, symbol=window.symbol, timeframe=timeframe, direction=direction,
            window_opened_at_index=window.open_index, resolved_at_index=fail_idx, confidence=round(confidence, 3),
            evidence={"max_penetration_atr": window.max_penetration_atr, "level_tier": window.level_tier, "is_confluent": window.is_confluent, "confluent_with": window.confluent_with, "confluence_strength": window.confluence_strength},
        )

    # از این‌جا به بعد: شکست کامل تأیید شده — جهت ادامه/شکست مشخص است.
    direction = _direction_from_approach(window.approach_direction, is_continuation=True)

    # ------------------------------------------------------------------
    # مرحله ۲.۵ — BRT (بریک‌اند‌ریتست، پورت مستقل از B5/S5 موتور قدیم؛
    # طبق درخواست کاربر، خارج از تاکسونومی پنج‌تایی اصلی سند). فقط به
    # «شکست تأییدشده + ری‌تست تمیز بدون عبور معکوس قاطع» نیاز دارد — نه
    # لزوماً از‌سرگیری کامل بعدی مثل BPB/BP/CPB — پس اگر شرط سبک‌ترش
    # زودتر برآورده شود، همین‌جا حل می‌شود؛ اگر نه (نه ری‌تستی رخ داد، نه
    # قبلش عبور معکوس قاطعی افتاد که این مسیر را ببندد)، بدون هیچ
    # اولویت دستی‌ای به مرحله‌ی پولبک/از‌سرگیری زیر واگذار می‌شود — انتخاب
    # کاملاً به رفتار واقعی قیمت بستگی دارد.
    # ------------------------------------------------------------------
    retest_index = _find_break_retest_hold(window, breakout_confirm_index, cfg["retest_tolerance_atr"])
    if retest_index is not None:
        retest_pen = window.penetration_depth_atr_by_index.get(retest_index, 0.0)
        hold_quality = max(0.0, 1.0 - abs(retest_pen) / max(cfg["retest_tolerance_atr"], 1e-9))
        confidence = min(1.0, 0.55 + 0.25 * tier_weight + 0.1 * hold_quality)
        return SetupEvent(
            id=f"setup_{timeframe}_{window.id}", setup_type="BRT", level_name=window.level_name,
            level_price=window.level_price, symbol=window.symbol, timeframe=timeframe, direction=direction,
            window_opened_at_index=window.open_index, resolved_at_index=retest_index,
            confidence=round(confidence, 3),
            evidence={
                "breakout_confirm_index": breakout_confirm_index,
                "penetration_at_retest": round(retest_pen, 3),
                "hold_quality": round(hold_quality, 3),
                "level_tier": window.level_tier, "is_confluent": window.is_confluent,
                "confluent_with": window.confluent_with, "confluence_strength": window.confluence_strength,
            },
        )

    # ------------------------------------------------------------------
    # مرحله ۳: آیا پولبکی بعد از شکست تأییدشده رخ می‌دهد؟
    # ------------------------------------------------------------------
    indices_after = [i for i in sorted(window.candle_indices) if i > breakout_confirm_index]
    if not indices_after:
        return None  # شکست تأیید شد ولی داده‌ی بعدی برای دیدن پولبک نداریم

    pen_at_confirm = window.penetration_depth_atr_by_index.get(breakout_confirm_index, 0.0)

    # نکته‌ی اصلاح (مهم‌ترین مورد این بازبینی): نسخه‌ی قبلی trough را با
    # min() روی *کل* indices_after پیدا می‌کرد — یعنی کمینه‌ی سراسری در
    # تمام پنجره‌ی باقی‌مانده (تا ۲۰ کندل)، نه لزوماً کف همان پولبکِ
    # بلافاصله بعد از شکست. اگر بعد از یک پولبک کوچک و از سرگیری، قیمت
    # دیرتر و در یک رویداد جداگانه دوباره افت می‌کرد، آن افتِ دیرتر و
    # نامرتبط به‌جای کف واقعیِ همین پولبک انتخاب می‌شد — دقیقاً همان نوع
    # نگاه‌به‌آینده‌ای (non-causal) که بقیه‌ی این موتور (طبق
    # NEW_ENGINE_MIGRATION_PROGRESS.md) عمداً حذفش کرده. اصلاح: یک پیمایش
    # ترتیبی رو-به-جلو، کمینه‌ی در-حال-اجرا را دنبال می‌کند و به محض اولین
    # از سرگیریِ معتبر (resumption_min_atr) همان‌جا اولین چرخه‌ی
    # «پولبک → از سرگیری» را می‌بندد — سازگار با ماهیت state machine
    # ترتیبی‌ای که در docstring بالای فایل تأکید شده.
    trough_index = breakout_confirm_index
    trough_pen = pen_at_confirm
    resumption_index: Optional[int] = None
    for i in indices_after:
        pen = window.penetration_depth_atr_by_index.get(i, float("-inf"))
        if pen < trough_pen:
            trough_index = i
            trough_pen = pen
        elif pen >= trough_pen + cfg["resumption_min_atr"]:
            resumption_index = i
            break

    pullback_occurred = (pen_at_confirm - trough_pen) >= cfg["pullback_min_retrace_atr"]
    if not pullback_occurred:
        return None  # شکست بدون پولبک قابل‌توجه — طبق سند، خارج از دامنه‌ی این پنج ستاپ

    if resumption_index is None:
        return None  # پولبک هنوز حل نشده (می‌تواند بعداً در پنجره‌ی جدید حل شود)

    # ------------------------------------------------------------------
    # مرحله ۴: چند موج اصلاحی داشت؟ + آیا به خودِ سطح برگشت؟ + سیگنال ضعف؟
    # ------------------------------------------------------------------
    swing_count = _count_pullback_swings(df, breakout_confirm_index, trough_index, timeframe)
    pullback_reached_level = trough_pen <= 0  # یعنی واقعاً به سطح (یا فراتر) برگشته

    # نکته‌ی اصلاح: `except Exception` قبلی هر خطایی — از جمله باگ‌های
    # واقعی مثل نام ستون اشتباه یا خرابی داده‌ی ورودی — را بی‌صدا به
    # weakness_signal=False تبدیل می‌کرد و برای همیشه پنهانش می‌کرد. اینجا
    # فقط دو خطای *مورد انتظار* و بی‌خطر برای منطق کسب‌وکار را می‌گیریم:
    # IndexError (اندیس بیرون از df — مثلاً به‌خاطر breakout_confirm_index/
    # trough_index نامعتبر) و KeyError (ستون OHLC غایب). هر خطای دیگر باید
    # بالا برود، نه این‌که به‌عنوان «بدون سیگنال ضعف» قلمداد شود.
    weakness_signal = False
    try:
        breakout_candle = df.iloc[breakout_confirm_index]
        trough_candle = df.iloc[trough_index]
        breakout_geom = compute_candle_geometry(breakout_candle["open"], breakout_candle["high"],
                                                  breakout_candle["low"], breakout_candle["close"])
        trough_geom = compute_candle_geometry(trough_candle["open"], trough_candle["high"],
                                               trough_candle["low"], trough_candle["close"])
        if pd.notna(trough_geom.body_to_range_ratio) and pd.notna(breakout_geom.body_to_range_ratio):
            weakness_signal = (
                trough_geom.primitive == "doji"
                or trough_geom.body_to_range_ratio <= cfg["weakness_body_ratio_factor"] * breakout_geom.body_to_range_ratio
            )
    except (IndexError, KeyError):
        weakness_signal = False

    evidence = {
        "penetration_depth_atr": round(pen_at_confirm, 3),
        "full_breakout_confirmed": True,
        "pullback_swing_count": swing_count,
        "pullback_reached_level": pullback_reached_level,
        "weakness_signal": weakness_signal,
        "level_significance_tier": window.level_tier,
        "is_confluent": window.is_confluent,
        "confluent_with": window.confluent_with,
        "confluence_strength": window.confluence_strength,
    }

    if swing_count >= 2:
        setup_type: SetupType = "CPB"
    elif pullback_reached_level and weakness_signal:
        setup_type = "BP"
    else:
        setup_type = "BPB"

    base_conf = {"BP": 0.65, "BPB": 0.55, "CPB": 0.6}[setup_type]
    confidence = min(1.0, base_conf + 0.2 * tier_weight + (0.1 if weakness_signal else 0.0))

    return SetupEvent(
        id=f"setup_{timeframe}_{window.id}", setup_type=setup_type, level_name=window.level_name,
        level_price=window.level_price, symbol=window.symbol, timeframe=timeframe, direction=direction,
        window_opened_at_index=window.open_index, resolved_at_index=resumption_index,
        confidence=round(confidence, 3), evidence=evidence,
    )


def classify_all(
    windows: List[InteractionWindow], df: pd.DataFrame, timeframe: str, config: Optional[dict] = None,
) -> List[SetupEvent]:
    """روی همه‌ی پنجره‌های بسته‌شده اجرا می‌شود و فقط SetupEvent های واقعی
    (غیر None) را برمی‌گرداند.
    """
    events: List[SetupEvent] = []
    for w in windows:
        ev = classify_setup(w, df, timeframe, config)
        if ev is not None:
            events.append(ev)
    return events
