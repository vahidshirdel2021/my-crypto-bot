import os
import subprocess
import sys

# لیست ۳۰ ارز برتر بازار فیوچرز
TOP_SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT",
    "XRP/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT", "DOGE/USDT:USDT",
    "DOT/USDT:USDT", "NEAR/USDT:USDT", "LINK/USDT:USDT", "MATIC/USDT:USDT",
    "UNI/USDT:USDT", "ATOM/USDT:USDT", "LTC/USDT:USDT", "ETC/USDT:USDT",
    "ICP/USDT:USDT", "APT/USDT:USDT", "RENDER/USDT:USDT", "INJ/USDT:USDT",
    "TAO/USDT:USDT", "AR/USDT:USDT", "FET/USDT:USDT", "OP/USDT:USDT",
    "ARB/USDT:USDT", "SUI/USDT:USDT", "SEI/USDT:USDT", "TIA/USDT:USDT",
    "FTM/USDT:USDT", "IMX/USDT:USDT"
]

TIMEFRAME = "5m"
START_DATE = "2026-06-01"
END_DATE = "2026-08-29"

python_executable = sys.executable  # استفاده از پایتونِ محیط مجازی فعال

print(f"--- شروع بک‌تست گروهی روی {len(TOP_SYMBOLS)} نماد بازار ---")

for symbol in TOP_SYMBOLS:
    print(f"\nدر حال پردازش نماد: {symbol}")
    
    # ۱. اجرای نسخه قدیمی (Legacy)
    cmd_legacy = [
        python_executable, "backtest.py",
        "--symbol", symbol,
        "--timeframe", TIMEFRAME,
        "--start", START_DATE,
        "--end", END_DATE,
        "--strategy", "dynamic",
        "--side", "both",
        "--legacy",
        "--csv", f"logs_{symbol.replace('/', '_').replace(':', '_')}_legacy.csv"
    ]
    
    # ۲. اجرای نسخه جدید (با فیلترها)
    cmd_new = [
        python_executable, "backtest.py",
        "--symbol", symbol,
        "--timeframe", TIMEFRAME,
        "--start", START_DATE,
        "--end", END_DATE,
        "--strategy", "dynamic",
        "--side", "both",
        "--csv", f"logs_{symbol.replace('/', '_').replace(':', '_')}_new.csv"
    ]
    
    try:
        # اجرای لگیوسی (با تایم‌اوت ۶۰۰ ثانیه برای جلوگیری از خطای قطعی)
        res_legacy = subprocess.run(cmd_legacy, capture_output=True, text=True, timeout=600)
        # اجرای جدید
        res_new = subprocess.run(cmd_new, capture_output=True, text=True, timeout=600)
        
        print(f"[{symbol}] با موفقیت تست شد.")
    except subprocess.TimeoutExpired:
        print(f"[خطا] زمان پردازش نماد {symbol} طولانی شد و متوقف گردید (Timeout).")
    except Exception as e:
        print(f"خطا در پردازش {symbol}: {e}")

print("\n--- بک‌تست گروهی به پایان رسید! فایل‌های CSV نتایج ذخیره شدند. ---")
