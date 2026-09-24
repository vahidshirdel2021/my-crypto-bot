#!/usr/bin/env python3
"""
تست سریع منابع داده (بدون API key، بدون import کردن bot.py).
اجرا روی همان سروری که ربات روی آن بالا می‌آید:

    python check_market_data.py            # BTC و SOL
    python check_market_data.py ETH XRP    # نمادهای دلخواه

برای هر منبع (Binance Futures / Bybit / KuCoin Futures) وضعیت HTTP، تعداد کندل، ۳ کندل آخر
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


def binance(base):
    r = requests.get("https://fapi.binance.com/fapi/v1/klines",
                     params={"symbol": f"{base}USDT", "interval": "5m", "limit": 650}, timeout=TIMEOUT)
    return r.status_code, (_df(r.json()) if r.ok and isinstance(r.json(), list) else None), r.text[:120]


def bybit(base):
    r = requests.get("https://api.bybit.com/v5/market/kline",
                     params={"category": "linear", "symbol": f"{base}USDT", "interval": "5", "limit": 650}, timeout=TIMEOUT)
    j = r.json() if r.ok else {}
    rows = (j.get("result") or {}).get("list") or []
    return r.status_code, (_df(rows) if j.get("retCode") == 0 and rows else None), r.text[:120]


def kucoin(base):
    sym = ("XBT" if base == "BTC" else base) + "USDTM"
    now = int(time.time() * 1000)
    r = requests.get("https://api-futures.kucoin.com/api/v1/kline/query",
                     params={"symbol": sym, "granularity": 5, "from": now - 500 * 300000, "to": now}, timeout=TIMEOUT)
    j = r.json() if r.ok else {}
    rows = j.get("data") or []
    return r.status_code, (_df(rows) if j.get("code") == "200000" and rows else None), r.text[:120]


def main(symbols):
    for base in symbols:
        print(f"\n===== {base} =====")
        for name, fn in (("binance", binance), ("bybit", bybit), ("kucoin", kucoin)):
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
