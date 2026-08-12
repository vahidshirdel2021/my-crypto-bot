from strategy import FILTERS, STRATEGY_CONFIG

def get_bottom_menu_keyboard(is_active=False):
    scan_btn_text = "🔴 توقف اسکن" if is_active else "🟢 شروع اسکن"
    return {
        "keyboard": [
            [{"text": "🏠 منوی اصلی"}, {"text": "🔄 پوزیشن‌های باز"}],
            [{"text": "📈 گزارش عملکرد کلی"}, {"text": "📊 گزارش وضعیت بازار"}],
            [{"text": "⚙️ تنظیمات فیلترها"}, {"text": "🎛️ تنظیم پارامترها"}],
            [{"text": scan_btn_text}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_filters_menu_keyboard():
    vol_icon = "🟢 فعال" if FILTERS['volume_filter'] else "🔴 غیرفعال"
    trail_icon = "🟢 فعال" if FILTERS['trailing_stop'] else "🔴 غیرفعال"
    candle_icon = "🟢 فعال" if FILTERS['candlestick_filter'] else "🔴 غیرفعال"
    return {"inline_keyboard": [
        [{"text": f"فیلتر حجم معاملات: {vol_icon}", "callback_data": "/toggle_vol"}],
        [{"text": f"تریلینگ استاپ: {trail_icon}", "callback_data": "/toggle_trail"}],
        [{"text": f"کندل‌تاییدیه پرایس‌آکشن: {candle_icon}", "callback_data": "/toggle_candle"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]
    ]}

def get_params_menu_keyboard():
    adx_val = STRATEGY_CONFIG["min_adx"]
    sl_val = STRATEGY_CONFIG["sl_multiplier"]
    tp_val = STRATEGY_CONFIG["tp_multiplier"]
    return {"inline_keyboard": [
        [{"text": f"🎯 آستانه ADX: {adx_val}", "callback_data": "/dummy"}],
        [{"text": "➕ ADX (افزایش)", "callback_data": "/adx_up"}, {"text": "➖ ADX (کاهش)", "callback_data": "/adx_down"}],
        [{"text": f"🛡️ حد ضرر ATR: {sl_val}x", "callback_data": "/dummy"}],
        [{"text": "➕ SL +0.2", "callback_data": "/sl_up"}, {"text": "➖ SL -0.2", "callback_data": "/sl_down"}],
        [{"text": f"🎯 حد سود ATR: {tp_val}x", "callback_data": "/dummy"}],
        [{"text": "➕ TP +0.5", "callback_data": "/tp_up"}, {"text": "➖ TP -0.5", "callback_data": "/tp_down"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]
    ]}

def get_positions_keyboard(positions):
    keyboard = []
    has_shorts = any("SELL" in pos['side'] or "Short" in pos['side'] for pos in positions)
    for pos in positions:
        keyboard.append([{"text": f"❌ بستن {pos['symbol']}", "callback_data": f"/close_{pos['symbol']}"}])
    if has_shorts:
        keyboard.append([{"text": "❌ بستن تمام معاملات Short", "callback_data": "/close_shorts"}])
    keyboard.append([{"text": "🏠 منوی اصلی", "callback_data": "/menu"}])
    return {"inline_keyboard": keyboard}

def get_start_keyboard():
    return {"inline_keyboard": [[{"text": "حساب کاغذی", "callback_data": "/mode_paper"}, {"text": "حساب واقعی", "callback_data": "/mode_real"}]]}

def get_balance_keyboard():
    return {"inline_keyboard": [
        [{"text": "500 USDT", "callback_data": "/set_bal_500"}, {"text": "1000 USDT", "callback_data": "/set_bal_1000"}],
        [{"text": "5000 USDT", "callback_data": "/set_bal_5000"}, {"text": "10000 USDT", "callback_data": "/set_bal_10000"}]
    ]}

def get_margin_keyboard():
    return {"inline_keyboard": [
        [{"text": "10 USDT", "callback_data": "/set_margin_10"}, {"text": "25 USDT", "callback_data": "/set_margin_25"}],
        [{"text": "50 USDT", "callback_data": "/set_margin_50"}, {"text": "100 USDT", "callback_data": "/set_margin_100"}]
    ]}

def get_leverage_keyboard():
    return {"inline_keyboard": [[{"text": "3X", "callback_data": "/set_lev_3"}, {"text": "5X", "callback_data": "/set_lev_5"}, {"text": "10X", "callback_data": "/set_lev_10"}]]}

def get_max_positions_keyboard():
    return {"inline_keyboard": [
        [{"text": "2", "callback_data": "/set_max_2"}, {"text": "3", "callback_data": "/set_max_3"}], 
        [{"text": "5", "callback_data": "/set_max_5"}, {"text": "10", "callback_data": "/set_max_10"}],
        [{"text": "15", "callback_data": "/set_max_15"}, {"text": "بدون محدودیت", "callback_data": "/set_max_0"}]
    ]}

def get_timeframe_keyboard():
    return {"inline_keyboard": [
        [{"text": "5م", "callback_data": "/set_tf_5m"}, {"text": "15م", "callback_data": "/set_tf_15m"}],
        [{"text": "1س", "callback_data": "/set_tf_1h"}, {"text": "4ساعته", "callback_data": "/set_tf_4h"}],
        [{"text": "روزانه", "callback_data": "/set_tf_1d"}, {"text": "مولتی آبشاری", "callback_data": "/set_tf_multi"}]
    ]}

def get_main_menu_keyboard(is_active):
    text = "🔴 توقف اسکن" if is_active else "🟢 روشن کردن اسکن"
    return {"inline_keyboard": [
        [{"text": text, "callback_data": "/toggle_active"}],
        [{"text": "📊 گزارش وضعیت بازار", "callback_data": "/market_report"}],
        [{"text": "⚙️ مدیریت تنظیمات معامله", "callback_data": "/check_wizard"}],
        [{"text": "🔍 تحلیل ارز", "callback_data": "/analyze_single"}, {"text": "📊 انتخاب استراتژی", "callback_data": "/strategies_menu"}],
        [{"text": "⚙️ تنظیمات فیلترها", "callback_data": "/filters_menu"}, {"text": "🎛️ تنظیم پارامترها", "callback_data": "/params_menu"}],
        [{"text": "📋 مدیریت واچ‌لیست", "callback_data": "/manage_watchlist"}, {"text": "❌ بستن کل پوزیشن‌ها", "callback_data": "/close_all"}]
    ]}

def get_strategies_selection_keyboard():
    return {"inline_keyboard": [
        [{"text": "⚡ تشخیص هوشمند (Dynamic ADX)", "callback_data": "/set_strat_dynamic"}],
        [{"text": "📈 روندپیروی (Trend)", "callback_data": "/set_strat_trend"}],
        [{"text": "🚀 شکست کانال (Breakout)", "callback_data": "/set_strat_breakout"}],
        [{"text": "🔄 بازگشت به میانگین RSI", "callback_data": "/set_strat_mean_reversion"}],
        [{"text": "🌊 مولتی‌تایم‌فریم آبشاری", "callback_data": "/set_strat_multi"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]
    ]}

def get_strategies_menu_keyboard():
    return {"inline_keyboard": [[{"text": "اسکالپ 5م", "callback_data": "/desc_5min"}, {"text": "روزانه 15م", "callback_data": "/desc_15min"}], [{"text": "سوئینگ 1س", "callback_data": "/desc_1hour"}, {"text": "مولتی آبشاری", "callback_data": "/desc_multi"}]]}

def get_watchlist_manage_keyboard():
    return {"inline_keyboard": [[{"text": "➕ افزودن ارز", "callback_data": "/add_symbol_prompt"}, {"text": "➖ حذف ارز", "callback_data": "/remove_symbol_prompt"}], [{"text": "📋 لیست واچ‌لیست", "callback_data": "/manage_watchlist"}], [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}
