# Paper V3 — Real Bot + Adaptive Strategy V2 + Professional Backtest

این Build از کد واقعی فروشنده ساخته شده و هسته اجرای PAPER آن حفظ شده است.

## تغییرات اصلی
1. `strategy.py` با Strategy V2 جایگزین شده است.
2. تشخیص Regime و انتخاب Setup تطبیقی فعال است.
3. برای dynamic، سیگنال و Trade Plan از یک engine واحد می‌آیند.
4. BTC/ETH market guard و risk engine اصلی حفظ شده‌اند.
5. Paper execution به‌صورت محافظه‌کارانه Slippage مدل می‌کند.
6. Paper PnL فاندینگ قابل تنظیم را نیز کسر می‌کند.
7. این Build با `PAPER_ONLY=true` به‌صورت پیش‌فرض قفل است و تغییر به REAL را اجازه نمی‌دهد.
8. Universe پیش‌فرض Paper روی 30 نماد نسبتاً نقدشونده محدود شده؛ با `PAPER_SYMBOLS` قابل تغییر است.
9. `v3_backtest.py` برای Walk-Forward، OOS، MAE/MFE، PF، Expectancy، Sharpe/Sortino و تحلیل Regime/Setup همراه پروژه است.

## پیشنهاد تست 30 روزه
- PAPER_ONLY=true
- ریسک هر معامله: 0.5%
- Max open positions: 3
- Slippage: 2 bps
- Funding فرضی: 0.01% در هر 8 ساعت
- بدون تغییر دستی پارامترها در طول ماه
- همه معاملات و دلایل ورود/خروج را نگه دارید.

این تست برای سنجش Robustness است، نه تضمین سود آینده.
