# Smart Bias / Anti-Overfilter V12

## هدف
کاهش بیش‌فیلتر شدن ربات در تایم‌فریم‌های 5m و 15m بدون ضعیف کردن مدیریت ریسک.

## تغییرات اصلی
- اکثریت ساده 5/10 یا 6/10 دیگر مسیر Long/Short را نمی‌بندد.
- اجماع تایم‌فریم فقط در صورت حداقل 70٪ یک‌طرفه بودن و حداقل 3 نماد اختلاف، به «Extreme Bias» تبدیل می‌شود.
- Market Bias دیگر در V2 دروازه سخت نیست؛ برای ستاپ هم‌جهت کمی امتیاز می‌دهد و برای ستاپ خلاف جهت فقط «مالیات کیفیت» و حداقل Score/RR بالاتر اعمال می‌کند.
- واچ‌لیست فقط در شرایط Macro Extreme یک‌طرفه می‌شود؛ رژیم معمولی دیگر باعث حذف کامل واچ‌لیست سمت مقابل نمی‌شود.
- حداقل Score V2 از 62 به 60 کاهش یافت؛ High Vol از 68/1.50R به 66/1.45R کاهش یافت تا چند فیلتر جزئی به‌تنهایی ربات را خاموش نکنند.
- داشبورد دوره‌ای تشخیص ورود اکنون آخرین وضعیت همه نمادهای اسکن‌شده را نمایش می‌دهد، نه فقط نمادهای فعال.
- توضیحات داخلی جهت بازار و مسیر خلاف‌جهت برای گزارش‌گیری شفاف‌تر شده‌اند.

## چیزهایی که عمداً تغییر نکردند
- Risk sizing
- SL ساختاری و ATR cap
- TP و منطق R:R اصلی
- Adaptive Liquidity
- Anti-FOMO / Active Setup
- Same Direction Guard
- Edge Proxy به‌عنوان Gate خاموش باقی مانده است.

## تست
- `py_compile` برای `strategy.py` و `bot.py` موفق بود.
- تست‌های مستقل هسته استراتژی: **86 passed, 1 skipped**.
- تست‌هایی که `bot.py` را import می‌کنند در محیط فعلی به دلیل نصب نبودن `ccxt` قابل اجرا نبودند.

## V12.1 — Entry Gate Integrity Fix

- Final V2 Score/R:R gates now respect the active user/session `min_trade_score` and `min_rr` settings instead of silently falling back to the V2 base thresholds.
- The effective threshold is the strictest of: user profile, V2 safety floor, and (when applicable) High-Volatility floor.
- No Risk Management, SL/TP, position sizing, liquidity-adaptive logic, or execution sizing was changed.

\n## V13 — Smart Entry / Opportunity Preservation\n\n- V2 candidate builders no longer hard-reject a structurally valid setup on raw score before HTF/bias evidence is applied; the final adaptive V2 gate remains authoritative.\n- 5m/15m now allow a clean trend-pullback candidate to compete with the existing liquidity-sweep candidate. This does not lower final score/RR safety floors; candidates are ranked and only the best passing candidate is selected.\n- Risk sizing, structural SL, ATR cap, TP/RR floors, Anti-FOMO, Active Setup, Adaptive Liquidity, correlation and execution logic were not relaxed.\n