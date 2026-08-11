def get_bottom_menu_keyboard():
    return {
        "keyboard": [
            [{"text": "🏠 منوی اصلی"}, {"text": "🔄 پوزیشن‌های باز"}],
            [{"text": "📈 گزارش عملکرد کلی"}, {"text": "📊 انتخاب استراتژی"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

def get_start_keyboard():
    return {"inline_keyboard": [[{"text": "حساب کاغذی", "callback_data": "/mode_paper"}, {"text": "حساب واقعی", "callback_data": "/mode_real"}]]}

def get_balance_keyboard():
    return {"inline_keyboard": [[{"text": "500", "callback_data": "/set_bal_500"}, {"text": "1000", "callback_data": "/set_bal_1000"}], [{"text": "5000", "callback_data": "/set_bal_5000"}, {"text": "10000", "callback_data": "/set_bal_10000"}]]}

def get_margin_keyboard():
    return {"inline_keyboard": [[{"text": "10", "callback_data": "/set_margin_10"}, {"text": "25", "callback_data": "/set_margin_25"}], [{"text": "50", "callback_data": "/set_margin_50"}, {"text": "100", "callback_data": "/set_margin_100"}]]}

def get_leverage_keyboard():
    return {"inline_keyboard": [[{"text": "3X", "callback_data": "/set_lev_3"}, {"text": "5X", "callback_data": "/set_lev_5"}, {"text": "10X", "callback_data": "/set_lev_10"}]]}

def get_max_positions_keyboard():
    return {"inline_keyboard": [[{"text": "2", "callback_data": "/set_max_2"}, {"text": "3", "callback_data": "/set_max_3"}, {"text": "5", "callback_data": "/set_max_5"}]]}

def get_timeframe_keyboard():
    return {"inline_keyboard": [[{"text": "5م", "callback_data": "/set_tf_5m"}, {"text": "15م", "callback_data": "/set_tf_15m"}], [{"text": "1س", "callback_data": "/set_tf_1h"}, {"text": "مولتی آبشاری", "callback_data": "/set_tf_multi"}]]}

def get_main_menu_keyboard(is_active):
    text = "🔴 توقف اسکن" if is_active else "🟢 روشن کردن اسکن"
    return {"inline_keyboard": [[{"text": text, "callback_data": "/toggle_active"}], [{"text": "🔍 تحلیل ارز", "callback_data": "/analyze_single"}, {"text": "📋 مدیریت واچ‌لیست", "callback_data": "/manage_watchlist"}], [{"text": "❌ بستن کل پوزیشن‌ها", "callback_data": "/close_all"}]]}

def get_strategies_menu_keyboard():
    return {"inline_keyboard": [[{"text": "اسکالپ 5م", "callback_data": "/desc_5min"}, {"text": "روزانه 15م", "callback_data": "/desc_15min"}], [{"text": "سوئینگ 1س", "callback_data": "/desc_1hour"}, {"text": "مولتی آبشاری", "callback_data": "/desc_multi"}]]}

def get_watchlist_manage_keyboard():
    return {"inline_keyboard": [[{"text": "➕ افزودن ارز", "callback_data": "/add_symbol_prompt"}, {"text": "➖ حذف ارز", "callback_data": "/remove_symbol_prompt"}], [{"text": "📋 لیست واچ‌لیست", "callback_data": "/manage_watchlist"}], [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}
