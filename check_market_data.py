#!/usr/bin/env python3
"""
تست سریع منابع داده (بدون API key، بدون import کردن bot.py).
اجرا روی همان سروری که ربات روی آن بالا می‌آید:

    python check_market_data.py            # BTC و SOL
    python check_market_data.py ETH XRP    # نمادهای دلخواه

برای هر منبع (Bitunix فیوچرز / Binance اسپات / آینه‌ی Binance Vision) وضعیت HTTP، تعداد کندل، ۳ کندل آخر
و مقدار ATRx (نسبت ATR کندل آخرِ بسته‌شده به میانه‌ی ATRهای قبل؛ در حالت سالم حدود ۱ است) را چاپ می‌کند.
"""
import sys
import time

import pandas as pd
import requests

from strategy import calculate_indicators, detect_market_regime

TIMEOUT = 10


def _df(rows):
    df = pd.DataFrame([r[:6] for r in rows], columns=["timestamp", "open", "high", "low", "close", "volume"])
    for c in df.columns:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)


def binance(base, host="https://api.binance.com"):
    r = requests.get(f"{host}/api/v3/klines",
                     params={"symbol": f"{base}USDT", "interval": "5m", "limit": 650}, timeout=TIMEOUT)
    j = r.json() if r.ok else None
    return r.status_code, (_df(j) if isinstance(j, list) and j else None), r.text[:120]


def binance_vision(base):
    return binance(base, "https://data-api.binance.vision")


def bitunix(base):
    """Bitunix Futures: فقط کندل‌های بسته؛ حداکثر ۲۰۰ کندل در هر درخواست (ربات کندل در حال تشکیل را خودش اضافه می‌کند)."""
    r = requests.get("https://fapi.bitunix.com/api/v1/futures/market/kline",
                     params={"symbol": f"{base}USDT", "interval": "5m", "limit": 200}, timeout=TIMEOUT)
    j = r.json() if r.ok else {}
    rows = [[k.get("time"), k.get("open"), k.get("high"), k.get("low"), k.get("close"), k.get("baseVol")]
            for k in (j.get("data") or []) if isinstance(k, dict)]
    return r.status_code, (_df(rows) if j.get("code") == 0 and rows else None), r.text[:120]


def main(symbols):
    for base in symbols:
        print(f"\n===== {base} =====")
        for name, fn in (("bitunix-futures", bitunix), ("binance-spot", binance), ("binance-vision", binance_vision)):
            try:
                status, df, body = fn(base)
            except Exception as exc:
                print(f"[{name}] خطای شبکه: {exc}")
                continue
            if df is None or df.empty:
                hint = " (احتمالاً بلاک جغرافیایی/محدودیت IP)" if status in (403, 451) else ""
                print(f"[{name}] HTTP {status}{hint} - داده‌ی معتبر نیامد: {body}")
                continue
            ind = calculate_indicators(df)
            reg = detect_market_regime(ind, None)
            print(f"[{name}] HTTP {status} | {len(df)} کندل | ATRx={reg['atr_ratio']:.2f} | regime={reg['name']} | atr[-2]={ind.iloc[-2]['atr']:.6g}")
            print(df.tail(3).to_string(index=False))


if __name__ == "__main__":
    main([s.upper() for s in sys.argv[1:]] or ["BTC", "SOL"])
