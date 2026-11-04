"""ثبت کامل قیف ورود برای مقایسه‌ی کلیدهای پریست (V3.44.72).

هر رویداد یک خط JSON در فایل روزانه‌ی funnel/funnel_YYYY-MM-DD.jsonl است (UTC) و همیشه این‌ها را دارد:
    ts، kind، chat (حساب)، preset (کلید فعال)، pmod (آیا دستی تغییر کرده)، v (ورژن ربات)، tf، mode (PAPER/REAL).

kind ها:
    scan_summary : شمارنده‌ی هر ~۱۵ دقیقه: چند نماد بررسی شد، چند تا «ستاپی روی سطوح نبود»، چند برخورد، چند رد با گارد...
    scan         : نتیجه‌ی بررسیِ نمادهای مهم (گارد سقف/کف دیروز، تکراری، سطح قبلاً معامله‌شده، ...)
    touch        : برخورد با سطح (tid، جهت، سناریو، سطح، قیمت، طرح entry/sl/tp)
    vote         : وضعیت رأی‌ها (وقتی عوض شود) + «کلید ۳/۴/۵ روی همین برخورد چه می‌گفتند» (cf)
    block        : ورود خودکار بعد از تایید رأی‌ها چرا انجام نشد (دروازه‌ی R:R، دریفت، PDH/PDL، کندل BTC ...)
    pass_vote    : رأی‌گیری رد نشد: queued (صف تایید حرکت) / opened / card_sent
    fav_queue    : ورود به صف تایید حرکت (min_r، max_r، مهلت)
    fav_final    : پایان صف تایید حرکت (opened / expired / cancelled ... و علت)
    touch_final  : پایان عمر برخورد (expired / skipped / opened ...)
    entry        : معامله باز شد (trade_id، tid)
    trade_close  : معامله بسته شد (R، علت، MFE/MAE)
    shadow       : اگر در لحظه‌ی برخورد/صف وارد می‌شدیم تا چند ساعت بعد چه می‌شد (tp/sl اول، MFE/MAE، زمان رسیدن به +۰.۱۵/۰.۲۵/۰.۳۵R)
                   V3.44.107: sk = touch_d1 / touch_d2 = «ورود روی کلوز کندل برخورد» / «روی کلوز کندل بعدی» با همان SL/TP مطلق؛
                   فیلدهای entry (قیمت ورود فرضی)، plan_entry، shift_r (+ = قیمت بهتر از طرح)، و outcome='void' وقتی قیمت از قبل بیرون از SL/TP بوده.
    react        : V3.44.139: «واکنش قیمت به سطح» برای هر برخورد (۸ کندل بعد): label = held (≥۱R در جهت واکنش بدون کلوز پشت سطح) /
                   broke (کلوز پشت سطح اول رخ داد) / chop؛ k_res = شماره‌ی کندلِ تعیین‌تکلیف، run_r = ادامه‌ی حرکت بعد از شکست (دنبال‌شدن)،
                   c0 = مشخصات کندل برخورد (body_r، rej_wick، pen_r، range_r، vol_ratio، close_r)، c = کلوز ۳ کندل اول نسبت به سطح (به R)،
                   ok3 = چندتا از ۳ کلوز اول سمت درستِ سطح بودند. R = فاصله‌ی entry تا SL طرح؛ علامت‌ها در جهت واکنشِ مورد انتظار.
    settings     : V3.44.107: عکس کلیدهای روشن/تنظیمات مهم هر حساب (هر بار که عوض شود + روزی یک‌بار)؛ هش آن (cfg) در همه‌ی رکوردها هست.

هیچ‌چیز از این ماژول نباید جلوی کار ربات را بگیرد: همه‌ی خطاها قورت داده می‌شوند.
"""
import json
import logging
import os
import threading
import time

_log = logging.getLogger('funnel')
ENABLED = os.environ.get('FUNNEL_LOG_ENABLED', '1') != '0'
RETENTION_DAYS = int(os.environ.get('FUNNEL_RETENTION_DAYS', '60') or 60)
SUMMARY_SECONDS = int(os.environ.get('FUNNEL_SUMMARY_SECONDS', '900') or 900)
SHADOW_HORIZON_SECONDS = int(os.environ.get('FUNNEL_SHADOW_HORIZON_SECONDS', '21600') or 21600)   # ۶ ساعت
SHADOW_CHECK_SECONDS = 120
REACH_LEVELS = (0.15, 0.25, 0.35, 0.5, 1.0)
_MAX_STR = 500
_MAX_FILE_BYTES = int(os.environ.get('FUNNEL_MAX_FILE_MB', '150') or 150) * 1024 * 1024     # سقف هر فایل روزانه

_LOCK = threading.RLock()
_DIR = None
_COUNTERS = {}            # {(chat, preset, tf, mode): {key: n}}
_SHADOW = []              # صف ردیابی‌های در انتظار
_SHADOW_LOADED = False
_last_cleanup_day = None
_threads_started = False


def configure(dir_path):
    global _DIR
    _DIR = dir_path
    try:
        os.makedirs(_DIR, exist_ok=True)
    except OSError:
        pass


def _dir():
    return os.environ.get('FUNNEL_DIR', '').strip() or _DIR


def _clip(v, depth=0):
    if isinstance(v, str):
        return v if len(v) <= _MAX_STR else v[:_MAX_STR] + '…'
    if isinstance(v, float):
        return round(v, 10)
    if isinstance(v, dict):
        return {str(k): _clip(x, depth + 1) for k, x in list(v.items())[:60]} if depth < 4 else str(v)[:_MAX_STR]
    if isinstance(v, (list, tuple)):
        return [_clip(x, depth + 1) for x in list(v)[:60]] if depth < 4 else str(v)[:_MAX_STR]
    if v is None or isinstance(v, (bool, int)):
        return v
    return str(v)[:_MAX_STR]


def _day_file(ts=None):
    d = _dir()
    if not d:
        return None
    day = time.strftime('%Y-%m-%d', time.gmtime(ts or time.time()))
    return os.path.join(d, f'funnel_{day}.jsonl')


def emit(kind, **fields):
    """یک خط به فایل روزانه اضافه می‌کند. True اگر نوشته شد."""
    if not ENABLED:
        return False
    try:
        path = _day_file()
        if not path:
            return False
        rec = {'ts': round(time.time(), 3), 'kind': kind}
        rec.update({k: _clip(v) for k, v in fields.items()})
        line = json.dumps(rec, ensure_ascii=False, separators=(',', ':'), default=str) + '\n'
        with _LOCK:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            try:
                if os.path.getsize(path) > _MAX_FILE_BYTES:
                    return False
            except OSError:
                pass
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line)
        _maybe_cleanup()
        return True
    except Exception:
        return False


def _maybe_cleanup():
    global _last_cleanup_day
    day = time.strftime('%Y-%m-%d', time.gmtime())
    if _last_cleanup_day == day:
        return
    _last_cleanup_day = day
    d = _dir()
    if not d:
        return
    try:
        cutoff = time.time() - RETENTION_DAYS * 86400
        for name in os.listdir(d):
            if name.startswith('funnel_') and name.endswith('.jsonl'):
                p = os.path.join(d, name)
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
    except Exception:
        pass


# ------------------------------------------------------------------ شمارنده‌ها ----------
def count(chat, preset, tf, mode, key, n=1):
    if not ENABLED:
        return
    try:
        with _LOCK:
            c = _COUNTERS.setdefault((chat, preset, tf, mode), {})
            c[key] = c.get(key, 0) + n
        _start_threads()
    except Exception:
        pass


def flush_counters(force=True):
    with _LOCK:
        items = list(_COUNTERS.items())
        _COUNTERS.clear()
    for (chat, preset, tf, mode), c in items:
        if c:
            emit('scan_summary', chat=chat, preset=preset, tf=tf, mode=mode, window_s=SUMMARY_SECONDS, counts=c)


# ------------------------------------------------------------------ ردیاب سایه ----------
def _pending_path():
    d = _dir()
    return os.path.join(d, 'shadow_pending.json') if d else None


def _load_pending():
    global _SHADOW, _SHADOW_LOADED
    if _SHADOW_LOADED:
        return
    _SHADOW_LOADED = True
    p = _pending_path()
    if not p:
        return
    try:
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            _SHADOW = [x for x in data if isinstance(x, dict)]
    except (OSError, ValueError):
        _SHADOW = []


def _save_pending():
    p = _pending_path()
    if not p:
        return
    try:
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(_SHADOW, f, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        pass


def shadow_register(tid, shadow_kind, ctx, symbol, side, entry, sl, tp, tf, tf_seconds, start_ts=None, delay=None, level=None, due_s=None):
    """ثبت یک ردیابی: «اگر با این entry/sl/tp وارد می‌شدیم». هر (tid, kind) فقط یک‌بار."""
    if not ENABLED:
        return False
    try:
        entry, sl, tp = float(entry), float(sl), float(tp)
        if side not in ('BUY', 'SELL') or abs(entry - sl) <= 0:
            return False
        if delay is not None:
            delay = int(delay)       # V3.44.107: 0 = ورود روی کلوز کندل برخورد، 1 = روی کلوز کندل بعدی
        with _LOCK:
            _load_pending()
            if any(x.get('tid') == tid and x.get('sk') == shadow_kind for x in _SHADOW):
                return False
            _SHADOW.append({'tid': tid, 'sk': shadow_kind, 'ctx': dict(ctx or {}), 'symbol': symbol, 'side': side,
                            'entry': entry, 'sl': sl, 'tp': tp, 'tf': tf, 'tfs': int(tf_seconds or 900),
                            'start_ts': float(start_ts or time.time()),
                            'due': float(start_ts or time.time()) + (float(due_s) if due_s else SHADOW_HORIZON_SECONDS),
                            'delay': delay, 'level': (float(level) if level is not None else None)})
            if len(_SHADOW) > 4000:
                del _SHADOW[:len(_SHADOW) - 4000]
            _save_pending()
        _start_threads()
        return True
    except Exception:
        return False


def evaluate_path(side, entry, sl, tp, timestamps, highs, lows, start_ts, end_ts, tf_seconds):
    """مسیر فرضی روی کندل‌ها. اگر SL و TP در یک کندل لمس شوند محافظه‌کارانه SL حساب می‌شود.
    خروجی: dict با outcome ('tp'|'sl'|'none')، mfe_r، mae_r، reach{r: دقیقه}، mae_before{r: بیشترین ضرر قبل از رسیدن به r}، r_end."""
    is_long = side == 'BUY'
    risk = abs(entry - sl)
    mfe = mae = 0.0
    reach, mae_before = {}, {}
    outcome, out_ts = 'none', None
    last_close_r = None
    for t, hi, lo in zip(timestamps, highs, lows):
        if t < start_ts - 90:
            continue
        if t > end_ts:
            break
        fav = ((hi - entry) if is_long else (entry - lo)) / risk
        adv = ((entry - lo) if is_long else (hi - entry)) / risk
        hit_sl = (lo <= sl) if is_long else (hi >= sl)
        hit_tp = (hi >= tp) if is_long else (lo <= tp)
        if not hit_sl:           # اگر در همان کندل SL هم لمس شده، ترتیب نامعلوم است و محافظه‌کارانه «نرسید» حساب می‌شود
            for lv in REACH_LEVELS:
                k = f'{lv:g}'
                if k not in reach and fav >= lv:
                    reach[k] = round(max(0.0, (t - start_ts)) / 60.0, 1)
                    mae_before[k] = round(max(mae, adv), 3)
        if hit_sl:
            mae = max(mae, adv)
            outcome, out_ts = 'sl', t
            break
        if hit_tp:
            mfe = max(mfe, fav)
            outcome, out_ts = 'tp', t
            break
        mfe = max(mfe, fav)
        mae = max(mae, adv)
    r_tp = abs(tp - entry) / risk
    r_end = -1.0 if outcome == 'sl' else (r_tp if outcome == 'tp' else None)
    return {'outcome': outcome, 'out_min': (round((out_ts - start_ts) / 60.0, 1) if out_ts is not None else None),
            'mfe_r': round(mfe, 3), 'mae_r': round(mae, 3), 'reach': reach, 'mae_before': mae_before,
            'r_end': (round(r_end, 3) if r_end is not None else None), 'tp_r': round(r_tp, 3)}


def _evaluate_delayed(x, df, ts):
    """V3.44.107: ورودِ فرضیِ تأخیری. delay=0 → ورود روی کلوز کندلی که برخورد در آن رخ داد؛ delay=1 → روی کلوز کندل بعدی.
    SL/TP همان قیمت‌های مطلقِ طرح می‌مانند؛ R نسبت به ریسکِ جدید (فاصله‌ی ورودِ جدید تا SL) سنجیده می‌شود.
    خروجی: (res, entry_used, extra). اگر قیمت کلوز از قبل بیرون SL یا TP باشد outcome='void'."""
    side, sl, tp = x['side'], float(x['sl']), float(x['tp'])
    plan_entry = float(x['entry'])
    tfs = int(x.get('tfs') or 900)
    open_ts = (int(x['start_ts']) // tfs) * tfs + int(x['delay']) * tfs
    ent_ts = open_ts + tfs
    tsv, closes = ts.values, df['close'].values
    idx = None
    for j in range(len(tsv)):
        if abs(float(tsv[j]) - open_ts) < 1.0:
            idx = j
            break
    extra = {'delay': int(x['delay']), 'plan_entry': plan_entry, 'entry_ts': ent_ts}
    if idx is None:
        return {'outcome': 'void', 'void': 'no_candle'}, plan_entry, extra
    entry_new = float(closes[idx])
    risk_plan = abs(plan_entry - sl) or 1e-12
    is_long = side == 'BUY'
    extra['shift_r'] = round(((plan_entry - entry_new) if is_long else (entry_new - plan_entry)) / risk_plan, 3)
    beyond_sl = (entry_new <= sl) if is_long else (entry_new >= sl)
    beyond_tp = (entry_new >= tp) if is_long else (entry_new <= tp)
    if beyond_sl or beyond_tp:
        return {'outcome': 'void', 'void': ('beyond_sl' if beyond_sl else 'beyond_tp')}, entry_new, extra
    res = evaluate_path(side, entry_new, sl, tp, tsv, df['high'].values, df['low'].values, ent_ts,
                        float(x['start_ts']) + SHADOW_HORIZON_SECONDS, tfs)
    return res, entry_new, extra


REACT_CANDLES = 8
REACT_BREAK_R = 0.10       # کلوز دست‌کم این‌قدر (به R) پشت سطح = شکست
REACT_HELD_R = 1.0         # حرکت دست‌کم این‌قدر (به R) از سطح در جهت واکنش = نگه داشت


def _evaluate_reaction(x, df, ts):
    """V3.44.139: واکنش قیمت به سطح روی ۸ کندل بعد از کندل برخورد. جهت واکنشِ مورد انتظار = جهت سیگنال
    (BUY: بالای سطح می‌ماند، SELL: پایین سطح). خروجی dict (بدون tid/ctx) یا {'label': 'void', ...}."""
    side = x['side']
    level = x.get('level')
    risk = abs(float(x['entry']) - float(x['sl']))
    if level is None or risk <= 0:
        return {'label': 'void', 'void': 'no_level'}
    level = float(level)
    sg = 1.0 if side == 'BUY' else -1.0
    tfs = int(x.get('tfs') or 900)
    open_ts = (int(x['start_ts']) // tfs) * tfs
    tsv = ts.values
    idx = None
    for j in range(len(tsv)):
        if abs(float(tsv[j]) - open_ts) < 1.0:
            idx = j
            break
    if idx is None:
        return {'label': 'void', 'void': 'no_candle'}
    o, h, l, c = (df[k].values for k in ('open', 'high', 'low', 'close'))
    vol = df['volume'].values if 'volume' in df else None

    def sr(px):             # فاصله‌ی علامت‌دار از سطح به R؛ مثبت = سمت درستِ سطح
        return sg * (float(px) - level) / risk
    rng = float(h[idx]) - float(l[idx])
    if side == 'BUY':
        wick = (min(float(o[idx]), float(c[idx])) - float(l[idx])) / rng if rng > 0 else 0.0
        pen = max(0.0, level - float(l[idx])) / risk
    else:
        wick = (float(h[idx]) - max(float(o[idx]), float(c[idx]))) / rng if rng > 0 else 0.0
        pen = max(0.0, float(h[idx]) - level) / risk
    vr = None
    if vol is not None and idx >= 5:
        prev = [float(v) for v in vol[max(0, idx - 20):idx] if v == v]
        if prev and sum(prev) > 0:
            vr = round(float(vol[idx]) / (sum(prev) / len(prev)), 2)
    c0 = {'close_r': round(sr(c[idx]), 3), 'body_r': round(sg * (float(c[idx]) - float(o[idx])) / risk, 3),
          'rej_wick': round(wick, 3), 'pen_r': round(pen, 3), 'range_r': round(rng / risk, 3), 'vol_ratio': vr}
    last = min(len(tsv) - 1, idx + REACT_CANDLES)
    n_after = last - idx
    label, k_res = 'chop', None
    mfe = mae = 0.0
    closes_r = []
    for k in range(idx, last + 1):
        fav = sr(h[k] if side == 'BUY' else l[k])                 # بهترین نقطه‌ی کندل در جهت واکنش
        adv = -sr(l[k] if side == 'BUY' else h[k])                # بدترین نقطه‌ی کندل (پشت سطح)
        mfe, mae = max(mfe, fav), max(mae, adv)
        cl = sr(c[k])
        if k > idx and len(closes_r) < 3:
            closes_r.append(round(cl, 3))
        if k_res is None:
            brk, held = cl <= -REACT_BREAK_R, fav >= REACT_HELD_R
            if brk and held:
                label, k_res = 'chop', k - idx
            elif brk:
                label, k_res = 'broke', k - idx
            elif held:
                label, k_res = 'held', k - idx
    run_r = None
    if label == 'broke':          # بعد از شکست چقدر پشت سطح دنبال شد (حیوان درنده)
        run_r = round(max(0.0, mae), 3)
    return {'label': label, 'k_res': k_res, 'n_after': n_after, 'partial': bool(n_after < REACT_CANDLES),
            'level': level, 'risk_pct': round(risk / level * 100.0, 3) if level else None,
            'mfe_r': round(mfe, 3), 'mae_r': round(mae, 3), 'run_r': run_r, 'c0': c0, 'c': closes_r,
            'ok3': sum(1 for v in closes_r if v > 0)}


def shadow_run_once(get_klines_fn):
    """موارد سررسیدشده را روی کندل‌ها حل می‌کند و رویداد shadow می‌نویسد. تعداد حل‌شده را برمی‌گرداند."""
    if not ENABLED:
        return 0
    now = time.time()
    with _LOCK:
        _load_pending()
        due = [x for x in _SHADOW if x.get('due', 0) <= now]
    if not due:
        return 0
    by_key = {}
    for x in due:
        by_key.setdefault((x['symbol'], x['tf']), []).append(x)
    done = []
    for (symbol, tf), items in by_key.items():
        try:
            df = get_klines_fn(symbol, tf, 300)
        except Exception:
            df = None
        ok_df = df is not None and not getattr(df, 'empty', True)
        for x in items:
            if not ok_df:
                if now - x.get('due', now) > 86400:      # بعد از ۲۴ ساعت بی‌داده رها می‌شود
                    done.append(x)
                continue
            try:
                ts = df['timestamp'].astype('float64')
                if float(ts.max()) > 1e12:
                    ts = ts / 1000.0
                if x.get('sk') == 'react':
                    rr = _evaluate_reaction(x, df, ts)
                    pl = {'tid': x['tid'], 'symbol': x['symbol'], 'side': x['side'], 'entry': x['entry'], 'sl': x['sl']}
                    pl.update(dict(x.get('ctx') or {}))
                    pl['tf'] = tf
                    pl.update(rr)
                    emit('react', **pl)
                    done.append(x)
                    continue
                entry_used, extra = x['entry'], {}
                if x.get('delay') is not None:
                    res, entry_used, extra = _evaluate_delayed(x, df, ts)
                else:
                    res = evaluate_path(x['side'], x['entry'], x['sl'], x['tp'], ts.values, df['high'].values, df['low'].values,
                                        x['start_ts'], x['start_ts'] + SHADOW_HORIZON_SECONDS, x.get('tfs', 900))
                payload = {'tid': x['tid'], 'sk': x['sk'], 'symbol': x['symbol'], 'side': x['side'], 'entry': entry_used, 'sl': x['sl'],
                           'tp': x['tp'], 'horizon_s': SHADOW_HORIZON_SECONDS}
                payload.update(extra)
                payload.update(dict(x.get('ctx') or {}))
                payload['tf'] = tf
                payload.update(res)
                emit('shadow', **payload)
                done.append(x)
            except Exception:
                _log.exception('funnel shadow evaluate failed tid=%s', x.get('tid'))
                done.append(x)
    if done:
        with _LOCK:
            ids = {id(x) for x in done}
            _SHADOW[:] = [x for x in _SHADOW if id(x) not in ids]
            _save_pending()
    return len(done)


# ------------------------------------------------------------------ ترد پس‌زمینه ----------
_get_klines_fn = None


def start_background(get_klines_fn):
    global _get_klines_fn
    _get_klines_fn = get_klines_fn
    _start_threads()


def _loop():
    last_flush = time.time()
    last_shadow = 0.0
    while True:
        try:
            time.sleep(15)
            now = time.time()
            if now - last_flush >= SUMMARY_SECONDS:
                last_flush = now
                flush_counters()
            if _get_klines_fn and now - last_shadow >= SHADOW_CHECK_SECONDS:
                last_shadow = now
                shadow_run_once(_get_klines_fn)
        except Exception:
            time.sleep(30)


def _start_threads():
    global _threads_started
    if _threads_started or not ENABLED:
        return
    with _LOCK:
        if _threads_started:
            return
        _threads_started = True
    threading.Thread(target=_loop, daemon=True, name='funnel-log').start()
