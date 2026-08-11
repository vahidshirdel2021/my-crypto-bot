def get_main_menu_keyboard(is_active):
    active_btn_text = "🟢 روشن کردن اسکن" if not is_active else "🔴 متوقف کردن اسکن"
    return {
        "inline_keyboard": [
            [
                {"text": active_btn_text, "callback_data": "/toggle_active"},
                {"text": "🔍 تحلیل تک ارز", "callback_data": "/analyze_single"}
            ],
            [
                {"text": "📋 مدیریت واچ‌لیست", "callback_data": "/manage_watchlist"},
                {"text": "⚙️ تنظیمات معاملاتی", "callback_data": "/wizard_start"}
            ],
            [
                {"text": "🔄 پوزیشن‌های باز", "callback_data": "/open_positions"},
                {"text": "📈 گزارش عملکرد", "callback_data": "/performance"}
            ]
        ]
    }

def get_margin_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "10 USDT", "callback_data": "/set_margin_10"}, {"text": "25 USDT", "callback_data": "/set_margin_25"}],
            [{"text": "50 USDT", "callback_data": "/set_margin_50"}, {"text": "100 USDT", "callback_data": "/set_margin_100"}]
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
            [{"text": "2 معامله", "callback_data": "/set_max_2"}, {"text": "3 معامله", "callback_data": "/set_max_3"}, {"text": "5 معامله", "callback_data": "/set_max_5"}],
            [{"text": "10 معامله", "callback_data": "/set_max_10"}, {"text": "بدون محدودیت", "callback_data": "/set_max_0"}]
        ]
    }

def get_timeframe_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "5 دقیقه", "callback_data": "/set_tf_5m"}, {"text": "15 دقیقه", "callback_data": "/set_tf_15m"}, {"text": "1 ساعت", "callback_data": "/set_tf_1h"}]
        ]
    }