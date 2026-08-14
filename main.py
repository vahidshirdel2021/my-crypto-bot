import os
import json
import time
import asyncio
import aiohttp
import requests
import sqlite3
import logging
import math
import io
import hashlib
from threading import Thread, RLock
from typing import Optional, Dict, Any

import pandas as pd
import ccxt
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from flask import Flask

from strategy import (
    FILTER_DEFAULTS,
    STRATEGY_DEFAULTS,
    FILTERS,
    STRATEGY_CONFIG,
    calculate_indicators,
    get_signal_with_reason,
    get_strategy_params,
    get_strategy_description,
    strategy_trend_following,
    strategy_breakout,
    strategy_mean_reversion,
)
from ui import (
    get_start_keyboard,
    get_balance_keyboard,
    get_margin_keyboard,
    get_leverage_keyboard,
    get_max_positions_keyboard,
    get_timeframe_keyboard,
    get_main_menu_keyboard,
    get_watchlist_manage_keyboard,
    get_strategies_selection_keyboard,
    get_filters_menu_keyboard,
    get_params_menu_keyboard,
    get_positions_keyboard,
    get_bottom_menu_keyboard,
    get_confirm_close_all_keyboard,
    get_strategies_menu_keyboard,
)


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
COINEX_API_KEY = (os.environ.get("COINEX_API_KEY", "") or os.environ.get("coinexaccessid", "")).strip()
COINEX_SECRET = (os.environ.get("COINEX_SECRET", "") or os.environ.get("coinexSecretKey", "")).strip()
PORT = int(os.environ.get("PORT", "10000"))
DB_PATH = os.environ.get("BOT_DB_PATH", "trader_bot.sqlite3")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
ALLOWED_CHAT_IDS_RAW = os.environ.get("ALLOWED_CHAT_IDS", "").strip()
ALLOWED_CHAT_IDS = {
    int(x.strip()) for x in ALLOWED_CHAT_IDS_RAW.split(",") if x.strip().lstrip("-").isdigit()
}

SCAN_INTERVAL_SECONDS = max(20, int(os.environ.get("SCAN_INTERVAL_SECONDS", "45")))
DATA_CACHE_SECONDS = max(5, int(os.environ.get("DATA_CACHE_SECONDS", "20")))
MAX_ASYNC_REQUESTS = max(2, int(os.environ.get("MAX_ASYNC_REQUESTS", "10")))
DEFAULT_DAILY_LOSS_LIMIT_PCT = float(os.environ.get("DAILY_LOSS_LIMIT_PCT", "3.0"))
DEFAULT_RISK_PER_TRADE_PCT = float(os.environ.get("RISK_PER_TRADE_PCT", "0.5"))
DEFAULT_MAX_MARGIN_USAGE_PCT = float(os.environ.get("MAX_MARGIN_USAGE_PCT", "50"))

ALL_SYMBOLS = [
    'BTC', 'ETH', 'YFI', 'MKR', 'BCH', 'COMP', 'KSM', 'LTC', 'AAVE', 'ZEC',
    'EGLD', 'BNB', 'DASH', 'FIL', 'ZEN', 'SOL', 'UNI', 'DOT', 'BAL',
    'LIT', 'BAND', 'UNFI', 'SUSHI', 'SNX', 'AVAX', 'ATOM', 'TRB', 'ETC', 'NEO',
    'SFP', 'BEL', 'IOTA', 'AXS', 'RLC', 'SXP', 'GRT', 'RUNE', 'ONT',
    'KAVA', 'OCEAN', '1INCH', 'REN', 'KNC', 'HNT', 'ENJ', 'ICX',
    'CRV', 'NEAR', 'CTK', 'LUNA', 'EOS', 'THETA', 'QTUM', 'MANA', 'OMG', 'SAND',
    'ADA', 'XEM', 'FTM', 'RVN', 'MTL', 'SC', 'STORJ', 'ZIL', 'SLP', 'BTS',
    'XRP', 'BLZ', 'FET', 'ALGO', 'DODO', 'CHR', 'AKRO', 'CVC', 'STMX',
    'CELR', 'HBAR', 'SKL', 'RSR', 'REEF', 'CHZ', 'LINK', 'ALICE', 'ZRX', 'COTI',
    'ONE', 'MATIC', 'XTZ', 'NKN', 'ANKR', 'LINA', 'HOT', 'LRC', 'DOGE', 'DENT',
    'DGB', 'WIN', 'IOST', 'TRX', 'BTT', 'FLM', 'BAT', 'VET', 'SHIB', 'ARPA',
    'AR', 'C98', 'DYDX', 'TLM', 'GALA', 'AUDIO', 'MASK', 'BAKE', 'KEEP', 'OGN',
    'RAY', 'KLAY', 'ATA', 'GTC', 'CELO', 'YFII', 'CTSI'
]

TIMEFRAME_MAP = {
    "5min": "5min",
    "15min": "15min",
    "1hour": "1hour",
    "4hour": "4hour",
    "1day": "1day",
}

TF_DISPLAY = {
    "5min": "5م",
    "15min": "15م",
    "1hour": "1س",
    "4hour": "4ساعته",
    "1day": "روزانه",
    "multi": "مولتی آبشاری",
}

logger = logging.getLogger("trader_bot")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(threadName)s | %(message)s",
)

app = Flask(__name__)
STATE_LOCK = RLock()
DATA_CACHE: Dict[str, Any] = {}
DATA_CACHE_LOCK = RLock()
ASYNC_SEMAPHORE = None

USER_SESSIONS: Dict[int, Dict[str, Any]] = {}


# -----------------------------------------------------------------------------
# Persistence
# -----------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions (chat_id INTEGER PRIMARY KEY, data TEXT NOT NULL, updated_at INTEGER NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()


def save_session(chat_id: int):
    with STATE_LOCK:
        session = USER_SESSIONS.get(chat_id)
        if session is None:
            return
        payload = json.dumps(session, ensure_ascii=False, separators=(",", ":"), default=str)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT INTO sessions(chat_id,data,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(chat_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
            (chat_id, payload, int(time.time())),
        )
        conn.commit()
    finally:
        conn.close()


def load_sessions():
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute("SELECT chat_id, data FROM sessions").fetchall()
    finally:
        conn.close()

    with STATE_LOCK:
        for chat_id, raw in rows:
            try:
                data = json.loads(raw)
                data = normalize_session(data)
                USER_SESSIONS[int(chat_id)] = data
            except Exception as exc:
                logger.exception("Could not restore session %s: %s", chat_id, exc)


def normalize_session(data: Dict[str, Any]) -> Dict[str, Any]:
    base = default_session()
    base.update(data or {})
    base["filters"] = {**FILTER_DEFAULTS, **(data.get("filters") or {})}
    base["strategy_config"] = {**STRATEGY_DEFAULTS, **(data.get("strategy_config") or {})}
    base["paper_positions"] = list(data.get("paper_positions") or [])
    base["closed_positions"] = list(data.get("closed_positions") or [])
    base["cooldowns"] = dict(data.get("cooldowns") or {})
    base["active_symbols"] = list(data.get("active_symbols") or ALL_SYMBOLS[:])
    base["daily_start_balance"] = float(base.get("daily_start_balance", base["paper_balance"]))
    base["daily_loss_limit_pct"] = float(base.get("daily_loss_limit_pct", DEFAULT_DAILY_LOSS_LIMIT_PCT))
    base["risk_per_trade_pct"] = float(base.get("risk_per_trade_pct", DEFAULT_RISK_PER_TRADE_PCT))
    base["max_margin_usage_pct"] = float(base.get("max_margin_usage_pct", DEFAULT_MAX_MARGIN_USAGE_PCT))
    base["is_bot_active"] = bool(base.get("is_bot_active", False))
    base["daily_stopped"] = bool(base.get("daily_stopped", False))
    return base


def default_session():
    return {
        "is_bot_active": False,
        "trading_mode": "PAPER",
        "paper_balance": 1000.0,
        "daily_start_balance": 1000.0,
        "daily_stopped": False,
        "trade_amount_usdt": 50.0,
        "leverage": 10,
        "max_open_positions": 3,
        "timeframe": "5min",
        "active_strategy": "dynamic",
        "paper_positions": [],
        "closed_positions": [],
        "cooldowns": {},
        "user_state": None,
        "active_symbols": ALL_SYMBOLS[:],
        "filters": FILTER_DEFAULTS.copy(),
        "strategy_config": STRATEGY_DEFAULTS.copy(),
        "daily_loss_limit_pct": DEFAULT_DAILY_LOSS_LIMIT_PCT,
        "risk_per_trade_pct": DEFAULT_RISK_PER_TRADE_PCT,
        "max_margin_usage_pct": DEFAULT_MAX_MARGIN_USAGE_PCT,
        "created_at": int(time.time()),
        "last_equity_check": 0,
    }


def get_user_session(chat_id: int) -> Dict[str, Any]:
    with STATE_LOCK:
        if chat_id not in USER_SESSIONS:
            USER_SESSIONS[chat_id] = default_session()
            save_session(chat_id)
        return USER_SESSIONS[chat_id]


# -----------------------------------------------------------------------------
# Exchange setup
# -----------------------------------------------------------------------------
exchange = None
if COINEX_API_KEY and COINEX_SECRET:
    try:
        exchange = ccxt.coinex({
            "apiKey": COINEX_API_KEY,
            "secret": COINEX_SECRET,
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
                "defaultMarginMode": "cross",
            },
        })
        exchange.load_markets()
        logger.info("CoinEx exchange initialized; %s swap markets loaded", len(exchange.markets))
    except Exception as exc:
        logger.exception("CoinEx initialization failed: %s", exc)
        exchange = None


# -----------------------------------------------------------------------------
# Telegram helpers
# -----------------------------------------------------------------------------
def is_allowed_chat(chat_id: int) -> bool:
    return not ALLOWED_CHAT_IDS or chat_id in ALLOWED_CHAT_IDS


def telegram_request(method: str, payload=None, timeout=10):
    if not TELEGRAM_TOKEN:
        return None
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}"
    try:
        response = requests.post(url, json=payload or {}, timeout=timeout)
        if response.status_code != 200:
            logger.warning("Telegram %s returned %s: %s", method, response.status_code, response.text[:300])
            return None
        return response.json()
    except Exception as exc:
        logger.warning("Telegram %s failed: %s", method, exc)
        return None


def answer_callback(callback_id: str):
    if callback_id:
        telegram_request("answerCallbackQuery", {"callback_query_id": callback_id}, timeout=5)


def send_telegram_msg(message, chat_target=None, reply_markup=None, message_id=None, parse_mode="Markdown"):
    if not TELEGRAM_TOKEN:
        return False
    target = chat_target
    if target is None:
        with STATE_LOCK:
            target = next(iter(USER_SESSIONS.keys()), None)
    if target is None or not is_allowed_chat(target):
        return False

    session = get_user_session(target)
    if reply_markup is None:
        reply_markup = get_bottom_menu_keyboard(session["is_bot_active"])

    if message_id:
        payload = {
            "chat_id": target,
            "message_id": message_id,
            "text": message,
            "reply_markup": reply_markup,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        result = telegram_request("editMessageText", payload, timeout=10)
        if result and result.get("ok"):
            return True

    payload = {"chat_id": target, "text": message, "reply_markup": reply_markup}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    result = telegram_request("sendMessage", payload, timeout=10)
    return bool(result and result.get("ok"))


def send_telegram_photo(photo_bytes, caption="", chat_target=None, reply_markup=None):
    if not TELEGRAM_TOKEN:
        return False
    target = chat_target
    if target is None:
        with STATE_LOCK:
            target = next(iter(USER_SESSIONS.keys()), None)
    if target is None or not is_allowed_chat(target):
        return False

    session = get_user_session(target)
    if reply_markup is None:
        reply_markup = get_bottom_menu_keyboard(session["is_bot_active"])

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", photo_bytes, "image/png")}
    data = {
        "chat_id": target,
        "caption": caption,
        "parse_mode": "Markdown",
        "reply_markup": json.dumps(reply_markup, ensure_ascii=False),
    }
    try:
        response = requests.post(url, data=data, files=files, timeout=15)
        return response.status_code == 200
    except Exception as exc:
        logger.warning("Telegram sendPhoto failed: %s", exc)
        return False


def fmt_p(val):
    if val is None:
        return "0.00"
    try:
        f = float(val)
        if abs(f) < 0.0001:
            return f"{f:.8f}"
        if abs(f) < 1:
            return f"{f:.6f}"
        return f"{f:.4f}"
    except Exception:
        return str(val)


# -----------------------------------------------------------------------------
# CoinEx market data (public, v2) with fallback to KuCoin
# -----------------------------------------------------------------------------
COINEX_PUBLIC_BASE = "https://api.coinex.com/v2"
KUCOIN_PUBLIC_BASE = "https://api.kucoin.com/api/v1"


def _coinex_market_symbol(base: str) -> str:
    return f"{base.upper().replace('USDT', '').replace('/', '')}USDT"


def _normalize_klines(data):
    if not data:
        return pd.DataFrame()
    rows = []
    for item in data:
        if isinstance(item, dict):
            rows.append({
                "timestamp": item.get("created_at"),
                "open": item.get("open"),
                "close": item.get("close"),
                "high": item.get("high"),
                "low": item.get("low"),
                "volume": item.get("volume"),
            })
        elif isinstance(item, (list, tuple)) and len(item) >= 7:
            rows.append({
                "timestamp": item[0], "open": item[1], "close": item[2],
                "high": item[3], "low": item[4], "volume": item[5],
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["timestamp"] = pd.to_numeric(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)
    return df


def get_crypto_klines(coin_symbol, interval_type="5min", limit=200):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    period = TIMEFRAME_MAP.get(interval_type, interval_type)
    cache_key = f"{coin_symbol}:{period}:{limit}"
    now = time.time()
    with DATA_CACHE_LOCK:
        cached = DATA_CACHE.get(cache_key)
        if cached and now - cached["ts"] <= DATA_CACHE_SECONDS:
            return cached["df"].copy()

    # CoinEx futures is used first so the signal data is closer to the execution venue.
    try:
        res = requests.get(
            f"{COINEX_PUBLIC_BASE}/futures/kline",
            params={"market": _coinex_market_symbol(coin_symbol), "period": period, "limit": min(limit, 1000)},
            headers={"User-Agent": "TraderBot/2.0"},
            timeout=6,
        )
        if res.status_code == 200:
            payload = res.json()
            if payload.get("code") == 0:
                df = _normalize_klines(payload.get("data"))
                if len(df) >= 30:
                    with DATA_CACHE_LOCK:
                        DATA_CACHE[cache_key] = {"ts": now, "df": df.copy()}
                    return df
    except Exception as exc:
        logger.debug("CoinEx kline failed for %s: %s", coin_symbol, exc)

    # Fallback for public market data.
    try:
        res = requests.get(
            f"{KUCOIN_PUBLIC_BASE}/market/candles",
            params={"symbol": f"{coin_symbol}-USDT", "type": period},
            headers={"User-Agent": "TraderBot/2.0"},
            timeout=6,
        )
        if res.status_code == 200:
            payload = res.json()
            if payload.get("code") == "200000":
                data = payload.get("data") or []
                df = pd.DataFrame(
                    data,
                    columns=["timestamp", "open", "close", "high", "low", "volume", "turnover"],
                )
                df = df.iloc[::-1].reset_index(drop=True)
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                if len(df) >= 30:
                    with DATA_CACHE_LOCK:
                        DATA_CACHE[cache_key] = {"ts": now, "df": df.copy()}
                    return df
    except Exception as exc:
        logger.debug("KuCoin kline failed for %s: %s", coin_symbol, exc)

    return pd.DataFrame()


async def get_crypto_klines_async(session_http, coin_symbol, interval_type="5min", limit=200):
    coin_symbol = coin_symbol.upper().replace("USDT", "").replace("/", "").strip()
    period = TIMEFRAME_MAP.get(interval_type, interval_type)
    cache_key = f"{coin_symbol}:{period}:{limit}"
    now = time.time()
    with DATA_CACHE_LOCK:
        cached = DATA_CACHE.get(cache_key)
        if cached and now - cached["ts"] <= DATA_CACHE_SECONDS:
            return cached["df"].copy()

    await ASYNC_SEMAPHORE.acquire()
    try:
        try:
            async with session_http.get(
                f"{COINEX_PUBLIC_BASE}/futures/kline",
                params={"market": _coinex_market_symbol(coin_symbol), "period": period, "limit": min(limit, 1000)},
                headers={"User-Agent": "TraderBot/2.0"},
            ) as res:
                if res.status == 200:
                    payload = await res.json()
                    if payload.get("code") == 0:
                        df = _normalize_klines(payload.get("data"))
                        if len(df) >= 30:
                            with DATA_CACHE_LOCK:
                                DATA_CACHE[cache_key] = {"ts": now, "df": df.copy()}
                            return df
        except Exception as exc:
            logger.debug("Async CoinEx kline failed for %s: %s", coin_symbol, exc)

        try:
            async with session_http.get(
                f"{KUCOIN_PUBLIC_BASE}/market/candles",
                params={"symbol": f"{coin_symbol}-USDT", "type": period},
                headers={"User-Agent": "TraderBot/2.0"},
            ) as res:
                if res.status == 200:
                    payload = await res.json()
                    if payload.get("code") == "200000":
                        data = payload.get("data") or []
                        df = pd.DataFrame(
                            data,
                            columns=["timestamp", "open", "close", "high", "low", "volume", "turnover"],
                        )
                        df = df.iloc[::-1].reset_index(drop=True)
                        for col in ["open", "high", "low", "close", "volume"]:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                        if len(df) >= 30:
                            with DATA_CACHE_LOCK:
                                DATA_CACHE[cache_key] = {"ts": now, "df": df.copy()}
                            return df
        except Exception as exc:
            logger.debug("Async KuCoin kline failed for %s: %s", coin_symbol, exc)
    finally:
        ASYNC_SEMAPHORE.release()

    return pd.DataFrame()


def get_latest_price(symbol: str) -> Optional[float]:
    base = symbol.upper().replace("USDT", "").replace("/", "")
    try:
        res = requests.get(
            f"{COINEX_PUBLIC_BASE}/futures/ticker",
            params={"market": _coinex_market_symbol(base)},
            headers={"User-Agent": "TraderBot/2.0"},
            timeout=5,
        )
        if res.status_code == 200:
            payload = res.json()
            if payload.get("code") == 0 and payload.get("data"):
                item = payload["data"][0]
                price = float(item.get("last") or item.get("mark_price"))
                if price > 0:
                    return price
    except Exception as exc:
        logger.debug("Latest price failed for %s: %s", symbol, exc)
    return None


# -----------------------------------------------------------------------------
# Utility / risk
# -----------------------------------------------------------------------------
def side_is_long(side: str) -> bool:
    return "BUY" in side.upper() or "LONG" in side.upper()


def sanitize_market_symbol(symbol: str) -> str:
    return f"{symbol.upper().replace('USDT', '').replace('/', '')}/USDT:USDT"


def reserved_margin(session):
    return sum(float(p.get("margin", 0.0)) for p in session["paper_positions"])


def current_equity(session):
    base = float(session.get("paper_balance", 0.0))
    floating = 0.0
    for p in session.get("paper_positions", []):
        try:
            price = get_latest_price(p["symbol"])
            if price is not None:
                entry = float(p["entry_price"])
                pct = ((price - entry) / entry) if side_is_long(p["side"]) else ((entry - price) / entry)
                floating += float(p.get("margin", 0)) * pct * float(p.get("leverage", 1))
        except Exception:
            continue
    return base + floating


def apply_daily_loss_guard(chat_id: int):
    session = get_user_session(chat_id)
    if session.get("daily_stopped"):
        return False

    start = float(session.get("daily_start_balance", session.get("paper_balance", 0.0)))
    if start <= 0:
        return True

    if session["trading_mode"] == "REAL" and exchange:
        try:
            balance = exchange.fetch_balance({"type": "swap"})
            total = float((balance.get("total") or {}).get("USDT", 0.0))
            equity = total
        except Exception as exc:
            logger.warning("Real balance check failed for %s: %s", chat_id, exc)
            return True
    else:
        equity = current_equity(session)

    limit = start * (1 - float(session.get("daily_loss_limit_pct", DEFAULT_DAILY_LOSS_LIMIT_PCT)) / 100.0)
    if equity <= limit:
        session["daily_stopped"] = True
        session["is_bot_active"] = False
        save_session(chat_id)
        send_telegram_msg(
            f"🛑 *سقف ضرر روزانه فعال شد.*\n\n"
            f"• موجودی شروع روز: `${start:.2f}`\n"
            f"• equity فعلی: `${equity:.2f}`\n"
            f"• حد ضرر روزانه: `{session.get('daily_loss_limit_pct', DEFAULT_DAILY_LOSS_LIMIT_PCT):.2f}%`\n\n"
            f"اسکن متوقف شد؛ پوزیشن‌های باز خودکار بسته نمی‌شوند.",
            chat_target=chat_id,
        )
        return False
    return True


def calculate_safe_trade_size(session, entry_price, sl_price):
    requested_margin = float(session["trade_amount_usdt"])
    leverage = max(1, int(session["leverage"]))
    balance = float(session.get("paper_balance", 0.0))
    stop_distance = abs(float(entry_price) - float(sl_price)) / max(abs(float(entry_price)), 1e-12)
    if stop_distance <= 0:
        return 0.0, "فاصله SL معتبر نیست"

    risk_budget = max(0.0, balance * float(session.get("risk_per_trade_pct", DEFAULT_RISK_PER_TRADE_PCT)) / 100.0)
    risk_limited_notional = risk_budget / stop_distance if risk_budget > 0 else 0.0
    requested_notional = requested_margin * leverage

    current_margin = reserved_margin(session)
    margin_cap = balance * float(session.get("max_margin_usage_pct", DEFAULT_MAX_MARGIN_USAGE_PCT)) / 100.0
    available_margin = max(0.0, margin_cap - current_margin)

    final_margin = min(requested_margin, available_margin, risk_limited_notional / leverage if leverage else 0)
    if final_margin <= 0:
        return 0.0, "ریسک یا سقف مارجین اجازه ورود جدید نمی‌دهد"

    return final_margin, "OK"


# -----------------------------------------------------------------------------
# Charts
# -----------------------------------------------------------------------------
def generate_and_send_trade_chart(chat_id, symbol, df, trade):
    try:
        if df is None or df.empty or len(df) < 30:
            return
        plot_df = df.tail(60).copy()
        plt.figure(figsize=(10, 5))
        plt.plot(plot_df["close"].values, label="Close Price", linewidth=2)
        if "ema20" in plot_df:
            plt.plot(plot_df["ema20"].values, label="EMA20", linestyle="--", alpha=0.8)
        if "ema50" in plot_df:
            plt.plot(plot_df["ema50"].values, label="EMA50", linestyle="--", alpha=0.8)

        entry_val = float(trade["entry_price"])
        tp_val = float(trade["tp"])
        sl_val = float(trade["sl"])
        plt.axhline(entry_val, linestyle="-", label=f"Entry: {fmt_p(entry_val)}")
        plt.axhline(tp_val, linestyle=":", label=f"TP: {fmt_p(tp_val)}")
        plt.axhline(sl_val, linestyle=":", label=f"SL: {fmt_p(sl_val)}")
        plt.title(f"Trade Chart: {symbol} ({trade['side']})", fontsize=14, fontweight="bold")
        plt.legend(loc="upper left", fontsize=9)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=100)
        plt.close()
        buf.seek(0)

        side_icon = "🟢" if side_is_long(trade["side"]) else "🔴"
        mode_badge = "واقعی" if trade.get("is_real") else "کاغذی"
        caption = (
            f"📊 *معامله جدید [{mode_badge}] {side_icon} ({trade['side']})*\n"
            f"• نماد: `{symbol}`\n"
            f"• قیمت ورود واقعی: `{fmt_p(entry_val)}`\n"
            f"• مارجین: `${float(trade['margin']):.2f} USDT` | اهرم `{trade['leverage']}X`\n"
            f"• TP: `{fmt_p(tp_val)}` | SL: `{fmt_p(sl_val)}`\n"
            f"• ریسک هدف: `{float(trade.get('risk_pct', 0)):.2f}%`"
        )
        send_telegram_photo(buf.getvalue(), caption=caption, chat_target=chat_id)
    except Exception as exc:
        logger.exception("Chart error: %s", exc)


# -----------------------------------------------------------------------------
# CoinEx protected orders / positions
# -----------------------------------------------------------------------------
def call_implicit(name: str, params: Dict[str, Any]):
    if not exchange:
        raise RuntimeError("CoinEx connection is unavailable")
    fn = getattr(exchange, name, None)
    if not callable(fn):
        raise AttributeError(f"CCXT implicit method not available: {name}")
    return fn(params)


def set_exchange_protection(symbol: str, sl: float, tp: float):
    """Set full-position SL/TP through CoinEx v2 protected position endpoints.
    The current CCXT CoinEx implementation exposes the exchange endpoints as
    implicit methods. A generic createOrder fallback is intentionally not used;
    failure to protect a real position is treated as unsafe.
    """
    market = _coinex_market_symbol(symbol)
    errors = []
    try:
        call_implicit(
            "v2PrivatePostFuturesSetPositionStopLoss",
            {
                "market": market,
                "market_type": "FUTURES",
                "stop_loss_type": "mark_price",
                "stop_loss_price": str(float(sl)),
            },
        )
    except Exception as exc:
        errors.append(f"SL: {exc}")

    try:
        call_implicit(
            "v2PrivatePostFuturesSetPositionTakeProfit",
            {
                "market": market,
                "market_type": "FUTURES",
                "take_profit_type": "mark_price",
                "take_profit_price": str(float(tp)),
            },
        )
    except Exception as exc:
        errors.append(f"TP: {exc}")

    if errors:
        return False, " | ".join(errors)
    return True, "OK"


def modify_exchange_stop_loss(symbol: str, sl: float):
    market = _coinex_market_symbol(symbol)
    try:
        call_implicit(
            "v2PrivatePostFuturesSetPositionStopLoss",
            {
                "market": market,
                "market_type": "FUTURES",
                "stop_loss_type": "mark_price",
                "stop_loss_price": str(float(sl)),
            },
        )
        return True, "OK"
    except Exception as exc:
        return False, str(exc)


def get_exchange_position(symbol: str):
    if not exchange:
        return None
    try:
        return exchange.fetch_position(sanitize_market_symbol(symbol))
    except Exception as exc:
        logger.debug("fetch_position failed for %s: %s", symbol, exc)
        return None


def get_exchange_balance_usdt():
    if not exchange:
        return 0.0
    try:
        bal = exchange.fetch_balance({"type": "swap"})
        return float((bal.get("total") or {}).get("USDT", 0.0))
    except Exception as exc:
        logger.warning("fetch_balance failed: %s", exc)
        return 0.0


def sync_real_positions(chat_id: int):
    session = get_user_session(chat_id)
    if session["trading_mode"] != "REAL" or not exchange:
        return

    try:
        positions = exchange.fetch_positions()
    except Exception as exc:
        logger.warning("Could not fetch CoinEx positions: %s", exc)
        return

    live = {}
    for pos in positions:
        contracts = pos.get("contracts")
        if contracts is None:
            contracts = pos.get("contractSize") or pos.get("amount")
        try:
            contracts = abs(float(contracts or 0))
        except Exception:
            contracts = 0
        if contracts <= 0:
            continue
        symbol = pos.get("symbol", "")
        base = symbol.split("/")[0].upper() if "/" in symbol else symbol.replace(":USDT", "").replace("USDT", "")
        side = str(pos.get("side") or "").lower()
        live[base] = {
            "symbol": base,
            "side": "BUY (Long)" if side == "long" else "SELL (Short)",
            "entry_price": float(pos.get("entryPrice") or pos.get("average") or 0),
            "amount": contracts,
            "leverage": int(float(pos.get("leverage") or session["leverage"])),
            "unrealized_pnl": float(pos.get("unrealizedPnl") or 0),
            "position_id": pos.get("id"),
        }

    known = {p["symbol"]: p for p in session["paper_positions"] if p.get("is_real")}
    unknown = [x for s, x in live.items() if s not in known]
    if unknown:
        session["is_bot_active"] = False
        session["real_reconciliation_required"] = True
        save_session(chat_id)
        names = ", ".join(x["symbol"] for x in unknown[:10])
        send_telegram_msg(
            f"⚠️ *پوزیشن واقعی ناشناخته شناسایی شد:* `{names}`\n\n"
            f"اسکن ربات متوقف شد تا وضعیت این پوزیشن‌ها با داده داخلی ربات تطبیق داده شود.",
            chat_target=chat_id,
        )
        return

    for symbol, pos in known.items():
        if symbol in live:
            pos.update(live[symbol])
        else:
            # Exchange has closed it; finalize locally using recent price/history fallback.
            finalize_external_real_close(chat_id, pos)

    save_session(chat_id)


def finalize_external_real_close(chat_id: int, pos: Dict[str, Any]):
    session = get_user_session(chat_id)
    if pos not in session["paper_positions"]:
        return
    current_price = get_latest_price(pos["symbol"]) or float(pos["entry_price"])
    if side_is_long(pos["side"]):
        pct = (current_price - float(pos["entry_price"])) / float(pos["entry_price"])
    else:
        pct = (float(pos["entry_price"]) - current_price) / float(pos["entry_price"])
    pnl = float(pos.get("margin", 0)) * pct * float(pos.get("leverage", 1))
    pos["pnl_usdt"] = pnl
    pos["close_timestamp"] = time.time()
    pos["close_reason"] = "CoinEx position disappeared / external TP-SL"
    session["closed_positions"].append(pos.copy())
    session["paper_positions"].remove(pos)
    session["cooldowns"][pos["symbol"]] = time.time() + 300
    send_telegram_msg(
        f"📌 *پوزیشن واقعی بسته شد (تأیید از صرافی)*\n"
        f"• نماد: `{pos['symbol']}`\n"
        f"• سود/زیان برآوردی: `{pnl:+.2f} USDT`\n"
        f"• علت: `{pos['close_reason']}`",
        chat_target=chat_id,
    )
    save_session(chat_id)


# -----------------------------------------------------------------------------
# Trade execution
# -----------------------------------------------------------------------------
def execute_trade(chat_id, symbol, side, price, sl, tp, signal_reason=""):
    session = get_user_session(chat_id)
    if not session["is_bot_active"] or session["daily_stopped"]:
        return False
    if not apply_daily_loss_guard(chat_id):
        return False

    now = time.time()
    if symbol in session.get("cooldowns", {}) and now < float(session["cooldowns"][symbol]):
        return False
    if now >= float(session.get("cooldowns", {}).get(symbol, 0)):
        session.get("cooldowns", {}).pop(symbol, None)

    filters = session["filters"]
    if filters.get("no_short_filter") and "SELL" in side:
        return False
    if filters.get("no_buy_filter") and "BUY" in side:
        return False
    if session["max_open_positions"] > 0 and len(session["paper_positions"]) >= session["max_open_positions"]:
        return False
    if any(p["symbol"] == symbol for p in session["paper_positions"]):
        return False

    # Use current executable price for paper trading, not the previous candle close.
    live_price = get_latest_price(symbol) or float(price)
    direction = "BUY" if side_is_long(side) else "SELL"
    atr_gap = abs(float(price) - float(sl))
    # Keep the original stop distance around the actual execution price.
    if direction == "BUY":
        sl = live_price - atr_gap
        tp = live_price + abs(float(tp) - float(price))
    else:
        sl = live_price + atr_gap
        tp = live_price - abs(float(tp) - float(price))

    final_margin, size_reason = calculate_safe_trade_size(session, live_price, sl)
    if final_margin <= 0:
        return False
    leverage = int(session["leverage"])
    notional = final_margin * leverage
    amount = notional / max(live_price, 1e-12)

    trade = {
        "symbol": symbol,
        "side": side,
        "entry_price": live_price,
        "sl": float(sl),
        "tp": float(tp),
        "margin": float(final_margin),
        "leverage": leverage,
        "amount": float(amount),
        "timeframe": session["timeframe"],
        "close_timestamp": None,
        "pnl_usdt": 0.0,
        "trailing_activated": False,
        "is_real": False,
        "signal_reason": signal_reason[:500],
        "opened_at": time.time(),
        "risk_pct": session.get("risk_per_trade_pct", DEFAULT_RISK_PER_TRADE_PCT),
    }

    if session["trading_mode"] == "REAL":
        if not exchange:
            send_telegram_msg("❌ اتصال امن به CoinEx در دسترس نیست؛ معامله واقعی لغو شد.", chat_target=chat_id)
            return False
        market_symbol = sanitize_market_symbol(symbol)
        try:
            exchange.set_margin_mode("cross", market_symbol, {"leverage": leverage})
        except Exception:
            try:
                exchange.set_leverage(leverage, market_symbol, {"marginMode": "cross"})
            except Exception as exc:
                send_telegram_msg(f"❌ تنظیم اهرم CoinEx انجام نشد: {exc}", chat_target=chat_id)
                return False

        try:
            order = exchange.create_order(
                market_symbol,
                "market",
                "buy" if direction == "BUY" else "sell",
                amount,
                None,
                {"timeInForce": "IOC"},
            )
            order_id = order.get("id")
            exec_price = float(order.get("average") or order.get("price") or live_price)
            filled_amount = float(order.get("filled") or order.get("amount") or amount)

            trade["entry_price"] = exec_price
            trade["amount"] = filled_amount
            trade["margin"] = (exec_price * filled_amount) / leverage
            if direction == "BUY":
                trade["sl"] = exec_price - atr_gap
                trade["tp"] = exec_price + abs(float(tp) - live_price)
            else:
                trade["sl"] = exec_price + atr_gap
                trade["tp"] = exec_price - abs(float(tp) - live_price)

            protection_ok, protection_error = set_exchange_protection(symbol, trade["sl"], trade["tp"])
            if not protection_ok:
                # Never leave a real position unprotected.
                try:
                    exchange.close_position(market_symbol, None, {"type": "market", "amount": filled_amount})
                except Exception as close_exc:
                    send_telegram_msg(
                        f"🚨 *بحرانی:* تنظیم SL/TP شکست خورد و بستن خودکار هم خطا داد.\n"
                        f"• نماد: `{symbol}`\n• خطای حفاظت: `{protection_error}`\n• خطای بستن: `{close_exc}`",
                        chat_target=chat_id,
                        parse_mode="Markdown",
                    )
                else:
                    send_telegram_msg(
                        f"⚠️ معامله `{symbol}` به‌دلیل عدم امکان تنظیم SL/TP فوراً بسته شد.\n`{protection_error}`",
                        chat_target=chat_id,
                    )
                return False

            trade["is_real"] = True
            trade["order_id"] = order_id
            trade["protection_ok"] = True
            session["paper_positions"].append(trade)
            save_session(chat_id)
        except Exception as exc:
            logger.exception("Real order failed for %s: %s", symbol, exc)
            send_telegram_msg(f"❌ خطا در ثبت سفارش واقعی `{symbol}`: {exc}", chat_target=chat_id, parse_mode=None)
            return False
    else:
        available = session["paper_balance"] - reserved_margin(session)
        if available < final_margin:
            return False
        session["paper_positions"].append(trade)
        save_session(chat_id)

    df_chart = get_crypto_klines(symbol, interval_type=session["timeframe"] if session["timeframe"] != "multi" else "5min", limit=80)
    if not df_chart.empty:
        df_chart = calculate_indicators(df_chart)
    generate_and_send_trade_chart(chat_id, symbol, df_chart, trade)
    return True


def close_position_manually(chat_id, pos, current_price=None, reason="manual"):
    session = get_user_session(chat_id)
    if pos not in session["paper_positions"]:
        return False

    if pos.get("is_real"):
        if not exchange:
            send_telegram_msg("❌ اتصال CoinEx در دسترس نیست؛ پوزیشن واقعی بسته نشد.", chat_target=chat_id)
            return False
        try:
            market_symbol = sanitize_market_symbol(pos["symbol"])
            amount = float(pos.get("amount") or 0)
            if amount <= 0:
                live_pos = get_exchange_position(pos["symbol"])
                amount = abs(float((live_pos or {}).get("contracts") or (live_pos or {}).get("amount") or 0))
            if amount <= 0:
                send_telegram_msg(f"⚠️ مقدار پوزیشن `{pos['symbol']}` برای بستن پیدا نشد.", chat_target=chat_id)
                return False
            close_result = exchange.close_position(
                market_symbol,
                None,
                {"type": "market", "amount": amount},
            )
            current_price = float(close_result.get("average") or close_result.get("price") or get_latest_price(pos["symbol"]) or pos["entry_price"])
        except Exception as exc:
            send_telegram_msg(f"❌ خطا در بستن پوزیشن واقعی `{pos['symbol']}`: {exc}", chat_target=chat_id, parse_mode=None)
            return False
    else:
        if current_price is None:
            current_price = get_latest_price(pos["symbol"])
        if current_price is None:
            df = get_crypto_klines(pos["symbol"], interval_type=pos.get("timeframe", session["timeframe"]) if pos.get("timeframe") != "multi" else "5min", limit=5)
            current_price = float(df.iloc[-1]["close"]) if not df.empty else float(pos["entry_price"])

    entry = float(pos["entry_price"])
    current = float(current_price)
    if side_is_long(pos["side"]):
        raw_pnl = (current - entry) / entry
    else:
        raw_pnl = (entry - current) / entry
    pnl_usdt = float(pos.get("margin", 0)) * raw_pnl * float(pos.get("leverage", 1))

    if not pos.get("is_real"):
        session["paper_balance"] += pnl_usdt

    pos["pnl_usdt"] = pnl_usdt
    pos["close_timestamp"] = time.time()
    pos["close_price"] = current
    pos["close_reason"] = reason

    session["cooldowns"][pos["symbol"]] = time.time() + 300
    session["closed_positions"].append(pos.copy())
    session["paper_positions"].remove(pos)
    save_session(chat_id)

    mode_text = "واقعی (CoinEx)" if pos.get("is_real") else "کاغذی"
    send_telegram_msg(
        f"📌 *پوزیشن {mode_text} بسته شد.*\n"
        f"• نماد: `{pos['symbol']}`\n"
        f"• قیمت خروج: `{fmt_p(current)}`\n"
        f"• سود/زیان: `{pnl_usdt:+.2f} USDT`\n"
        f"• علت: `{reason}`",
        chat_target=chat_id,
    )
    return True


def update_open_positions(chat_id):
    session = get_user_session(chat_id)
    if not session["paper_positions"]:
        return

    if session["trading_mode"] == "REAL":
        sync_real_positions(chat_id)
        # Trailing is controlled on the exchange; local loop only moves SL upward once activated.
        for pos in session["paper_positions"][:]:
            if not pos.get("is_real"):
                continue
            price = get_latest_price(pos["symbol"])
            if price is None:
                continue
            entry = float(pos["entry_price"])
            margin = float(pos["margin"])
            lev = float(pos["leverage"])
            pnl_pct = ((price - entry) / entry) if side_is_long(pos["side"]) else ((entry - price) / entry)
            pnl = margin * pnl_pct * lev
            pos["last_unrealized_pnl"] = pnl
            if session["filters"].get("trailing_stop", True) and not pos.get("trailing_activated"):
                if pnl >= margin * 0.10:
                    new_sl = entry
                    ok, err = modify_exchange_stop_loss(pos["symbol"], new_sl)
                    if ok:
                        pos["sl"] = new_sl
                        pos["trailing_activated"] = True
                        send_telegram_msg(
                            f"🛡️ *Trailing Stop فعال شد*\n• نماد: `{pos['symbol']}`\n• SL روی سر‌به‌سر قرار گرفت.",
                            chat_target=chat_id,
                        )
                    else:
                        logger.warning("Could not move real SL for %s: %s", pos["symbol"], err)
        save_session(chat_id)
        return

    # PAPER mode: local price checks.
    for pos in session["paper_positions"][:]:
        df = get_crypto_klines(
            pos["symbol"],
            interval_type=pos.get("timeframe", session["timeframe"]) if pos.get("timeframe") != "multi" else "5min",
            limit=5,
        )
        if df.empty:
            continue
        candle = df.iloc[-1]
        high, low = float(candle["high"]), float(candle["low"])
        current_price = float(candle["close"])

        if side_is_long(pos["side"]):
            current_pnl = ((current_price - float(pos["entry_price"])) / float(pos["entry_price"])) * float(pos["leverage"]) * float(pos["margin"])
        else:
            current_pnl = ((float(pos["entry_price"]) - current_price) / float(pos["entry_price"])) * float(pos["leverage"]) * float(pos["margin"])

        # Move local stop to break-even after +10% on margin.
        if session["filters"].get("trailing_stop", True) and not pos.get("trailing_activated"):
            if current_pnl >= float(pos["margin"]) * 0.10:
                pos["sl"] = float(pos["entry_price"])
                pos["trailing_activated"] = True
                send_telegram_msg(
                    f"🛡️ *تریلینگ استاپ فعال شد*\n• نماد: `{pos['symbol']}`\n• حد ضرر به سر‌به‌سر منتقل شد.",
                    chat_target=chat_id,
                )

        closed_reason = None
        if side_is_long(pos["side"]):
            if high >= float(pos["tp"]):
                closed_reason = "TP"
                exit_price = float(pos["tp"])
            elif low <= float(pos["sl"]):
                closed_reason = "SL"
                exit_price = float(pos["sl"])
            else:
                exit_price = current_price
        else:
            if low <= float(pos["tp"]):
                closed_reason = "TP"
                exit_price = float(pos["tp"])
            elif high >= float(pos["sl"]):
                closed_reason = "SL"
                exit_price = float(pos["sl"])
            else:
                exit_price = current_price

        if closed_reason:
            close_position_manually(chat_id, pos, current_price=exit_price, reason=closed_reason)

    save_session(chat_id)


# -----------------------------------------------------------------------------
# Signal scan
# -----------------------------------------------------------------------------
async def check_symbol_async(session_http, chat_id, coin_symbol):
    session = get_user_session(chat_id)
    if not session["is_bot_active"] or session["daily_stopped"]:
        return
    if not apply_daily_loss_guard(chat_id):
        return

    cooldown_until = float(session.get("cooldowns", {}).get(coin_symbol, 0))
    if time.time() < cooldown_until:
        return

    tf = session["timeframe"]
    strat = session["active_strategy"]
    try:
        market_data = {}
        if tf == "multi" or strat == "multi":
            for tf_key, tf_val in [("1d", "1day"), ("4h", "4hour"), ("1h", "1hour"), ("15m", "15min"), ("5m", "5min")]:
                df_t = await get_crypto_klines_async(session_http, coin_symbol, interval_type=tf_val, limit=120)
                if not df_t.empty:
                    ind = calculate_indicators(df_t)
                    if len(ind) >= 60:
                        market_data[tf_key] = ind
            df_primary = market_data.get("5m")
            if df_primary is None or df_primary.empty or len(df_primary) < 60:
                return
            primary_tf = "5min"
            timeframe_mode = "multi"
        else:
            df_primary = await get_crypto_klines_async(session_http, coin_symbol, interval_type=tf, limit=160)
            if df_primary.empty or len(df_primary) < 60:
                return
            df_primary = calculate_indicators(df_primary)
            primary_tf = tf
            timeframe_mode = "single"

        signal, reason = get_signal_with_reason(
            df_primary,
            market_data_dict=market_data,
            timeframe_mode=timeframe_mode,
            timeframe=primary_tf,
            strategy_type=strat,
            filters=session["filters"],
            strategy_config=session["strategy_config"],
        )
        if not signal:
            return

        # Always use the last fully closed candle as signal source.
        curr = df_primary.iloc[-2]
        close_p = float(curr["close"])
        atr = float(curr["atr"])
        if not math.isfinite(atr) or atr <= 0:
            return

        params = get_strategy_params(primary_tf, session["strategy_config"])
        if signal == "BUY":
            sl = close_p - (atr * params["sl"])
            tp = close_p + (atr * params["tp"])
            execute_trade(chat_id, coin_symbol, "BUY (Long)", close_p, sl, tp, reason)
        elif signal == "SELL":
            sl = close_p + (atr * params["sl"])
            tp = close_p - (atr * params["tp"])
            execute_trade(chat_id, coin_symbol, "SELL (Short)", close_p, sl, tp, reason)
    except Exception as exc:
        logger.exception("Scan error %s/%s: %s", chat_id, coin_symbol, exc)


def analyze_symbol_detailed(chat_id, text_val):
    session = get_user_session(chat_id)
    tf = session["timeframe"]
    actual_tf = "5min" if tf == "multi" else tf
    df = get_crypto_klines(text_val, interval_type=actual_tf, limit=160)
    if df.empty or len(df) < 60:
        return f"❌ اطلاعات کافی برای نماد `{text_val}` یافت نشد."

    df = calculate_indicators(df)
    curr = df.iloc[-2]
    adx_val = float(curr.get("adx", 20))
    rsi_val = float(curr.get("rsi", 50))

    res_trend, reason_trend = strategy_trend_following(df, actual_tf, session["filters"], session["strategy_config"])
    res_breakout, reason_breakout = strategy_breakout(df, session["filters"], session["strategy_config"])
    res_rsi, reason_rsi = strategy_mean_reversion(df, session["filters"], session["strategy_config"])

    return (
        f"🔍 *تحلیل جامع `{text_val}`*\n\n"
        f"• قیمت بسته‌شده اخیر: `{fmt_p(curr['close'])}`\n"
        f"• EMA20: `{fmt_p(curr['ema20'])}` | EMA50: `{fmt_p(curr['ema50'])}`\n"
        f"• ADX: `{adx_val:.1f}` | RSI: `{rsi_val:.1f}`\n"
        f"• ATR: `{fmt_p(curr['atr'])}` | Volume Ratio: `{float(curr.get('volume_ratio', 0)):.2f}x`\n\n"
        f"📋 *بررسی استراتژی‌ها:*\n"
        f"1️⃣ Trend: `{res_trend or 'بدون سیگنال'}` — {reason_trend}\n"
        f"2️⃣ Breakout: `{res_breakout or 'بدون سیگنال'}` — {reason_breakout}\n"
        f"3️⃣ Mean Reversion: `{res_rsi or 'بدون سیگنال'}` — {reason_rsi}\n\n"
        f"💡 *ارزیابی:* "
        + (
            "روند پرقدرت؛ Trend/Breakout مناسب‌تر است."
            if adx_val > 25
            else "بازار کم‌روند؛ Mean Reversion با تأیید مناسب‌تر است."
            if adx_val < 20
            else "فاز گذار؛ منتظر تأیید بهتر بمانید."
        )
    )


# -----------------------------------------------------------------------------
# Main menu / reports
# -----------------------------------------------------------------------------
def generate_market_health_report(session):
    benchmarks = ["BTC", "ETH", "SOL", "BNB", "XRP"]
    up_count = 0
    total_adx = 0.0
    valid_coins = 0
    tf = session["timeframe"]
    actual_tf = "5min" if tf == "multi" else tf

    for sym in benchmarks:
        df = get_crypto_klines(sym, interval_type=actual_tf, limit=120)
        if df.empty or len(df) < 60:
            continue
        df = calculate_indicators(df)
        curr = df.iloc[-2]
        if curr["close"] > curr["ema50"]:
            up_count += 1
        total_adx += float(curr["adx"])
        valid_coins += 1

    if valid_coins == 0:
        return "❌ اطلاعات کافی بازار در دسترس نیست."

    avg_adx = total_adx / valid_coins
    bullish_pct = (up_count / valid_coins) * 100
    if avg_adx > 25:
        regime = "رونددار پرقدرت"
        rec = "Trend / Breakout"
    elif avg_adx >= 20:
        regime = "فاز گذار"
        rec = "احتیاط و تأیید بیشتر"
    else:
        regime = "رنج / کم‌روند"
        rec = "Mean Reversion با تأیید"
    trend = "صعودی" if bullish_pct >= 60 else "نزولی" if bullish_pct <= 40 else "مخلوط"

    return (
        f"📊 *گزارش هوشمند وضعیت بازار*\n\n"
        f"• روند کلی: `{trend}` ({up_count}/{valid_coins} ارز بالای EMA50)\n"
        f"• میانگین ADX: `{avg_adx:.1f}`\n"
        f"• رژیم بازار: `{regime}`\n"
        f"• پیشنهاد: `{rec}`"
    )


def send_main_menu(chat_id, message_id=None):
    session = get_user_session(chat_id)
    mode = "معامله واقعی" if session["trading_mode"] == "REAL" else "معامله کاغذی"
    status = "فعال (اسکن)" if session["is_bot_active"] else "متوقف"
    max_pos = session["max_open_positions"] if session["max_open_positions"] > 0 else "نامحدود"
    balance = get_exchange_balance_usdt() if session["trading_mode"] == "REAL" and exchange else session["paper_balance"]

    msg = (
        f"📊 *پنل مدیریت ربات معامله‌گر*\n\n"
        f"• حالت: `{mode}`\n"
        f"• وضعیت: `{status}`\n"
        f"• استراتژی: `{session['active_strategy'].upper()}`\n"
        f"• موجودی/Equity: `${balance:.2f} USDT`\n"
        f"• مارجین سقف هر معامله: `${session['trade_amount_usdt']:.0f}`\n"
        f"• اهرم: `{session['leverage']}X` | پوزیشن: `{max_pos}`\n"
        f"• تایم‌فریم: `{TF_DISPLAY.get(session['timeframe'], session['timeframe'])}`\n"
        f"• واچ‌لیست: `{len(session['active_symbols'])}`\n"
        f"• ریسک هر معامله: `{session['risk_per_trade_pct']:.2f}%`\n"
        f"• سقف ضرر روزانه: `{session['daily_loss_limit_pct']:.2f}%`"
    )
    send_telegram_msg(msg, chat_target=chat_id, reply_markup=get_main_menu_keyboard(session["is_bot_active"]), message_id=message_id)


# -----------------------------------------------------------------------------
# Command processing
# -----------------------------------------------------------------------------
def process_command(data, chat_id, message_id=None):
    session = get_user_session(chat_id)
    cmd = (data or "").strip()
    cmd_lower = cmd.lower()

    if cmd_lower == "/cancel":
        session["user_state"] = None
        save_session(chat_id)
        send_main_menu(chat_id, message_id)
        return

    if cmd_lower == "/confirm_close_all":
        session["is_bot_active"] = False
        count = len(session["paper_positions"])
        for pos in session["paper_positions"][:]:
            close_position_manually(chat_id, pos, reason="close_all")
        send_telegram_msg(f"🛑 اسکن متوقف شد و `{count}` پوزیشن پردازش شد.", chat_target=chat_id)
        send_main_menu(chat_id)
        return

    if cmd_lower == "/close_all_prompt":
        send_telegram_msg(
            "⚠️ *تأیید لازم است*\n\nتمام پوزیشن‌های باز بسته خواهند شد و اسکن متوقف می‌شود.",
            chat_target=chat_id,
            reply_markup=get_confirm_close_all_keyboard(),
        )
        return

    if cmd_lower.startswith("/close_") and cmd_lower not in ("/close_shorts", "/close_longs", "/close_all", "/close_all_prompt"):
        symbol_to_close = cmd_lower.replace("/close_", "").upper()
        found = False
        for pos in session["paper_positions"][:]:
            if pos["symbol"] == symbol_to_close:
                found = close_position_manually(chat_id, pos, reason="manual")
                break
        if not found:
            send_telegram_msg(f"❌ پوزیشنی با نماد `{symbol_to_close}` یافت نشد.", chat_target=chat_id)
        return

    if cmd_lower == "/close_shorts":
        shorts = [p for p in session["paper_positions"] if not side_is_long(p["side"])]
        if not shorts:
            send_telegram_msg("❌ پوزیشن شورت فعالی وجود ندارد.", chat_target=chat_id)
            return
        for pos in shorts[:]:
            close_position_manually(chat_id, pos, reason="manual_close_shorts")
        return

    if cmd_lower == "/close_longs":
        longs = [p for p in session["paper_positions"] if side_is_long(p["side"])]
        if not longs:
            send_telegram_msg("❌ پوزیشن لانگ فعالی وجود ندارد.", chat_target=chat_id)
            return
        for pos in longs[:]:
            close_position_manually(chat_id, pos, reason="manual_close_longs")
        return

    setting_commands = [
        "/check_wizard", "مدیریت تنظیمات معامله", "/mode_paper", "/mode_real",
        "/set_bal_", "/set_margin_", "/set_lev_", "/set_max_", "/set_tf_",
    ]
    if session["is_bot_active"] and any(cmd_lower.startswith(sc) or sc in cmd_lower for sc in setting_commands):
        send_telegram_msg("⚠️ *اسکن بازار فعال است!*\n\nبرای تغییر تنظیمات ابتدا اسکن را متوقف کنید.", chat_target=chat_id)
        return

    if "منوی اصلی" in cmd or cmd_lower == "/menu":
        session["user_state"] = None
        send_main_menu(chat_id, message_id)
        return

    if "گزارش وضعیت بازار" in cmd or cmd_lower == "/market_report":
        send_telegram_msg("🔄 در حال تحلیل بازار...", chat_target=chat_id)
        send_telegram_msg(generate_market_health_report(session), chat_target=chat_id)
        return

    if "انتخاب استراتژی" in cmd or cmd_lower == "/strategies_menu":
        send_telegram_msg(
            "📊 *انتخاب استراتژی معاملاتی*",
            chat_target=chat_id,
            reply_markup=get_strategies_selection_keyboard(),
        )
        return

    if "تنظیم پارامترها" in cmd or cmd_lower == "/params_menu":
        send_telegram_msg(
            "🎛️ *مدیریت پارامترهای استراتژی*",
            chat_target=chat_id,
            reply_markup=get_params_menu_keyboard(session),
        )
        return

    if cmd_lower == "/adx_up":
        session["strategy_config"]["min_adx"] = min(50.0, float(session["strategy_config"]["min_adx"]) + 1)
        save_session(chat_id)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(session), message_id=message_id)
        return
    if cmd_lower == "/adx_down":
        session["strategy_config"]["min_adx"] = max(10.0, float(session["strategy_config"]["min_adx"]) - 1)
        save_session(chat_id)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(session), message_id=message_id)
        return
    if cmd_lower == "/sl_up":
        session["strategy_config"]["sl_multiplier"] = round(float(session["strategy_config"]["sl_multiplier"]) + 0.2, 1)
        save_session(chat_id)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(session), message_id=message_id)
        return
    if cmd_lower == "/sl_down":
        session["strategy_config"]["sl_multiplier"] = max(0.5, round(float(session["strategy_config"]["sl_multiplier"]) - 0.2, 1))
        save_session(chat_id)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(session), message_id=message_id)
        return
    if cmd_lower == "/tp_up":
        session["strategy_config"]["tp_multiplier"] = round(float(session["strategy_config"]["tp_multiplier"]) + 0.5, 1)
        save_session(chat_id)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(session), message_id=message_id)
        return
    if cmd_lower == "/tp_down":
        session["strategy_config"]["tp_multiplier"] = max(0.5, round(float(session["strategy_config"]["tp_multiplier"]) - 0.5, 1))
        save_session(chat_id)
        send_telegram_msg("🎛️ *تنظیمات استراتژی*", chat_target=chat_id, reply_markup=get_params_menu_keyboard(session), message_id=message_id)
        return

    if "پوزیشن‌های باز" in cmd or cmd_lower == "/open_positions":
        if session["paper_positions"]:
            lines = [f"🔄 *پوزیشن‌های باز ({len(session['paper_positions'])})*"]
            for p in session["paper_positions"]:
                icon = "🟢" if side_is_long(p["side"]) else "🔴"
                mode = "واقعی" if p.get("is_real") else "کاغذی"
                lines.append(
                    f"{icon} `{p['symbol']}` | {p['side']} | {mode}\n"
                    f"  ورود: `{fmt_p(p['entry_price'])}` | SL: `{fmt_p(p['sl'])}` | TP: `{fmt_p(p['tp'])}`\n"
                    f"  مارجین: `${float(p['margin']):.2f}` | اهرم: `{p['leverage']}X`"
                )
            send_telegram_msg("\n".join(lines), chat_target=chat_id, reply_markup=get_positions_keyboard(session["paper_positions"]))
        else:
            send_telegram_msg("پوزیشن بازی وجود ندارد.", chat_target=chat_id)
        return

    if "گزارش عملکرد" in cmd or cmd_lower == "/performance":
        closed = session["closed_positions"]
        wins = [p for p in closed if float(p.get("pnl_usdt", 0)) > 0]
        losses = [p for p in closed if float(p.get("pnl_usdt", 0)) <= 0]
        total_pnl = sum(float(p.get("pnl_usdt", 0)) for p in closed)
        long_count = sum(1 for p in closed if side_is_long(p["side"]))
        short_count = len(closed) - long_count
        win_rate = (len(wins) / len(closed) * 100) if closed else 0
        send_telegram_msg(
            f"📈 *گزارش عملکرد*\n\n"
            f"• کل معاملات بسته‌شده: `{len(closed)}`\n"
            f"• برد: `{len(wins)}` | باخت: `{len(losses)}`\n"
            f"• Win Rate: `{win_rate:.1f}%`\n"
            f"• Long: `{long_count}` | Short: `{short_count}`\n"
            f"• سود/زیان خالص: `{total_pnl:+.2f} USDT`\n"
            f"• موجودی PAPER: `${session['paper_balance']:.2f}`",
            chat_target=chat_id,
        )
        return

    if "مدیریت تنظیمات معامله" in cmd or cmd_lower == "/check_wizard":
        send_telegram_msg(
            "⚙️ *مدیریت تنظیمات معامله*\n\nپارامتر مورد نظر را انتخاب کنید:",
            chat_target=chat_id,
            reply_markup=get_margin_keyboard(),
        )
        return

    if "تنظیمات فیلترها" in cmd or cmd_lower == "/filters_menu":
        send_telegram_msg(
            "⚙️ *مدیریت فیلترهای استراتژی*",
            chat_target=chat_id,
            reply_markup=get_filters_menu_keyboard(session),
        )
        return

    if cmd_lower in ("/toggle_vol", "/toggle_trail", "/toggle_candle", "/toggle_short", "/toggle_buy"):
        mapping = {
            "/toggle_vol": "volume_filter",
            "/toggle_trail": "trailing_stop",
            "/toggle_candle": "candlestick_filter",
            "/toggle_short": "no_short_filter",
            "/toggle_buy": "no_buy_filter",
        }
        key = mapping[cmd_lower]
        session["filters"][key] = not bool(session["filters"].get(key, False))
        save_session(chat_id)
        send_telegram_msg("⚙️ *تنظیمات فیلترها*", chat_target=chat_id, reply_markup=get_filters_menu_keyboard(session), message_id=message_id)
        return

    if cmd_lower == "/toggle_active" or any(x in cmd for x in ["شروع اسکن", "توقف اسکن", "روشن کردن اسکن"]):
        if not session["is_bot_active"]:
            if session["daily_stopped"]:
                session["daily_start_balance"] = get_exchange_balance_usdt() if session["trading_mode"] == "REAL" and exchange else session["paper_balance"]
                session["daily_stopped"] = False
            if session.get("real_reconciliation_required"):
                sync_real_positions(chat_id)
                if session.get("real_reconciliation_required"):
                    send_telegram_msg("❌ ابتدا پوزیشن‌های واقعی ناشناخته را در CoinEx بررسی و وضعیت ربات را هماهنگ کنید.", chat_target=chat_id)
                    return
            if session["trading_mode"] == "REAL" and not exchange:
                send_telegram_msg("❌ اتصال CoinEx برای حالت واقعی موجود نیست.", chat_target=chat_id)
                return
        session["is_bot_active"] = not session["is_bot_active"]
        save_session(chat_id)
        send_main_menu(chat_id, message_id)
        return

    if cmd_lower == "/start":
        session["is_bot_active"] = False
        session["daily_stopped"] = False
        session["user_state"] = None
        save_session(chat_id)
        send_telegram_msg("🤖 *به ربات معامله‌گر خوش آمدید.*\n\nنوع حساب را انتخاب کنید:", chat_target=chat_id, reply_markup=get_start_keyboard(), message_id=message_id)
        return

    if cmd_lower == "/mode_paper":
        session["trading_mode"] = "PAPER"
        send_telegram_msg("⚙️ موجودی اولیه حساب کاغذی را انتخاب کنید:", chat_target=chat_id, reply_markup=get_balance_keyboard(), message_id=message_id)
        return

    if cmd_lower.startswith("/set_bal_"):
        try:
            bal_val = float(cmd_lower.replace("/set_bal_", ""))
        except ValueError:
            return
        session["paper_balance"] = bal_val
        session["daily_start_balance"] = bal_val
        session["daily_stopped"] = False
        save_session(chat_id)
        send_telegram_msg("✅ موجودی ثبت شد.\n\n⚙️ مقدار مارجین هر معامله:", chat_target=chat_id, reply_markup=get_margin_keyboard(), message_id=message_id)
        return

    if cmd_lower == "/mode_real":
        if not exchange:
            send_telegram_msg("❌ اتصال CoinEx برقرار نیست یا API Key/Secret معتبر نیست.", chat_target=chat_id)
            return
        bal = get_exchange_balance_usdt()
        if bal <= 0:
            send_telegram_msg("❌ موجودی USDT واقعی صفر است یا دسترسی API صحیح نیست.", chat_target=chat_id)
            return
        session["trading_mode"] = "REAL"
        session["paper_balance"] = bal
        session["daily_start_balance"] = bal
        session["daily_stopped"] = False
        session["real_reconciliation_required"] = False
        sync_real_positions(chat_id)
        save_session(chat_id)
        send_telegram_msg(f"🔴 موجودی واقعی: `{bal:.2f} USDT`\n\n⚙️ مارجین هر معامله:", chat_target=chat_id, reply_markup=get_margin_keyboard(), message_id=message_id)
        return

    if cmd_lower.startswith("/set_strat_"):
        strat_key = cmd_lower.replace("/set_strat_", "")
        if strat_key in ["dynamic", "trend", "breakout", "mean_reversion", "multi"]:
            session["active_strategy"] = strat_key
            save_session(chat_id)
            send_telegram_msg(f"✅ استراتژی فعال: `{strat_key.upper()}`", chat_target=chat_id)
            send_main_menu(chat_id, message_id)
        return

    if cmd_lower == "/analyze_single":
        session["user_state"] = "WAITING_FOR_SINGLE_SYMBOL"
        save_session(chat_id)
        send_telegram_msg("🔍 نام رمزارز را ارسال کنید؛ مثال `BTC`:", chat_target=chat_id)
        return

    if cmd_lower == "/watchlist_list":
        symbols = session["active_symbols"]
        preview = ", ".join(symbols[:120])
        suffix = " ..." if len(symbols) > 120 else ""
        send_telegram_msg(f"📋 *واچ‌لیست ({len(symbols)})*\n\n`{preview}{suffix}`", chat_target=chat_id)
        return

    if cmd_lower == "/strategy_desc_menu":
        send_telegram_msg("📚 *توضیح پارامترها بر اساس تایم‌فریم*", chat_target=chat_id, reply_markup=get_strategies_menu_keyboard())
        return

    if cmd_lower == "/manage_watchlist":
        send_telegram_msg(
            f"📋 *مدیریت واچ‌لیست*\nتعداد: `{len(session['active_symbols'])}`",
            chat_target=chat_id,
            reply_markup=get_watchlist_manage_keyboard(),
        )
        return

    if cmd_lower == "/add_symbol_prompt":
        session["user_state"] = "WAITING_FOR_ADD_SYMBOL"
        save_session(chat_id)
        send_telegram_msg("➕ نماد جدید را ارسال کنید:", chat_target=chat_id)
        return

    if cmd_lower == "/remove_symbol_prompt":
        session["user_state"] = "WAITING_FOR_REMOVE_SYMBOL"
        save_session(chat_id)
        send_telegram_msg("➖ نماد برای حذف را ارسال کنید:", chat_target=chat_id)
        return

    if cmd_lower.startswith("/desc_"):
        tf = cmd_lower.replace("/desc_", "")
        tf_map = {"5min": "5min", "15min": "15min", "1hour": "1hour", "multi": "multi"}
        if tf in tf_map:
            send_telegram_msg(get_strategy_description(tf_map[tf], session["strategy_config"], session["filters"]), chat_target=chat_id)
        return

    if cmd_lower in ["/set_margin_10", "/set_margin_25", "/set_margin_50", "/set_margin_100"]:
        session["trade_amount_usdt"] = float(cmd_lower.replace("/set_margin_", ""))
        save_session(chat_id)
        send_telegram_msg("⚙️ ضریب اهرم:", chat_target=chat_id, reply_markup=get_leverage_keyboard(), message_id=message_id)
        return

    if cmd_lower in ["/set_lev_3", "/set_lev_5", "/set_lev_10"]:
        session["leverage"] = int(cmd_lower.replace("/set_lev_", ""))
        save_session(chat_id)
        send_telegram_msg("⚙️ حداکثر تعداد پوزیشن‌های هم‌زمان:", chat_target=chat_id, reply_markup=get_max_positions_keyboard(), message_id=message_id)
        return

    if cmd_lower.startswith("/set_max_"):
        session["max_open_positions"] = int(cmd_lower.replace("/set_max_", ""))
        save_session(chat_id)
        send_telegram_msg("⚙️ تایم‌فریم معاملاتی:", chat_target=chat_id, reply_markup=get_timeframe_keyboard(), message_id=message_id)
        return

    if cmd_lower in ["/set_tf_5m", "/set_tf_15m", "/set_tf_1h", "/set_tf_4h", "/set_tf_1d", "/set_tf_multi"]:
        session["timeframe"] = {
            "/set_tf_5m": "5min",
            "/set_tf_15m": "15min",
            "/set_tf_1h": "1hour",
            "/set_tf_4h": "4hour",
            "/set_tf_1d": "1day",
            "/set_tf_multi": "multi",
        }[cmd_lower]
        save_session(chat_id)
        send_telegram_msg("🚀 تنظیمات اعمال شد.", chat_target=chat_id)
        send_main_menu(chat_id, message_id)
        return

    if cmd_lower == "/daily_reset":
        session["daily_start_balance"] = get_exchange_balance_usdt() if session["trading_mode"] == "REAL" and exchange else session["paper_balance"]
        session["daily_stopped"] = False
        save_session(chat_id)
        send_telegram_msg("✅ مبنای Daily Loss Limit ریست شد.", chat_target=chat_id)
        return


def handle_free_text(session, chat_id, text_val):
    text_val = text_val.strip().upper()
    if session["user_state"] == "WAITING_FOR_SINGLE_SYMBOL":
        report_text = analyze_symbol_detailed(chat_id, text_val)
        send_telegram_msg(report_text, chat_target=chat_id)
        session["user_state"] = None
        save_session(chat_id)
        return
    if session["user_state"] == "WAITING_FOR_ADD_SYMBOL":
        if text_val not in session["active_symbols"] and len(text_val) <= 12:
            test = get_crypto_klines(text_val, "5min", 40)
            if not test.empty:
                session["active_symbols"].append(text_val)
                save_session(chat_id)
                send_telegram_msg(f"✅ `{text_val}` اضافه شد.", chat_target=chat_id)
            else:
                send_telegram_msg(f"❌ بازار Futures برای `{text_val}` پیدا نشد.", chat_target=chat_id)
        else:
            send_telegram_msg("⚠️ نماد از قبل وجود دارد یا نام نامعتبر است.", chat_target=chat_id)
        session["user_state"] = None
        save_session(chat_id)
        return
    if session["user_state"] == "WAITING_FOR_REMOVE_SYMBOL":
        if text_val in session["active_symbols"]:
            session["active_symbols"].remove(text_val)
            save_session(chat_id)
            send_telegram_msg(f"🗑️ `{text_val}` حذف شد.", chat_target=chat_id)
        else:
            send_telegram_msg("❌ نماد در واچ‌لیست نیست.", chat_target=chat_id)
        session["user_state"] = None
        save_session(chat_id)
        return

    if 2 <= len(text_val) <= 12 and (text_val.isalpha() or text_val.replace("1", "").isalnum()):
        send_telegram_msg(analyze_symbol_detailed(chat_id, text_val), chat_target=chat_id)
    else:
        process_command(text_val, chat_id)


# -----------------------------------------------------------------------------
# Telegram listener / scanning loop
# -----------------------------------------------------------------------------
def telegram_listener():
    offset = None
    while True:
        try:
            if not TELEGRAM_TOKEN:
                time.sleep(5)
                continue
            params = {"timeout": 25}
            if offset is not None:
                params["offset"] = offset
            res = requests.get(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                params=params,
                timeout=30,
            )
            if res.status_code != 200:
                time.sleep(2)
                continue

            for update in res.json().get("result", []):
                offset = update["update_id"] + 1
                callback = update.get("callback_query") or {}
                message = callback.get("message") or update.get("message") or {}
                chat_id = (message.get("chat") or {}).get("id")
                if not chat_id or not is_allowed_chat(chat_id):
                    if callback.get("id"):
                        answer_callback(callback["id"])
                    continue

                session = get_user_session(chat_id)
                data = callback.get("data") or (update.get("message") or {}).get("text")
                message_id = message.get("message_id")
                if callback.get("id"):
                    answer_callback(callback["id"])

                if not data:
                    continue

                if callback:
                    process_command(data, chat_id, message_id=message_id)
                else:
                    handle_free_text(session, chat_id, data)
        except Exception as exc:
            logger.exception("Telegram listener error: %s", exc)
            time.sleep(2)


async def async_main_scan_loop():
    global ASYNC_SEMAPHORE
    ASYNC_SEMAPHORE = asyncio.Semaphore(MAX_ASYNC_REQUESTS)

    while True:
        try:
            for chat_id, session in list(USER_SESSIONS.items()):
                if session["paper_positions"]:
                    update_open_positions(chat_id)

            timeout = aiohttp.ClientTimeout(total=8)
            connector = aiohttp.TCPConnector(limit=MAX_ASYNC_REQUESTS, ttl_dns_cache=300)
            async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session_http:
                active_tasks = []
                for chat_id, session in list(USER_SESSIONS.items()):
                    if session["is_bot_active"] and not session["daily_stopped"]:
                        symbols = list(session["active_symbols"])
                        # Avoid opening many positions concurrently for one user.
                        if session["max_open_positions"] > 0:
                            remaining = max(1, session["max_open_positions"] - len(session["paper_positions"]))
                        else:
                            remaining = len(symbols)
                        for sym in symbols:
                            active_tasks.append(check_symbol_async(session_http, chat_id, sym))
                        # all symbols are scanned; execute_trade itself caps entries.
                if active_tasks:
                    await asyncio.gather(*active_tasks, return_exceptions=True)
        except Exception as exc:
            logger.exception("Main scan loop error: %s", exc)
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


def bot_loop():
    time.sleep(3)
    asyncio.run(async_main_scan_loop())


# -----------------------------------------------------------------------------
# Flask / startup
# -----------------------------------------------------------------------------
@app.route("/")
def home():
    active_count = sum(1 for s in USER_SESSIONS.values() if s.get("is_bot_active"))
    return f"OK - Sessions: {len(USER_SESSIONS)} | Active Bots: {active_count}", 200


@app.route("/health")
def health():
    return "OK", 200


@app.route("/status")
def status():
    return {
        "status": "ok",
        "sessions": len(USER_SESSIONS),
        "active_bots": sum(1 for s in USER_SESSIONS.values() if s.get("is_bot_active")),
        "coinex_connected": bool(exchange),
        "db_path": DB_PATH,
    }, 200


if __name__ == "__main__":
    init_db()
    load_sessions()
    ASYNC_SEMAPHORE = asyncio.Semaphore(MAX_ASYNC_REQUESTS)
    logger.info("Loaded %s saved sessions", len(USER_SESSIONS))
    Thread(target=telegram_listener, daemon=True, name="telegram-listener").start()
    Thread(target=bot_loop, daemon=True, name="scanner").start()
    app.run(host="0.0.0.0", port=PORT, threaded=True)
