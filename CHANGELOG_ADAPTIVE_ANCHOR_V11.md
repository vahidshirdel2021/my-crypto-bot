# Adaptive Intraday Anchor V11

## هدف
رفع بن‌بست 5m/15m وقتی قیمت از PDH/PDL روز قبل فاصله زیادی می‌گیرد، بدون باز کردن درِ سیگنال‌های فیک یا Chase.

## تغییرات
- PDH/PDL همچنان مرجع Tier 1 و اولویت اصلی است.
- وقتی نزدیک‌ترین سطح روز قبل حداقل `adaptive_activation_distance_atr` از قیمت فاصله داشته باشد، موتور به‌صورت کنترل‌شده وارد Adaptive mode می‌شود.
- Tier 2: سقف/کف سشن‌های Asia، London و New York.
- Opening Range نیم‌ساعته به‌عنوان سطح ثابت درون‌روزی.
- Tier 3: آخرین Swing High/Low تأییدشده؛ بدون استفاده از کندل آینده.
- فقط یک Anchor نزدیک و معنادار وارد رقابت می‌شود؛ هر نوسان کوچک Level محسوب نمی‌شود.
- Adaptive Sweep فقط با نفوذ حداقل ATR، Reclaim، کندل معکوس قوی و حجم بالاتر از نرمال فعال می‌شود.
- Adaptive Continuation فقط با Breakout Acceptance کندل قبل + Retest/hold کندل فعلی + ADX/حجم/بدنه مناسب فعال می‌شود.
- در Adaptive Sweep، هدف تا حد امکان روی نزدیک‌ترین liquidity مخالف قرار می‌گیرد؛ در غیر این صورت TP محافظه‌کارانه باقی می‌ماند.
- Active Setup قبلی بزرگ‌تر نشده و محدودیت ضد-FOMO حفظ شده است.
- V2 همچنان score/RR/edge/regime filters را روی خروجی اعمال می‌کند.

## پارامترهای کلیدی
- `adaptive_activation_distance_atr = 1.00`
- `adaptive_max_anchor_distance_atr = 1.60`
- `adaptive_min_anchor_distance_atr = 0.20`
- `adaptive_sweep_min_distance_atr = 0.15`
- `adaptive_retest_tolerance_atr = 0.22`
- `adaptive_min_volume_ratio = 1.12`
- `adaptive_min_body_ratio = 0.50`
- `adaptive_trend_adx = 23`

این نسخه برای «بیشتر سیگنال دادن» طراحی نشده؛ هدف آن تبدیل روزهای مرده به فرصت‌های محدود و باکیفیت، بدون Chase است.
