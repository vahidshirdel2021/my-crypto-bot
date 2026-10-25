# -*- coding: utf-8 -*-
"""V3.44.78: دکمه‌ی «📢 کانال تلگرام» در منوی اصلی. اجرا: python3 channel_button_selftest.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ui
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(('PASS ' if c else 'FAIL ') + n)
def btns(kb): return [b for row in kb['inline_keyboard'] for b in row]
for k in ('CHANNEL_LINK', 'SIGNAL_CHANNEL_ID'): os.environ.pop(k, None)
check('no link configured -> empty', ui.channel_link() == '')
os.environ['SIGNAL_CHANNEL_ID'] = '-1001234567890'
check('numeric private id -> no link', ui.channel_link() == '')
os.environ['SIGNAL_CHANNEL_ID'] = '@mychan'
check('@name derives link', ui.channel_link() == 'https://t.me/mychan')
os.environ['CHANNEL_LINK'] = 't.me/other'
check('CHANNEL_LINK wins and is normalised', ui.channel_link() == 'https://t.me/other')
os.environ['CHANNEL_LINK'] = '@third'
check('@name in CHANNEL_LINK', ui.channel_link() == 'https://t.me/third')
os.environ['CHANNEL_LINK'] = 'javascript:alert(1)'
check('bad scheme rejected', ui.channel_link() == '')
os.environ['CHANNEL_LINK'] = 'https://t.me/mychan'
for adm in (False, True):
    b = [x for x in btns(ui.get_main_menu_keyboard(True, True, adm)) if 'url' in x]
    check(f'main menu has URL button (admin={adm})', len(b) == 1 and b[0]['url'] == 'https://t.me/mychan' and 'کانال' in b[0]['text'])
os.environ.pop('CHANNEL_LINK'); os.environ.pop('SIGNAL_CHANNEL_ID')
check('no link -> no URL button', not [x for x in btns(ui.get_main_menu_keyboard(True, True, False)) if 'url' in x])
print('ALL PASS' if ok else 'SOME FAILED'); sys.exit(0 if ok else 1)
