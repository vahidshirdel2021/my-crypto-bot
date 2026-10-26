"""V3.44.88: گزارش «رأی برگشت»: آیا معکوس‌کردن مومنتوم در حالت‌های برگشتی ارزش دارد؟

استفاده:  python3 contra_report.py /مسیر/funnel
(پوشه‌ی funnel کنار دیتابیس ربات است؛ یا خروجی /funnel_export را باز کن و پوشه‌اش را بده.)

از هر برخورد، نتیجه‌ی دو حالت را که ربات در ثبت قیف می‌نویسد (cx.n بدون معکوس، cx.f با معکوس) با نتیجه‌ی
«اگر همان لحظه وارد می‌شدیم» (shadow) مقایسه می‌کند. هر رویداد بازار فقط یک‌بار شمرده می‌شود (حساب‌های مختلف تکراری‌اند).
خروجی برای سه حد سود: TP خودِ ربات، ۱R و ۰.۵R (با ضرر ۱R). کارمزد رفت‌وبرگشت حدود ۰.۱۱R در معامله‌ی معمولی است.
"""
import glob
import json
import os
import statistics as st
import sys

REV = ('1', '2', '5', '6')


def load(path):
    recs = []
    for f in sorted(glob.glob(os.path.join(path, 'funnel_*.jsonl'))):
        with open(f, encoding='utf-8') as fh:
            for line in fh:
                try:
                    recs.append(json.loads(line))
                except ValueError:
                    pass
    return recs


def result(shadow, L=None):
    if L is None:
        return 'W' if shadow.get('outcome') == 'tp' else 'L' if shadow.get('outcome') == 'sl' else None
    k = str(L)
    if k in (shadow.get('reach') or {}) and (shadow.get('mae_before') or {}).get(k, 0) < 1.0:
        return 'W'
    return 'L' if shadow.get('outcome') == 'sl' else None


def line(group, L=None):
    w = sum(1 for e in group if result(e['s'], L) == 'W')
    l = sum(1 for e in group if result(e['s'], L) == 'L')
    if L is None:
        tps = [e['s']['tp_r'] for e in group if e['s'].get('tp_r')]
        Lr = st.median(tps) if tps else 0.0
    else:
        Lr = float(L)
    wr = w / max(1, w + l)
    ex = (w * Lr - l) / max(1, w + l)
    return f"n={len(group):3d} برد={w:3d} باخت={l:3d} باز={len(group) - w - l:3d} نرخبرد={wr:.2f} متوسطTP={Lr:.2f}R میانگین={ex:+.2f}R"


def main(path):
    recs = load(path)
    touch = {r['tid']: r for r in recs if r.get('kind') == 'touch'}
    shadow = {r['tid']: r for r in recs if r.get('kind') == 'shadow' and r.get('sk') == 'touch'}
    cx = {}
    for r in recs:
        if r.get('kind') == 'vote' and r.get('cx'):
            cx[r['tid']] = r['cx']
    events = {}
    for tid, c in cx.items():
        t, s = touch.get(tid), shadow.get(tid)
        if not t or not s:
            continue
        key = (t['symbol'], t.get('scn'), round(float(t['level_value']), 8), t['touch_sig'], t['tf'], int(t['ts'] // 1800))
        events.setdefault(key, {'t': t, 's': s, 'c': c})
    ev = list(events.values())
    print(f"برخوردهای دارای cx و نتیجه‌ی shadow: {len(ev)} رویداد یکتا (فایل‌ها: {path})")
    if not ev:
        print('هنوز داده‌ای با فیلد cx نیست (نسخه‌ی 3.44.88 باید چند ساعت اجرا شده باشد و نتیجه‌ی ۶ ساعته‌ی shadow برسد).')
        return
    groups = [
        ('برگشتی (۱،۲،۵،۶) - رأی عادی قبول می‌کرد', [e for e in ev if e['c'].get('rev') and e['c']['n'][3] == 1]),
        ('برگشتی - رأی عادی قبول نمی‌کرد', [e for e in ev if e['c'].get('rev') and e['c']['n'][3] == 0]),
        ('برگشتی - رأی با معکوس قبول می‌کند', [e for e in ev if e['c'].get('rev') and e['c']['f'][3] == 1]),
        ('برگشتی - رأی با معکوس قبول نمی‌کند', [e for e in ev if e['c'].get('rev') and e['c']['f'][3] == 0]),
        ('ادامه‌ی روند (۳،۴) - رأی عادی قبول می‌کرد', [e for e in ev if not e['c'].get('rev') and e['c']['n'][3] == 1]),
        ('ادامه‌ی روند - اگر معکوس می‌شد قبول می‌کرد', [e for e in ev if not e['c'].get('rev') and e['c']['f'][3] == 1]),
    ]
    for name, g in groups:
        print(f"\n== {name}")
        if not g:
            print('   (خالی)')
            continue
        for L, label in ((None, 'TP ربات'), (1, 'TP=1R   '), (0.5, 'TP=0.5R ')):
            print(f"   {label}: {line(g, L)}")
    print('\nراهنما: اگر «برگشتی - با معکوس قبول می‌کند» در چند روزِ مختلف و در بازار روندی هم میانگین مثبت (بعد از کسر حدود ۰.۱۱R کارمزد) داشت، ارزش روشن‌کردن دارد.')
    print('اگر «ادامه‌ی روند - اگر معکوس می‌شد» هم خوب بود، یعنی اثر مربوط به رنج‌بودن بازار است نه برگشتی‌بودن سناریو.')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'funnel')
