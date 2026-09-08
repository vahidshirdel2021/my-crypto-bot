# -*- coding: utf-8 -*-
"""
signal_engine
==============
معماری جدید، طبق اسناد طراحی این پروژه، جایگزین pdh_eq_pdl_engine.py /
extra_orb_engine.py / swing_detection.py.

زیرپکیج‌ها:
    common          — ATR، Trend Context، هندسه‌ی کندل (مشترک بین همه)
    swing_structure — سوئینگ واقعی + BOS/CHoCH + هم‌راستایی چندتایم‌فریمی   [ساخته‌شده]
    key_level_setup — P4H/PDH/PWH/PMH...، BOF/TST/BPB/BP/CPB                 [ساخته‌شده]
    confluence      — لایه‌ی نهایی تجمیع سیگنال (USCL)                       [ساخته‌شده]

توجه: سه موتور پیشین این معماری — pattern_recognition (PRE)،
candlestick (CPDE) و market_cycle (MCDE، فازهای کلان/ریز Wyckoff) — طبق
درخواست صریح کاربر به‌طور کامل از پروژه حذف شده‌اند (کد، آداپتور در
confluence.adapters، قوانین anchor/امتیاز مرتبط در correlation.py/
scoring.py، و وابستگی MCDE در watchlist_bridge.compute_btc_context).
معماری فعلی فقط از دو موتور مستقل (SDE از طریق swing_structure، و
KLSDE از طریق key_level_setup) تشکیل شده است.
"""
