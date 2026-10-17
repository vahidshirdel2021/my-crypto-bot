#!/usr/bin/env python3
"""تحلیل ژورنال معاملات (نسخه‌ی ۳.۴۴.۱۲ به بعد؛ با ژورنال‌های قدیمی‌تر هم تا حد ممکن کار می‌کند).

    python analyze_journal.py trade_journal.json [trade_journal2.json ...]

خروجی:
  ۱) خلاصه به‌تفکیک معکوس/عادی (برچسب inverse_trade، یا حدس از روی سناریو و جهت برای ژورنال قدیمی)
  ۲) علت خروج‌ها
  ۳) تفکیک هزینه‌ها: کارمزد، فاندینگ، سهم پلتفرم، اسلیپیج SL، اسلیپیج/تأخیر ورود
  ۴) تفکیک بر اساس سناریو و ستاپ
  ۵) شبیه‌سازی دقیق سر به سر روی مسیر قیمت (path) برای چند تریگر
  ۶) دلیل سیگنال‌های ردشده (اگر در فایل باشد)
  ۷) تغییر تنظیمات بین معاملات (settings_hash)
"""
import json, sys, collections, statistics as st

SELL = {1, 4, 5}; BUY = {2, 3, 6}

def load(paths):
    trades, settings, rejected = [], {}, []
    for p in paths:
        with open(p, encoding='utf-8') as fh:
            d = json.load(fh)
        if isinstance(d, dict):
            trades += d.get('trades') or []
            settings.update(d.get('settings') or {})
            rejected += d.get('rejected') or []
        else:
            trades += d
    return trades, settings, rejected

def is_inverse(t):
    if 'inverse_trade' in t:
        return bool(t['inverse_trade'])
    try:   # ژورنال قدیمی: جهت با سناریو نمی‌خواند (ممکن است از دکمه‌ی دستی «معکوس» هم باشد)
        s = int(t.get('scenario')); side = t.get('side') or ''
        return (s in SELL and 'BUY' in side) or (s in BUY and 'SELL' in side)
    except Exception:
        return False

def summarize(name, rows):
    if not rows:
        return
    pnl = sum(t['pnl_usdt'] for t in rows); rs = [t['realized_r'] for t in rows if t.get('realized_r') is not None]
    wins = sum(1 for t in rows if t['pnl_usdt'] > 0)
    sl = sum(1 for t in rows if (t.get('close_reason') or '').startswith('SL'))
    print(f'{name:<26} n={len(rows):>4}  pnl={pnl:>+8.2f}  avgR={st.mean(rs) if rs else 0:>+6.3f}  برد={100*wins/len(rows):>3.0f}%  SL={100*sl/len(rows):>3.0f}%')

def mean(xs):
    xs = [x for x in xs if x is not None]
    return st.mean(xs) if xs else None

def fmt(x, nd=2):
    return '—' if x is None else f'{x:.{nd}f}'

def be_on_path(t, trig, cost_r):
    """سر به سر روی مسیر قیمت: اگر path به trig رسید و بعد به ≤۰ برگشت، خروج با -cost_r."""
    path = t.get('path') or []
    armed = False
    for _, r in path:
        if not armed and r >= trig:
            armed = True
        elif armed and r <= 0:
            return True
    return False

def main(paths):
    trades, settings, rejected = load(paths)
    if not trades:
        print('هیچ معامله‌ای پیدا نشد.'); return
    print(f'کل معاملات: {len(trades)}   نسخه‌های ربات: {dict(collections.Counter(t.get("bot_version", "قدیمی") for t in trades))}\n')

    print('== ۱) معکوس در برابر عادی ==')
    inv = [t for t in trades if is_inverse(t)]; nor = [t for t in trades if not is_inverse(t)]
    has_flag = any('inverse_trade' in t for t in trades)
    print('(برچسب inverse_trade موجود است)' if has_flag else '(برچسب نیست؛ از روی سناریو/جهت حدس زده شد)')
    summarize('همه', trades); summarize('عادی', nor); summarize('معکوس', inv)

    print('\n== ۲) علت خروج ==')
    by = collections.defaultdict(list)
    for t in trades:
        by[(t.get('close_reason') or '?')[:30]].append(t)
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        summarize(k, v)

    print('\n== ۳) هزینه‌ها (میانگین هر معامله؛ — یعنی فیلد در ژورنال نبود) ==')
    rows = [t for t in trades if t.get('fee_usdt') is not None]
    print(f'معاملات دارای تفکیک هزینه: {len(rows)}')
    if rows:
        print(f"کارمزد: {fmt(mean(t.get('fee_usdt') for t in rows))}$  فاندینگ: {fmt(mean(t.get('funding_usdt') for t in rows))}$  سهم پلتفرم: {fmt(mean(t.get('platform_fee_usdt') for t in rows))}$")
        sls = [t.get('sl_slippage_r') for t in rows if t.get('sl_slippage_r') is not None]
        print(f"اورشوت/اسلیپیج SL (R) روی معاملات SL: میانگین {fmt(mean(sls), 3)}  حداکثر {fmt(max(sls) if sls else None, 3)}")
        ent = []
        for t in rows:
            sp, raw, ep = t.get('signal_price'), t.get('raw_entry_price'), t.get('entry_price')
            if sp and raw and ep:
                long_ = 'BUY' in (t.get('side') or '')
                delay = ((raw - sp) / sp) * (1 if long_ else -1) * 1e4      # مثبت = قیمت لحظه‌ی ورود بدتر از قیمت سیگنال
                slip = ((ep - raw) / raw) * (1 if long_ else -1) * 1e4      # اسلیپیج پیپر
                ent.append((delay, slip))
        if ent:
            print(f'ورود در برابر سیگنال (bps، مثبت = به ضرر): تأخیر قیمتی میانگین {mean([e[0] for e in ent]):+.1f}  اسلیپیج {mean([e[1] for e in ent]):+.1f}')
        moved = [t for t in rows if t.get('sl_initial') is not None and abs(float(t['sl_initial']) - float(t['sl'])) > 1e-12 * max(1.0, abs(float(t['sl'])))]
        print(f'معاملاتی که SL‌شان بعد از ورود جابه‌جا شده: {len(moved)}')

    print('\n== ۴) بر اساس سناریو و ستاپ ==')
    for key in ('scenario', 'setup'):
        g = collections.defaultdict(list)
        for t in trades:
            g[t.get(key)].append(t)
        for k, v in sorted(g.items(), key=lambda kv: str(kv[0])):
            summarize(f'{key}={k}', v)

    print('\n== ۵) سر به سر روی مسیر قیمت (فقط معاملاتی که path دارند) ==')
    prows = [t for t in trades if t.get('path') and t.get('risk_usdt')]
    print(f'معاملات دارای مسیر: {len(prows)}')
    if prows:
        for trig in (0.3, 0.5, 0.75, 1.0):
            gain = loss = 0.0; saved = killed = 0
            for t in prows:
                cost_r = 0.1
                if be_on_path(t, trig, cost_r):
                    d = -cost_r - t['realized_r']
                    if d > 0.05: saved += 1; gain += d
                    elif d < -0.05: killed += 1; loss += d
            print(f'تریگر {trig:>4}R: نجات {saved:>3} ({gain:+.1f}R)  زیان‌ده {killed:>3} ({loss:+.1f}R)  خالص {gain+loss:+.1f}R')
        tm = [(t['path_max_t'], t['path_min_t']) for t in prows if t.get('path_max_t') is not None]
        if tm:
            first_up = sum(1 for a, b in tm if a < b)
            print(f'ترتیب اکسترمم‌ها: در {first_up} از {len(tm)} معامله بیشینه‌ی مثبت قبل از بیشینه‌ی منفی آمد')

    print('\n== ۶) سیگنال‌های ردشده ==')
    if rejected:
        c = collections.Counter((r.get('reason') or '')[:70] for r in rejected)
        print(f'تعداد ثبت‌شده: {len(rejected)}')
        for k, v in c.most_common(12):
            print(f'  {v:>4}  {k}')
    else:
        print('چیزی در فایل نیست (فقط ژورنال ۳.۴۴.۱۲ به بعد).')

    print('\n== ۷) تغییر تنظیمات بین معاملات ==')
    hs = collections.Counter(t.get('settings_hash') for t in trades if t.get('settings_hash'))
    if not hs:
        print('هش تنظیمات در فایل نیست.')
    else:
        for h, n in hs.most_common():
            first = (settings.get(h) or {}).get('first_seen_text', '?')
            print(f'  {h}: {n} معامله، اولین بار {first}')
        keys = list(hs)
        if len(keys) >= 2:
            a = (settings.get(keys[0]) or {}).get('config') or {}; b = (settings.get(keys[1]) or {}).get('config') or {}
            diff = [k for k in set(a) | set(b) if a.get(k) != b.get(k)]
            print('  اختلاف دو تنظیم پرتکرار (سطح اول):', diff[:15])
    h4_tier_section(trades)

def h4_tier_section(trades):
    print('\n== ۸) رتبه‌ی نرم ۴ ساعته (h4_tier) ==')
    rows = [t for t in trades if isinstance(t.get('h4_tier'), dict)]
    if not rows:
        print('معامله‌ای با h4_tier نیست (کلید خاموش بوده یا ژورنال قدیمی است).'); return
    for label, grp in (('ریسک کامل (×1)', [t for t in rows if float(t['h4_tier'].get('risk_mult') or 1) >= 1.0]),
                       ('ریسک کم‌شده', [t for t in rows if float(t['h4_tier'].get('risk_mult') or 1) < 1.0])):
        summarize(label, grp)
    print('(R هر معامله بر اساس ریسک خودش است؛ برای اثر روی سود دلاری pnl_usdt را ببین)')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1:])
