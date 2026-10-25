"""گزارش مقایسه‌ی کلیدهای پریست از روی فایل‌های funnel/*.jsonl (V3.44.72).

استفاده‌ی مستقل:   python3 funnel_report.py /مسیر/funnel [روز]
داخل ربات:        /funnel_report  یا  /funnel_report_14  یا  /funnel_export
"""
import glob
import json
import os
import statistics as st
import sys
import tempfile
import time
import zipfile

try:
    import presets as _presets
except Exception:           # گزارش بدون ماژول پریست هم کار کند
    _presets = None

MIN_SAMPLE = 30
GATE_FA = {'min_rr': 'R:R کم', 'drift': 'قیمت دور شد', 'price_crossed': 'قیمت از SL/TP گذشت', 'pd_level': 'سقف/کف دیروز',
           'btc_candle': 'کندل BTC', 'final_regime': 'رژیم بازار', 'btc_front': 'سطح جلوی BTC', 'manual_block': 'بلاک دستی',
           'risk_limits': 'ریسک/ظرفیت/کول‌داون', 'other': 'سایر'}
KEY_FA = {'btcpat': 'الگوی BTC', 'btceth': 'رژیم BTC/ETH', 'h4': 'رژیم ۴ساعته', 'tf': 'رژیم ۵/۱۵', 'rsi': 'RSI', 'macd': 'MACD',
          'adx': 'ADX', 'level': 'کلوز نسبت به سطح', 'ylevel': 'سقف/کف دیروز', 'vol': 'حجم'}


FAV_FA = {'opened': 'باز شد', 'card_sent': 'کارت دستیار', 'handed_to_warning': 'کارت هشدار', 'expired': 'منقضی', 'cancelled': 'کنسل',
          'skipped': 'پوزیشن باز شد', 'blocked': 'مسدود بعد از تایید', 'rejected': 'رد دستی', 'entered_manual': 'ورود دستی',
          'timeout': 'مهلت تمام شد', 'overrun': 'قیمت از سقف گذشت', 'regime': 'رژیم', 'btc': 'کندل BTC', 'front': 'سطح جلوی BTC', 'pdlevel': 'سقف/کف دیروز'}


def _fav_label(status, why=None):
    return FAV_FA.get(status, status) + (f" ({FAV_FA.get(why, why)})" if why else '')


def _fa(x):
    return str(x).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


def load_events(dir_path, days=7, now=None):
    now = now or time.time()
    cutoff = now - days * 86400
    out = []
    for path in sorted(glob.glob(os.path.join(dir_path or '.', 'funnel_*.jsonl'))):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict) and float(e.get('ts', 0) or 0) >= cutoff:
                        out.append(e)
        except OSError:
            continue
    out.sort(key=lambda e: e.get('ts', 0))
    return out


def group_of(e):
    p = e.get('preset')
    if not p:
        return 'بدون کلید'
    return f"کلید {_fa(p)}" + (' (دستی)' if e.get('pmod') else '')


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return (sum(xs) / len(xs)) if xs else None


def _fmt_r(x):
    return 'نامشخص' if x is None else f'{x:+.2f}R'


def _preset_params(n):
    """(min_r، مهلت دقیقه، حالت ورود) هر کلید برای شبیه‌سازی تایید حرکت."""
    try:
        _cfg, ses = _presets._full(str(n))
        return float(ses.get('fav_confirm_min_r', 0.15)), float(ses.get('fav_confirm_wait_sec', 1800)) / 60.0, ses.get('touch_auto_mode')
    except Exception:
        return 0.15, 30.0, None


def _shadow_stats(rows):
    """rows: لیست dict با outcome/r_end. خروجی (تعداد حل‌شده، برد، باخت، میانگین R، بدون نتیجه)."""
    res = [r for r in rows if r.get('outcome') in ('tp', 'sl')]
    wins = sum(1 for r in res if r['outcome'] == 'tp')
    return len(res), wins, len(res) - wins, _avg([r.get('r_end') for r in res]), len(rows) - len(res)


def _index(events):
    by = {}
    for e in events:
        by.setdefault(e.get('kind'), []).append(e)
    return by


def build_report(dir_path, days=7, now=None):
    events = load_events(dir_path, days, now)
    if not events:
        return 'هنوز داده‌ای برای گزارش قیف ثبت نشده است. بعد از چند ساعت کار ربات دوباره امتحان کنید.'
    by = _index(events)
    touches = by.get('touch', [])
    votes = by.get('vote', [])
    shadows = [e for e in by.get('shadow', []) if e.get('sk') == 'touch']
    fav_shadows = {(e.get('tid')): e for e in by.get('shadow', []) if e.get('sk') == 'fav'}
    sh_by_tid = {e.get('tid'): e for e in shadows}
    last_vote, ever_cf = {}, {}
    for v in votes:
        tid = v.get('tid')
        last_vote[tid] = v
        for n, c in (v.get('cf') or {}).items():
            if c and c.get('ok'):
                ever_cf.setdefault(tid, set()).add(n)
    finals = {e.get('tid'): e for e in by.get('touch_final', [])}
    passes = {e.get('tid'): e for e in by.get('pass_vote', [])}
    blocks = {}
    for e in by.get('block', []):
        blocks.setdefault(e.get('tid'), []).append(e)
    favq = {e.get('tid'): e for e in by.get('fav_queue', []) if e.get('tid')}
    favf = {e.get('tid'): e for e in by.get('fav_final', []) if e.get('tid')}
    entries = {e.get('trade_id'): e for e in by.get('entry', [])}
    closes = by.get('trade_close', [])

    t0, t1 = events[0]['ts'], events[-1]['ts']
    span_h = max(0.1, (t1 - t0) / 3600.0)
    lines = [f"🧬 *گزارش قیف کلیدها* — {_fa(len(events))} رویداد در {_fa(round(span_h, 1))} ساعت", '']

    # ---------------------------------------------------------------- ۱) قیف هر کلید ----------
    groups = sorted({group_of(e) for e in events if e.get('kind') in ('touch', 'scan_summary', 'entry', 'trade_close')})
    lines.append('*۱) قیف واقعی هر کلید*')
    for g in groups:
        scans = no_setup = 0
        for e in by.get('scan_summary', []):
            if group_of(e) == g:
                c = e.get('counts') or {}
                scans += int(c.get('scans', 0) or 0)
                no_setup += int(c.get('no_setup', 0) or 0)
        t_g = [t for t in touches if group_of(t) == g]
        tids = {t.get('tid') for t in t_g}
        n_pass = sum(1 for t in tids if t in passes)
        n_q = sum(1 for t in tids if t in favq)
        fin = {}
        for t in tids:
            f = favf.get(t)
            if f:
                k = _fav_label(f.get('status'), f.get('why'))
                fin[k] = fin.get(k, 0) + 1
        n_entry = sum(1 for en in entries.values() if group_of(en) == g)
        cl = [c for c in closes if group_of(c) == g and c.get('r') is not None]
        rs = [float(c['r']) for c in cl]
        lines.append(f"• *{g}*")
        lines.append(f"   بررسی نماد `{_fa(scans)}` | بدون ستاپ روی سطح `{_fa(round(100 * no_setup / scans, 1)) if scans else '؟'}٪` | برخورد `{_fa(len(t_g))}`")
        lines.append(f"   رأی‌ها تایید `{_fa(n_pass)}` | صف تایید حرکت `{_fa(n_q)}` | ورود `{_fa(n_entry)}`")
        if fin:
            lines.append('   پایان صف: ' + '، '.join(f"{k} `{_fa(v)}`" for k, v in sorted(fin.items(), key=lambda x: -x[1])))
        if rs:
            w = sum(1 for r in rs if r > 0)
            lines.append(f"   معاملهٔ بسته `{_fa(len(rs))}` | برد `{_fa(w)}` | جمع `{sum(rs):+.2f}R` | میانگین `{_avg(rs):+.2f}R`")
    lines.append('')

    # ---------------------------------------------------------------- ۲) مقایسه‌ی منصفانه روی همان برخوردها ----------
    lines.append('*۲) مقایسهٔ منصفانه: همان برخوردها، قانون هر کلید*')
    lines.append('_(با ورود فرضی در لحظهٔ برخورد، تا ۶ ساعت بعد؛ R ناخالص و بدون کارمزد)_')
    seen_touch, n_eval = set(), 0
    base = {}
    for t in touches:
        tid = t.get('tid')
        key = (t.get('symbol'), t.get('level_token'), t.get('level_value'), int(float(t.get('ts', 0)) // 1800))
        if key in seen_touch or tid not in last_vote:
            continue
        seen_touch.add(key)
        n_eval += 1
        base[tid] = t
    if not base:
        lines.append('هنوز برخوردی با رأی ثبت‌شده نداریم.')
    else:
        lines.append(f"برخوردهای مقایسه‌شده: `{_fa(n_eval)}` | نتیجهٔ سایه‌ی تعیین‌شده: `{_fa(sum(1 for t in base if t in sh_by_tid))}`")
        for n in ('3', '4', '5'):
            mn, wait_min, mode = _preset_params(n)
            passed = [tid for tid in base if n in ever_cf.get(tid, set())]
            sh = [sh_by_tid[tid] for tid in passed if tid in sh_by_tid]
            nres, w, l, av, pend = _shadow_stats(sh)
            conf = []
            for r in sh:
                k = f'{mn:g}'
                reach = (r.get('reach') or {})
                if k in reach and reach[k] <= wait_min:
                    conf.append(r)
            cres, cw, cl_, cav, _cp = _shadow_stats(conf)
            lines.append(f"• *کلید {_fa(n)}* ({mode}، تایید حرکت ≥{_fa(mn)}R تا {_fa(int(wait_min))}دقیقه)")
            lines.append(f"   رأی تایید `{_fa(len(passed))}` از `{_fa(len(base))}` ({_fa(round(100 * len(passed) / len(base)))}٪)")
            if nres:
                lines.append(f"   ورود فوری فرضی: برد `{_fa(w)}` باخت `{_fa(l)}` میانگین {_fmt_r(av)}" + (f" | نامعلوم `{_fa(pend)}`" if pend else ''))
            else:
                lines.append('   هنوز نتیجهٔ سایه‌ای تعیین نشده (۶ ساعت بعد از برخورد کامل می‌شود).')
            if cres:
                lines.append(f"   بعد از تایید حرکت: `{_fa(cres)}` مورد | برد `{_fa(cw)}` | میانگین {_fmt_r(cav)}")
        if n_eval < MIN_SAMPLE:
            lines.append(f"_توجه: نمونه کمتر از {_fa(MIN_SAMPLE)} برخورد است؛ قطعی نتیجه نگیرید._")
    lines.append('')

    # ---------------------------------------------------------------- ۳) برخوردها کجا می‌میرند ----------
    lines.append('*۳) برخوردها کجا متوقف شدند؟ (و اگر وارد می‌شدیم چه می‌شد)*')
    cats = {}
    for tid, t in base.items():
        f = finals.get(tid)
        if tid in favf:
            ff = favf[tid]
            cat = 'صف تایید: ' + _fav_label(ff.get('status'), ff.get('why'))
        elif tid in passes:
            cat = f"رأی تایید شد: {passes[tid].get('result')}"
        elif blocks.get(tid):
            cat = 'بعد از رأی، دروازه: ' + GATE_FA.get(blocks[tid][-1].get('gate'), 'سایر')
        elif f is not None or tid in last_vote:
            cat = 'رأی‌ها کافی نبود'
        else:
            cat = 'نامشخص'
        cats.setdefault(cat, []).append(tid)
    for cat, tids in sorted(cats.items(), key=lambda x: -len(x[1])):
        sh = [sh_by_tid[t] for t in tids if t in sh_by_tid]
        nres, w, l, av, pend = _shadow_stats(sh)
        extra = f" | اگر وارد می‌شدیم: برد `{_fa(w)}` باخت `{_fa(l)}` {_fmt_r(av)}" if nres else ''
        lines.append(f"• {cat}: `{_fa(len(tids))}`{extra}")
    lines.append('')

    # ---------------------------------------------------------------- ۴) کدام رأی‌دهنده پیش‌بینی خوبی بوده ----------
    lines.append('*۴) کدام رأی‌دهنده پیش‌بینی بهتری بوده؟* (میانگین R فرضی بعد از برخورد)')
    per_key = {}
    for tid, t in base.items():
        r = sh_by_tid.get(tid)
        v = last_vote.get(tid)
        if not r or not v or r.get('outcome') not in ('tp', 'sl'):
            continue
        side = 'B' if t.get('touch_sig') == 'BUY' else 'S'
        for k, val in (v.get('raw') or {}).items():
            tag = 'agree' if val == side or (k == 'vol' and val == 'O') else ('none' if val == '-' else 'against')
            per_key.setdefault(k, {}).setdefault(tag, []).append(r.get('r_end'))
    if not per_key:
        lines.append('هنوز نتیجهٔ سایه‌ای کافی برای این بخش نداریم.')
    else:
        for k in sorted(per_key):
            d = per_key[k]
            parts = []
            for tag, nm in (('agree', 'موافق'), ('against', 'مخالف'), ('none', 'بی‌نظر')):
                xs = d.get(tag) or []
                if xs:
                    parts.append(f"{nm} `{_fa(len(xs))}` ({_fmt_r(_avg(xs))})")
            lines.append(f"• {KEY_FA.get(k, k)}: " + ' | '.join(parts))
        lines.append('_اگر «موافق» از «مخالف» بهتر نباشد، آن رأی‌دهنده کمکی نمی‌کند._')
    lines.append('')

    # ---------------------------------------------------------------- ۵) تایید حرکت: آیا صف کمک کرده؟ ----------
    lines.append('*۵) صف تایید حرکت: فیلتر کمک کرد یا ضرر زد؟*')
    imm, delayed = [], []
    for tid, q in favq.items():
        r = fav_shadows.get(tid)
        if not r or r.get('outcome') not in ('tp', 'sl'):
            continue
        imm.append(r.get('r_end'))
        ff = favf.get(tid)
        if ff and ff.get('status') in ('opened', 'card_sent', 'handed_to_warning'):
            delayed.append(r.get('r_end'))
    if imm:
        lines.append(f"• سیگنال‌های وارد صف با نتیجهٔ سایه: `{_fa(len(imm))}` | اگر همه را فوری می‌گرفتیم: {_fmt_r(_avg(imm))} به‌ازای هر سیگنال")
        lines.append(f"• آنهایی که صف تایید کرد: `{_fa(len(delayed))}` | {_fmt_r(_avg(delayed))}" + (f" (بقیه {_fa(len(imm) - len(delayed))} مورد حذف شدند)" if len(imm) > len(delayed) else ''))
    else:
        lines.append('هنوز نتیجه‌ای تعیین نشده.')
    return '\n'.join(lines)


def split_text(text, limit=3500):
    out, cur = [], ''
    for ln in text.split('\n'):
        if len(cur) + len(ln) + 1 > limit and cur:
            out.append(cur)
            cur = ''
        cur += ln + '\n'
    if cur.strip():
        out.append(cur)
    return out or ['']


def export_zip(dir_path, days=14, now=None):
    now = now or time.time()
    cutoff = now - days * 86400
    files = [p for p in sorted(glob.glob(os.path.join(dir_path or '.', 'funnel_*.jsonl'))) if os.path.getmtime(p) >= cutoff]
    if not files:
        return None
    out = os.path.join(tempfile.gettempdir(), f"funnel_data_{time.strftime('%Y-%m-%d_%H-%M-%S', time.gmtime(now))}.zip")
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, os.path.basename(p))
    return out


if __name__ == '__main__':
    d = sys.argv[1] if len(sys.argv) > 1 else 'funnel'
    print(build_report(d, int(sys.argv[2]) if len(sys.argv) > 2 else 7))
