"""پریست‌های آماده (کلید ۱، ۲، ...) برای مقایسه‌ی تنظیمات روی نتیجه‌ی واقعی معاملات.

هر پریست یک مجموعه‌ی کامل از تنظیمات «شرایط ورود» است. با لمس یک کلید همه‌ی کلیدهای مدیریت‌شده
روی مقدار همان پریست می‌نشینند (چیزی از پریست قبلی باقی نمی‌ماند). هر معامله موقع باز شدن با نام
پریست برچسب می‌خورد و در ژورنال (trade_journal.json) ذخیره می‌شود؛ پس بعداً می‌شود نتیجه‌ی هر پریست
را جدا حساب کرد.

آنچه در پریست‌ها نیست و بین همه ثابت می‌ماند (تا مقایسه فقط به «شرایط ورود» وابسته باشد):
خروج و حفظ سود (بستن با سود، بستن همه با مجموع سود، هشدارها)، ریسک هر معامله، تایم‌فریم، نمادها،
سقف تعداد معاملات، حالت دستیار.

برای عوض‌کردن محتوای یک پریست فقط دیکشنری‌های بالای همین فایل را ویرایش کن.
"""
import time

# ---------------------------------------------------------------- پایه (کلید ۱) ----------
_GATES_ON = (
    'gate_4h_close_block_enabled', 'gate_fc_level_enabled',
    'sweep_require_reclaim', 'sweep_require_reversal_candle', 'sweep_enable_retest_continuation',
    'gate_min_score_enabled', 'gate_min_rr_enabled', 'gate_max_sl_atr_enabled',
    'gate_fee_ratio_enabled', 'gate_open_fee_ratio_enabled', 'gate_total_risk_cap_enabled',
    'gate_cooldown_enabled', 'gate_traded_level_enabled', 'gate_risk_guard_enabled',
    'gate_btceth_aligned_enabled',
)
_GATES_OFF = (
    'gate_fc_btceth_enabled', 'gate_fc_h4_enabled', 'gate_fc_tf_enabled',
    'gate_fc_rsi_enabled', 'gate_fc_macd_enabled', 'gate_fc_adx_enabled',
    'gate_fc_vol_enabled', 'use_edge_proxy_gate',
    'gate_fc_ylevel_enabled',      # V3.44.36: رأی «سقف/کف دیروز» در پریست‌ها خاموش می‌ماند تا مقایسه‌ی پریست‌ها تغییر نکند
)

BASE_CFG = {
    **{k: True for k in _GATES_ON},
    **{k: False for k in _GATES_OFF},
    'sweep_require_confirmation_candle': True,
    # مدل سطوح نصف‌کردن
    'halving_model_enabled': True,
    'halving_k_atr': 3.0,
    'halving_max_depth': 10,
    'halving_max_trade_depth': 0,          # 0 = همه‌ی عمق‌ها
    'halving_dynamic_k': False,
    # حالت‌های ۶گانه
    **{f'scenario_{n}_enabled': True for n in range(1, 7)},
}

# کلیدهای سطح‌بالای سشن. هشدارهای «بله، وارد شو / نه» در همه‌ی پریست‌ها خاموش‌اند تا
# نتیجه به تصمیم دستی تو وابسته نشود (هشدار = آدم در حلقه = متغیر اضافه در مقایسه).
BASE_SESSION = {
    'trend_warn_enabled': False,
    'ind_warn_enabled': False,
    'symbol_tf_regime_warn_enabled': False,
    'symbol_h4_regime_warn_enabled': False,
    'fav_confirm_enabled': False,
    'fav_confirm_min_r': 0.15,
    'fav_confirm_max_r': 0.30,
    'fav_confirm_max_mode': 'tp',
    'fav_confirm_max_tp_pct': 0.20,
    'fav_confirm_wait_sec': 1800,
}

PRESETS = {
    '1': {
        'label': 'پایه (هفته ۱)',
        'desc': 'مدل نصف‌کردن k=3 + هم‌جهتی BTC/ETH + بلاک ۳۰ دقیقه‌ی آخر کندل ۴ساعته + همه‌ی گیت‌های کیفیت و ریسک. '
                'تاییدهای سخت RSI/MACD/ADX و رژیم‌ها خاموش.',
        'cfg': {}, 'session': {},
    },
    '2': {
        'label': 'پایه + k پویا (هفته ۲)',
        'desc': 'مثل کلید ۱، فقط k پویا روشن (عمق سطوح با نوسان تطبیق می‌یابد).',
        'cfg': {'halving_dynamic_k': True}, 'session': {},
    },
    '3': {
        'label': 'پایه + صبر برای تایید حرکت',
        'desc': 'مثل کلید ۱، فقط «صبر برای تایید حرکت به نفع معامله» روشن (حداقل +0.15R، سقف ۲۰٪ مسیر تا هدف، مهلت ۳۰ دقیقه).',
        'cfg': {}, 'session': {'fav_confirm_enabled': True},
    },
    '4': {
        'label': 'پایه + سخت‌گیر',
        'desc': 'مثل کلید ۱، به‌علاوه تاییدهای سخت: RSI، MACD، ADX، رژیم ۵/۱۵ و ۴ساعته‌ی نماد و هم‌جهتی BTC/ETH با معامله. '
                'سیگنال کم‌تر، ولی احتمالاً تمیزتر.',
        'cfg': {'gate_fc_btceth_enabled': True, 'gate_fc_h4_enabled': True, 'gate_fc_tf_enabled': True,
                'gate_fc_rsi_enabled': True, 'gate_fc_macd_enabled': True, 'gate_fc_adx_enabled': True},
        'session': {},
    },
    '5': {
        'label': 'باز (کم‌فیلتر، شاهد)',
        'desc': 'مثل کلید ۱ ولی بدون شرط هم‌جهتی BTC/ETH و بدون کندل تایید اضافه. برای اینکه ببینیم فیلترها اصلاً کمک می‌کنند یا نه.',
        'cfg': {'gate_btceth_aligned_enabled': False, 'sweep_require_confirmation_candle': False},
        'session': {},
    },
}


def _full(name):
    p = PRESETS[name]
    return {**BASE_CFG, **p['cfg']}, {**BASE_SESSION, **p['session']}


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
    lines = ['🎚 *پریست‌های آماده*', '',
             'هر کلید یک مجموعه‌ی کامل از شرایط ورود است. با لمس آن همه‌ی تنظیماتِ مربوطه یک‌جا عوض می‌شود. '
             'هر معامله با نام پریستِ فعال برچسب می‌خورد تا بعداً نتیجه‌ی هر کلید جدا حساب شود.', '']
    for n, p in PRESETS.items():
        mark = '✅ ' if n == act else ''
        lines.append(f"{mark}کلید {_fa(n)} — {p['label']}\n{p['desc']}")
        lines.append('')
    if act in PRESETS:
        diff = preset_diff(s, act)
        if diff:
            lines.append(f"⚠️ بعد از اعمال کلید {_fa(act)} این تنظیمات دستی عوض شده: {len(diff)} مورد. "
                         "معامله‌های جدید با علامت «دستی تغییر کرده» ثبت می‌شوند و در مقایسه جدا حساب می‌شوند. "
                         "برای تمیز ماندن آمار، دوباره همان کلید را بزن.")
    else:
        lines.append('هنوز هیچ پریستی اعمال نشده؛ معامله‌ها بدون برچسب ثبت می‌شوند.')
    lines.append('')
    lines.append('ثابت بین همه‌ی کلیدها: خروج و حفظ سود، ریسک، تایم‌فریم، نمادها و حالت دستیار. '
                 'هشدارهای «بله، وارد شو / نه» در همه‌ی کلیدها خاموش‌اند تا نتیجه به تصمیم دستی وابسته نشود.')
    return '\n'.join(lines)[:3900]


def keyboard(s):
    act = s.get('active_preset')
    rows = [[{'text': f"{'✅' if n == act else '⚪'} کلید {_fa(n)} — {p['label']}", 'callback_data': f'/preset_apply_{n}'}]
            for n, p in PRESETS.items()]
    rows.append([{'text': '📊 نتیجه‌ی هر کلید', 'callback_data': '/preset_stats'}])
    rows.append([{'text': '📤 ارسال فایل ژورنال معاملات', 'callback_data': '/preset_export'}])
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
