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


def shadow_register(tid, shadow_kind, ctx, symbol, side, entry, sl, tp, tf, tf_seconds, start_ts=None):
    """ثبت یک ردیابی: «اگر با این entry/sl/tp وارد می‌شدیم». هر (tid, kind) فقط یک‌بار."""
    if not ENABLED:
        return False
    try:
        entry, sl, tp = float(entry), float(sl), float(tp)
        if side not in ('BUY', 'SELL') or abs(entry - sl) <= 0:
            return False
        with _LOCK:
            _load_pending()
            if any(x.get('tid') == tid and x.get('sk') == shadow_kind for x in _SHADOW):
                return False
            _SHADOW.append({'tid': tid, 'sk': shadow_kind, 'ctx': dict(ctx or {}), 'symbol': symbol, 'side': side,
                            'entry': entry, 'sl': sl, 'tp': tp, 'tf': tf, 'tfs': int(tf_seconds or 900),
                            'start_ts': float(start_ts or time.time()), 'due': float(start_ts or time.time()) + SHADOW_HORIZON_SECONDS})
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
                res = evaluate_path(x['side'], x['entry'], x['sl'], x['tp'], ts.values, df['high'].values, df['low'].values,
                                    x['start_ts'], x['start_ts'] + SHADOW_HORIZON_SECONDS, x.get('tfs', 900))
                payload = {'tid': x['tid'], 'sk': x['sk'], 'symbol': x['symbol'], 'side': x['side'], 'entry': x['entry'], 'sl': x['sl'],
                           'tp': x['tp'], 'horizon_s': SHADOW_HORIZON_SECONDS}
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
