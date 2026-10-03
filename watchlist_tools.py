# -*- coding: utf-8 -*-
"""
اعتبارسنجی واچ‌لیست با فهرست *اسپات* صرافی‌ها (Binance / Bybit / KuCoin) - بدون API key و
بدون وابستگی به bot.py. هم داخل ربات استفاده می‌شود و هم به‌صورت CLI:

    python watchlist_tools.py            # گزارش: کدام نمادها روی اسپات نیستند و چه جایگزینی پیشنهاد می‌شود
    python watchlist_tools.py --json     # همان گزارش به‌صورت JSON

منطق: نمادی که روی هیچ‌کدام از منابع اسپات (USDT، وضعیت Trading) نیست حذف می‌شود و به‌جایش از
RESERVE_TOP_SYMBOLS (به ترتیب اولویت) نماد موجود اضافه می‌شود تا اندازه‌ی لیست حفظ شود.
اگر هیچ منبعی فهرست قابل‌اعتماد (≥ MIN_SANE_SYMBOLS نماد) برنگرداند، هیچ چیزی حذف نمی‌شود.
"""
import json
import os
import sys
import time

import requests

BINANCE_SPOT = os.environ.get('BINANCE_SPOT_URL', 'https://api.binance.com').rstrip('/')
BINANCE_VISION = os.environ.get('BINANCE_VISION_URL', 'https://data-api.binance.vision').rstrip('/')
BYBIT_PUBLIC = os.environ.get('BYBIT_PUBLIC_URL', 'https://api.bybit.com').rstrip('/')
KUCOIN_SPOT = os.environ.get('KUCOIN_SPOT_URL', 'https://api.kucoin.com/api/v1').rstrip('/')

MIN_SANE_SYMBOLS = 100
MAX_REMOVE_FRACTION = 0.6   # اگر بیش از ۶۰٪ لیست حذف شود، داده‌ی صرافی مشکوک است و هیچ حذفی انجام نمی‌شود

# نمادهای برتر (تقریباً به ترتیب ارزش بازار/نقدینگی) برای جایگزینی. استیبل‌کوین و توکن‌های wrapped ندارد.
# وجودشان روی اسپات از دانش عمومی است؛ ربات قبل از افزودن، با فهرست زنده‌ی صرافی‌ها فیلترشان می‌کند.
RESERVE_TOP_SYMBOLS = [
    'BTC', 'ETH', 'BNB', 'XRP', 'SOL', 'DOGE', 'TRX', 'ADA', 'LINK', 'AVAX', 'XLM', 'SUI', 'BCH', 'HBAR',
    'LTC', 'TON', 'DOT', 'UNI', 'AAVE', 'NEAR', 'ICP', 'ETC', 'APT', 'ONDO', 'POL', 'ARB', 'OP', 'ATOM',
    'FIL', 'INJ', 'TIA', 'SEI', 'RENDER', 'FET', 'WLD', 'TAO', 'ENA', 'JUP', 'PEPE', 'SHIB', 'BONK', 'WIF',
    'FLOKI', 'PENDLE', 'CRV', 'LDO', 'ALGO', 'VET', 'GRT', 'IMX', 'STX', 'SAND', 'MANA', 'AXS', 'GALA',
    'RUNE', 'EGLD', 'THETA', 'JTO', 'PYTH', 'CAKE', 'COMP', 'SNX', 'SUSHI', 'CHZ', 'ENS', 'LRC', 'ZEC',
    'DASH', 'NEO', 'IOTA', 'XTZ', 'KAVA', 'ZIL', 'ANKR', 'BAT', '1INCH', 'MASK', 'CELO', 'ZRO', 'PENGU',
    'TRUMP', 'VIRTUAL', 'S', 'KAITO', 'BERA', 'IP', 'PNUT', 'NEIRO', 'ORDI', 'WLFI', 'HYPE', 'PUMP',
]


def _get(url, params=None, timeout=12):
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_binance_spot(timeout=12):
    """{'binance': bases, ...}؛ اول api.binance.com و اگر نشد آینه‌ی data-api.binance.vision."""
    last = None
    for base_url in (BINANCE_SPOT, BINANCE_VISION):
        try:
            j = _get(f'{base_url}/api/v3/exchangeInfo', {'symbolStatus': 'TRADING'}, timeout)
            out = {str(s.get('baseAsset', '')).upper() for s in j.get('symbols') or []
                   if s.get('quoteAsset') == 'USDT' and s.get('status') == 'TRADING' and s.get('isSpotTradingAllowed') is not False}
            if out:
                return out
        except Exception as exc:  # noqa: BLE001
            last = exc
    raise RuntimeError(f'binance spot: {last}')


def fetch_bybit_spot(timeout=12):
    out, cursor = set(), None
    for _ in range(10):
        params = {'category': 'spot', 'limit': 1000}
        if cursor: params['cursor'] = cursor
        j = _get(f'{BYBIT_PUBLIC}/v5/market/instruments-info', params, timeout)
        if j.get('retCode') != 0:
            raise RuntimeError(f"bybit spot: retCode={j.get('retCode')}")
        res = j.get('result') or {}
        for s in res.get('list') or []:
            if s.get('quoteCoin') == 'USDT' and str(s.get('status', '')).lower() == 'trading':
                out.add(str(s.get('baseCoin', '')).upper())
        cursor = res.get('nextPageCursor')
        if not cursor: break
    return out


def fetch_kucoin_spot(timeout=12):
    base = KUCOIN_SPOT.replace('/api/v1', '')
    j = _get(f'{base}/api/v2/symbols', None, timeout)
    if j.get('code') != '200000':
        raise RuntimeError(f"kucoin spot: code={j.get('code')}")
    return {str(s.get('baseCurrency', '')).upper() for s in j.get('data') or []
            if s.get('quoteCurrency') == 'USDT' and s.get('enableTrading') is True}


def fetch_available(timeout=12):
    """(union, per_source, errors). منبعِ خراب نادیده گرفته می‌شود و خطایش در errors می‌آید."""
    per, errors = {}, {}
    for name, fn in (('binance', fetch_binance_spot), ('bybit', fetch_bybit_spot), ('kucoin', fetch_kucoin_spot)):
        try:
            per[name] = fn(timeout)
        except Exception as exc:  # noqa: BLE001
            errors[name] = str(exc)[:160]
    union = set().union(*per.values()) if per else set()
    return union, per, errors


def availability_is_sane(per_source):
    """فقط وقتی حذف کنیم که حداقل یک منبع فهرست بزرگ و معتبر داده باشد (وگرنه خرابیِ API به‌اشتباه لیست را خالی می‌کند)."""
    return any(len(v) >= MIN_SANE_SYMBOLS for v in per_source.values())


def plan_watchlist(candidates, reserve, available):
    """حذف نمادهای غیرموجود و جایگزینی با نمادهای برتر موجود؛ ترتیب و اندازه‌ی لیست حفظ می‌شود."""
    kept = [s for s in candidates if s in available]
    removed = [s for s in candidates if s not in available]
    present = set(kept)
    added = []
    for s in reserve:
        if len(added) >= len(removed): break
        if s in available and s not in present:
            added.append(s); present.add(s)
    return {'kept': kept, 'removed': removed, 'added': added, 'final': kept + added}


def plan_is_suspicious(plan, total):
    """حذفِ بیش‌ازحد یعنی احتمالاً فهرست صرافی ناقص/خراب برگشته، نه اینکه واقعاً اکثر نمادها delist شده باشند."""
    return total > 0 and len(plan['removed']) > MAX_REMOVE_FRACTION * total


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    candidates = _read_long_watchlist_from_bot()
    union, per, errors = fetch_available()
    report = {'generated_at': int(time.time()), 'sources_ok': {k: len(v) for k, v in per.items()}, 'sources_error': errors}
    if not availability_is_sane(per):
        report['note'] = 'هیچ منبعی فهرست معتبر نداد؛ چیزی حذف نمی‌شود (احتمالاً بلاک جغرافیایی یا قطعی شبکه).'
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 1
    plan = plan_watchlist(candidates, RESERVE_TOP_SYMBOLS, union)
    if plan_is_suspicious(plan, len(candidates)):
        report['note'] = f"بیش از {int(MAX_REMOVE_FRACTION * 100)}٪ لیست غایب بود ({len(plan['removed'])} از {len(candidates)})؛ داده‌ی صرافی مشکوک است و حذفی انجام نمی‌شود."
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 1
    report.update(removed=plan['removed'], added=plan['added'], kept_count=len(plan['kept']), final_count=len(plan['final']))
    report['per_source_missing'] = {k: [s for s in plan['final'] if s not in v] for k, v in per.items()}
    if '--json' in argv:
        report['final'] = plan['final']
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    print(f"منابع سالم: {report['sources_ok']}  |  منابع خراب: {errors or '-'}")
    print(f"لیست فعلی: {len(candidates)} نماد | حذف: {len(plan['removed'])} | جایگزین: {len(plan['added'])}")
    print('حذف‌شده (روی هیچ اسپاتی نیست):', ', '.join(plan['removed']) or '-')
    print('جایگزین‌شده (به ترتیب):', ', '.join(plan['added']) or '-')
    return 0


def _read_long_watchlist_from_bot():
    """LONG_WATCHLIST را بدون import کردن bot.py (که ccxt/flask می‌خواهد) از متن آن می‌خواند."""
    import ast
    here = os.path.dirname(os.path.abspath(__file__))
    tree = ast.parse(open(os.path.join(here, 'bot.py'), encoding='utf-8').read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'LONG_WATCHLIST' for t in node.targets):
            return list(ast.literal_eval(node.value))
    raise RuntimeError('LONG_WATCHLIST در bot.py پیدا نشد')


if __name__ == '__main__':
    sys.exit(main())
