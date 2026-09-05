# KLSDE V2 Crypto Trading Bot

A Python crypto trading bot built around the KLSDE key-level setup engine with multi-engine confirmation, risk controls, trade management, watchlist/opportunity handling, reporting, and backtest/live parity safeguards.

## Architecture

```text
Market Data
    ↓
Closed HTF Data
    ↓
Regime / Filters
    ↓
PRE + SDE + MCDE + CPDE confirmations
    ↓
KLSDE (sole setup / entry anchor)
    ↓
Confluence / Quality Gate
    ↓
Risk Guard (SL / TP / RR / leverage / fee protection)
    ↓
Execution
    ↓
Trade Management / Audit / Reporting
```

KLSDE remains the only engine allowed to anchor a Live setup. The other engines provide confirmation/evidence.

## Supported trading timeframes

- 5m
- 15m
- 1h
- 4h

Higher-timeframe decisions use confirmed/closed candles only.

## Setup types

KLSDE can classify key-level interactions into:

- BOF
- TST
- BPB
- BP
- CPB

## Safety

The repository intentionally does **not** contain API keys, Telegram tokens, local databases, or runtime secrets.

Keep real credentials in environment variables/local configuration and never commit them.

Default `PAPER_ONLY=true` is recommended for initial validation.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

On Windows:

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

## Configure

Copy:

```text
.env.example
```

to your local environment configuration and provide only the credentials/settings required for your deployment.

Important environment variables include:

- `TELEGRAM_TOKEN`
- `ADMIN_CHAT_IDS`
- `COINEX_ACCOUNTS_JSON`
- `PAPER_ONLY`
- `BOT_DB_PATH`

Do not commit a real `.env` file.

## Run tests

```bash
pytest -q
```

## Notes

Legacy B/S and Extra modules may remain in the repository for historical/backtest compatibility. They are not the Live setup anchor; the Live strategy path is pinned to KLSDE/Confluence.

See `KLSDE_LIVE_ARCHITECTURE.md` and `CLAUDE_FIX_IMPLEMENTED.md` for architecture and repair details.
