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
    return {
        "inline_keyboard": [
            [{"text": "حساب کاغذی (تستی)", "callback_data": "/mode_paper"}],
            [{"text": "حساب واقعی (صرافی CoinEx)", "callback_data": "/mode_real"}]
        ]
    }

def get_balance_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "500 USDT", "callback_data": "/set_bal_500"}, {"text": "1000 USDT", "callback_data": "/set_bal_1000"}],
            [{"text": "5000 USDT", "callback_data": "/set_bal_5000"}, {"text": "10000 USDT", "callback_data": "/set_bal_10000"}]
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
            [{"text": "بدون محدودیت", "callback_data": "/set_max_0"}]
        ]
    }

def get_timeframe_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "5 دقیقه", "callback_data": "/set_tf_5m"}, {"text": "15 دقیقه", "callback_data": "/set_tf_15m"}],
            [{"text": "1 ساعت", "callback_data": "/set_tf_1h"}, {"text": "مولتی تایم‌فریم آبشاری", "callback_data": "/set_tf_multi"}]
        ]
    }

def get_strategies_menu_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "📊 استراتژی اسکالپ (5 دقیقه)", "callback_data": "/desc_5min"}],
            [{"text": "📊 استراتژی روزانه (15 دقیقه)", "callback_data": "/desc_15min"}],
            [{"text": "📊 استراتژی سوئینگ (1 ساعت)", "callback_data": "/desc_1hour"}],
            [{"text": "📊 استراتژی مولتی‌تایم‌فریم آبشاری", "callback_data": "/desc_multi"}],
            [{"text": "🏠 بازگشت به منوی اصلی", "callback_data": "/menu"}]
        ]
    }

def get_main_menu_keyboard(is_active):
    active_btn_text = "🟢 روشن کردن اسکن" if not is_active else "🔴 متوقف کردن اسکن"
    return {
        "inline_keyboard": [
            [{"text": active_btn_text, "callback_data": "/toggle_active"}, {"text": "⚙️ تغییر تنظیمات", "callback_data": "/check_wizard"}],
            [{"text": "🔍 تحلیل تک ارز", "callback_data": "/analyze_single"}, {"text": "📋 مدیریت واچ‌لیست", "callback_data": "/manage_watchlist"}],
            [{"text": "📊 انتخاب و تشریح استراتژی‌ها", "callback_data": "/strategies_list"}, {"text": "📈 گزارش عملکرد کلی", "callback_data": "/performance"}],
            [{"text": "🔄 پوزیشن‌های باز", "callback_data": "/open_positions"}, {"text": "❌ بستن کل پوزیشن‌ها", "callback_data": "/close_all"}]
        ]
    }

def get_watchlist_manage_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "➕ افزودن ارز", "callback_data": "/add_symbol_prompt"}, {"text": "➖ حذف ارز", "callback_data": "/remove_symbol_prompt"}],
            [{"text": "📋 لیست واچ‌لیست", "callback_data": "/manage_watchlist"}, {"text": "🏠 بازگشت به منو", "callback_data": "/menu"}]
        ]
    }
