#!/usr/bin/env python3
"""V3.44.47: تحلیل رأی‌ها در ژورنال معاملات.

    python analyze_votes.py trade_journal.json [trade_journal2.json ...]

۱) خلاصه‌ی هر پریست (کلید): تعداد، نرخ برد، جمع، میانگین R
۲) به‌تفکیک عمق سطح نصف‌کردن (فیلد hv_depth)
۳) برای هر رأی (BTC، روند، مومنتوم، سطح...): معامله‌هایی که آن رأی «موافق» بود در برابر «مخالف/بی‌نظر»
   (معامله‌های قدیمی بدون فیلد votes نادیده گرفته می‌شوند)
نمونه‌ی کم (کمتر از ۳۰) = تفاوت‌ها بیشتر شانس است تا واقعیت.
"""
import json
import sys
import collections


def load(paths):
    out = []
    for p in paths:
        with open(p, encoding='utf-8') as fh:
            d = json.load(fh)
        out += (d.get('trades') if isinstance(d, dict) else d) or []
    return out


def num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def stat(ts):
    pn = [num(t.get('pnl_usdt')) for t in ts if num(t.get('pnl_usdt')) is not None]
    rs = [num(t.get('realized_r')) for t in ts if num(t.get('realized_r')) is not None]
    if not pn:
        return None
    return {'n': len(pn), 'win': sum(1 for x in pn if x > 0) / len(pn) * 100, 'pnl': sum(pn),
            'avg_r': (sum(rs) / len(rs)) if rs else None}


def line(name, s):
    if not s:
        return f"  {name}: —"
    r = '—' if s['avg_r'] is None else f"{s['avg_r']:+.2f}R"
    small = '  (نمونه کم)' if s['n'] < 30 else ''
    return f"  {name}: {s['n']} معامله | برد {s['win']:.0f}% | جمع {s['pnl']:+.2f}$ | میانگین {r}{small}"


def main(paths):
    trades = load(paths)
    print(f"تعداد معامله‌ها: {len(trades)}")
    by_preset = collections.defaultdict(list)
    for t in trades:
        by_preset[('کلید ' + str(t.get('preset'))) if t.get('preset') else 'بدون برچسب'].append(t)
    print('\n== به‌تفکیک پریست ==')
    for k in sorted(by_preset):
        print(line(k, stat(by_preset[k])))
    voted = [t for t in trades if t.get('votes')]
    print(f"\n== به‌تفکیک رأی‌ها (از {len(voted)} معامله‌ی دارای رأی) ==")
    keys = sorted({k for t in voted for k in t['votes']})
    for k in keys:
        print(f"[{k}]")
        for lab, code in (('موافق', 'Y'), ('مخالف', 'N'), ('بی‌نظر/منتظر', '-')):
            print(line(lab, stat([t for t in voted if t['votes'].get(k) == code])))
    print('\n== به‌تفکیک عمق سطح نصف‌کردن (عمق کمتر = سطح مهم‌تر) ==')
    by_depth = collections.defaultdict(list)
    for t in trades:
        d = t.get('hv_depth')
        by_depth[d if isinstance(d, int) else -1].append(t)
    for d in sorted(by_depth):
        print(line('نامشخص' if d == -1 else f'عمق {d}', stat(by_depth[d])))
    print('\n(Y = رأی موافق جهت معامله، N = مخالف، - = بی‌نظر؛ وضعیت در لحظه‌ی عبور از مرحله‌ی رأی‌گیری)')


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1:])
