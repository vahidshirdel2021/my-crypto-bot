# V6 — Active Setup Recovery + Live Position PnL

## 1) Missed-entry recovery for 5m/15m
- The core entry logic remains based on the latest fully closed candle and PDH/PDL.
- If the scanner misses a valid recent Liquidity Sweep / Retest setup, the setup can remain actionable for a short freshness window.
- Default freshness: up to 3 closed candles.
- Entry is allowed only while live price remains close to the original PDH/PDL level.
- If price has moved too far from the level, the bot does **not** chase it.
- The setup must still pass the normal V2 quality, R:R, fee-risk, and market-direction guards.
- Active setups are re-planned from the original setup candle, while actual execution uses the current live price.

## 2) Live PnL in open positions
The `/open_positions` view now shows for every open position:
- Entry price
- Current live price
- Live profit/loss in USDT
- Live return percentage
- Current R multiple
- TP and SL

REAL uses the connected exchange price; PAPER uses the market price source already used by the bot.

## 3) REAL MFE/MAE correction
REAL position excursion tracking no longer feeds the last 120 historical candles into MFE/MAE. It starts from the actual live position lifetime, preventing false historical MFE from activating profit protection too early.

## 4) No changes to the core strategy families
- 5m/15m remain PDH/PDL Liquidity Sweep based.
- 1h/4h remain the existing Adaptive Trend/Breakout/Mean-Reversion engine.
- Position management mapping remains 5m→1m, 15m→5m, 1h→15m, 4h→1h.


## V7 fix
- Fixed Dynamic V2 live-price propagation into the 5m/15m Liquidity Sweep engine.
- Prevented a fresh closed-candle signal from chasing price when live price is already beyond the allowed PDH/PDL distance.
- Active Setup now remains the recovery path for a missed setup; no FOMO entry when price has escaped.
- Fixed trade-plan fallback so active setup index/live price are preserved.
- Removed a duplicated Trend Following call.
- Verified Python syntax and strategy import.
