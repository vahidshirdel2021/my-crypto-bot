# راه‌اندازی نسخه Multi-User

## فایل‌ها

```text
bot.py
strategy.py
ui.py
requirements.txt
.env.example
```

`bot.py` فایل اجرایی اصلی است.

## نصب

```bash
pip install -r requirements.txt
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
  },
  "987654321": {
    "apiKey": "API_KEY_USER_B",
    "secret": "SECRET_USER_B"
  }
}
```

هر کاربر باید API Key و Secret حساب CoinEx خودش را داشته باشد. کلیدها را فقط با مجوزهای لازم برای Futures ایجاد کنید و در Git/Telegram/کد هاردکد نکنید.

## Multi-User

هر `chat_id` Session جدا دارد:

- تنظیمات استراتژی جدا
- فیلترها جدا
- واچ‌لیست جدا
- موجودی PAPER جدا
- پوزیشن‌های PAPER جدا
- وضعیت Daily Loss جدا
- API Client CoinEx جدا

در حالت REAL کاربر فقط به حسابی دسترسی دارد که همان `chat_id` در `COINEX_ACCOUNTS_JSON` برایش تعریف شده است.

## نکته مهم درباره Restart

بعد از Restart، اسکن خودکار خاموش می‌ماند. برای حساب REAL ابتدا وضعیت پوزیشن‌های CoinEx بررسی و reconcile می‌شود و سپس کاربر می‌تواند اسکن را فعال کند.

## قبل از REAL

ابتدا با PAPER تست کنید. سپس API Key کاربر را اضافه کنید، موجودی و پوزیشن‌های CoinEx را بررسی کنید و با حجم بسیار کم اولین معامله REAL را انجام دهید.


## V19 AI

این نسخه علاوه بر منوی اصلی، یک دکمه جمع‌وجور `☰ منو` در پایین چت نگه می‌دارد و منوی بزرگ ثابت قبلی را حذف می‌کند. دکمه‌های منوی اصلی به‌صورت Inline باز می‌شوند.

متغیرهای AI:

```text
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash
AI_TIMEOUT_SECONDS=35
AI_RETRIES=3
OPENAI_API_KEY=...   # اختیاری
OPENAI_MODEL=gpt-4.1-mini
```

اگر Gemini با 503/429/5xx یا timeout مواجه شود، درخواست با backoff دوباره تلاش می‌شود و خطای AI باعث توقف اسکن نمی‌شود.

نکته: Telegram Bot API اجازه قرار دادن یک آیکون سفارشی «داخل خود فیلد تایپ متن» را نمی‌دهد؛ نزدیک‌ترین و پایدارترین حالت، همان دکمه تک‌خطی `☰ منو` به‌عنوان Reply Keyboard است.
