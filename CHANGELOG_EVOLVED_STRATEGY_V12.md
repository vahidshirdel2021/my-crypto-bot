# V12 — Evolved Strategy Logic

این نسخه منطق فعلی را به نسخه تکامل‌یافته نزدیک می‌کند:

- 1h/4h از استراتژی اختصاصی `HTF Liquidity Reversal` استفاده می‌کنند و فقط نقدینگی تکمیل‌شده هفتگی/ماهانه را بررسی می‌کنند.
- Regime Confidence دیگر قفل سخت ورود نیست و صرفاً diagnostic است.
- خلاف‌جهت BULLISH/BEARISH به‌جای veto به score tax تبدیل شده است.
- Premium/Discount بر اساس midpoint روز قبل (PDH/PDL) در امتیاز ستاپ اعمال می‌شود.
- در 5m/15m سه خانواده با هم رقابت می‌کنند: Liquidity Sweep، Trend Pullback با پنجره ۳ کندلی EMA20، و Breakout Retest.
- Active Setup قبل از بازیابی نیازمند شکست واقعی PDH/PDL و تأیید micro-structure است و سپس Pullback/Reclaim جدید را می‌خواهد.
- مدیریت ضعف پوزیشن به تایم‌فریم سریع‌تر منتقل شد: 5m→1m، 15m→5m، 1h→15m، 4h→1h.
- Early Loss Weakness Exit به‌صورت پیش‌فرض فعال شد و از `-0.10R` با تأیید ضعف روند شروع می‌شود.
- آستانه‌های V2 به `60 / 66 / 1.45R` برای حالت عادی/High-Vol برگشتند.
- برای 1h/4h تاریخچه بیشتری در اسکن دریافت می‌شود تا سطح ماهانه قبلی واقعاً قابل محاسبه باشد.
- تست‌های واحد برای منطق HTF، equilibrium، active setup و thresholdها اضافه شد.

## اعتبارسنجی

- `py_compile` برای تمام فایل‌های Python موفق بود.
- `pytest tests/test_strategy_v2.py` با 5 تست موفق اجرا شد.
- `v3_backtest.py --help` و `backtest.py --help` بدون خطا اجرا شدند.
