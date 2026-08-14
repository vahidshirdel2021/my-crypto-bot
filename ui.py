from strategy import FILTER_DEFAULTS, STRATEGY_DEFAULTS


def get_bottom_menu_keyboard(is_active=False):
    text = "🔴 توقف اسکن" if is_active else "🟢 شروع اسکن"
    return {"keyboard": [[{"text": "🏠 منوی اصلی"}, {"text": "🔄 پوزیشن‌های باز"}], [{"text": "📈 گزارش عملکرد کلی"}, {"text": "📊 گزارش وضعیت بازار"}], [{"text": "⚙️ تنظیمات فیلترها"}, {"text": "🎛️ تنظیم پارامترها"}], [{"text": text}]], "resize_keyboard": True, "one_time_keyboard": False}


def get_filters_menu_keyboard(session=None):
    f = (session or {}).get("filters", FILTER_DEFAULTS)
    return {"inline_keyboard": [
        [{"text": f"فیلتر حجم: {'🟢 فعال' if f.get('volume_filter', True) else '🔴 خاموش'}", "callback_data": "/toggle_vol"}],
        [{"text": f"حد ضرر دنبال‌کننده: {'🟢 فعال' if f.get('trailing_stop', True) else '🔴 خاموش'}", "callback_data": "/toggle_trail"}],
        [{"text": f"تأیید کندل: {'🟢 فعال' if f.get('candlestick_filter', True) else '🔴 خاموش'}", "callback_data": "/toggle_candle"}],
        [{"text": f"توقف Short: {'🟢 بله' if f.get('no_short_filter', False) else '🔴 خیر'}", "callback_data": "/toggle_short"}],
        [{"text": f"توقف Buy: {'🟢 بله' if f.get('no_buy_filter', False) else '🔴 خیر'}", "callback_data": "/toggle_buy"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_params_menu_keyboard(session=None):
    s = session or {}
    c = s.get("strategy_config", STRATEGY_DEFAULTS)
    return {"inline_keyboard": [
        [{"text": f"🎯 ADX: {float(c.get('min_adx',20)):.1f}", "callback_data": "/dummy"}],
        [{"text": "➕ ADX +1", "callback_data": "/adx_up"}, {"text": "➖ ADX -1", "callback_data": "/adx_down"}],
        [{"text": f"🛡️ SL ATR: {float(c.get('sl_multiplier',1.5)):.1f}x", "callback_data": "/dummy"}],
        [{"text": "➕ SL +0.2", "callback_data": "/sl_up"}, {"text": "➖ SL -0.2", "callback_data": "/sl_down"}],
        [{"text": f"🎯 TP ATR: {float(c.get('tp_multiplier',2.0)):.1f}x", "callback_data": "/dummy"}],
        [{"text": "➕ TP +0.5", "callback_data": "/tp_up"}, {"text": "➖ TP -0.5", "callback_data": "/tp_down"}],
        [{"text": f"⚠️ ریسک: {float(s.get('risk_per_trade_pct',0.5)):.2f}%", "callback_data": "/dummy"}],
        [{"text": f"🛑 حد ضرر روزانه: {float(s.get('daily_loss_limit_pct',3.0)):.2f}%", "callback_data": "/dummy"}],
        [{"text": f"📦 سقف مارجین: {float(s.get('max_margin_usage_pct',50)):.0f}%", "callback_data": "/dummy"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_positions_keyboard(positions):
    k = [[{"text": f"❌ بستن {p['symbol']}", "callback_data": f"/close_{p['symbol']}"}] for p in positions]
    if any("BUY" in p["side"] for p in positions):
        k.append([{"text": "❌ بستن همه خرید", "callback_data": "/close_longs"}])
    if any("SELL" in p["side"] for p in positions):
        k.append([{"text": "❌ بستن همه فروش", "callback_data": "/close_shorts"}])
    k.append([{"text": "🏠 منوی اصلی", "callback_data": "/menu"}])
    return {"inline_keyboard": k}


def get_confirm_close_all_keyboard():
    return {"inline_keyboard": [[{"text": "✅ بله، همه را ببند", "callback_data": "/confirm_close_all"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


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
    return {"inline_keyboard": [[{"text": "5م", "callback_data": "/set_tf_5m"}, {"text": "15م", "callback_data": "/set_tf_15m"}], [{"text": "1س", "callback_data": "/set_tf_1h"}, {"text": "4س", "callback_data": "/set_tf_4h"}], [{"text": "1روز", "callback_data": "/set_tf_1d"}, {"text": "مولتی", "callback_data": "/set_tf_multi"}]]}


def get_main_menu_keyboard(active):
    return {"inline_keyboard": [[{"text": "🔴 توقف اسکن" if active else "🟢 شروع اسکن", "callback_data": "/stop_scan" if active else "/start_scan"}], [{"text": "📊 وضعیت بازار", "callback_data": "/market_report"}], [{"text": "⚙️ تنظیمات معامله", "callback_data": "/check_wizard"}], [{"text": "🔍 تحلیل ارز", "callback_data": "/analyze_single"}, {"text": "📊 استراتژی", "callback_data": "/strategies_menu"}], [{"text": "⚙️ فیلترها", "callback_data": "/filters_menu"}, {"text": "🎛️ پارامترها", "callback_data": "/params_menu"}], [{"text": "📋 واچ‌لیست", "callback_data": "/manage_watchlist"}, {"text": "❌ بستن همه", "callback_data": "/close_all_prompt"}], [{"text": "🔄 پوزیشن‌ها", "callback_data": "/open_positions"}, {"text": "📈 عملکرد", "callback_data": "/performance"}]]}


def get_strategies_selection_keyboard():
    return {"inline_keyboard": [[{"text": "⚡ پویا", "callback_data": "/set_strat_dynamic"}], [{"text": "📈 روندی", "callback_data": "/set_strat_trend"}], [{"text": "🚀 شکست", "callback_data": "/set_strat_breakout"}], [{"text": "🔄 بازگشت به میانگین", "callback_data": "/set_strat_mean_reversion"}], [{"text": "🌊 چندزمانه", "callback_data": "/set_strat_multi"}], [{"text": "📚 توضیح", "callback_data": "/strategy_desc_menu"}], [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}


def get_strategies_menu_keyboard():
    return {"inline_keyboard": [[{"text": "5 دقیقه", "callback_data": "/desc_5min"}, {"text": "15 دقیقه", "callback_data": "/desc_15min"}], [{"text": "1 ساعت", "callback_data": "/desc_1hour"}, {"text": "مولتی", "callback_data": "/desc_multi"}], [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}


def get_watchlist_manage_keyboard():
    return {"inline_keyboard": [[{"text": "➕ افزودن", "callback_data": "/add_symbol_prompt"}, {"text": "➖ حذف", "callback_data": "/remove_symbol_prompt"}], [{"text": "📋 لیست", "callback_data": "/watchlist_list"}], [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}
