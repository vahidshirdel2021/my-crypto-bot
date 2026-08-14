from strategy import FILTER_DEFAULTS, STRATEGY_DEFAULTS


def get_bottom_menu_keyboard(is_active=False):
    scan_btn_text = "🔴 توقف اسکن" if is_active else "🟢 شروع اسکن"
    return {
        "keyboard": [
            [{"text": "🏠 منوی اصلی"}, {"text": "🔄 پوزیشن‌های باز"}],
            [{"text": "📈 گزارش عملکرد کلی"}, {"text": "📊 گزارش وضعیت بازار"}],
            [{"text": "⚙️ تنظیمات فیلترها"}, {"text": "🎛️ تنظیم پارامترها"}],
            [{"text": scan_btn_text}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def get_filters_menu_keyboard(session=None):
    filters = (session or {}).get("filters", FILTER_DEFAULTS)
    vol_icon = "🟢 فعال" if filters.get("volume_filter", True) else "🔴 غیرفعال"
    trail_icon = "🟢 فعال" if filters.get("trailing_stop", True) else "🔴 غیرفعال"
    candle_icon = "🟢 فعال" if filters.get("candlestick_filter", True) else "🔴 غیرفعال"
    short_icon = "🟢 محدود" if filters.get("no_short_filter", False) else "🔴 آزاد"
    buy_icon = "🟢 محدود" if filters.get("no_buy_filter", False) else "🔴 آزاد"
    return {
        "inline_keyboard": [
            [{"text": f"فیلتر حجم: {vol_icon}", "callback_data": "/toggle_vol"}],
            [{"text": f"Trailing Stop: {trail_icon}", "callback_data": "/toggle_trail"}],
            [{"text": f"تأیید کندل: {candle_icon}", "callback_data": "/toggle_candle"}],
            [{"text": f"توقف Short: {short_icon}", "callback_data": "/toggle_short"}],
            [{"text": f"توقف Buy: {buy_icon}", "callback_data": "/toggle_buy"}],
            [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
        ]
    }


def get_params_menu_keyboard(session=None):
    cfg = (session or {}).get("strategy_config", STRATEGY_DEFAULTS)
    risk = float((session or {}).get("risk_per_trade_pct", 0.5))
    daily = float((session or {}).get("daily_loss_limit_pct", 3.0))
    max_margin = float((session or {}).get("max_margin_usage_pct", 50.0))
    adx_val = float(cfg.get("min_adx", 20))
    sl_val = float(cfg.get("sl_multiplier", 1.5))
    tp_val = float(cfg.get("tp_multiplier", 2.0))
    return {
        "inline_keyboard": [
            [{"text": f"🎯 ADX: {adx_val:.1f}", "callback_data": "/dummy"}],
            [{"text": "➕ ADX +1", "callback_data": "/adx_up"}, {"text": "➖ ADX -1", "callback_data": "/adx_down"}],
            [{"text": f"🛡️ SL ATR: {sl_val:.1f}x", "callback_data": "/dummy"}],
            [{"text": "➕ SL +0.2", "callback_data": "/sl_up"}, {"text": "➖ SL -0.2", "callback_data": "/sl_down"}],
            [{"text": f"🎯 TP ATR: {tp_val:.1f}x", "callback_data": "/dummy"}],
            [{"text": "➕ TP +0.5", "callback_data": "/tp_up"}, {"text": "➖ TP -0.5", "callback_data": "/tp_down"}],
            [{"text": f"⚠️ ریسک/معامله: {risk:.2f}%", "callback_data": "/dummy"}],
            [{"text": f"🛑 حد ضرر روزانه: {daily:.2f}%", "callback_data": "/dummy"}],
            [{"text": f"📦 سقف مصرف مارجین: {max_margin:.0f}%", "callback_data": "/dummy"}],
            [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
        ]
    }


def get_positions_keyboard(positions):
    keyboard = []
    has_shorts = any("SELL" in pos["side"] or "Short" in pos["side"] for pos in positions)
    has_longs = any("BUY" in pos["side"] or "Long" in pos["side"] for pos in positions)

    for pos in positions:
        keyboard.append([
            {"text": f"❌ بستن {pos['symbol']}", "callback_data": f"/close_{pos['symbol']}"}
        ])

    if has_longs:
        keyboard.append([{"text": "❌ بستن تمام معاملات Long", "callback_data": "/close_longs"}])
    if has_shorts:
        keyboard.append([{"text": "❌ بستن تمام معاملات Short", "callback_data": "/close_shorts"}])
    keyboard.append([{"text": "🏠 منوی اصلی", "callback_data": "/menu"}])
    return {"inline_keyboard": keyboard}


def get_confirm_close_all_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "✅ بله، همه را ببند", "callback_data": "/confirm_close_all"}],
            [{"text": "❌ انصراف", "callback_data": "/cancel"}],
        ]
    }


def get_start_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "حساب کاغذی", "callback_data": "/mode_paper"}, {"text": "حساب واقعی", "callback_data": "/mode_real"}]
        ]
    }


def get_balance_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "500 USDT", "callback_data": "/set_bal_500"}, {"text": "1000 USDT", "callback_data": "/set_bal_1000"}],
            [{"text": "5000 USDT", "callback_data": "/set_bal_5000"}, {"text": "10000 USDT", "callback_data": "/set_bal_10000"}],
        ]
    }


def get_margin_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "10 USDT", "callback_data": "/set_margin_10"}, {"text": "25 USDT", "callback_data": "/set_margin_25"}],
            [{"text": "50 USDT", "callback_data": "/set_margin_50"}, {"text": "100 USDT", "callback_data": "/set_margin_100"}],
        ]
    }


def get_leverage_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "3X", "callback_data": "/set_lev_3"}, {"text": "5X", "callback_data": "/set_lev_5"}, {"text": "10X", "callback_data": "/set_lev_10"}]
        ]
    }


def get_max_positions_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "2", "callback_data": "/set_max_2"}, {"text": "3", "callback_data": "/set_max_3"}],
            [{"text": "5", "callback_data": "/set_max_5"}, {"text": "10", "callback_data": "/set_max_10"}],
            [{"text": "15", "callback_data": "/set_max_15"}, {"text": "بدون محدودیت", "callback_data": "/set_max_0"}],
        ]
    }


def get_timeframe_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "5م", "callback_data": "/set_tf_5m"}, {"text": "15م", "callback_data": "/set_tf_15m"}],
            [{"text": "1س", "callback_data": "/set_tf_1h"}, {"text": "4ساعته", "callback_data": "/set_tf_4h"}],
            [{"text": "روزانه", "callback_data": "/set_tf_1d"}, {"text": "مولتی آبشاری", "callback_data": "/set_tf_multi"}],
        ]
    }


def get_main_menu_keyboard(is_active):
    text = "🔴 توقف اسکن" if is_active else "🟢 روشن کردن اسکن"
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": "/toggle_active"}],
            [{"text": "📊 گزارش وضعیت بازار", "callback_data": "/market_report"}],
            [{"text": "⚙️ مدیریت تنظیمات معامله", "callback_data": "/check_wizard"}],
            [{"text": "🔍 تحلیل ارز", "callback_data": "/analyze_single"}, {"text": "📊 انتخاب استراتژی", "callback_data": "/strategies_menu"}],
            [{"text": "⚙️ تنظیمات فیلترها", "callback_data": "/filters_menu"}, {"text": "🎛️ تنظیم پارامترها", "callback_data": "/params_menu"}],
            [{"text": "📋 مدیریت واچ‌لیست", "callback_data": "/manage_watchlist"}, {"text": "❌ بستن کل پوزیشن‌ها", "callback_data": "/close_all_prompt"}],
            [{"text": "🔄 پوزیشن‌های باز", "callback_data": "/open_positions"}, {"text": "📈 گزارش عملکرد", "callback_data": "/performance"}],
        ]
    }


def get_strategies_selection_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "⚡ تشخیص هوشمند Dynamic", "callback_data": "/set_strat_dynamic"}],
            [{"text": "📈 روندپیروی Trend", "callback_data": "/set_strat_trend"}],
            [{"text": "🚀 شکست کانال Breakout", "callback_data": "/set_strat_breakout"}],
            [{"text": "🔄 بازگشت به میانگین RSI", "callback_data": "/set_strat_mean_reversion"}],
            [{"text": "🌊 مولتی‌تایم‌فریم", "callback_data": "/set_strat_multi"}],
            [{"text": "📚 توضیح استراتژی‌ها", "callback_data": "/strategy_desc_menu"}],
            [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
        ]
    }


def get_strategies_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "5 دقیقه", "callback_data": "/desc_5min"}, {"text": "15 دقیقه", "callback_data": "/desc_15min"}],
            [{"text": "1 ساعته", "callback_data": "/desc_1hour"}, {"text": "مولتی", "callback_data": "/desc_multi"}],
            [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
        ]
    }


def get_watchlist_manage_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "➕ افزودن ارز", "callback_data": "/add_symbol_prompt"}, {"text": "➖ حذف ارز", "callback_data": "/remove_symbol_prompt"}],
            [{"text": "📋 لیست واچ‌لیست", "callback_data": "/watchlist_list"}],
            [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
        ]
    }
