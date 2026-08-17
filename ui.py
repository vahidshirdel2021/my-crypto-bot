from strategy import FILTER_DEFAULTS, STRATEGY_DEFAULTS


def get_bottom_menu_keyboard(is_active=False, is_open=True):
    # Reply Keyboard پایین چت عمداً حذف شده است.
    # منوی اصلی فقط از Menu بومی تلگرام (کنار کادر پیام) باز می‌شود.
    return {"remove_keyboard": True}


def get_filters_menu_keyboard(session=None):
    f = (session or {}).get("filters", FILTER_DEFAULTS)
    return {"inline_keyboard": [
        [{"text": f"فیلتر حجم: {'🟢 فعال' if f.get('volume_filter', True) else '🔴 خاموش'}", "callback_data": "/toggle_vol"}],
        [{"text": f"حد ضرر دنبال‌کننده: {'🟢 فعال' if f.get('trailing_stop', True) else '🔴 خاموش'}", "callback_data": "/toggle_trail"}],
        [{"text": f"تأیید کندل: {'🟢 فعال' if f.get('candlestick_filter', True) else '🔴 خاموش'}", "callback_data": "/toggle_candle"}],
        [{"text": f"توقف فروش: {'🟢 بله' if f.get('no_short_filter', False) else '🔴 خیر'}", "callback_data": "/toggle_short"}],
        [{"text": f"توقف خرید: {'🟢 بله' if f.get('no_buy_filter', False) else '🔴 خیر'}", "callback_data": "/toggle_buy"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_params_menu_keyboard(session=None):
    s=session or {}; c=s.get("strategy_config", STRATEGY_DEFAULTS)
    if s.get("user_experience","simple") != "advanced":
        return {"inline_keyboard":[
            [{"text":"🟢 حالت متعادل ⭐","callback_data":"/profile_balanced"}],
            [{"text":"🛡️ محافظه‌کارانه","callback_data":"/profile_conservative"},{"text":"⚡ فرصت‌های بیشتر","callback_data":"/profile_opportunity"}],
            [{"text":"🎓 حالت حرفه‌ای / جزئیات","callback_data":"/profile_advanced"}],
            [{"text":"❓ آموزش مفاهیم","callback_data":"/learn_menu"}],
            [{"text":"🏠 منوی اصلی","callback_data":"/menu"}],
        ]}
    return {"inline_keyboard":[
        [{"text":"🔵 حالت ساده","callback_data":"/profile_simple"}],
        [{"text":"❓ ADX چیست؟","callback_data":"/learn_adx"},{"text":"❓ ATR چیست؟","callback_data":"/learn_atr"}],
        [{"text":"❓ RSI چیست؟","callback_data":"/learn_rsi"},{"text":"❓ R:R چیست؟","callback_data":"/learn_rr"}],
        [{"text":f"🎯 ADX: {float(c.get('min_adx',20)):.1f}","callback_data":"/dummy"}],
        [{"text":"➕ ADX +۱","callback_data":"/adx_up"},{"text":"➖ ADX -۱","callback_data":"/adx_down"}],
        [{"text":f"🛡️ ضریب حد ضرر: {float(c.get('sl_multiplier',1.5)):.1f}x","callback_data":"/dummy"}],
        [{"text":"➕ حد ضرر +۰٫۲","callback_data":"/sl_up"},{"text":"➖ حد ضرر -۰٫۲","callback_data":"/sl_down"}],
        [{"text":f"🎯 ضریب حد سود پایه: {float(c.get('tp_multiplier',2.0)):.1f}x","callback_data":"/dummy"}],
        [{"text":"➕ حد سود پایه +۰٫۵","callback_data":"/tp_up"},{"text":"➖ حد سود -۰٫۵","callback_data":"/tp_down"}],
        [{"text":f"🧠 خروج پویا: {'🟢 فعال' if c.get('dynamic_exits',True) else '🔴 خاموش'}","callback_data":"/dummy"}],
        [{"text":f"📊 حداقل کیفیت: {float(c.get('min_trade_score',68)):.0f}/100","callback_data":"/dummy"}],
        [{"text":f"⚖️ حداقل R:R: {float(c.get('min_rr',1.3)):.2f}R","callback_data":"/dummy"}],
        [{"text":f"⚠️ ریسک: {float(s.get('risk_per_trade_pct',0.5)):.2f}%","callback_data":"/dummy"}],
        [{"text":"🏠 منوی اصلی","callback_data":"/menu"}],
    ]}

def get_learn_menu_keyboard():
    return {"inline_keyboard":[
        [{"text":"📈 ADX — قدرت روند","callback_data":"/learn_adx"}],
        [{"text":"🌪 ATR — نوسان بازار","callback_data":"/learn_atr"}],
        [{"text":"📊 RSI — قدرت حرکت","callback_data":"/learn_rsi"}],
        [{"text":"⚖️ R:R — سود به ضرر","callback_data":"/learn_rr"}],
        [{"text":"🧠 چرا ربات این‌ها را می‌بیند؟","callback_data":"/learn_why"}],
        [{"text":"🏠 منوی اصلی","callback_data":"/menu"}],
    ]}

def get_performance_keyboard():
    return {"inline_keyboard": [
        [{"text": "📅 امروز", "callback_data": "/performance_today"}, {"text": "📆 ۷ روز", "callback_data": "/performance_week"}],
        [{"text": "🗓 ۳۰ روز", "callback_data": "/performance_month"}, {"text": "📊 کل سابقه", "callback_data": "/performance"}],
        [{"text": "🔎 ممیزی آخرین معامله", "callback_data": "/trade_audit"}],
        [{"text": "📦 خروجی کامل معاملات", "callback_data": "/export_trade_data"}],
        [{"text": "🔄 ریست آمار تست", "callback_data": "/reset_stats_prompt"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_positions_keyboard(positions):
    k = [[{"text": f"❌ بستن {p['symbol']}", "callback_data": f"/close_prompt_{p['symbol']}"}] for p in positions]
    if any("BUY" in p["side"] for p in positions):
        k.append([{"text": "❌ بستن همه خرید", "callback_data": "/close_longs_prompt"}])
    if any("SELL" in p["side"] for p in positions):
        k.append([{"text": "❌ بستن همه فروش", "callback_data": "/close_shorts_prompt"}])
    k.append([{"text": "🏠 منوی اصلی", "callback_data": "/menu"}])
    return {"inline_keyboard": k}


def get_confirm_close_all_keyboard():
    return {"inline_keyboard": [[{"text": "✅ بله، همه را ببند", "callback_data": "/confirm_close_all"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


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
    return {"inline_keyboard": [[{"text": "5م", "callback_data": "/set_tf_5m"}, {"text": "15م", "callback_data": "/set_tf_15m"}], [{"text": "1س", "callback_data": "/set_tf_1h"}, {"text": "4س", "callback_data": "/set_tf_4h"}], [{"text": "مولتی", "callback_data": "/set_tf_multi"}]]}


def get_main_menu_keyboard(active, entry_diag_enabled=True):
    # منوی اصلی به‌صورت شبکه‌ای و گروه‌بندی‌شده طراحی شده تا خواناتر از منوی خطی باشد.
    diag_label = "🟢 لاگ ورود: فعال" if entry_diag_enabled else "🔴 لاگ ورود: خاموش"
    return {"inline_keyboard": [
        [{"text": "🔴 توقف اسکن" if active else "🟢 شروع اسکن", "callback_data": "/stop_scan" if active else "/start_scan"}],
        [{"text": "📊 وضعیت بازار", "callback_data": "/market_report"},
         {"text": "🔍 لاگ تشخیصی ورود", "callback_data": "/entry_diag"}],
        [{"text": "⚙️ تنظیمات معامله", "callback_data": "/check_wizard"},
         {"text": "📋 واچ‌لیست", "callback_data": "/manage_watchlist"}],
        [{"text": "🔄 پوزیشن‌ها", "callback_data": "/open_positions"},
         {"text": "📈 عملکرد و گزارش‌ها", "callback_data": "/performance"}],
        [{"text": "❌ بستن همه", "callback_data": "/close_all_prompt"}],
        [{"text": "🔎 ممیزی آخرین معامله", "callback_data": "/trade_audit"}],
    ]}


def get_entry_diag_keyboard(enabled=True):
    return {"inline_keyboard": [
        [{"text": "🟢 فعال است — خاموش کردن" if enabled else "🔴 خاموش است — فعال کردن",
          "callback_data": "/toggle_entry_diag"}],
        [{"text": "📋 نمایش آخرین تشخیص‌ها", "callback_data": "/entry_diag_log"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_strategies_selection_keyboard():
    return {"inline_keyboard": [[{"text": "⚡ پویا", "callback_data": "/set_strat_dynamic"}], [{"text": "📈 روندی", "callback_data": "/set_strat_trend"}], [{"text": "🚀 شکست", "callback_data": "/set_strat_breakout"}], [{"text": "🔄 بازگشت به میانگین", "callback_data": "/set_strat_mean_reversion"}], [{"text": "🌊 چندزمانه", "callback_data": "/set_strat_multi"}], [{"text": "📚 توضیح", "callback_data": "/strategy_desc_menu"}], [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}


def get_strategies_menu_keyboard():
    return {"inline_keyboard": [[{"text": "5 دقیقه", "callback_data": "/desc_5min"}, {"text": "15 دقیقه", "callback_data": "/desc_15min"}], [{"text": "1 ساعت", "callback_data": "/desc_1hour"}, {"text": "مولتی", "callback_data": "/desc_multi"}], [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}


def get_watchlist_manage_keyboard():
    return {"inline_keyboard": [[{"text": "➕ افزودن", "callback_data": "/add_symbol_prompt"}, {"text": "➖ حذف", "callback_data": "/remove_symbol_prompt"}], [{"text": "📋 لیست", "callback_data": "/watchlist_list"}], [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}

