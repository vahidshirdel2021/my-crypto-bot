# V10 — Render + Neon persistence

## 1) Neon
Create a PostgreSQL database in Neon and copy its connection string.

## 2) Render Environment Variables
Set:

- `DATABASE_URL` = Neon PostgreSQL connection string
- `LEGACY_SQLITE_PATH` = path to the old `trader_bot.sqlite3` file **if the old SQLite file is still available**

`psycopg[binary]` is already in `requirements.txt`.

## 3) First deploy
At startup the bot:

1. Creates the PostgreSQL schema if needed.
2. Checks whether the one-time migration marker exists.
3. If an old SQLite file exists, imports sessions, open/closed positions, trade audit/report state, fee ledger, user fee settings, users and Telegram offset.
4. Does not overwrite a newer PostgreSQL session with an older SQLite session.
5. Advances the PostgreSQL fee ledger sequence after importing explicit IDs.
6. Loads sessions from PostgreSQL before starting scanner/position management.

## 4) After deploys
Future deploys use PostgreSQL directly. Render disk loss/replacement no longer deletes bot state, because the state is stored in Neon.

## Important limitation
If the old SQLite file was already lost because it lived only on an ephemeral Render disk, the bot cannot reconstruct that historical data. Restore the SQLite backup first and point `LEGACY_SQLITE_PATH` to it.
