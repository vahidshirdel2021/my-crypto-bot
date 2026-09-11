from strategy import STRATEGY_DEFAULTS

CHAT_INPUT_PLACEHOLDER = "نام ارز خود را جهت تحلیل وارد کنید"


def get_bottom_menu_keyboard(is_active=False, is_open=True):
    # کیبورد سفارشی سبک و ثابت (پایین صفحه) - همیشه در دسترس، مستقل از منوی این‌لاین
    scan_button = {"text": "🔴 توقف اسکن"} if is_active else {"text": "🟢 شروع اسکن"}
    return {
        "keyboard": [
            [scan_button, {"text": "📊 وضعیت بازار"}],
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


def get_performance_keyboard():
    return {"inline_keyboard": [
        [{"text": "📅 امروز", "callback_data": "/performance_today"}, {"text": "📆 ۷ روز", "callback_data": "/performance_week"}],
        [{"text": "🗓 ۳۰ روز", "callback_data": "/performance_month"}, {"text": "📊 کل سابقه", "callback_data": "/performance"}],
        [{"text": "🔎 ممیزی آخرین معامله", "callback_data": "/trade_audit"}],
        [{"text": "🎯 تفکیک کیفیت سیگنال", "callback_data": "/quality_report"}],
        [{"text": "📋 معاملات امروز", "callback_data": "/today_trades"}],
        [{"text": "🧭 ردیابی مسیر معاملات (Pipeline)", "callback_data": "/trade_tracking_menu"}],
        [{"text": "📦 خروجی کامل معاملات", "callback_data": "/export_trade_data"}],
        [{"text": "🔄 ریست آمار تست", "callback_data": "/reset_stats_prompt"}],
        [{"text": "🗑 ریست کامل ربات (شروع از صفر)", "callback_data": "/full_reset_prompt"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_positions_keyboard(positions, chart_urls=None):
    chart_urls = chart_urls or {}
    k = []
    for p in positions:
        sym = p['symbol']
        k.append([{"text": f"{'🟢' if 'BUY' in p['side'] else '🔴'} {sym} — مدیریت", "callback_data": f"/manage_{sym}"}])
        chart_url = chart_urls.get(sym)
        if chart_url:
            k.append([{"text": f"📊 چارت {sym} با سطوح (MiniApp)", "web_app": {"url": chart_url}}])
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
        [{"text": "📈 دسته ۲: معاملات روندی (تأیید روند و شکست)", "callback_data": "/dummy"}],
        [{"text": "⏱ ۱ ساعته", "callback_data": "/set_tf_1h"}, {"text": "⏱ ۴ ساعته", "callback_data": "/set_tf_4h"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]
    ]}


SETUP_TAG_ORDER = ("1h", "4h", "Daily", "Weekly", "Monthly")
SETUP_TAG_LABELS = {
    "1h": "Setup 1h",
    "4h": "Setup 4h",
    "Daily": "Setup Daily",
    "Weekly": "Setup Weekly",
    "Monthly": "Setup Monthly",
}
SETUP_TAG_CALLBACK = {
    "1h": "/toggle_setup_1h",
    "4h": "/toggle_setup_4h",
    "Daily": "/toggle_setup_daily",
    "Weekly": "/toggle_setup_weekly",
    "Monthly": "/toggle_setup_monthly",
}


def get_setup_management_keyboard(session=None):
    s = session or {}
    enabled = set(s.get("enabled_setup_tags") or SETUP_TAG_ORDER)
    rows = []
    for tag in SETUP_TAG_ORDER:
        is_on = tag in enabled
        icon = "🟢" if is_on else "🔴"
        rows.append([{"text": f"{icon} {SETUP_TAG_LABELS[tag]}", "callback_data": SETUP_TAG_CALLBACK[tag]}])
    rows.append([{"text": "🏠 منوی اصلی", "callback_data": "/menu"}])
    return {"inline_keyboard": rows}


def get_main_menu_keyboard(active, entry_diag_enabled=True, is_admin_user=False):
    rows = [
        [{"text": "🔴 توقف اسکن" if active else "🟢 شروع اسکن", "callback_data": "/stop_scan" if active else "/start_scan"}],
        [{"text": "🔄 بارگذاری مجدد و شروع اسکن", "callback_data": "/reload_and_start"}],
        [{"text": "📊 وضعیت بازار", "callback_data": "/market_report"},
         {"text": "🔍 لاگ تشخیصی ورود", "callback_data": "/entry_diag"}],
        [{"text": "🎛 مدیریت ستاپ‌های معاملاتی", "callback_data": "/setup_management"}],
        [{"text": "⚙️ تنظیمات معامله", "callback_data": "/check_wizard"},
         {"text": "📋 واچ‌لیست", "callback_data": "/manage_watchlist"}],
        [{"text": "🔄 پوزیشن‌ها", "callback_data": "/open_positions"},
         {"text": "📈 عملکرد و گزارش‌ها", "callback_data": "/performance"}],
        [{"text": "💰 کارمزد من", "callback_data": "/fee_menu"}],
        [{"text": "🖐 معامله دستی", "callback_data": "/manual_trade"}],
        [{"text": "❌ بستن همه", "callback_data": "/close_all_prompt"}],
        [{"text": "🔎 ممیزی آخرین معامله", "callback_data": "/trade_audit"}],
    ]
    if is_admin_user:
        rows.append([{"text": "👑 پنل مدیریت", "callback_data": "/admin_panel"}])
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
        [{"text": "📋 نمایش آخرین تشخیص‌ها", "callback_data": "/entry_diag_log"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_watchlist_manage_keyboard():
    return {"inline_keyboard": [
        [{"text":"➕ افزودن Long","callback_data":"/add_long_symbol"},{"text":"➖ حذف Long","callback_data":"/remove_long_symbol"}],
        [{"text":"➕ افزودن Short","callback_data":"/add_short_symbol"},{"text":"➖ حذف Short","callback_data":"/remove_short_symbol"}],
        [{"text":"🧪 تست استراتژی","callback_data":"/backtest_start"}],
        [{"text":"🔍 پیشنهاد نماد با استراتژی فعال","callback_data":"/scan_signal_start"}],
        [{"text":"🏠 منوی اصلی","callback_data":"/menu"}]
    ]}


def get_manual_side_keyboard():
    return {"inline_keyboard": [
        [{"text": "🟢 خرید (Long)", "callback_data": "/manual_side_buy"},
         {"text": "🔴 فروش (Short)", "callback_data": "/manual_side_sell"}],
        [{"text": "❌ انصراف", "callback_data": "/cancel"}],
    ]}
