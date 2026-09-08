from strategy import STRATEGY_DEFAULTS
import os
_ADMIN_CHAT_IDS_RAW = os.environ.get("ADMIN_CHAT_IDS", os.environ.get("ALLOWED_CHAT_IDS", "")).strip()
ADMIN_CHAT_IDS = {int(x.strip()) for x in _ADMIN_CHAT_IDS_RAW.split(",") if x.strip().lstrip("-").isdigit()}
ADMIN_CHAT_IDS.update({115981067, 8621862979, 1878257830, 8714168271})

CHAT_INPUT_PLACEHOLDER = "نام ارز خود را جهت تحلیل وارد کنید"


def get_bottom_menu_keyboard(is_active=False, is_open=True):
    # کیبورد سفارشی سبک و ثابت (پایین صفحه) - همیشه در دسترس، مستقل از منوی این‌لاین
    return {
        "keyboard": [
            [{"text": "📊 وضعیت بازار"}, {"text": "🔄 پیگیری پوزیشن‌ها"}],
            [{"text": "🏠 منوی اصلی"}, {"text": "🆘 بستن اضطراری همه"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": CHAT_INPUT_PLACEHOLDER,
    }


def get_params_menu_keyboard(session=None):
    s = session or {}; c = s.get("strategy_config", STRATEGY_DEFAULTS)
    if s.get("user_experience", "simple") != "advanced":
        return {"inline_keyboard": [
            [{"text": "🟢 حالت متعادل ⭐", "callback_data": "/profile_balanced"}],
            [{"text": "🛡️ محافظه‌کارانه", "callback_data": "/profile_conservative"}, {"text": "⚡ فرصت‌های بیشتر", "callback_data": "/profile_opportunity"}],
            [{"text": "🎓 حالت حرفه‌ای / جزئیات", "callback_data": "/profile_advanced"}],
            [{"text": "❓ آموزش مفاهیم", "callback_data": "/learn_menu"}],
            [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
        ]}
    return {"inline_keyboard": [
        [{"text": "🔵 حالت ساده", "callback_data": "/profile_simple"}],
        [{"text": "❓ ADX چیست؟", "callback_data": "/learn_adx"}, {"text": "❓ ATR چیست؟", "callback_data": "/learn_atr"}],
        [{"text": "❓ RSI چیست؟", "callback_data": "/learn_rsi"}, {"text": "❓ R:R چیست؟", "callback_data": "/learn_rr"}],
        [{"text": f"🎯 ADX: {float(c.get('min_adx',20)):.1f}", "callback_data": "/dummy"}],
        [{"text": "➕ ADX +۱", "callback_data": "/adx_up"}, {"text": "➖ ADX -۱", "callback_data": "/adx_down"}],
        [{"text": f"🛡️ ضریب حد ضرر: {float(c.get('sl_multiplier',1.5)):.1f}x", "callback_data": "/dummy"}],
        [{"text": "➕ حد ضرر +۰٫۲", "callback_data": "/sl_up"}, {"text": "➖ حد ضرر -۰٫۲", "callback_data": "/sl_down"}],
        [{"text": f"🎯 ضریب حد سود پایه: {float(c.get('tp_multiplier',2.0)):.1f}x", "callback_data": "/dummy"}],
        [{"text": "➕ حد سود پایه +۰٫۵", "callback_data": "/tp_up"}, {"text": "➖ حد سود -۰٫۵", "callback_data": "/tp_down"}],
        [{"text": f"🧠 خروج پویا: {'🟢 فعال' if c.get('dynamic_exits',True) else '🔴 خاموش'}", "callback_data": "/dummy"}],
        [{"text": f"📊 حداقل کیفیت: {float(c.get('min_trade_score',60)):.0f}/100", "callback_data": "/dummy"}],
        [{"text": f"⚖️ حداقل R:R: {float(c.get('min_rr',1.3)):.2f}R", "callback_data": "/dummy"}],
        [{"text": f"⚠️ ریسک: {float(s.get('risk_per_trade_pct',0.5)):.2f}%", "callback_data": "/dummy"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_learn_menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "📈 ADX — قدرت روند", "callback_data": "/learn_adx"}],
        [{"text": "🌪 ATR — نوسان بازار", "callback_data": "/learn_atr"}],
        [{"text": "📊 RSI — قدرت حرکت", "callback_data": "/learn_rsi"}],
        [{"text": "⚖️ R:R — سود به ضرر", "callback_data": "/learn_rr"}],
        [{"text": "🧠 چرا ربات این‌ها را می‌بیند؟", "callback_data": "/learn_why"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_performance_keyboard(chat_id=None, session=None):
    k = [
        [{"text": "📅 امروز", "callback_data": "/performance_today"}, {"text": "📆 ۷ روز", "callback_data": "/performance_week"}],
        [{"text": "🗓 ۳۰ روز", "callback_data": "/performance_month"}, {"text": "📊 کل سابقه", "callback_data": "/performance"}],
        [{"text": "📋 معاملات امروز", "callback_data": "/today_trades"}],
        [{"text": "🔎 ممیزی آخرین معامله", "callback_data": "/trade_audit"}],
    ]
    # Audit controls are admin-only. The toggle status is shown with a real-state icon.
    is_admin = False
    try:
        is_admin = int(chat_id) in ADMIN_CHAT_IDS
    except Exception:
        pass
    if is_admin:
        enabled = bool((session or {}).get("trade_pipeline_enabled", False))
        icon = "🟢" if enabled else "🔴"
        state = "روشن" if enabled else "خاموش"
        k += [
            [{"text": "🧭 ردیابی معاملات", "callback_data": "/trade_tracking"}],
        ]
    k += [
        [{"text": "📦 خروجی کامل معاملات", "callback_data": "/export_trade_data"}],
        [{"text": "🔄 ریست آمار تست", "callback_data": "/reset_stats_prompt"}],
        [{"text": "🗑 ریست کامل ربات (شروع از صفر)", "callback_data": "/full_reset_prompt"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]
    return {"inline_keyboard": k}


def get_positions_keyboard(positions):
    k = [[{"text": f"{'🟢' if 'BUY' in p['side'] else '🔴'} {p['symbol']} — مدیریت", "callback_data": f"/manage_{p['symbol']}"}] for p in positions]
    if any("BUY" in p["side"] for p in positions):
        k.append([{"text": "❌ بستن همه خرید", "callback_data": "/close_longs_prompt"}])
    if any("SELL" in p["side"] for p in positions):
        k.append([{"text": "❌ بستن همه فروش", "callback_data": "/close_shorts_prompt"}])
    k.append([{"text": "🏠 منوی اصلی", "callback_data": "/menu"}])
    return {"inline_keyboard": k}


def get_confirm_close_all_keyboard():
    return {"inline_keyboard": [[{"text": "✅ بله، همه را ببند", "callback_data": "/confirm_close_all"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


def get_confirm_emergency_close_keyboard():
    return {"inline_keyboard": [[{"text": "🆘 بله، فوراً همه را ببند", "callback_data": "/confirm_emergency_close_all"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


def get_confirm_close_longs_keyboard():
    return {"inline_keyboard": [[{"text": "✅ بله، همه خریدها را ببند", "callback_data": "/confirm_close_longs"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


def get_confirm_close_shorts_keyboard():
    return {"inline_keyboard": [[{"text": "✅ بله، همه فروش‌ها را ببند", "callback_data": "/confirm_close_shorts"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


def get_start_keyboard():
    return {"inline_keyboard": [[{"text": "حساب کاغذی", "callback_data": "/mode_paper"}, {"text": "حساب واقعی", "callback_data": "/mode_real"}]]}


def get_balance_keyboard():
    return {"inline_keyboard": [[{"text": "500 USDT", "callback_data": "/set_bal_500"}, {"text": "1000 USDT", "callback_data": "/set_bal_1000"}], [{"text": "5000 USDT", "callback_data": "/set_bal_5000"}, {"text": "10000 USDT", "callback_data": "/set_bal_10000"}]]}


def get_margin_keyboard():
    return {"inline_keyboard": [[{"text": "10 USDT", "callback_data": "/set_margin_10"}, {"text": "25 USDT", "callback_data": "/set_margin_25"}], [{"text": "50 USDT", "callback_data": "/set_margin_50"}, {"text": "100 USDT", "callback_data": "/set_margin_100"}]]}


def get_leverage_keyboard():
    return {"inline_keyboard": [[{"text": "3X", "callback_data": "/set_lev_3"}, {"text": "5X", "callback_data": "/set_lev_5"}, {"text": "10X", "callback_data": "/set_lev_10"}]]}


def get_max_positions_keyboard():
    return {"inline_keyboard": [[{"text": "2", "callback_data": "/set_max_2"}, {"text": "3", "callback_data": "/set_max_3"}], [{"text": "5", "callback_data": "/set_max_5"}, {"text": "10", "callback_data": "/set_max_10"}], [{"text": "15", "callback_data": "/set_max_15"}, {"text": "بدون محدودیت", "callback_data": "/set_max_0"}]]}


def get_timeframe_keyboard():
    return {"inline_keyboard": [
        [{"text": "⚡ دسته ۱: اسکالپینگ (شکار نقدینگی ۵ و ۱۵ دقیقه)", "callback_data": "/dummy"}],
        [{"text": "⏱ ۵ دقیقه", "callback_data": "/set_tf_5m"}, {"text": "⏱ ۱۵ دقیقه", "callback_data": "/set_tf_15m"}],
        [{"text": "🧪 دسته ۲: اکسترا (Killzone + Judas Swing + MSS)", "callback_data": "/dummy"}],
        [{"text": "⏱ اکسترا ۵ دقیقه", "callback_data": "/set_tf_extra5m"}, {"text": "⏱ اکسترا ۱۵ دقیقه", "callback_data": "/set_tf_extra15m"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]
    ]}


def get_main_menu_keyboard(active, entry_diag_enabled=True, is_admin_user=False, session=None):
    rows = [
        [{"text": "🔴 توقف اسکن" if active else "🟢 شروع اسکن", "callback_data": "/stop_scan" if active else "/start_scan"}],
        [{"text": "🔄 بارگذاری مجدد و شروع اسکن", "callback_data": "/reload_and_start"}],
        [{"text": "📊 وضعیت بازار", "callback_data": "/market_report"},
         {"text": "🔍 لاگ تشخیصی ورود", "callback_data": "/entry_diag"}],
        [{"text": "⚙️ تنظیمات معامله", "callback_data": "/check_wizard"},
         {"text": "📋 واچ‌لیست", "callback_data": "/manage_watchlist"}],
        [{"text": "🧭 مدیریت روند معاملات", "callback_data": "/trend_management"}],
        [{"text": "🎯 ستاپ‌های معاملاتی", "callback_data": "/setups_menu"}],
        [{"text": "🔄 پیگیری پوزیشن‌ها", "callback_data": "/open_positions"},
         {"text": "📈 عملکرد و گزارش‌ها", "callback_data": "/performance"}],
        [{"text": "💰 کارمزد من", "callback_data": "/fee_menu"}],
        [{"text": "🖐 معامله دستی", "callback_data": "/manual_trade"}],
        [{"text": "❌ بستن همه", "callback_data": "/close_all_prompt"}],
        [{"text": "🔎 ممیزی آخرین معامله", "callback_data": "/trade_audit"}],
    ]
    if is_admin_user:
        enabled = bool((session or {}).get("trade_pipeline_enabled", False))
        icon = "🟢" if enabled else "🔴"
        state = "روشن" if enabled else "خاموش"
        rows.append([{"text": "🧭 ردیابی معاملات", "callback_data": "/trade_tracking"}])
        rows.append([{"text": "👑 پنل مدیریت", "callback_data": "/admin_panel"}])
    return {"inline_keyboard": rows}


SETUP_NUMBERS = (1, 2, 3, 4, 5, 6, 7)


def get_setups_keyboard(session=None):
    s = session or {}
    disabled = set(s.get('disabled_setups') or [])
    rows = []
    for n in SETUP_NUMBERS:
        b_code, s_code = f"B{n}", f"S{n}"
        b_on = b_code not in disabled
        s_on = s_code not in disabled
        rows.append([
            {"text": f"{'🟢' if b_on else '🔴'} {b_code}", "callback_data": f"/toggle_setup_{b_code}"},
            {"text": f"{'🟢' if s_on else '🔴'} {s_code}", "callback_data": f"/toggle_setup_{s_code}"},
        ])
    rows.append([
        {"text": "✅ روشن کردن همه", "callback_data": "/setups_enable_all"},
        {"text": "⛔ خاموش کردن همه", "callback_data": "/setups_disable_all"},
    ])
    rows.append([{"text": "🏠 منوی اصلی", "callback_data": "/menu"}])
    return {"inline_keyboard": rows}


def get_fee_menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "📅 امروز", "callback_data": "/fee_today"}, {"text": "📆 ۷ روز", "callback_data": "/fee_week"}],
        [{"text": "🗓 ۳۰ روز", "callback_data": "/fee_month"}, {"text": "📊 کل سابقه", "callback_data": "/fee_all"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_admin_panel_keyboard():
    return {"inline_keyboard": [
        [{"text": "💰 گزارش کارمزد پلتفرم", "callback_data": "/admin_fee_menu"}],
        [{"text": "👥 لیست کاربران", "callback_data": "/admin_users_list"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_admin_fee_menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "📅 امروز", "callback_data": "/admin_fee_day"}, {"text": "📆 ۷ روز", "callback_data": "/admin_fee_week"}],
        [{"text": "🗓 ۳۰ روز", "callback_data": "/admin_fee_month"}, {"text": "📊 کل سابقه", "callback_data": "/admin_fee_report"}],
        [{"text": "⚙️ تنظیم نرخ کارمزد کاربر", "callback_data": "/admin_set_fee_prompt"}],
        [{"text": "👑 بازگشت به پنل مدیریت", "callback_data": "/admin_panel"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_entry_diag_keyboard(enabled=True):
    return {"inline_keyboard": [
        [{"text": "🟢 فعال است — خاموش کردن" if enabled else "🔴 خاموش است — فعال کردن",
          "callback_data": "/toggle_entry_diag"}],
        [{"text": "🔎 چرا الان وارد نمی‌شویم؟ (یک‌خطی)", "callback_data": "/why_no_entry"}],
        [{"text": "📋 نمایش آخرین تشخیص‌ها", "callback_data": "/entry_diag_log"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_watchlist_manage_keyboard():
    return {"inline_keyboard": [[{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}


_TM_TF_LABELS = {'5min': '۵ دقیقه', '15min': '۱۵ دقیقه', '1hour': '۱ ساعته', '4hour': '۴ ساعته'}
_TM_TF_ORDER = ('5min', '15min', '1hour', '4hour')
_TM_DEFAULTS = {
    'allow_buy_in_bearish': False,
    'allow_sell_in_bullish': False,
    'allow_buy_in_range': True,
    'allow_sell_in_range': True,
    'b7_s7_enabled': True,
    'quality_profile': 'balanced',
}


def get_trend_management_keyboard(session=None):
    s = session or {}
    view_tf = s.get('trend_mgmt_view_tf') if s.get('trend_mgmt_view_tf') in _TM_TF_ORDER else s.get('timeframe', '5min')
    if view_tf not in _TM_TF_ORDER:
        view_tf = '5min'
    tm = (s.get('trend_mgmt') or {}).get(view_tf) or _TM_DEFAULTS
    buy_bear = bool(tm.get('allow_buy_in_bearish', False))
    sell_bull = bool(tm.get('allow_sell_in_bullish', False))
    buy_range = bool(tm.get('allow_buy_in_range', True))
    sell_range = bool(tm.get('allow_sell_in_range', True))
    b7s7 = bool(tm.get('b7_s7_enabled', True))
    qp = tm.get('quality_profile', 'balanced')
    # ردیف انتخاب تایم‌فریم: این تنظیمات مستقل برای هر تایم‌فریم است — این
    # دکمه‌ها فقط تعیین می‌کنند کدام تایم‌فریم را می‌بینی/ویرایش می‌کنی، و
    # باعث تغییر تایم‌فریم فعال اسکن ربات نمی‌شوند.
    tf_row = [
        {"text": ("✅ " if tf == view_tf else "") + _TM_TF_LABELS[tf], "callback_data": f"/tm_tf_{tf}"}
        for tf in _TM_TF_ORDER
    ]
    return {"inline_keyboard": [
        tf_row[:2], tf_row[2:],
        [{"text": "📉 روند نزولی قطعی — پوزیشن خرید", "callback_data": "/dummy"}],
        [{"text": f"{'🟢 روشن' if buy_bear else '🔴 خاموش'} (پیش‌فرض استراتژی: خاموش)", "callback_data": "/toggle_trend_buy_bearish"}],
        [{"text": "📈 روند صعودی قطعی — پوزیشن فروش", "callback_data": "/dummy"}],
        [{"text": f"{'🟢 روشن' if sell_bull else '🔴 خاموش'} (پیش‌فرض استراتژی: خاموش)", "callback_data": "/toggle_trend_sell_bullish"}],
        [{"text": "➡️ بازار رنج (هر دو جهت با حساسیت بالا)", "callback_data": "/dummy"}],
        [{"text": f"{'🟢' if buy_range else '🔴'} خرید در رنج", "callback_data": "/toggle_trend_buy_range"},
         {"text": f"{'🟢' if sell_range else '🔴'} فروش در رنج", "callback_data": "/toggle_trend_sell_range"}],
        [{"text": "⚙️ حالت B7/S7 (ادامه‌ی مومنتوم بدون ری‌تست)", "callback_data": "/dummy"}],
        [{"text": f"{'🟢 فعال' if b7s7 else '🔴 خاموش'} — B7/S7 (پیش‌فرض استراتژی: روشن)", "callback_data": "/toggle_b7s7"}],
        [{"text": "🎚 کیفیت معاملات", "callback_data": "/dummy"}],
        [{"text": f"{'🟢' if qp=='opportunity' else '🔴'} کیفیت پایین‌تر — سیگنال بیشتر", "callback_data": "/qp_opportunity"}],
        [{"text": f"{'🟢' if qp=='conservative' else '🔴'} کیفیت بالاتر — سیگنال کمتر", "callback_data": "/qp_conservative"}],
        [{"text": f"{'🟢' if qp=='balanced' else '🔴'} حالت پیش‌فرض (متعادل) ⭐", "callback_data": "/qp_balanced"}],
        [{"text": f"♻️ بازگشت به پیش‌فرض استراتژی (فقط {_TM_TF_LABELS[view_tf]})", "callback_data": "/trend_mgmt_reset"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_manual_side_keyboard():
    return {"inline_keyboard": [
        [{"text": "🟢 خرید (Long)", "callback_data": "/manual_side_buy"},
         {"text": "🔴 فروش (Short)", "callback_data": "/manual_side_sell"}],
        [{"text": "❌ انصراف", "callback_data": "/cancel"}],
    ]}
