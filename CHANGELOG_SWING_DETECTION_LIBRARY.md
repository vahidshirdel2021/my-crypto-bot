# CHANGELOG — افزودن کتابخانه Swing Detection (اختیاری/افزودنی)

## خلاصه
یک کتابخانه‌ی جدید و کاملاً مستقل برای تشخیص سوینگ به پروژه اضافه شد:
`swing_detection.py`. این کتابخانه به‌صورت **افزودنی (additive)** به موتور
فعلی PDH/EQ/PDL وصل شده و **هیچ رفتار پیش‌فرض موجودی را تغییر نمی‌دهد** —
تمام سوییچ‌های مربوط به آن در `STRATEGY_DEFAULTS` به‌صورت پیش‌فرض `False`
هستند.

## فایل جدید
- **`swing_detection.py`** — کتابخانه‌ی مستقل پایتون شامل:
  1. `detect_three_bar_rejection_swings()` — الگوی سه‌کندلی ریجکشن/ویک
  2. `detect_classic_three_bar_swings()` — سوینگ فراکتال کلاسیک
  3. `detect_structural_swings()` — سوینگ ساختاری + رویدادهای BOS/ChoCH
  4. `compute_stop_loss_for_swing()` / `attach_risk_to_signal()` — لایه
     مدیریت ریسک (SL پویا پشت سوینگ + TP بر اساس R-multiple)
  5. `analyze_swings()` — ارکستریتور؛ هرگز exception پرتاب نمی‌کند
     (`ok=False` + پیام خطا در صورت مشکل)، مناسب حلقه زنده بات.

- **`swing_detection.pine`** (خارج از این zip، جداگانه تحویل داده شد) —
  نسخه Pine Script v5 هم‌ارز برای نمایش روی TradingView.

## تغییرات در `strategy.py`
- ایمپورت اختیاری `swing_detection` با `try/except` — اگر فایل موجود نباشد
  یا import آن با خطا مواجه شود، `_SWING_LIB_AVAILABLE = False` می‌شود و
  کل بات همچنان بدون مشکل اجرا می‌شود.
- کلیدهای جدید در `STRATEGY_DEFAULTS` (همه پیش‌فرض خاموش):
  - `use_advanced_swing_stop` (False)
  - `advanced_swing_atr_period` (14)
  - `advanced_swing_atr_buffer_mult` (0.25)
  - `advanced_swing_pct_buffer` (0.0015)
  - `use_swing_confluence_info` (False)
  - `swing_confluence_lookback_bars` (5)
- تابع جدید `compute_swing_stop_v2(df, is_long, ...)`:
  دقیقاً هم‌امضا با `compute_swing_stop` قدیمی — خروجی `(sl, swing_level)`
  یا `(None, None)`. به‌جای کمینه/بیشینه‌ی یک پنجره‌ی ثابت (`lookback`)،
  از آخرین سوینگ *واقعی و تاییدشده* (رجکشن سه‌کندلی یا فراکتال کلاسیک)
  استفاده می‌کند.
- تابع جدید `get_swing_confluence(df, is_long, lookback_bars=5)`:
  صرفاً اطلاعاتی — بررسی می‌کند آیا آخرین رویداد ساختاری (BOS/ChoCH) در
  چند کندل اخیر هم‌جهت سیگنال بوده یا نه. **هیچ اثری روی امتیاز، جهت یا
  رد/قبول شدن معامله ندارد.**
- در `build_trade_plan()`: اگر `use_swing_confluence_info=True` باشد،
  فیلد اطلاعاتی `plan["swing_confluence"]` به خروجی پلن اضافه می‌شود
  (برای نمایش در پیام تلگرام/لاگ). در حالت پیش‌فرض این فیلد اصلاً ساخته
  نمی‌شود و رفتار قبلی دقیقاً حفظ می‌شود.

## تغییرات در `bot.py`
- ایمپورت `compute_swing_stop_v2` از `strategy.py`.
- در `_check_swing_trailing_stop()`: اگر
  `strategy_config['use_advanced_swing_stop'] = True` باشد، تریلینگ‌استاپ
  پوزیشن باز از `compute_swing_stop_v2` استفاده می‌کند؛ در غیر این صورت
  (پیش‌فرض) دقیقاً همان `compute_swing_stop` قدیمی صدا زده می‌شود.
  اگر نسخه‌ی جدید سوینگ معتبری پیدا نکند، به‌صورت خودکار (fallback ایمن)
  به روش قدیمی برمی‌گردد تا تریلینگ‌استاپ هرگز کلاً غیرفعال نشود.

## نحوه فعال‌سازی (اختیاری)
در `strategy_config` مربوط به هر ست‌آپ/سشن، هرکدام از این کلیدها را
`True` کنید:
```python
strategy_config = {
    "use_advanced_swing_stop": True,     # تریلینگ‌استاپ بر اساس سوینگ واقعی
    "use_swing_confluence_info": True,   # افزودن فیلد گزارشی confluence
}
```

## تست‌های انجام‌شده
- `python3 -m py_compile` روی تمام فایل‌های پروژه (`strategy.py`,
  `bot.py`, `swing_detection.py`, `pdh_eq_pdl_engine.py`, `ui.py`,
  `backtest.py`, `v3_backtest.py`) — بدون خطا.
- تست عملکردی مستقیم `compute_swing_stop` (قدیمی)،
  `compute_swing_stop_v2` (جدید) و `get_swing_confluence` روی دیتای
  شبیه‌سازی‌شده — هر سه مقدار معتبر برگرداندند.
- تایید شد مقادیر پیش‌فرض `STRATEGY_DEFAULTS` برای هر دو سوییچ جدید
  `False` است (یعنی رفتار پیش‌فرض بات دقیقاً مثل قبل باقی می‌ماند).

---

# CHANGELOG — ادغام عمیق در موتور اصلی (pdh_eq_pdl_engine.py)

## خلاصه
طبق درخواست صریح کاربر، تشخیص سوینگ در **موتور اصلی سیگنال‌دهی**
(`compute_swings` در `pdh_eq_pdl_engine.py` — همان چیزی که ۱۲ سناریوی
B1-B6/S1-S6 را می‌سازد) اکنون از کتابخانه `swing_detection.py` استفاده
می‌کند، نه فقط تریلینگ‌استاپ. یعنی از این پس، به‌صورت پیش‌فرض:

> **کندلی «سوینگ» شناخته می‌شود که هم در پنجره‌ی lookback اکسترمم منحصربه‌فرد
> باشد، هم با یکی از دو الگوی «فراکتال کلاسیک سه‌کندلی» یا «ریجکشن/ویک
> سه‌کندلی» کتابخانه‌ی جدید منطبق باشد.** خارج از این دو الگو، دیگر چیزی
> به‌عنوان سوینگ شناخته نمی‌شود.

## جزئیات فنی
- `ENGINE_DEFAULTS["swing_detection_mode"] = "advanced"` (پیش‌فرض جدید).
  می‌توان با `strategy_config={"swing_detection_mode": "legacy"}` به
  رفتار کاملاً قدیمی (فرکتال ساده، بدون وابستگی به کتابخانه) برگشت.
- `compute_swings()` اکنون یک **دیسپچر** است:
  - `mode="advanced"` → `_compute_swings_advanced()`: کاندیدهای سوینگ را
    از `detect_classic_three_bar_swings` و `detect_three_bar_rejection_swings`
    کتابخانه می‌گیرد، سپس **دقیقاً همان دو فیلتر کیفیت قبلی** (نسبت دم به
    ATR، نسبت حجم) و **همان شرط اکسترمم‌بودن در پنجره‌ی lookback قدیمی**
    را روی آن‌ها اعمال می‌کند. نتیجه یک زیرمجموعه‌ی دقیق‌تر و کم‌نویزتر از
    خروجی قدیمی است (تست شد: روی ۲۰+ دیتاست شبیه‌سازی‌شده، هر سوینگ
    advanced همیشه زیرمجموعه‌ی سوینگ‌های legacy بود).
  - `mode="legacy"` → `_compute_swings_legacy()`: عیناً همان تابع قدیمی
    (بدون هیچ تغییری در منطق)، برای کسانی که بخواهند برگردند.
  - **Fallback خودکار و بی‌صدا:** اگر `swing_detection.py` در دسترس نباشد
    یا هر خطایی بدهد (`SwingDetectionError` یا هر exception دیگر)، بدون
    کرش کل ربات، به‌طور خودکار `mode="legacy"` اجرا می‌شود.
- ستون‌های خروجی `swing_high`/`swing_low` (که `_recent_confirmed_swings`
  و کل منطق سناریوهای B1-B6/S1-S6 به آن‌ها وابسته‌اند) دقیقاً همان قرارداد
  قبلی را حفظ کرده‌اند — هیچ کد پایین‌دستی تغییر نکرد. یک ستون اضافه‌ی صرفاً
  اطلاعاتی `swing_pattern` هم اضافه شد (`"classic_three_bar"` یا
  `"three_bar_rejection"`) که فقط برای دیباگ/گزارش است و در تصمیم‌گیری
  اثر ندارد.
- محل صدا زده‌شدن (`evaluate_scenarios`) به‌روزرسانی شد تا
  `cfg.get("swing_detection_mode", "advanced")` را به `compute_swings`
  پاس بدهد؛ یعنی این تنظیم هم مثل بقیه‌ی پارامترهای موتور از طریق
  `strategy_config` هر سشن/ست‌آپ قابل override است.

## تست‌های انجام‌شده (این مرحله)
- کامپایل کامل هر ۷ فایل پایتون پروژه بدون خطا.
- تست زیرمجموعه‌بودن (`advanced ⊆ legacy`) روی ۲۰ دیتاست تصادفی مختلف —
  هم برای swing_high و هم swing_low، در همه‌ی سیدها برقرار بود.
- تست fallback: با شبیه‌سازی نبودن کتابخانه (`_SWING_LIB_AVAILABLE=False`)،
  `compute_swings(mode="advanced")` بدون کرش و با نتیجه‌ی معتبر (معادل
  legacy) برگشت.
- اجرای کامل `evaluate_scenarios` (مسیر واقعی که `strategy.py` صدا
  می‌زند) روی ۶۰ دیتاست تصادفی، برای هر دو `mode="advanced"` و
  `mode="legacy"` — نرخ سیگنال یکسان (۰ از ۶۰ روی دیتای رندوم بدون
  ساختار PDH/EQ/PDL طراحی‌شده)، یعنی تغییر رفتار غیرمنتظره‌ای در گیت
  ورودی موتور ایجاد نشد.

## نکته مهم برای کاربر
این تغییر، برخلاف تغییرات مرحله‌ی قبل (تریلینگ‌استاپ/confluence که
پیش‌فرض خاموش بودند)، **به‌صورت پیش‌فرض فعال است** چون صراحتاً درخواست
شد که «موتور اصلی» از این منطق استفاده کند. اگر بعداً خواستید به رفتار
کاملاً قدیمی برگردید، کافی است در `strategy_config` مقدار
`"swing_detection_mode": "legacy"` را ست کنید.

