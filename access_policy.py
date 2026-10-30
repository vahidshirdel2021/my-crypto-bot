# -*- coding: utf-8 -*-
"""V3.44.59: قفل نقش‌ها (کاربر عادی / ادمین).

هدف: کاربر عادی فقط بخش‌هایی را ببیند و اجرا کند که واقعاً لازم دارد (شروع/توقف اسکن، پوزیشن‌های خودش،
سود و زیان ساده، تنظیمات ریسک، اتصال حساب، بستن معامله و دکمه‌های کارت‌های سیگنال). هر چیز دیگر
(ستاپ‌ها، فیلترها، رژیم، ممیزی، لاگ تشخیصی، خروجی داده، پریست‌ها ...) فقط برای ادمین است.

اصل: «پیش‌فرض = ممنوع». هر دستور جدیدی که در آینده به ربات اضافه شود، تا وقتی عمداً به این لیست
اضافه نشود برای کاربر عادی بسته می‌ماند.

این فایل عمداً مستقل از bot.py است تا بدون تلگرام و بدون سرور قابل تست باشد.
"""
import copy
import json
import re

# --- دستورهای دقیق مجاز برای کاربر عادی ---------------------------------------------------------
USER_EXACT = frozenset({
    # ناوبری
    '/start', '/menu', '/cancel', '/noop', '/dummy',
    '☰ منو', '🏠 منوی اصلی', '🏠 منو', 'منوی اصلی',
    # اسکن
    '/start_scan', '/stop_scan', '/reload_and_start',
    '🔴 توقف اسکن', 'توقف اسکن', '🔴 توقف', '🟢 شروع اسکن', 'شروع اسکن', '🟢 اسکن',
    # پوزیشن‌ها و بستن
    '/open_positions', '/positions',
    '/close_all_prompt', '/confirm_close_all', '/close_longs_prompt', '/close_shorts_prompt',
    '/confirm_close_longs', '/confirm_close_shorts', '/emergency_close_all', '/confirm_emergency_close_all',
    # سود و زیان ساده
    '/performance', '/performance_today', '/performance_week', '/performance_month',
    '/daily_pnl', '/today_trades',
    # تنظیمات ریسک و حساب
    '/menu_settings', '/check_wizard', '/mode_paper', '/paper_bal', '/mode_real', '/trade_mode_menu',
    # کارمزد خود کاربر
    '/fee_menu', '/fee_today', '/fee_week', '/fee_month', '/fee_all', '/my_fee_report', '/my_fees',
    # لیست سیگنال‌های در انتظار خود کاربر (کارت‌ها)
    '/assist_pending',
    # V3.44.91: «⏳ سیگنال‌های در حال تایید» (صف تایید حرکت) و «🧭 رژیم BTC/ETH» برای کاربر عادی هم باز شد
    # (متن هر دو در bot.py برای کاربر عادی ساده می‌شود: بدون پارامتر و اطلاعات فنی)
    '/fav_queue', '/btc_eth_regime',
    # V3.44.75: کلید حالت دستیار در منوی اصلی
    '/assist_main_toggle',
    # V3.44.76: پشتیبان ربات
    '/support',
    # V3.44.84: دکمه‌ی برگشتِ مراحل ویزارد تنظیمات معامله
    '/wiz_lev', '/wiz_max', '/wiz_same',
    # V3.44.85: مرحله‌ی «حالت معامله» در ویزارد
    '/wiz_tf', '/wiz_mode_done',
})

# V3.44.83: ریست آمار و ریست کامل ربات؛ فقط برای کاربر عادیِ «حساب کاغذی» مجاز است (در حساب واقعی بسته می‌ماند)
PAPER_ONLY_EXACT = frozenset({
    '/reset_stats_prompt', '/reset_stats_confirm', '/full_reset_prompt', '/full_reset_confirm',
})

# --- الگوهای مجاز (regex کامل‌منطبق) -------------------------------------------------------------
_USER_PATTERNS = tuple(re.compile(p) for p in (
    r'^/start(\s.*)?$',
    # تنظیمات ریسک (فقط عدد). «هم‌جهت» فقط از داخل ویزارد (/set_wsame_N)؛ منوی جداگانه‌ی آن و «کولداون» بیرون است
    r'^/set_bal_\d+(\.\d+)?$', r'^/set_margin_\d+(\.\d+)?$', r'^/set_lev_\d+$', r'^/set_max_\d+$', r'^/set_wsame_\d+$', r'^/trade_mode_set_[345]$', r'^/set_wmode_[345]$',
    # تایم‌فریم: مرحله‌ی اجباریِ ویزارد اولیه
    r'^/set_tf_(5m|15m|1h|4h)$',
    # اتصال صرافی (REAL)
    r'^/real_(pick|use|new|del)_[a-z0-9_]+$',
    # V3.44.108: انتخاب صرافی حساب کاغذی (اولین مرحله‌ی ویزارد کاغذی) و بازگشت به صفحه‌ی موجودی
    r'^/paper_pick_(binance|bitunix)$',
    # پوزیشن‌های خود کاربر
    r'^/manage_(?!watchlist$)[a-z0-9_]+$',
    r'^/close_prompt_[a-z0-9_]+$', r'^/confirm_close_[a-z0-9_]+$', r'^/pclose_[a-z0-9_]+$',
    r'^/edit_(sl|tp)_[a-z0-9_]+$',
    r'^/show_chart_[a-z0-9_]+$', r'^/view_chart_[a-z0-9_]+$',
    # دکمه‌های کارت‌های سیگنال/تایید/لمس که ربات خودش برای کاربر می‌فرستد
    r'^/assist_(ok|no|rev|revok|man|open|save|saved|cd|ext|farok|farno|tgok|trendcancel)_?[a-z0-9_.:\-]*$',
    r'^/(autotg_(ok|no)|tgref|keep_channel_msg|del_channel_msg|check_entry|cancel_watch)_[a-z0-9_.:\-]*$',
    r'^/(qt|qtm)_(buy|sell|tgok)_[a-z0-9_.:\-]*$', r'^/quick_manual_trade_[a-z0-9_.:\-]*$',
    r'^/tw_(qe|open|ref)_[a-z0-9_.:\-]*$', r'^/fq_(qe|ref|rej|ext)_[a-z0-9_.:\-]*$',
    r'^/becl_[a-z0-9_.:\-]*$', r'^/(rvshow|rvdel)_[a-z0-9_.:\-]*$',
    r'^/(manual_entry_tgok|confirm_manual_entry|confirm_manual_trade)([a-z0-9_.:\-]*)$',
    # سؤال تاییدِ «مطمئنی؟» (خودش بعداً دستور اصلی را دوباره از همین فیلتر رد می‌کند)
    r'^/cfm(no)?_[a-z0-9_.:\-]*$',
    # V3.44.61: دکمه‌ی «✅ واریز کردم» روی فاکتور کارمزد روزانه
    r'^/fee_claim_\d+$',
))

# دکمه‌های کیبورد ثابت پایین چت که برای کاربر عادی نمایش داده نمی‌شود
USER_HIDDEN_REPLY_BUTTONS = frozenset({
    '📊 وضعیت بازار',
})

# V3.44.91: دکمه‌ی ثابت «📋 سیگنال‌های در انتظار» برای کاربر عادی با «⏳ سیگنال‌های در حال تایید» عوض می‌شود
# (همان جای دکمه‌ی قبلی؛ نسخه‌ی تکراری پایین کیبورد حذف می‌شود). فرمان /assist_pending هنوز مجاز است.
USER_REPLY_BUTTON_SWAPS = {
    '📋 سیگنال‌های در انتظار': '⏳ سیگنال‌های در حال تایید',
}


def user_command_allowed(cmd, paper=False):
    """آیا کاربر عادی اجازه‌ی اجرای این دستور/دکمه را دارد؟ (پیش‌فرض: خیر)
    paper=True یعنی حساب فعلی کاربر کاغذی است؛ فقط در این حالت دستورهای PAPER_ONLY_EXACT مجازند."""
    c = str(cmd or '').strip()
    if not c:
        return False
    if c.startswith('/back:'):
        return user_command_allowed(c[len('/back:'):] or '/menu', paper)
    cl = c.lower()
    if cl in PAPER_ONLY_EXACT:
        return bool(paper)
    if c in USER_EXACT or cl in USER_EXACT:
        return True
    return any(p.match(cl) for p in _USER_PATTERNS)


def is_restricted(chat_id, admin_ids, enabled=True):
    """کاربر عادی؟ فقط چت‌های خصوصی (آیدی مثبت) و فقط وقتی حداقل یک ادمین تعریف شده؛ وگرنه قفل خاموش است
    تا مالک به‌خاطر خالی‌بودن ADMIN_CHAT_IDS از ربات خودش بیرون نماند."""
    if not enabled or not admin_ids:
        return False
    try:
        cid = int(chat_id)
    except Exception:
        return False
    if cid <= 0:          # کانال/گروه
        return False
    return cid not in admin_ids


def filter_markup(markup, paper=False):
    """کیبورد را برای کاربر عادی پاک‌سازی می‌کند: دکمه‌های مخصوص ادمین، و ردیف‌های نمایشی (/dummy) که
    مقدار پارامترها را لو می‌دهند حذف می‌شوند. ورودی تغییر نمی‌کند."""
    if isinstance(markup, str):
        try:
            markup = json.loads(markup)
        except Exception:
            return markup
    if not isinstance(markup, dict):
        return markup
    out = copy.deepcopy(markup)
    if isinstance(out.get('inline_keyboard'), list):
        rows = []
        for row in out['inline_keyboard']:
            kept = []
            for b in row:
                cd = b.get('callback_data') if isinstance(b, dict) else None
                if cd is None:
                    kept.append(b)                      # url / web_app / ...
                elif str(cd).strip().lower() == '/dummy':
                    continue                            # ردیف نمایشی (اطلاعات پارامتر)
                elif user_command_allowed(cd, paper):
                    kept.append(b)
            if kept:
                rows.append(kept)
        out['inline_keyboard'] = rows
    if isinstance(out.get('keyboard'), list):
        rows = []
        seen_texts = set()
        for row in out['keyboard']:
            kept = []
            for b in row:
                if isinstance(b, dict):
                    t = b.get('text')
                    if t in USER_HIDDEN_REPLY_BUTTONS:
                        continue
                    t2 = USER_REPLY_BUTTON_SWAPS.get(t, t)
                    if t2 != t:
                        b['text'] = t2
                    if t2 in seen_texts:                # دکمه‌ی جایگزین‌شده فقط یک‌بار (همان جای اول) بماند
                        continue
                    seen_texts.add(t2)
                kept.append(b)
            if kept:
                rows.append(kept)
        out['keyboard'] = rows
        if 'input_field_placeholder' in out:
            out['input_field_placeholder'] = 'از دکمه‌های منو استفاده کنید'    # تحلیل نماد با تایپ فقط برای ادمین است
    return out
