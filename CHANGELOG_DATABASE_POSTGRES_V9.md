# V9 — انتخاب خودکار SQLite / PostgreSQL (Neon)

- رفتار پیش‌فرض قبلی حفظ شده است: اگر URL دیتابیس تنظیم نشود، ربات از SQLite استفاده می‌کند.
- اگر `DATABASE_URL` یا `NEON_DATABASE_URL` یا `POSTGRES_URL` با `postgres://` یا `postgresql://` تنظیم شود، ربات به‌صورت خودکار PostgreSQL را انتخاب می‌کند.
- برای اتصال PostgreSQL در صورت نبود `sslmode`، `sslmode=require` به URL اضافه می‌شود؛ بنابراین Connection String معمول Neon مستقیم قابل استفاده است.
- تمام جدول‌های فعلی (`sessions`, `bot_meta`, `fee_ledger`, `user_fee_settings`, `users`) روی PostgreSQL نیز ایجاد می‌شوند.
- منطق سشن، کارمزد، رجیستری کاربران، پوزیشن‌ها و سایر بخش‌های ربات تغییر نکرده است؛ فقط لایه اتصال دیتابیس دوحالته شده است.
- SQLite محلی و فایل `BOT_DB_PATH` همچنان به‌عنوان fallback باقی مانده‌اند.
- این نسخه مهاجرت خودکار داده‌های SQLite قدیمی به PostgreSQL انجام نمی‌دهد؛ برای جلوگیری از کپی ناخواسته/دوباره‌کاری. اگر لازم باشد، مهاجرت یک‌باره را جداگانه می‌توان انجام داد.

# V10 — ماندگاری واقعی و مهاجرت خودکار SQLite → Neon

- اگر `DATABASE_URL`/`NEON_DATABASE_URL`/`POSTGRES_URL` تنظیم باشد، دیتابیس اصلی PostgreSQL/Neon است.
- در اولین اجرای PostgreSQL، اگر فایل SQLite قدیمی در `LEGACY_SQLITE_PATH` (یا `BOT_DB_PATH`) وجود داشته باشد، مهاجرت یک‌باره و idempotent انجام می‌شود.
- جدول `sessions` شامل پوزیشن‌های باز، تاریخچه پوزیشن‌های بسته، گزارش‌ها و Audit است؛ بنابراین همین داده‌ها نیز مهاجرت می‌شوند.
- `fee_ledger`، تنظیم کارمزد کاربران، رجیستری کاربران و `bot_meta` نیز مهاجرت می‌شوند.
- داده موجود در PostgreSQL که جدیدتر از SQLite باشد روی PostgreSQL باقی می‌ماند؛ داده قدیمی‌تر SQLite آن را overwrite نمی‌کند.
- بعد از مهاجرت، sequence مربوط به `fee_ledger.id` هم هماهنگ می‌شود.
- با marker `sqlite_migration_v1` مهاجرت دوباره انجام نمی‌شود.
- اگر SQLite قدیمی دیگر روی Render موجود نباشد، هیچ کدی نمی‌تواند داده‌ای را که دیگر در دسترس نیست بازیابی کند؛ در این حالت باید فایل SQLite قدیمی را در مسیر `LEGACY_SQLITE_PATH` قرار داد یا یک backup آن را فراهم کرد.
