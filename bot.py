def get_crypto_klines(coin_symbol, aggregate=1, limit=400):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    
    # ۱. تلاش اول: CryptoCompare
    url = "https://min-api.cryptocompare.com/data/v2/histohour"
    params = {"fsym": coin_symbol, "tsym": "USDT", "limit": limit, "aggregate": aggregate}
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, params=params, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("Response") == "Success" and data.get("Data", {}).get("Data"):
                df = pd.DataFrame(data["Data"]["Data"])
                df = df.rename(columns={'time': 'timestamp', 'volumefrom': 'volume'})
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                if not df.empty and len(df) > 50:
                    return df
    except Exception as e:
        print(f"⚠️ CryptoCompare Error ({coin_symbol}): {e}")

    # ۲. تلاش دوم (پشتیبان): CoinEx API
    try:
        coinex_market = f"{coin_symbol}USDT"
        interval = "1hour" if aggregate == 1 else "4hour"
        url_coinex = f"https://api.coinex.com/v2/spot/market/kline?market={coinex_market}&interval={interval}&limit={limit}"
        res = requests.get(url_coinex, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == 0 and data.get("data"):
                raw_data = data["data"]
                # فرمت داده CoinEx: [created_at, open, close, high, low, volume, amount]
                df = pd.DataFrame(raw_data)
                df = df.rename(columns={
                    'created_at': 'timestamp',
                    'open': 'open',
                    'close': 'close',
                    'high': 'high',
                    'low': 'low',
                    'volume': 'volume'
                })
                for col in ['open', 'high', 'low', 'close', 'volume']:
                    df[col] = df[col].astype(float)
                if not df.empty and len(df) > 50:
                    return df
    except Exception as e:
        print(f"⚠️ CoinEx API Error ({coin_symbol}): {e}")

    return pd.DataFrame()
