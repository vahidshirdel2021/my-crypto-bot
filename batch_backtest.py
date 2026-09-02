import os
import subprocess
import sys

TOP_SYMBOLS = [
    "BTC/USDT:USDT", "ETH/USDT:USDT", "SOL/USDT:USDT", "BNB/USDT:USDT",
    "XRP/USDT:USDT", "ADA/USDT:USDT", "AVAX/USDT:USDT", "DOGE/USDT:USDT",
    "DOT/USDT:USDT", "NEAR/USDT:USDT", "LINK/USDT:USDT",
    "UNI/USDT:USDT", "ATOM/USDT:USDT", "LTC/USDT:USDT", "ETC/USDT:USDT",
    "ICP/USDT:USDT", "APT/USDT:USDT", "RENDER/USDT:USDT", "INJ/USDT:USDT",
    "TAO/USDT:USDT", "AR/USDT:USDT", "FET/USDT:USDT", "OP/USDT:USDT",
    "ARB/USDT:USDT", "SUI/USDT:USDT", "SEI/USDT:USDT", "TIA/USDT:USDT",
    "FTM/USDT:USDT", "IMX/USDT:USDT"
]

# You can change this to "5m" or "15m" whenever needed
TIMEFRAME = "15m" 
START_DATE = "2026-06-01"
END_DATE = "2026-08-29"
INITIAL_CAPITAL = 500.0

python_executable = sys.executable

print(f"--- Starting Batch Backtest | Timeframe: {TIMEFRAME} | Capital: ${INITIAL_CAPITAL} ---")

for symbol in TOP_SYMBOLS:
    print(f"\nProcessing symbol: {symbol}")
    clean_sym = symbol.replace('/', '_').replace(':', '_')
    
    # 1. Run Legacy version with timeframe in filename
    cmd_legacy = [
        python_executable, "backtest.py",
        "--symbol", symbol,
        "--timeframe", TIMEFRAME,
        "--start", START_DATE,
        "--end", END_DATE,
        "--strategy", "dynamic",
        "--side", "both",
        "--capital", str(INITIAL_CAPITAL),
        "--legacy",
        "--csv", f"logs_{clean_sym}_{TIMEFRAME}_legacy.csv"
    ]
    
    # 2. Run New version with timeframe in filename
    cmd_new = [
        python_executable, "backtest.py",
        "--symbol", symbol,
        "--timeframe", TIMEFRAME,
        "--start", START_DATE,
        "--end", END_DATE,
        "--strategy", "dynamic",
        "--side", "both",
        "--capital", str(INITIAL_CAPITAL),
        "--csv", f"logs_{clean_sym}_{TIMEFRAME}_new.csv"
    ]
    
    try:
        subprocess.run(cmd_legacy, capture_output=True, text=True, timeout=600)
        subprocess.run(cmd_new, capture_output=True, text=True, timeout=600)
        print(f"[{symbol}] successfully tested on {TIMEFRAME}.")
    except Exception as e:
        print(f"Error processing {symbol}: {e}")

print(f"\n--- Batch backtest for {TIMEFRAME} completed successfully! ---")
