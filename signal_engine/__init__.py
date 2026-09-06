# -*- coding: utf-8 -*-
"""
signal_engine
==============
معماری جدید ۵ موتور مستقل + یک لایه‌ی تجمیع سیگنال، طبق ۶ سند طراحی این
پروژه، جایگزین pdh_eq_pdl_engine.py / extra_orb_engine.py / swing_detection.py.

زیرپکیج‌ها:
    common          — ATR، Trend Context، هندسه‌ی کندل (مشترک بین همه)
    swing_structure — سوئینگ واقعی + BOS/CHoCH + هم‌راستایی چندتایم‌فریمی   [ساخته‌شده]
    key_level_setup — P4H/PDH/PWH/PMH...، BOF/TST/BPB/BP/CPB                 [ساخته‌شده]
    candlestick     — الگوهای کندل استیک                                    [برنامه‌ریزی‌شده]
    pattern_recognition — الگوهای کلاسیک نموداری                            [برنامه‌ریزی‌شده]
    market_cycle    — فازهای Wyckoff + مدل ال بروکس                         [برنامه‌ریزی‌شده]
    confluence      — لایه‌ی نهایی تجمیع سیگنال (USCL)                       [برنامه‌ریزی‌شده]
"""
