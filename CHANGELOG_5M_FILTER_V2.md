# 5m Filter V2

این تغییرات فقط روی تایم‌فریم `5min` اعمال شده‌اند و منطق `15min`، `1hour` و `4hour` دست‌نخورده باقی مانده است.

## Entry filter
- `breakout_retest` در 5m موقتاً غیرفعال شد.
- در رژیم `RANGE` فقط `liquidity_sweep` اجازه ورود دارد.
- برای 5m، HTF باید معنی‌دار و غیر افراطی باشد (`abs(HTF)` حدود 0.15 تا 0.85).
- RANGE liquidity sweep نیازمند سطح ساختاری معتبر + حجم حداقل 1.5x + body حداقل 0.70 است.
- `trend_pullback` حفظ شد، اما حداقل score اختصاصی 5m برابر 64 است.
- EdgeProxy همچنان فقط diagnostic است و به عنوان hard gate استفاده نمی‌شود.

## Position management
- فقط در 5m: با رسیدن MFE به +0.50R، حد ضرر تا Break-even محافظت می‌شود.
- فقط در 5m: با رسیدن MFE به +1.00R، حداقل +0.30R قفل می‌شود.
- فقط در 5m، early-loss weakness exit سخت‌گیرانه‌تر شده تا نزدیک ورود معامله را زود نبندد.
- سایر تایم‌فریم‌ها از ladder و weakness-exit قبلی خود استفاده می‌کنند.

## Validation
- `py_compile`: موفق
- تست‌های strategy/context/risk: 6 passed
