import os
import subprocess
import sys

# Top 30 futures market symbols list
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

python_executable = sys.executable  # Use current virtual environment Python

print(f"--- Starting batch backtest across {len(TOP_SYMBOLS)} symbols ---")

for symbol in TOP_SYMBOLS:
    print(f"\nProcessing symbol: {symbol}")
    
    # 1. Run Legacy version (without filters)
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
    
    # 2. Run New version (with all filters active)
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
        # Run legacy with 600s timeout
        res_legacy = subprocess.run(cmd_legacy, capture_output=True, text=True, timeout=600)
        # Run new with 600s timeout
        res_new = subprocess.run(cmd_new, capture_output=True, text=True, timeout=600)
        
        print(f"[{symbol}] successfully tested.")
    except subprocess.TimeoutExpired:
        print(f"[Error] Processing symbol {symbol} timed out.")
    except Exception as e:
        print(f"Error processing {symbol}: {e}")

print("\n--- Batch backtest completed! CSV result logs saved. ---")
