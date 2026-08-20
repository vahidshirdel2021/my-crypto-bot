# Trading Bot Strategy V3 Professional Backtester

V3 is a research-grade backtester built directly on the Strategy V2 engine.

## Features
- Reuses V2 regime/setup selection.
- Historical CSV or CoinEx/CCXT data.
- Risk-per-trade position sizing from structural SL.
- Taker fees, configurable slippage and optional funding.
- Conservative same-candle SL/TP handling.
- Dynamic trailing and V2 weakness exits.
- Equity curve and drawdown.
- Profit Factor, Expectancy, Sharpe, Sortino, Calmar, SQN.
- VaR/CVaR, MFE/MAE, consecutive wins/losses and exposure.
- Attribution by regime, setup family and side.
- Bootstrap 95% confidence intervals.
- Walk-forward train/test evaluation.
- Optional TRAIN-only empirical edge calibration.
- JSON/CSV/PNG report bundle.

## Important
V2 `edge_proxy` and `model_win_proxy` are heuristic diagnostics, not
probabilities of winning. With `--calibrate-edge` in walk-forward mode,
score buckets can be filtered using TRAIN-only empirical average R.

## Example
```bash
python v3_backtest.py --symbol BTC/USDT:USDT --timeframe 15m   --start 2024-01-01 --end 2026-01-01 --side both   --risk 0.005 --fee 0.05 --slippage-bps 2 --funding-rate 0.01   --outdir reports/btc_15m

python v3_backtest.py --symbol BTC/USDT:USDT --timeframe 15m   --start 2024-01-01 --end 2026-01-01 --walk-forward   --train-days 90 --test-days 30 --calibrate-edge   --outdir reports/btc_wf
```

## CSV format
Required columns:
`ts` or `timestamp`, `open`, `high`, `low`, `close`, `volume`.

`ts` may be milliseconds or seconds since epoch.

## Report files
- report.json
- trades.csv
- equity_curve.csv
- monthly_pnl.csv
- by_regime.csv
- by_setup.csv
- by_side.csv
- walk_forward_folds.csv (walk-forward only)
- equity_curve.png
- drawdown.png

This is a research tool, not a guarantee of future returns.
