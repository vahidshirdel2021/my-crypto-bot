# -*- coding: utf-8 -*-
"""
اعتبارسنجی واچ‌لیست با فهرست نمادهای صرافی‌ها (Bitunix فیوچرز USDT + Binance فیوچرز USDⓈ-M) - بدون API key و
بدون وابستگی به bot.py. هم داخل ربات استفاده می‌شود و هم به‌صورت CLI:

    python watchlist_tools.py            # گزارش: کدام نمادها روی هیچ منبعی نیستند، چه جایگزینی پیشنهاد می‌شود و کدام‌ها روی بیتیونیکس نیستند
    python watchlist_tools.py --json     # همان گزارش به‌صورت JSON

منطق: نمادی که روی هیچ‌کدام از منابع (بیتیونیکس: USDT با وضعیت OPEN، باینانس فیوچرز: قرارداد دائمی USDT با وضعیت TRADING) نیست حذف می‌شود و به‌جایش از
RESERVE_TOP_SYMBOLS (به ترتیب اولویت) نماد موجود اضافه می‌شود تا اندازه‌ی لیست حفظ شود.
اگر هیچ منبعی فهرست قابل‌اعتماد (≥ MIN_SANE_SYMBOLS نماد) برنگرداند، هیچ چیزی حذف نمی‌شود.
"""
import json
import os
import re
import sys
import time

import requests

BINANCE_FUTURES = os.environ.get('BINANCE_FUTURES_URL', 'https://fapi.binance.com').rstrip('/')
BITUNIX_PUBLIC = os.environ.get('BITUNIX_PUBLIC_URL', 'https://fapi.bitunix.com').rstrip('/')

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


def fetch_binance_futures(timeout=12):
    """V3.44.120: نام پایه‌ی (به شکل ربات) همه‌ی قراردادهای دائمی USDT فیوچرز USDⓈ-M باینانس با وضعیت TRADING.
    1000PEPE => PEPE ، LUNA2 => LUNA (هم‌نام‌گذاری نمادهای ربات)."""
    try:
        j = _get(f'{BINANCE_FUTURES}/fapi/v1/exchangeInfo', None, timeout)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f'binance futures: {exc}')
    out = set()
    for s in j.get('symbols') or []:
        if s.get('quoteAsset') != 'USDT' or s.get('contractType') != 'PERPETUAL':
            continue
        if (s.get('status') or s.get('contractStatus')) != 'TRADING':
            continue
        raw = str(s.get('baseAsset', '')).upper()
        if not raw:
            continue
        out.add(raw)
        m = re.match(r'^(1000000|100000|10000|1000)([A-Z0-9]+)$', raw)
        if m:
            out.add(m.group(2))
        if raw == 'LUNA2':
            out.add('LUNA')
    if not out:
        raise RuntimeError('binance futures: empty')
    return out


fetch_binance_spot = fetch_binance_futures     # نام قدیمی (سازگاری)


def fetch_bitunix_futures(timeout=12):
    """نام پایه‌ی همه‌ی قراردادهای USDT بیتیونیکس با وضعیت OPEN (GET /api/v1/futures/market/trading_pairs)."""
    j = _get(f'{BITUNIX_PUBLIC}/api/v1/futures/market/trading_pairs', None, timeout)
    if j.get('code') != 0:
        raise RuntimeError(f"bitunix futures: code={j.get('code')}")
    return {str(s.get('base', '')).upper() for s in j.get('data') or []
            if str(s.get('quote', '')).upper() == 'USDT' and str(s.get('symbolStatus', 'OPEN')).upper() == 'OPEN'}


BITUNIX_PREFIXES = (1000, 10000, 100000, 1000000)


def on_bitunix(base, bitunix_bases):
    """V3.44.112: آیا نمادِ اسپات‌گونه‌ی ربات (PEPE) روی فیوچرز بیتیونیکس هست؟ بیتیونیکس بعضی‌ها را با پیشوند ۱۰۰۰ لیست می‌کند (1000PEPE)."""
    base = str(base).upper()
    return base in bitunix_bases or any(f'{p}{base}' in bitunix_bases for p in BITUNIX_PREFIXES)


class AvailableOnAll:
    """V3.44.122: «موجود» یعنی نماد روی *همه‌ی* منابعِ سالم (Binance فیوچرز و Bitunix فیوچرز) باشد، تا هیچ نمادی با
    not_listed / تایم‌اوت اسکن نشود. منبعِ ناقص/خراب (کمتر از MIN_SANE_SYMBOLS نماد) در معیار حساب نمی‌شود."""

    def __init__(self, per_source):
        self.per = {k: set(v) for k, v in (per_source or {}).items() if len(v) >= MIN_SANE_SYMBOLS}

    def __bool__(self):
        return bool(self.per)

    def __contains__(self, base):
        if not self.per:
            return False
        base = str(base).upper()
        for name, bases in self.per.items():
            ok = on_bitunix(base, bases) if name == 'bitunix' else base in bases
            if not ok:
                return False
        return True

    def missing_on(self, base):
        base = str(base).upper()
        return [n for n, b in self.per.items() if not (on_bitunix(base, b) if n == 'bitunix' else base in b)]


def fetch_available(timeout=12):
    """(union, per_source, errors). منبعِ خراب نادیده گرفته می‌شود و خطایش در errors می‌آید."""
    per, errors = {}, {}
    for name, fn in (('bitunix', fetch_bitunix_futures), ('binance', fetch_binance_futures)):
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
    avail = AvailableOnAll(per)
    if not avail:
        report['note'] = 'فهرست Binance معتبر نبود؛ هیچ چیزی فهرست معتبر نداد؛ چیزی حذف نمی‌شود (احتمالاً بلاک جغرافیایی یا قطعی شبکه).'
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 1
    plan = plan_watchlist(candidates, RESERVE_TOP_SYMBOLS, avail)      # V3.44.122: نماد باید روی همه‌ی منابعِ سالم (Binance و Bitunix) باشد
    if plan_is_suspicious(plan, len(candidates)):
        report['note'] = f"بیش از {int(MAX_REMOVE_FRACTION * 100)}٪ لیست غایب بود ({len(plan['removed'])} از {len(candidates)})؛ داده‌ی صرافی مشکوک است و حذفی انجام نمی‌شود."
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 1
    report.update(removed=plan['removed'], added=plan['added'], kept_count=len(plan['kept']), final_count=len(plan['final']))
    report['per_source_missing'] = {k: [s for s in plan['final'] if s not in v] for k, v in per.items()}
    if 'bitunix' in per:
        report['not_on_bitunix'] = [s for s in candidates if not on_bitunix(s, per['bitunix'])]
        report['bitunix_1000'] = {s: next(f'{p}{s}' for p in BITUNIX_PREFIXES if f'{p}{s}' in per['bitunix']) for s in candidates if s not in per['bitunix'] and on_bitunix(s, per['bitunix'])}   # نام ربات -> نام بیتیونیکس     # نمادهای واچ‌لیست فعلی که بیتیونیکس ندارد (داده‌شان از باینانس می‌آید)
    if '--json' in argv:
        report['final'] = plan['final']
        print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    print(f"منابع سالم: {report['sources_ok']}  |  منابع خراب: {errors or '-'}")
    print(f"لیست فعلی: {len(candidates)} نماد | حذف: {len(plan['removed'])} | جایگزین: {len(plan['added'])}")
    print('حذف‌شده (روی هیچ اسپاتی نیست):', ', '.join(plan['removed']) or '-')
    print('جایگزین‌شده (به ترتیب):', ', '.join(plan['added']) or '-')
    if 'not_on_bitunix' in report:
        nb = report['not_on_bitunix']
        print(f"روی بیتیونیکس نیست ({len(nb)} از {len(candidates)}؛ داده‌ی این‌ها از باینانس می‌آید):", ', '.join(nb) or '-')
        if report.get('bitunix_1000'):
            print('با پیشوند ۱۰۰۰ روی بیتیونیکس هست (ربات خودکار نگاشت می‌کند و قیمت را ÷۱۰۰۰ می‌کند):', ', '.join(f'{k}→{v}' for k, v in report['bitunix_1000'].items()))
    elif 'bitunix' in errors:
        print('بیتیونیکس در دسترس نبود:', errors['bitunix'])
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
