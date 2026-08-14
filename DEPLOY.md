# راه‌اندازی نسخه اصلاح‌شده Multi-User Trading Bot

> **نسخه فعلی برای PAPER و تست کنترل‌شده آماده‌تر شده است. REAL را فقط بعد از اجرای تست‌ها و یک معامله بسیار کوچک فعال کنید.**

## مشکل فوری که در نسخه قبلی دیده می‌شد

در Telegram، `getUpdates` بدون `offset` مصرف می‌شد؛ در نتیجه updateهای تأییدنشده دوباره برمی‌گشتند و پیام‌هایی مثل «حالت حساب را انتخاب کنید» چند بار تکرار می‌شدند. طبق مستندات رسمی Telegram، برای تأیید update باید `offset = update_id + 1` ارسال شود. نسخه جدید offset را در جدول `bot_meta` داخل SQLite ذخیره می‌کند تا بعد از restart هم ادامه پیدا کند.

## فایل‌ها

```text
bot.py
strategy.py
ui.py
requirements.txt
.env.example
DEPLOY.md
tests/test_safety.py
```

## نصب

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m unittest discover -s tests -v
python bot.py
```

## متغیرهای محیطی ضروری

```text
TELEGRAM_TOKEN=...
COINEX_ACCOUNTS_JSON=...
```

ساختار `COINEX_ACCOUNTS_JSON`:

```json
{
  "123456789": {
    "apiKey": "API_KEY_USER_A",
    "secret": "SECRET_USER_A"
  }
}
```

کلیدها را در Git، Telegram یا سورس‌کد قرار ندهید. برای Futures فقط permissionهای لازم را فعال کنید و withdrawal را غیرفعال نگه دارید.

## تنظیمات ایمنی جدید

```text
MARGIN_MODE=isolated
PROTECTION_TRIGGER=mark_price
ORDER_CONFIRM_RETRIES=4
ORDER_CONFIRM_DELAY=1.0
ENTRY_LOCK_TIMEOUT=5
PAPER_CONSERVATIVE_OHLC=true
```

`MARGIN_MODE=isolated` عمداً پیش‌فرض شده است. اگر Cross را آگاهانه می‌خواهید، آن را صریحاً در محیط تنظیم کنید.

## اصلاحات مهم

- Telegram `offset` پایدار و ضد تکرار شده است.
- ورود REAL برای هر کاربر lock دارد تا دو scanner task همزمان یک symbol را دوباره باز نکنند.
- خطای دریافت balance/positions دیگر به‌عنوان `0` یا `[]` تفسیر نمی‌شود؛ در خطای ارتباط، REAL متوقف و نیازمند reconciliation می‌شود.
- سفارش market تا زمانی که fill آن تأیید نشود ثبت‌شده فرض نمی‌شود.
- در وضعیت مبهم سفارش، retry خودکار انجام نمی‌شود تا duplicate order ایجاد نشود.
- SL/TP بعد از ثبت با پاسخ CoinEx و وضعیت position بررسی می‌شود.
- اگر protection شکست بخورد، REAL فوراً وارد safe-stop می‌شود و تلاش برای close اضطراری انجام می‌شود.
- Daily Risk از unrealized PnL پوزیشن‌های REAL نیز استفاده می‌کند.
- Paper candle که هم TP و هم SL را در یک OHLC بزند، در حالت محافظه‌کارانه SL را برنده فرض می‌کند.
- Multi-TF بر اساس timestamp کندل بسته‌شده هم‌تراز می‌شود، نه صرفاً `iloc[-2]` مستقل در هر timeframe.
- `aiohttp.ClientSession` در کل عمر scanner نگه داشته می‌شود.
- وضعیت endpoint عمومی `/status` حداقلی‌تر شده است.

## نکته مهم درباره CoinEx

CoinEx برای Futures endpointهای مستقل TP و SL دارد و در پاسخ position، قیمت‌های فعال TP/SL را برمی‌گرداند؛ نسخه جدید از همین اطلاعات برای verification استفاده می‌کند.

## قبل از REAL

1. Bot را خاموش نگه دارید.
2. Backup از `trader_bot.sqlite3` بگیرید.
3. تست‌ها را اجرا کنید.
4. با PAPER حداقل چند چرخه کامل باز/بسته‌شدن معامله را تست کنید.
5. در REAL ابتدا فقط یک symbol و margin بسیار کوچک استفاده کنید.
6. بعد از هر restart، اول reconciliation را انجام دهید و سپس اسکن را فعال کنید.
7. اگر پیام `توقف ایمنی REAL` دیدید، اسکن را دوباره روشن نکنید تا وضعیت CoinEx و پوزیشن‌ها بررسی شود.

### اگر همین الان پیام‌های تکراری در صف Telegram مانده‌اند

برای **اولین اجرای نسخه اصلاح‌شده** مقدار زیر را بگذارید:

```text
TELEGRAM_SKIP_BACKLOG=true
```

این گزینه فقط backlog فعلی را یک‌بار acknowledge می‌کند و commandهای قدیمی را اجرا نمی‌کند. بعد از اولین اجرای موفق، آن را می‌توانید `false` کنید. از این به بعد offset واقعی در SQLite ذخیره می‌شود.
