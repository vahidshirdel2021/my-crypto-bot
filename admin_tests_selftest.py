"""V3.44.51: تست اجرای تست‌ها از داخل ربات (جمع‌آوری، اجرای ایزوله، فرمت نتیجه) با فایل‌های تستِ ساختگی."""
import os, re, sys, time, tempfile, logging
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'bot.py'), encoding='utf-8').read()
a = src.index("# ===== V3.44.51: اجرای تست‌ها")
b = src.index("# ===== END admin tests =====")
sent = []
g = {'os': os, 're': re, 'time': time, 'logger': logging.getLogger('t'),
     'send_message': lambda chat, text, kb=None: sent.append((chat, text)),
     'get_admin_tests_keyboard': lambda: {'inline_keyboard': []}, '__file__': os.path.abspath(__file__)}
exec(src[a:b], g)
collect, execute, fmt = g['_admin_tests_collect'], g['_admin_tests_execute'], g['_admin_tests_format']

with tempfile.TemporaryDirectory() as base:
    def w(name, body):
        open(os.path.join(base, name), 'w', encoding='utf-8').write(body)
    w('pass_selftest.py', "import os\nprint('TOKEN=' + os.environ.get('TELEGRAM_BOT_TOKEN',''), 'PAPER=' + os.environ.get('PAPER_ONLY',''))\nopen('leak.txt','w').write('x')\nprint('ALL OK')\n")
    w('fail_selftest.py', "import sys\nprint('خطای ساختگی')\nsys.exit(1)\n")
    w('softfail_selftest.py', "print('PASS a')\nprint('FAIL b')\nprint('SOME FAILED')\n")
    w('slow_selftest.py', "import time\ntime.sleep(5)\n")
    w('test_pytest_style.py', "def test_x():\n    assert True\n")
    w('preset_selftest.py', "print('ALL OK')\n")      # عضو مجموعه‌ی core
    w('helper.py', "print('نباید اجرا شود')\n")
    allnames = collect(base, 'all')
    assert allnames == sorted(['pass_selftest.py', 'fail_selftest.py', 'softfail_selftest.py', 'slow_selftest.py', 'test_pytest_style.py', 'preset_selftest.py']), allnames
    assert collect(base, 'core') == ['preset_selftest.py'], collect(base, 'core')
    res = {r[0]: r for r in execute(base, allnames, timeout=2)}
    assert res['pass_selftest.py'][1] == 'ok' and 'TOKEN=123:abc' in res['pass_selftest.py'][3] and 'PAPER=true' in res['pass_selftest.py'][3], res['pass_selftest.py']
    assert not os.path.exists(os.path.join(base, 'leak.txt')), 'تست نباید در پوشه‌ی اصلی بنویسد'
    assert not os.path.exists('leak.txt')
    assert res['fail_selftest.py'][1] == 'fail'
    assert res['softfail_selftest.py'][1] == 'fail'          # کد خروج ۰ ولی FAIL در خروجی
    assert res['slow_selftest.py'][1] == 'timeout'
    assert res['test_pytest_style.py'][1] in ('ok', 'skip')    # بسته به نصب‌بودن pytest
    assert res['preset_selftest.py'][1] == 'ok'
    txt = fmt(list(res.values()), 'all')
    assert '❌' in txt and 'fail_selftest.py' in txt and 'slow_selftest.py' in txt and len(txt) <= 3800
    assert 'همه‌ی تست‌ها پاس شدند' in fmt([('a.py', 'ok', 1.0, '')], 'core')
    assert 'هیچ فایل تستی' in fmt([], 'all')
print('admin_tests_selftest OK')
