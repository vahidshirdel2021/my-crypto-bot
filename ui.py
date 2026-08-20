from strategy import STRATEGY_DEFAULTS

CHAT_INPUT_PLACEHOLDER = "نام ارز خود را جهت تحلیل وارد کنید"


def get_bottom_menu_keyboard(is_active=False, is_open=True):
    return {
        "keyboard": [
            [{"text": "📊 وضعیت بازار"}, {"text": "🔄 پوزیشن‌ها"}],
            [{"text": "🏠 منوی اصلی"}, {"text": "🆘 بستن اضطراری همه"}],
        ],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": CHAT_INPUT_PLACEHOLDER,
    }


def get_params_menu_keyboard(session=None):
    s = session or {}; c = s.get("strategy_config", STRATEGY_DEFAULTS)
    return {"inline_keyboard": [
        [{"text": "🟢 حالت متعادل ⭐", "callback_data": "/profile_balanced"}],
        [{"text": "🛡️ محافظه‌کارانه", "callback_data": "/profile_conservative"}, {"text": "⚡ فرصت‌های بیشتر", "callback_data": "/profile_opportunity"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_learn_menu_keyboard():
    return {"inline_keyboard": [
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_performance_keyboard():
    return {"inline_keyboard": [
        [{"text": "📊 کل سابقه", "callback_data": "/performance"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_positions_keyboard(positions):
    k = [[{"text": f"{'🟢' if 'BUY' in p['side'] else '🔴'} {p['symbol']} — مدیریت", "callback_data": f"/manage_{p['symbol']}"}] for p in positions]
    k.append([{"text": "🏠 منوی اصلی", "callback_data": "/menu"}])
    return {"inline_keyboard": k}


def get_confirm_close_all_keyboard():
    return {"inline_keyboard": [[{"text": "✅ بله، همه را ببند", "callback_data": "/confirm_close_all"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


def get_confirm_emergency_close_keyboard():
    return {"inline_keyboard": [[{"text": "🆘 بله، فوراً همه را ببند", "callback_data": "/confirm_emergency_close_all"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


def get_confirm_close_longs_keyboard():
    return {"inline_keyboard": [[{"text": "✅ بله", "callback_data": "/confirm_close_longs"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


def get_confirm_close_shorts_keyboard():
    return {"inline_keyboard": [[{"text": "✅ بله", "callback_data": "/confirm_close_shorts"}], [{"text": "❌ انصراف", "callback_data": "/cancel"}]]}


def get_start_keyboard():
    return {"inline_keyboard": [[{"text": "حساب کاغذی", "callback_data": "/mode_paper"}, {"text": "حساب واقعی", "callback_data": "/mode_real"}]]}


def get_balance_keyboard():
    return {"inline_keyboard": [[{"text": "1000 USDT", "callback_data": "/set_bal_1000"}]]}


def get_margin_keyboard():
    return {"inline_keyboard": [[{"text": "50 USDT", "callback_data": "/set_margin_50"}]]}


def get_leverage_keyboard():
    return {"inline_keyboard": [[{"text": "5X", "callback_data": "/set_lev_5"}]]}


def get_max_positions_keyboard():
    return {"inline_keyboard": [[{"text": "3", "callback_data": "/set_max_3"}]]}


def get_timeframe_keyboard():
    return {"inline_keyboard": [
        [{"text": "⏱ ۵ دقیقه", "callback_data": "/set_tf_5m"}, {"text": "⏱ ۱۵ دقیقه", "callback_data": "/set_tf_15m"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]
    ]}


def get_main_menu_keyboard(active, entry_diag_enabled=True):
    return {"inline_keyboard": [
        [{"text": "🔴 توقف اسکن" if active else "🟢 شروع اسکن", "callback_data": "/stop_scan" if active else "/start_scan"}],
        [{"text": "🔄 بارگذاری مجدد و شروع اسکن", "callback_data": "/reload_and_start"}],
        [{"text": "📊 وضعیت بازار", "callback_data": "/market_report"},
         {"text": "🔍 لاگ تشخیصی ورود", "callback_data": "/entry_diag"}],
        # دکمه‌های اضافه شده برای گزارش کارمزد
        [{"text": "💰 گزارش کارمزد من", "callback_data": "/my_fees"},
         {"text": "👑 گزارش درآمد ادمین", "callback_data": "/admin_fee_report"}],
        [{"text": "⚙️ تنظیمات معامله", "callback_data": "/check_wizard"},
         {"text": "📋 واچ‌لیست", "callback_data": "/manage_watchlist"}],
        [{"text": "🔄 پوزیشن‌ها", "callback_data": "/open_positions"},
         {"text": "📈 عملکرد و گزارش‌ها", "callback_data": "/performance"}],
        [{"text": "🖐 معامله دستی", "callback_data": "/manual_trade"}],
        [{"text": "❌ بستن همه", "callback_data": "/close_all_prompt"}],
        [{"text": "🔎 ممیزی آخرین معامله", "callback_data": "/trade_audit"}],
    ]}


def get_entry_diag_keyboard(enabled=True):
    return {"inline_keyboard": [
        [{"text": "🟢 فعال‌سازی/غیرفعال‌سازی", "callback_data": "/toggle_entry_diag"}],
        [{"text": "🏠 منوی اصلی", "callback_data": "/menu"}],
    ]}


def get_watchlist_manage_keyboard():
    return {"inline_keyboard": [[{"text": "🏠 منوی اصلی", "callback_data": "/menu"}]]}


def get_manual_side_keyboard():
    return {"inline_keyboard": [
        [{"text": "🟢 خرید (Long)", "callback_data": "/manual_side_buy"},
         {"text": "🔴 فروش (Short)", "callback_data": "/manual_side_sell"}],
        [{"text": "❌ انصراف", "callback_data": "/cancel"}],
    ]}
