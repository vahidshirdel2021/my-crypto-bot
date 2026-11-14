"""پریست «معمولی» - تنها پریست ربات (V3.44.169).

پریست یک مجموعه‌ی کامل از تنظیمات است. با لمس کلید، همه‌ی کلیدهای مدیریت‌شده روی مقدار همین پریست
می‌نشینند (چیزی از تنظیم قبلی باقی نمی‌ماند). هر معامله موقع باز شدن با نام پریست برچسب می‌خورد و در ژورنال
(trade_journal.json) ذخیره می‌شود.

شامل: شرایط ورود، رأی‌گیری بعد از برخورد با سطح، صبر برای تایید حرکت، دروازه‌های BTC، سربه‌سر خودکار
و تریلینگ هوشمند. آنچه در پریست نیست و دست‌نخورده می‌ماند: ریسک هر معامله، تایم‌فریم، نمادها، سقف تعداد معامله‌ها،
حالت دستیار، «تشخیص رژیم دقیق‌تر» (کلید سراسری ربات) و آستانه‌های سربه‌سر/تریلینگ.

برای عوض‌کردن محتوا فقط دیکشنری‌های بالای همین فایل را ویرایش کن.
"""
import copy
import json
import os
import threading
import time

# ---------------------------------------------------------------- پایه (کلید ۱) ----------
_GATES_ON = (
    'gate_touch_dir_fixed_enabled',         # V3.44.166: جهت ثابت از الگوی برخورد (پیش‌فرض روشن)
    'gate_min_rr_enabled', 'gate_max_sl_atr_enabled',        # کیفیت و ریسک (بدون تغییر)
    # شرایط ورود و رأی‌گیری
    'gate_touch_vote_enabled',              # رأی‌گیری فیلترها بعد از برخورد با سطح
    'gate_fc_level_enabled',                # هم‌جهتی: کندل بسته‌شده سمت درست سطح
    'gate_btc_candle_enabled',              # ورود وقتی کندل BTC با معامله هم‌جهت است
    # الگوهای سطح
    # کیفیت و ریسک
    'gate_cooldown_enabled', 'gate_traded_level_enabled', 'gate_risk_guard_enabled',
)
_GATES_OFF = (
    'gate_fc_btceth_enabled', 'gate_fc_h4_enabled',
    'gate_fc_rsi_enabled', 'gate_fc_macd_enabled', 'gate_fc_adx_enabled',
    'gate_fc_vol_enabled', 'use_edge_proxy_gate',
    # V3.44.166: پیش‌فرض خاموش (فهرست شماره‌دار کاربر)
    'gate_touch_pattern_vote_enabled', 'gate_4h_close_block_enabled', 'gate_fc_tf_enabled', 'gate_fc_ylevel_enabled',
    'gate_btc_front_level_enabled', 'gate_btc_chop_enabled', 'gate_pd_level_enabled',
    'sweep_require_reclaim', 'sweep_require_reversal_candle', 'sweep_enable_retest_continuation',
    'gate_min_score_enabled', 'gate_fee_ratio_enabled', 'gate_open_fee_ratio_enabled', 'gate_total_risk_cap_enabled',
    'gate_btceth_aligned_enabled',          # «فقط وقتی BTC و ETH هم‌جهت‌اند»
    'gate_final_regime_enabled',            # رژیم بازار در مرحله‌ی آخر ورود
    'gate_h4_tier_enabled',                 # رتبه‌ی نرم با رژیم ۴ ساعته
    'gate_inverse_trading_enabled',         # معاملات معکوس (آزمایشی)
    'gate_fc_btcpat_enabled',               # V3.44.47: رأی «الگوی BTC روی سطح خودش»
    'gate_fc_btcside_enabled',              # V3.44.102: رأی «سمت BTC نسبت به نزدیک‌ترین سطح»
    'gate_fc_symreg_enabled',               # V3.44.104: رأی «رژیم نماد در تایم‌فریم فعال»
    'gate_symbol_structure_block_enabled',  # V3.44.105: مانع ثبت وقتی ساختار سقف/کف نماد خلاف جهت سیگنال است
    'gate_touch_bias_block_enabled',        # V3.44.132: مانع جهت مخالفِ جهت غالب لیست انتظار (۷۰٪)
    'gate_touch_need_dominant_enabled',     # V3.44.133: جهت غالب مشخص نباشد = بدون معامله (پیش‌فرض خاموش)
)

BASE_CFG = {
    **{k: True for k in _GATES_ON},
    **{k: False for k in _GATES_OFF},
    'sweep_require_confirmation_candle': False,      # V3.44.166: پیش‌فرض خاموش
    # مدل سطوح نصف‌کردن (۱۵ دقیقه: ATR ۴، عمق ۱۰ = پیش‌فرض خود ربات برای این تایم)
    'halving_model_enabled': True,
    'halving_k_atr': 4.0,
    'halving_max_depth': 10,
    'halving_max_trade_depth': 0,          # 0 = همه‌ی عمق‌ها
    'halving_dynamic_k': False,
    # حالت‌های معامله: ۶ حالت روشن، حالت ۷ (برخورد ساده) خاموش
    **{f'scenario_{n}_enabled': True for n in range(1, 7)},
    'scenario_7_enabled': False,
}

# کلیدهای سطح‌بالای سشن. هشدارهای «بله، وارد شو / نه» در همه‌ی پریست‌ها خاموش‌اند تا
# نتیجه به تصمیم دستی تو وابسته نشود (هشدار = آدم در حلقه = متغیر اضافه در مقایسه).
BASE_SESSION = {
    # هشدارهای «بله، وارد شو / نه» خاموش‌اند
    'trend_warn_enabled': False,
    'ref_level_warn_enabled': False,
    'ind_warn_enabled': False,
    'symbol_tf_regime_warn_enabled': False,
    'symbol_h4_regime_warn_enabled': False,
    # ورود خودکار رأی‌گیری: اکثریت ساده
    'touch_auto_mode': 'majority',
    # صبر برای تایید حرکت به نفع معامله
    'fav_confirm_enabled': True,
    'fav_confirm_min_r': 0.15,
    'fav_confirm_max_r': 0.30,
    'fav_confirm_max_mode': 'tp',
    'fav_confirm_max_tp_pct': 0.20,
    'fav_confirm_wait_sec': 1800,
    # مدیریت معامله
    'be_close_auto_enabled': True,         # بستن خودکار سربه‌سر
    'trail_enabled': True,                 # تریلینگ استاپ هوشمند
}

# V3.44.47: چهار پریستِ مقایسه (هر حساب یکی). همه‌ی تنظیمات یکی است (۱۵ دقیقه، ATR ۴، عمق ۱۰، اکثریت ساده، تایید حرکت، دروازه‌های BTC)
# و فقط «چه کسی رأی می‌دهد» فرق دارد؛ جهت در همه از الگوی برخورد ثابت است و رأی‌ها فقط تایید/رد می‌کنند.
# رأی‌ها گروهی شمرده می‌شوند: الگوی BTC، روند، مومنتوم، سطح (+ حجم جدا اگر روشن باشد).
_FIXED_DIR = {'gate_touch_dir_fixed_enabled': True, 'gate_touch_pattern_vote_enabled': False}
_MOMENTUM = {'gate_fc_rsi_enabled': True, 'gate_fc_macd_enabled': True, 'gate_fc_adx_enabled': True}

# V3.44.169: فقط یک پریست داریم: «معمولی» (شناسه‌ی داخلی '3' برای سازگاری با ژورنال و نسخه‌های ذخیره‌شده).
# پریست‌های دیگر (تنظیمات من، جهت ثابت پایه، محافظه‌کار، سخت‌گیر) و انتخاب حالت معامله توسط کاربر حذف شدند.
PRESETS = {
    '3': {
        'label': 'معمولی',
        'desc': 'رأی‌دهنده‌ها: روند (رژیم ۵/۱۵)، سطح (کلوز + سقف/کف دیروز) و مومنتوم (RSI، MACD، ADX). ورود با اکثریت ساده‌ی رأی‌ها؛ '
                'صبر برای تایید حرکت: حداقل +0.15R.',
        'cfg': {**_FIXED_DIR, **_MOMENTUM},
        'session': {},
    },
}


# ---------------------------------------------------------------- V3.44.70: ذخیره‌ی دلخواه هر کلید ----------
# ادمین می‌تواند تنظیمات فعلی خودش را در «هر کلید جداگانه» ذخیره کند. نسخه‌ی ذخیره‌شده روی پیش‌فرضِ کد می‌نشیند
# (کلیدهایی که بعداً به کد اضافه شوند همچنان پیش‌فرض می‌گیرند) و با «بازگشت به پیش‌فرض» پاک می‌شود.
_CUSTOM_LOCK = threading.RLock()
_CUSTOM_PATH = None


def set_custom_path(path):
    global _CUSTOM_PATH
    _CUSTOM_PATH = path


def _custom_path():
    return os.environ.get('PRESETS_CUSTOM_PATH', '').strip() or _CUSTOM_PATH


def _load_custom():
    path = _custom_path()
    if not path:
        return {}
    with _CUSTOM_LOCK:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if k in PRESETS and isinstance(v, dict)
            and isinstance(v.get('cfg'), dict) and isinstance(v.get('session'), dict)}


def _write_custom(data):
    path = _custom_path()
    if not path:
        return False
    with _CUSTOM_LOCK:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or '.', exist_ok=True)
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    return True


def has_custom(name):
    return name in _load_custom()


def _default_full(name):
    p = PRESETS[name]
    return {**BASE_CFG, **p['cfg']}, {**BASE_SESSION, **p['session']}


def _full(name):
    cfg, ses = _default_full(name)
    c = _load_custom().get(name)
    if c:
        cfg = {**cfg, **c['cfg']}
        ses = {**ses, **c['session']}
    return cfg, ses


def save_custom(s, name):
    """تنظیمات فعلی سشن را در همین کلید ذخیره می‌کند و آن را کلید فعال می‌کند. تعداد کلیدهای ذخیره‌شده یا None."""
    if name not in PRESETS or not _custom_path():
        return None
    dcfg, dses = _default_full(name)
    cur = s.get('strategy_config') or {}
    cfg = {k: copy.deepcopy(cur[k]) if k in cur else dcfg[k] for k in BASE_CFG}
    # انتخاب دستی k/عمق هر تایم‌فریم (halving_tf) هم جزو کلید است تا بعد از اعمال پاک نشود
    if isinstance(cur.get('halving_tf'), dict) and cur['halving_tf']:
        cfg['halving_tf'] = copy.deepcopy(cur['halving_tf'])
    ses = {k: copy.deepcopy(s[k]) if k in s else dses[k] for k in BASE_SESSION}
    data = _load_custom()
    data[name] = {'cfg': cfg, 'session': ses, 'saved_at': time.time()}
    if not _write_custom(data):
        return None
    s['active_preset'] = name
    s['active_preset_at'] = time.time()
    return len(cfg) + len(ses)


def reset_custom(name):
    """نسخه‌ی ذخیره‌شده‌ی این کلید را پاک می‌کند (برگشت به پیش‌فرض کد). True اگر چیزی پاک شد."""
    data = _load_custom()
    if name not in data:
        return False
    del data[name]
    return _write_custom(data)


def managed_keys():
    return set(BASE_CFG) | set(BASE_SESSION)


def _eq(a, b):
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return a == b


def apply_preset(s, name):
    """پریست را کامل روی سشن می‌نشاند (همه‌ی کلیدهای مدیریت‌شده). True اگر نام معتبر بود."""
    if name not in PRESETS:
        return False
    cfg_vals, ses_vals = _full(name)
    cfg = s.setdefault('strategy_config', {})
    cfg.update(cfg_vals)
    cfg.pop('halving_tf', None)       # انتخاب‌های دستی k/عمق هر تایم‌فریم پاک می‌شود؛ پیش‌فرض ربات (۱۵ دقیقه: ATR ۴، عمق ۱۰) برقرار می‌شود
    if 'halving_tf' in cfg_vals:      # مگر اینکه نسخه‌ی ذخیره‌شده‌ی ادمین خودش آن را داشته باشد
        cfg['halving_tf'] = copy.deepcopy(cfg_vals['halving_tf'])
    s.update(ses_vals)
    s['setup_legacy_view'] = False
    s['active_preset'] = name
    s['active_preset_at'] = time.time()
    return True


def preset_diff(s, name=None):
    """کلیدهایی که الان با پریست فعال فرق دارند (یعنی بعد از اعمال پریست دستی عوض شده‌اند)."""
    name = name or s.get('active_preset')
    if name not in PRESETS:
        return []
    cfg_vals, ses_vals = _full(name)
    cfg = s.get('strategy_config') or {}
    out = []
    for k, v in cfg_vals.items():
        if k not in cfg or not _eq(cfg.get(k), v):
            out.append(k)
    for k, v in ses_vals.items():
        if k not in s or not _eq(s.get(k), v):
            out.append(k)
    return out


def trade_tag(s):
    """فیلدهایی که هنگام باز شدن هر معامله به آن اضافه می‌شود."""
    name = s.get('active_preset')
    if name not in PRESETS:
        return {'preset': None, 'preset_modified': False, 'preset_diff': []}
    diff = preset_diff(s, name)
    return {'preset': name, 'preset_modified': bool(diff), 'preset_diff': diff[:8]}


_FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def _fa(n):
    return str(n).translate(_FA)


def menu_text(s):
    act = s.get('active_preset')
    lines = ['🎚 *پریست*', '',
             'فقط یک پریست داریم: «معمولی». با لمس آن همه‌ی تنظیماتِ مربوطه یک‌جا روی مقدار همین پریست می‌نشیند. '
             'هر معامله با نام پریستِ فعال برچسب می‌خورد.', '']
    _custom_keys = _load_custom()
    for n, p in PRESETS.items():
        mark = '✅ ' if n == act else ''
        cust = ' ✏️ (نسخه‌ی ذخیره‌شده‌ی ادمین)' if n in _custom_keys else ''
        lines.append(f"{mark}{p['label']}{cust}\n{p['desc']}")
        lines.append('')
    if act in PRESETS:
        diff = preset_diff(s, act)
        if diff:
            lines.append(f"⚠️ بعد از اعمال پریست این تنظیمات دستی عوض شده: {len(diff)} مورد. "
                         "معامله‌های جدید با علامت «دستی تغییر کرده» ثبت می‌شوند و در مقایسه جدا حساب می‌شوند. "
                         "برای تمیز ماندن آمار، دوباره پریست را بزن.")
    else:
        lines.append('هنوز پریستی اعمال نشده؛ معامله‌ها بدون برچسب ثبت می‌شوند.')
    lines.append('')
    lines.append('💾 «ذخیره» تنظیمات فعلی خودت را در همین پریست می‌نویسد (توضیح بالا دیگر کامل نیست و فقط پیش‌فرض را نشان می‌دهد)؛ '
                 '«↩️ پیش‌فرض» نسخه‌ی ذخیره‌شده را پاک می‌کند. تغییرش برای همه‌ی کاربران اثر دارد.')
    lines.append('')
    lines.append('در پریست نیست و دست‌نخورده می‌ماند: ریسک هر معامله، تایم‌فریم، نمادها، حالت دستیار و تشخیص رژیم دقیق‌تر. '
                 'هشدارهای «بله، وارد شو / نه» خاموش‌اند.')
    return '\n'.join(lines)[:3900]


# V3.44.169: پریست پیش‌فرض همه‌ی کاربران «معمولی» است و انتخاب حالت معامله (منو و ویزارد) حذف شد.
DEFAULT_MODE = '3'


def keyboard(s):
    act = s.get('active_preset')
    rows = []
    custom = _load_custom()
    for n, p in PRESETS.items():
        rows.append([{'text': f"{'✅' if n == act else '⚪'} {p['label']}" + (' ✏️' if n in custom else ''),
                      'callback_data': f'/preset_apply_{n}'}])
        rows.append([{'text': '👁 نمایش فعال‌های پریست', 'callback_data': f'/preset_show_{n}'}])   # V3.44.87
        row = [{'text': '💾 ذخیره‌ی تنظیمات فعلی در پریست', 'callback_data': f'/preset_save_{n}'}]
        if n in custom:
            row.append({'text': '↩️ پیش‌فرض', 'callback_data': f'/preset_reset_{n}'})
        rows.append(row)
    rows.append([{'text': '📊 نتیجه‌ی هر کلید', 'callback_data': '/preset_stats'}])
    rows.append([{'text': '🧭 گزارش بلاتکلیفی BTC (روشن یا خاموش؟)', 'callback_data': '/undecided_report'}])
    rows.append([{'text': '🔎 نمادهای بین دو سطح زرد نزدیک (مثل BTC)', 'callback_data': '/levels_gap_scan'}])
    rows.append([{'text': '🧪 بک‌تست (نماد و دوره را خودم انتخاب می‌کنم)', 'callback_data': '/backtest_start'}])   # V3.44.126
    rows.append([{'text': '🧪 بک‌تست BTC (۶ ماه اول سال، ۱۵ دقیقه)', 'callback_data': '/backtest_btc'}])
    rows.append([{'text': '📤 ارسال فایل ژورنال معاملات', 'callback_data': '/preset_export'}])
    rows.append([{'text': '🧬 گزارش قیف کلیدها', 'callback_data': '/funnel_report'}, {'text': '📦 داده‌ی قیف', 'callback_data': '/funnel_export'}])
    rows.append([{'text': '🔙 قوانین معامله (فیلترها)', 'callback_data': '/trade_filter_management'}])
    rows.append([{'text': '🏠 منوی اصلی', 'callback_data': '/menu'}])
    return {'inline_keyboard': rows}


# ---------------------------------------------------------------- آمار ----------
def _num(x):
    try:
        v = float(x)
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def group_name(t):
    p = t.get('preset')
    if p not in PRESETS:
        return 'بدون برچسب'
    return f'کلید {_fa(p)} (دستی تغییر کرده)' if t.get('preset_modified') else f'کلید {_fa(p)}'


def summarize(trades):
    """trades: لیست رکوردهای ژورنال. خروجی: {گروه: آمار}."""
    groups = {}
    for t in trades:
        pnl = _num(t.get('pnl_usdt'))
        if pnl is None:
            continue
        groups.setdefault(group_name(t), []).append(t)
    out = {}
    for g, ts in groups.items():
        pnls = [_num(t.get('pnl_usdt')) for t in ts]
        wins = [x for x in pnls if x > 0]
        losses = [x for x in pnls if x < 0]
        rs = [r for r in (_num(t.get('realized_r')) for t in ts) if r is not None]
        mfe = [r for r in (_num(t.get('mfe_r')) for t in ts) if r is not None]
        gl = abs(sum(losses))
        out[g] = {
            'n': len(ts), 'wins': len(wins), 'win_rate': len(wins) / len(ts) * 100.0,
            'pnl': sum(pnls), 'avg_pnl': sum(pnls) / len(ts),
            'avg_r': (sum(rs) / len(rs)) if rs else None,
            'avg_mfe_r': (sum(mfe) / len(mfe)) if mfe else None,
            'profit_factor': (sum(wins) / gl) if gl > 0 else None,
        }
    return out


def format_stats(stats, min_sample=30):
    if not stats:
        return 'هنوز معامله‌ی بسته‌شده‌ای در ژورنال نیست.'
    lines = ['📊 *نتیجه‌ی هر کلید*', '']
    for g in sorted(stats):
        a = stats[g]
        r = '—' if a['avg_r'] is None else f"{a['avg_r']:+.2f}R"
        pf = '—' if a['profit_factor'] is None else f"{a['profit_factor']:.2f}"
        small = ' ⚠️ نمونه کم' if a['n'] < min_sample else ''
        lines.append(f"{g}{small}\nمعامله: {a['n']} | برد: {a['win_rate']:.0f}% | جمع: {a['pnl']:+.2f}$ | "
                     f"میانگین هر معامله: {a['avg_pnl']:+.2f}$ ({r}) | ضریب سود: {pf}")
        lines.append('')
    lines.append(f'با کمتر از {min_sample} معامله در هر کلید، تفاوت‌ها بیشتر شانس است تا واقعیت.')
    return '\n'.join(lines)[:3900]
