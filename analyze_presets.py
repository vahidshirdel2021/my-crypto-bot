"""تحلیل نتیجه‌ی پریست‌ها از فایل ژورنال.
اجرا:  python analyze_presets.py trade_journal.json
خروجی: جدول هر کلید + تفکیک بر اساس حالت (سناریو) و جهت + هشدار حجم نمونه.
"""
import json
import sys
from collections import defaultdict

import presets


def load(path):
    with open(path, 'r', encoding='utf-8') as fh:
        data = json.load(fh)
    return data.get('trades', data) if isinstance(data, dict) else data


def table(title, trades):
    st = presets.summarize(trades)
    print(f'\n== {title} ==')
    if not st:
        print('  (خالی)')
        return
    print(f"{'گروه':<28}{'n':>5}{'برد%':>7}{'جمع$':>10}{'میانگین$':>10}{'avgR':>8}{'PF':>7}")
    for g in sorted(st):
        a = st[g]
        r = '-' if a['avg_r'] is None else f"{a['avg_r']:+.2f}"
        pf = '-' if a['profit_factor'] is None else f"{a['profit_factor']:.2f}"
        print(f"{g:<28}{a['n']:>5}{a['win_rate']:>7.0f}{a['pnl']:>10.2f}{a['avg_pnl']:>10.2f}{r:>8}{pf:>7}")


def main(path):
    trades = load(path)
    print(f'کل معامله‌ها: {len(trades)}')
    table('همه', trades)
    by_scn = defaultdict(list)
    by_side = defaultdict(list)
    for t in trades:
        by_scn[f"حالت {t.get('scenario')}"].append(t)
        by_side[str(t.get('side'))].append(t)
    for k in sorted(by_scn):
        table(k, by_scn[k])
    for k in sorted(by_side):
        table(f'جهت {k}', by_side[k])


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
