# 5m Filter V4

- Implements the previously documented V3 research gate for 5min entries.
- 5min emitted entry reasons now explicitly use `V3`; 15min/1h/4h remain `V2`.
- 5m V3 gate: SELL only, regime TREND_BEAR/MIXED, HTF -0.70..-0.35, EdgeProxy >= 0.20.
- 5m smart loss protection is graduated and uses the faster 1min management timeframe.
- 5m weakness protection now gets first look before the primary 5m hard SL; hard SL remains the fallback.
- 5m-only graduated early-loss thresholds: -0.20R with weakness >=45, -0.35R with >=40, -0.50R with >=35.
- Non-5m position-management ordering and thresholds are unchanged.
- Keep in PAPER until validated on fresh trades.
