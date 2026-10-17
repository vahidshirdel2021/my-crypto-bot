#!/usr/bin/env python3
"""تحلیل ردیاب مجازی سر به سر (V3.44.11).

استفاده:
    python analyze_be_sim.py trade_journal.json [trade_journal2.json ...]

فقط معامله‌هایی که فیلد be_sim دارند (ژورنال نسخه‌ی 3.44.11 به بعد) شمرده می‌شوند.
خروجی برای هر تریگر (R):
  reached  = چند معامله به تریگر رسیدند
  be_hit   = از آن‌ها چندتا بعد از رسیدن به تریگر به قیمت ورود برگشتند (یعنی SL سر به سر می‌خورد)
  saved    = معامله‌هایی که با BE بهتر تمام می‌شدند (مثلاً SL که به ~0 تبدیل می‌شد) و مجموع R آن‌ها
  killed   = معامله‌هایی که با BE بدتر تمام می‌شدند (برنده‌ای که زودتر بسته می‌شد) و مجموع R آن‌ها
  net      = مجموع تغییر نتیجه با BE (R و تقریباً USDT)؛ مثبت = BE مفید بوده
"""
import json, sys, statistics as st

def load(paths):
    rows = []
    for p in paths:
        with open(p, encoding='utf-8') as fh:
            d = json.load(fh)
        rows += d['trades'] if isinstance(d, dict) else d
    return rows

def main(paths):
    rows = [t for t in load(paths) if isinstance(t.get('be_sim'), dict)]
    if not rows:
        print('هیچ معامله‌ای با be_sim پیدا نشد (ژورنال باید از نسخه‌ی 3.44.11 یا جدیدتر باشد).'); return
    risks = []
    for t in rows:
        r = t.get('realized_r')
        if r is not None and abs(r) > 0.2 and t.get('pnl_usdt') is not None:
            risks.append(abs(t['pnl_usdt'] / r))
    med_risk = st.median(risks) if risks else 5.0
    print(f'معاملات دارای be_sim: {len(rows)}  |  ریسک تقریبی هر R ≈ {med_risk:.2f} USDT')
    base = sum(t['realized_r'] for t in rows if t.get('realized_r') is not None)
    print(f'مجموع فعلی: {base:+.1f}R\n')
    keys = sorted({k for t in rows for k in t['be_sim']['levels']}, key=float)
    print(f"{'تریگر':>6} {'reached':>8} {'be_hit':>7} {'saved':>6} {'+R':>7} {'killed':>7} {'-R':>7} {'net R':>8} {'net USDT':>9} {'p(killed|winners reached)':>27}")
    for k in keys:
        reached = hit = saved = killed = 0; gain = loss = 0.0; win_reached = 0
        for t in rows:
            lv = t['be_sim']['levels'].get(k)
            if not lv: continue
            if lv.get('armed'):
                reached += 1
                if (t.get('realized_r') or 0) > 0: win_reached += 1
            if lv.get('hit'): hit += 1
            d = lv['sim_r'] - t['be_sim']['actual_r']
            if lv.get('verdict') == 'saved': saved += 1; gain += d
            elif lv.get('verdict') == 'killed': killed += 1; loss += d
        net = gain + loss
        p = (killed / win_reached) if win_reached else float('nan')
        print(f'{float(k):>5g}R {reached:>8} {hit:>7} {saved:>6} {gain:>+7.1f} {killed:>7} {loss:>+7.1f} {net:>+8.1f} {net*med_risk:>+9.1f} {p:>27.2f}')
    print('\nتفسیر: ستون net مثبت یعنی انتقال SL به سر به سر در این نمونه مفید بوده. حداقل ۱۰۰ معامله لازم است.')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    main(sys.argv[1:])
