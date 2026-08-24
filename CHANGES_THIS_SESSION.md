# خلاصه‌ی تغییرات این نشست

این فایل خلاصه‌ی همه‌ی فیکس‌ها و بهبودهایی‌ست که رو `bot.py` و `strategy.py` انجام شد،
به‌ترتیب زمانی، تا هنگام دیپلوی بدونی دقیقاً چی عوض شده.

## ۱. فیکس‌های رفتاری (باگ‌های واقعی)

- **گارد تمرکز ریسک هم‌جهت** — `max_same_direction_positions` +
  `same_direction_entry_cooldown_seconds`: جلوی بازشدن چند پوزیشن هم‌جهت
  همبسته (مثلاً چند Long روی آلت‌کوین‌های مختلف) رو تو یه بازه‌ی کوتاه می‌گیره.
  علتش: داده‌ی واقعی نشون داد ۷ پوزیشن Long تو ۳۰ ثانیه باز شده بودن و با هم
  ضرر دادن.

- **باگ reason تکراری / احتمال دور زدن گیت‌های کیفیت** — `build_trade_plan`
  دیگه `market_data_dict=None` رو داخلی صدا نمی‌زنه؛ context واقعی HTF از
  `scan_symbol` بهش پاس داده میشه. قبلاً این باعث می‌شد امتیاز و reason دو بار
  با اعداد متفاوت محاسبه بشه.

- **کرش `manual_signal_scan`** (قابلیت «بررسی دستی سیگنال»): پارامترهای
  اشتباه به `get_signal_with_reason` پاس داده می‌شد و خروجی `build_trade_plan`
  (یه تاپل) بدون unpack به‌عنوان plan ذخیره می‌شد که باعث کرش `.get()` می‌شد.

- **باگ تشخیص متن «پوزیشن‌ها»**: مقایسه‌ی رشته‌ی حاوی نیم‌فاصله با رشته‌ی
  بدون نیم‌فاصله همیشه شکست می‌خورد.

- **مدیریت هوشمند سمت SL** (فیچر جدید، قبلاً نصفه‌کاره بود):
  `_position_management_timeframe` حالا واقعاً از تایم‌فریم سریع‌تر
  (`POSITION_MANAGEMENT_TIMEFRAME_MAP`) استفاده می‌کنه؛ `early_loss_weakness_exit_enabled`
  پیش‌فرض `True` شد؛ آستانه‌ی ورود به چک از `-0.50R` به `-0.10R`
  (`POSITION_MANAGEMENT_MIN_LOSS_R`) کاهش پیدا کرد. **هشدار:** این یه تغییر
  رفتاری واقعیه (سرعت در برابر نویز) — بعد از دیپلوی حتماً چند روز داده جمع کن.

## ۲. زیرساخت تست خودکار (جدید)

پوشه‌ی `tests/` با ۶۵ تست pytest (۱ مورد skip به‌دلیل وابستگی به شانس داده‌ی
تصادفی، نسخه‌ی mock‌شده‌ش قطعیه):

| فایل | چی رو قفل می‌کنه |
|---|---|
| `test_risk_guards.py` | گارد هم‌جهت + throttle، دقیقاً سناریوی واقعی حادثه |
| `test_safe_size.py` | سه‌لایه‌ی سایزینگ ریسک |
| `test_strategy.py` | تشخیص ضعف روند + رگرسیون باگ reason تکراری |
| `test_weakness_exit.py` | مدیریت هوشمند SL/TP جدید |
| `test_execution.py` | پارس reason (regex شکننده)، setup_id، حد ضرر روزانه، محاسبه‌ی R:R قبل از معامله |
| `test_pnl.py` | فرمول‌های PnL، فاندینگ، realized_r |
| `test_excursions.py` | MFE/MAE (بیشترین سود/ضرر شناور) |

اجرا:
```bash
pip install -r requirements-dev.txt --break-system-packages
pytest tests/ -v
```

## ۳. توابع pure استخراج‌شده (رفکتور کوچیک، بدون تغییر رفتار)

این تیکه‌ها از وسط توابع بزرگ (`_execute_trade_unlocked`, `risk_guard`,
`close_position`, `current_paper_equity`, `set_protection`,
`_apply_profit_protection`, `_check_swing_trailing_stop`,
`_maybe_close_before_day_end`) بیرون کشیده شدن تا مستقل و قابل‌تست بشن:

- `_same_direction_guard_allows`
- `_parse_signal_reason`, `_compute_setup_id`
- `_daily_loss_limit_breached`
- `_directional_price_fraction`, `_gross_pnl_usdt`, `_paper_funding_cost_usdt`,
  `_risk_usdt_from_stop`, `_realized_r`
- `_verify_protection_prices` (تأیید ثبت واقعی SL/TP رو صرافی — safety-critical)
- `_risk_usdt_for_entry`, `_passes_min_risk_to_fee_ratio`
- `_is_order_filled`, `_capped_leverage`, `_meets_min_amount`
- `_compute_trailing_update` (تصمیم نردبان قفل سود، جدا از تماس صرافی)
- `_should_update_swing_stop` (تصمیم جابه‌جایی SL بر اساس سوینگ جدید)
- `_seconds_until_next_midnight`, `_should_close_before_day_end` (منطق بستن اجباری پایان روز)
- `_active_setup_distance_check`, `_is_daily_level_unreachable` — گارد
  انتی-FOMO/انتی-dead-bot تو استراتژی liquidity-sweep

**بدون استخراج، فقط تست:**
- `_find_recent_breakout`, `_detect_retest_continuation` — تشخیص شکست قبلی و
  تأیید پولبک/ادامه‌ی روند بعد از شکست PDH/PDL
- `_detect_adaptive_liquidity` — تشخیص sweep/reclaim یا ادامه‌ی روند روی سطوح
  انطباقی درون‌روزی (وقتی PDH/PDL خیلی دورن)
- `_adaptive_anchor_candidates`, `_adaptive_target_level` — رتبه‌بندی سطوح
  انطباقی (LONDON/NEW_YORK > ASIA/OPENING_RANGE > SWING) و انتخاب هدف سود
- `_v2_score_thresholds`, `_v2_passes_setup_gates`, `_v2_rank_key` — گیت‌های
  کیفیت/RR و منطق انتخاب بهترین ستاپ در میان چند سیگنال رقیب هم‌زمان (دقیقاً
  همون مکانیزمی که تصمیم می‌گیره کدوم سیگنال، در سناریوی تناقض QTUM، برنده بشه)

**بدون استخراج، فقط تست:**
- `strategy_trend_following`, `strategy_breakout`, `strategy_mean_reversion` —
  استراتژی‌های تایم‌فریم ۱ساعته/۴ساعته (مسیرهای رد قطعی پوشش کامل داده شدن؛
  مسیرهای BUY/SELL دقیق چون به الگوی کندل خاص وابسته‌ن با seed search بهترین‌تلاش
  تست شدن و در صورت عدم یافتن، skip می‌شن نه fail)
- `_clamp_pct` (یکی‌سازی ۶ نسخه‌ی تکراری از clamp درصد در سراسر فایل)
- `_platform_fee_amount` (کارمزد پلتفرم روی سود واقعی‌شده)
- `_live_position_metrics` (فرمول کارت نمایش پوزیشن باز: PnL/بازده%/R — دقیقاً
  همون عددهایی که تو اسکرین‌شات DASH دیدیم؛ تست با اعداد واقعی همون اسکرین‌شات
  تأیید کرد که خودِ فرمول درست بوده)
- `check_candlestick_confirmation` — تشخیص پین‌بار/engulfing/کندل قوی، زیربنای
  تأیید ورود همه‌ی استراتژی‌های legacy
- `_htf_trend_aligned` — چک هم‌راستایی روند تایم‌فریم بالاتر (EMA/DI)
- `_leader_correlation_decision` — دقیقاً همون گارد همبستگی BTC/ETH که اول کار
  گفتیم به‌خاطر lagging بودن نتونست جلوی خوشه‌ی هم‌جهت رو بگیره؛ الان منطق
  تصمیمش (جدا از fetch شبکه) کامل مستقل و تست‌دار شده

**بدون استخراج، فقط تست** (از قبل pure بودن، تست‌شون اضافه شد):
- `_has_confirmed_daily_breakout`, `_confirm_active_structure` — همون دو
  فیلتری که برای جلوگیری از تناقض سیگنال نزدیک PDH/PDL اضافه شده بودن
  (دقیقاً همون مشکلی که تو تحلیل QTUM دیدیم)
- `_compute_prev_day_levels` — محاسبه‌ی PDH/PDL که زیربنای همه‌ی ستاپ‌های
  liquidity-sweep هست؛ تست شد که با timestamp میلی‌ثانیه‌ای و ثانیه‌ای هر دو
  درست کار می‌کنه
- `_adaptive_intraday_levels` — سطوح نقدینگی درون‌روزی (ASIA/LONDON/NEW_YORK،
  Opening Range) که به‌عنوان جایگزین کم‌اولویت‌تر PDH/PDL استفاده می‌شن

هیچ‌کدوم رفتار موجود رو عوض نکردن — فقط جابه‌جا و مستقل شدن.

## ۵. تقسیم ساختاری فایل: `trading_math.py` (جدید)

مهم‌ترین قدم این نشست: تمام ۳۱ تابع pure که تا الان استخراج/تست کرده بودیم
از `bot.py` به یک فایل جدا (`trading_math.py`) منتقل شدن — یعنی برای اولین بار
`bot.py` دیگه یک فایل تک‌تکه‌ی ۴۲۰۰ خطی نیست.

- `bot.py`: از ۴۲۱۶ خط به **۳۸۹۶ خط** رسید
- `trading_math.py`: **۳۸۶ خط**، شامل ۳۱ تابع کاملاً pure (بدون تلگرام، بدون
  صرافی، بدون دیتابیس، بدون session) — همه‌شون قبلاً جدا تست شده بودن
- `bot.py` این توابع رو با `from trading_math import (...)` وارد می‌کنه؛ همه‌ی
  جاهایی که قبلاً این توابع رو صدا می‌زدن (`risk_guard`, `close_position`,
  `_execute_trade_unlocked`, و...) بدون تغییر باقی موندن — فقط تعریف تابع جابه‌جا
  شده، نه نحوه‌ی صداکردنش

**فرآیند اعتبارسنجی این تقسیم:**
1. با `ast` پایتون مرز دقیق هر تابع رو تشخیص دادم (نه با copy-paste دستی) تا
   ریسک خطای whitespace/خط جاافتاده صفر بشه
2. بعد از انتقال، دو تا وابستگی جا‌افتاده پیدا شد (`re` برای regex، `logger`
   برای لاگ خطا) و اضافه شدن — همون logger اصلی (`trader_bot`) استفاده شد تا
   لاگ‌ها تو یه جا جمع بمونن
3. کل ۲۶۹ تست بعد از تقسیم **بدون هیچ تغییری تو خود تست‌ها** دوباره اجرا شد و
   همه پاس شدن — چون تست‌ها از `bot.py` ایمپورت می‌کنن (`import bot as B`) و
   این توابع از قبل تو namespace اون فایل هستن، نیازی به تغییر تست نبود
4. زیپ نهایی از صفر extract و کامپایل و تست شد

این دقیقاً همون الگوییه که برای ادامه‌ی رفکتور (جدا کردن لایه‌ی اجرا، ریسک،
و handlers تلگرام) باید تکرار بشه: تست بنویس، تابع رو مستقل کن، بعد جابه‌جا کن.

## ۷. تست Integration واقعی (جدید — دقیقاً همون چیزی که برای رسیدن از ۸ به بالاتر لازم بود)

برخلاف همه‌ی تست‌های قبلی که یک تابع مجزا رو تست می‌کردن، این فایل
(`test_integration_trade_lifecycle.py`) مسیر واقعی یک معامله رو از تابع
`_execute_trade_unlocked` (همون تابع اصلی که خودِ ربات صدا می‌زنه، نه یه
نسخه‌ی ساده‌شده) تا `close_position` دنبال می‌کنه — یعنی برای اولین بار
تأیید می‌کنیم که تابع‌های مجزا واقعاً **به‌درستی به هم وصل شدن**.

**۵ تست، همه پاس:**
1. چرخه‌ی کامل: باز کردن پوزیشن BUY واقعی (نه mock) → افت قیمت تا SL →
   `close_position` واقعی → بررسی `pnl_usdt`/`realized_r` تو `closed_positions`
2. بلاک شدن ورود دوم روی همون نماد (از طریق مسیر واقعی اجرا، نه تست مجزا)
3. سقف هم‌جهت از طریق مسیر واقعی — تأیید می‌کنه گارد واقعاً تو `_execute_trade_unlocked`
   وصل شده، نه فقط تو تابع مجزاش درست کار می‌کنه
4. حد ضرر روزانه: بلاک ورود جدید ولی دست‌نخورده موندن پوزیشن باز
5. **ماندگاری session روی SQLite واقعی** بعد از شبیه‌سازی ری‌استارت کامل
   (`USER_SESSIONS.clear()` + `load_sessions()`) — این تست یه نکته‌ی مهم
   رو هم آشکار کرد: `get_session()` خودش مستقیم از دیتابیس نمی‌خونه، فقط
   `load_sessions()` (که موقع استارت واقعی صدا زده میشه) این کارو می‌کنه؛
   این رفتار واقعی سیستمه، نه باگ، ولی خوبه مستند بشه

تلگرام (`send_message`, `sync_bottom_keyboard`) و رندر چارت mock شدن (چون
هدف تست منطق معاملاتیه، نه فرمت پیام یا تولید تصویر)، ولی **دیتابیس واقعیه**
(یک فایل SQLite موقت) — یعنی مسیر `save_session`/`get_session`/`load_sessions`
هم واقعاً تست میشه، نه فرض گرفته میشه.

## ۹. تست Integration مسیر REAL (جدید — آخرین قدم مهم مونده)

مسیر PAPER با تست integration اول پوشش داده شده بود؛ این نوبت مسیر **REAL**
(سفارش واقعی رو صرافی) هم پوشش داده شد — با یه کلاس `FakeExchange` که دقیقاً
همون متدهایی که `bot.py` از `ccxt` صدا می‌زنه رو پیاده می‌کنه
(`create_order`, `fetch_order`, `cancel_order`, `close_position`,
`fetch_balance`, و متدهای implicit SL/TP کوینکس).

**۸ تست integration، همه پاس:**
1. پر شدن فوری سفارش + تأیید موفق SL/TP
2. پر شدن با تأخیر — تأیید می‌کنه حلقه‌ی retry واقعاً منتظر می‌مونه، نه فقط
   جواب اول رو باور می‌کنه
3. عدم پر شدن سفارش — لغو تمیز و رد کردن ورود
4. **شکست ثبت SL/TP → halt خودکار + تلاش برای بستن پوزیشن** (دقیقاً همون
   مکانیزمی که از اول کار به‌عنوان نقطه‌قوت این کد شناسایی شده بود — الان
   واقعاً با تست تأیید شد، نه فقط با خوندن کد)
5. عدم تطابق قیمت SL/TP برگشتی از صرافی با چیزی که خواسته بودیم → همون halt
6. بدترین حالت: هم SL/TP شکست بخوره هم بستن اضطراری شکست بخوره → بدون کرش،
   پیام هشدار درست ارسال بشه
7. محدود شدن اهرم به حداکثر مجاز بازار
8. رد کردن سفارش زیر حداقل حجم مجاز صرافی، **قبل از** ارسال هر سفارشی

در طول ساخت این تست‌ها، **۲ باگ واقعی تو خودِ تست پیدا و اصلاح شد** (نه تو
`bot.py`): یکی فراموشی mock کردن `fetch_balance` (که باعث می‌شد `risk_guard`
واقعی فکر کنه اتصال صرافی خرابه)، و یکی منطق fallthrough اشتباه تو mock
`fetch_order`. این خودش نشون میده ارزش این نوع تست چقدره — حتی تست نوشتن هم
جای اشتباه داره و باید با اجرای واقعی تأیید بشه.

## ۱۰. جمع کل تست‌ها: ۲۸۲ پاس، ۳ اسکیپ، در ۲۴ فایل

| فایل | تعداد |
|---|---|
| test_risk_guards.py | ۷ |
| test_safe_size.py | ۶ |
| test_strategy.py | ۵ (۱ skip) |
| test_weakness_exit.py | ۷ |
| test_execution.py | ۴۵ |
| test_pnl.py | ۱۷ |
| test_excursions.py | ۷ |
| test_trailing.py | ۲۰ |
| test_day_end.py | ۸ |
| test_fees.py | ۱۴ |
| test_edge_proxy.py | ۲۳ (شامل `_v2_edge_proxy`، `compute_swing_stop`، `detect_market_regime`، `_v2_htf_bias` با جزئیات بیشتر) |
| test_formatting.py | ۱۰ (`fmt`, `market_name`, `ccxt_symbol`) |
| test_entry_confirmation.py | ۱۱ (`_has_confirmed_daily_breakout`, `_confirm_active_structure`) |
| test_pdh_pdl.py | ۱۰ (`_compute_prev_day_levels`, `_adaptive_intraday_levels`) |
| test_active_setup_guard.py | ۹ (`_active_setup_distance_check`, `_is_daily_level_unreachable`) |
| test_retest_continuation.py | ۱۰ (`_find_recent_breakout`, `_detect_retest_continuation`) |
| test_adaptive_liquidity.py | ۷ (`_detect_adaptive_liquidity`) |
| test_adaptive_anchors.py | ۱۱ (`_adaptive_anchor_candidates`, `_adaptive_target_level`) |
| test_v2_ranking.py | ۱۰ (`_v2_score_thresholds`, `_v2_passes_setup_gates`, `_v2_rank_key`) |
| test_legacy_strategies.py | ۷ (۲ skip) (`strategy_trend_following`, `strategy_breakout`, `strategy_mean_reversion`) |
| test_leader_correlation.py | ۱۲ (`_leader_correlation_decision`) |
| test_candlestick_htf.py | ۱۲ (`check_candlestick_confirmation`, `_htf_trend_aligned`) |

## قدم بعدی (اگه خواستی ادامه بدیم)
- جدا کردن لایه‌ی handlers تلگرام (`process_command`, `handle_text`, کیبوردها)
  از `bot.py` به ماژول خودش — آخرین بخش بزرگ باقی‌مونده
- تست‌های integration برای مدیریت پوزیشن REAL باز (trailing/weakness-exit روی
  پوزیشن واقعی، نه فقط PAPER)


### Adaptive same-direction exposure
- Default same-direction cap remains active.
- When the cap is reached, exactly one additional same-direction position is allowed only for an exceptional setup: final quality score >= 80 and planned RR >= 1.60.
- A second overflow is never allowed.
- Same-direction entry cooldown remains a hard anti-burst guard.
