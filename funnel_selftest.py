"""تست ثبت قیف: برخورد → رأی → صف تایید → ورود/خروج → سایه → گزارش. اجرا: python3 funnel_selftest.py"""
import sys, types, os, tempfile, json, time, glob
for name in ('aiohttp', 'ccxt', 'ccxt.async_support'):
    try:
        __import__(name)
    except Exception:
        sys.modules[name] = types.ModuleType(name)
_tmp = tempfile.mkdtemp()
os.environ.update({'TELEGRAM_TOKEN': '123:abc', 'ADMIN_CHAT_IDS': '111', 'BOT_DB_PATH': os.path.join(_tmp, 'bot.sqlite3'),
                   'PRESETS_CUSTOM_PATH': os.path.join(_tmp, 'presets_custom.json'), 'FUNNEL_DIR': os.path.join(_tmp, 'funnel'),
                   'TELEGRAM_SKIP_BACKLOG': 'true'})
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib
bot = importlib.import_module('bot')
import funnel_log, funnel_report
bot.init_db()
P = bot.presets_mod

sent = []
bot.send_message = lambda chat_id, text, markup=None, *a, **k: sent.append((chat_id, text, markup)) or True
bot.edit_page = lambda *a, **k: True
bot._touch_update_card = lambda *a, **k: None
bot._fav_update_card = lambda *a, **k: None

ok = True
def check(name, cond, info=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name, info)

# رأی‌های قابل‌کنترل: همه‌ی رأی‌دهنده‌ها «فروش» جز MACD که مخالف است
VOTE_TABLE = {'btcpat': 'SELL', 'btceth': 'SELL', 'h4': 'SELL', 'tf': 'SELL', 'rsi': 'BUY', 'macd': 'BUY', 'adx': 'SELL', 'level': 'SELL', 'ylevel': 'SELL', 'vol': 'OK'}
def fake_votes(symbol, tf, reason, keys, ind_df=None, cfg=None):
    return [{'key': k, 'label': k, 'vote': VOTE_TABLE.get(k), 'detail': ''} for k in bot._TOUCH_KEYS if k in keys]
bot._touch_votes = fake_votes
PX = {'AAA': 100.0}
bot.latest_price = lambda sym: PX.get(sym, 100.0)
bot.exchange_latest_price = lambda cid, sym: PX.get(sym, 100.0)

ADMIN = 111
s = bot.get_session(ADMIN)
P.apply_preset(s, '3')
s['fav_confirm_enabled'] = True
s['is_bot_active'] = True
plan = {'entry': 100.0, 'sl': 101.0, 'tp': 97.0, 'rr': 3.0, 'score': 80, 'quality_label': 'A'}

res = bot._touch_register(ADMIN, 'AAA', 'SELL', 'reason HVL=100 [SETUP Daily]', '15min', plan)
check("برخورد ثبت شد", res[0] in ('touch_wait', 'fav_wait', 'entry_opened', 'assist_card'), res)
rec = list(s['touch_wait'].values())[0]
tid = rec['id']

def events(kind=None):
    out = []
    for p in sorted(glob.glob(os.path.join(os.environ['FUNNEL_DIR'], 'funnel_*.jsonl'))):
        for line in open(p, encoding='utf-8'):
            e = json.loads(line)
            if kind is None or e['kind'] == kind:
                out.append(e)
    return out

tv = events('touch'); vv = events('vote')
check("رویداد touch نوشته شد با کلید و ورژن", len(tv) == 1 and tv[0]['preset'] == '3' and tv[0]['tid'] == tid and tv[0]['v'] == bot.BOT_VERSION, tv[:1])
check("رویداد vote با cf هر سه کلید", len(vv) >= 1 and set(vv[0]['cf'].keys()) == {'3', '4', '5'} and vv[0]['cf']['3'] is not None, vv[0]['cf'] if vv else None)
check("cf کلید فعال (۳) با تصمیم واقعی یکی است", vv[0]['cf']['3']['ok'] == bool(vv[0]['auto_ok']) and vv[0]['cf']['3']['a'] == vv[0]['agree'], (vv[0]['cf']['3'], vv[0]['auto_ok'], vv[0]['agree']))
check("raw همه‌ی رأی‌دهنده‌ها ثبت شد", set(vv[0]['raw'].keys()) == set(bot._TOUCH_KEYS))
check("کلید ۵ (همه موافق) وقتی گروه مومنتوم مخالف است رد می‌کند", vv[0]['cf']['5']['ok'] is False, vv[0]['cf']['5'])
check("کلید ۳ (اکثریت) همان برخورد را می‌پذیرد", vv[0]['cf']['3']['ok'] is True, vv[0]['cf']['3'])
check("تصمیم‌ها قابل مقایسه است (۳ و ۴ و ۵)", all(vv[0]['cf'][n] for n in '345'))

# رأی بدون تغییر = رویداد تکراری نمی‌نویسد
n0 = len(events('vote'))
bot._touch_eval_one(ADMIN, rec)
check("رأی بدون تغییر رویداد تکراری نمی‌سازد", len(events('vote')) == n0)

# رأی تغییر کند → رویداد جدید
VOTE_TABLE['macd'] = 'SELL'; VOTE_TABLE['rsi'] = 'SELL'
bot._touch_eval_one(ADMIN, rec)
vv = events('vote')
check("تغییر رأی ثبت شد و حالا کلید ۵ هم تایید است", len(vv) == n0 + 1 and vv[-1]['cf']['5']['ok'] is True, vv[-1]['cf'])

# ورود به صف تایید حرکت / بلاک
rec['status'] = 'waiting'
bot._touch_auto_enter(ADMIN, rec)
pv = events('pass_vote'); fq = events('fav_queue'); bl = events('block')
check("pass_vote یا block ثبت شد", len(pv) + len(bl) >= 1, (len(pv), len(bl)))
if fq:
    check("fav_queue به tid وصل است", fq[0]['tid'] == tid and fq[0]['min_r'] is not None, fq[0])
    r = list(s['fav_wait'].values())[0]
    bot._fav_finish(ADMIN, s, r, 'expired', 'test')
    ff = events('fav_final')
    check("fav_final ثبت شد", len(ff) == 1 and ff[0]['tid'] == tid and ff[0]['status'] == 'expired', ff)
else:
    print('NOTE: صف تایید فعال نشد؛ مسیر بلاک تست شد:', [b['gate'] for b in bl])

# بلاک: قیمت از SL گذشته
PX['AAA'] = 102.0
rec2 = dict(rec); rec2['status'] = 'waiting'; rec2['id'] = 'tid2'; rec2['_fn_passed'] = None; rec2.pop('_fn_block', None)
bot._touch_auto_enter(ADMIN, rec2)
check("بلاک قیمت از SL گذشته با gate=price_crossed", any(b['gate'] == 'price_crossed' for b in events('block')), [b['gate'] for b in events('block')])
PX['AAA'] = 100.0

# پایان برخوردی که هیچ‌وقت تایید نشد: رأی‌ها شکست می‌خورد
VOTE_TABLE.update({'rsi': 'BUY', 'macd': 'BUY', 'adx': 'BUY', 'level': 'BUY', 'btceth': 'BUY', 'h4': 'BUY', 'tf': 'BUY'})
PX['BBB'] = 50.0
s['touch_wait_seen'] = {}
bot._touch_register(ADMIN, 'BBB', 'SELL', 'reason HVL=50 [SETUP Daily]', '15min', {'entry': 50.0, 'sl': 51.0, 'tp': 47.0, 'rr': 3.0, 'score': 70})
recb = [r for r in s['touch_wait'].values() if r['symbol'] == 'BBB'][0]
vb = [e for e in events('vote') if e['tid'] == recb['id']][0]
check("برخورد با رأی بد: کلید ۵ و ۴ رد می‌کنند", vb['cf']['5']['ok'] is False and vb['cf']['4']['ok'] is False, vb['cf'])
recb['expires_at'] = time.time() - 1
bot._touch_tick(ADMIN)
tf_ = events('touch_final')
check("touch_final هنگام انقضا بدون تایید", any(e['tid'] == recb['id'] and e['status'] == 'expired' and not e['passed'] for e in tf_), tf_[-1:])

# معامله باز/بسته
bot.audit_event(ADMIN, 'TR1', 'position_opened', {'symbol': 'AAA', 'side': 'SELL (Short)', 'entry_price': 100, 'sl': 101, 'tp': 97, 'planned_rr': 3, 'preset': '3', 'entry_reason': 'x |VOTES=rsi:Y,macd:Y|'})
s['closed_positions'].append({'trade_id': 'TR1', 'symbol': 'AAA', 'side': 'SELL (Short)', 'realized_r': 1.5, 'mfe_r': 2.0, 'mae_r': 0.2, 'close_reason': 'TP'})
bot.audit_event(ADMIN, 'TR1', 'position_closed', {'close_price': 97, 'pnl_usdt': 7.5, 'reason': 'TP', 'duration_seconds': 3600})
check("entry و trade_close ثبت شد", len(events('entry')) == 1 and events('entry')[0]['votes'] == 'rsi:Y,macd:Y' and events('trade_close')[0]['r'] == 1.5)

# اسکن: نویز شمارش می‌شود نه رویداد
bot._pipeline_record(ADMIN, 'AAA', 'watchlist_review', 'review_started', 'x')
bot._pipeline_record(ADMIN, 'AAA', 'signal', 'no_signal', 'مدل نصف‌کردن: ستاپی روی سطوح ثبت نشد (عمق درخت 9، فاصله‌ی سطوح 0.0001)')
bot._pipeline_record(ADMIN, 'AAA', 'signal', 'no_signal', 'گارد سقف/کف دیروز: کف دیروز (PDL=0.5) فقط 1.4×ATR جلوی فروش است')
funnel_log.flush_counters()
ss = events('scan_summary')
check("scan_summary با شمارنده‌ها", ss and ss[-1]['counts'].get('scans') == 1 and ss[-1]['counts'].get('no_setup') == 1 and ss[-1]['counts'].get('guard_pd') == 1, ss[-1:] )
check("نویز no_setup رویداد scan نمی‌سازد ولی گارد می‌سازد", len([e for e in events('scan')]) == 1)

# سایه: ثبت شد؟ حل با کندل‌های مصنوعی
pend = funnel_log._SHADOW
check("ردیاب سایه ثبت شد", any(x['tid'] == tid and x['sk'] == 'touch' for x in pend), len(pend))
import pandas as pd
base_ts = [x for x in pend if x['tid'] == tid][0]['start_ts']
class DF(pd.DataFrame): pass
def fake_klines(sym, tf, n):
    rows = []
    for i in range(1, 30):
        t = base_ts + i * 900
        rows.append({'timestamp': t * 1000, 'high': 100.2 if i < 3 else 99.5, 'low': 99.2 if i < 3 else (96.5 if i == 5 else 98.0)})
    return pd.DataFrame(rows)
for x in pend: x['due'] = 0
n = funnel_log.shadow_run_once(fake_klines)
sh = events('shadow')
check("shadow حل شد و tp اول خورد (فروش)", n >= 1 and any(e['tid'] == tid and e['sk'] == 'touch' and e['outcome'] == 'tp' for e in sh), [(e['sk'], e['outcome'], e['reach']) for e in sh][:2])
check("reach 0.35R ثبت شد", any('0.35' in (e.get('reach') or {}) for e in sh))
check("صف سایه بعد از حل خالی شد", not any(x['tid'] == tid and x['sk'] == 'touch' for x in funnel_log._SHADOW))

# گزارش
rep = funnel_report.build_report(os.environ['FUNNEL_DIR'], days=1)
check("گزارش ساخته شد و بخش‌ها را دارد", all(t in rep for t in ('قیف واقعی', 'مقایسهٔ منصفانه', 'کجا متوقف', 'پیش‌بینی')), rep[:200])
check("گزارش برای هر سه کلید ردیف دارد", all(f'کلید {n}' in rep for n in '۳۴۵'))
print(rep)
z = funnel_report.export_zip(os.environ['FUNNEL_DIR'], 1)
check("zip خروجی ساخته شد", z and os.path.getsize(z) > 100)

# دستورها فقط ادمین
sent.clear(); bot.process_command('/funnel_report', ADMIN)
check("دستور گزارش برای ادمین پاسخ می‌دهد", sent and 'گزارش قیف' in sent[0][1], sent[0][1][:60] if sent else None)
sent.clear(); bot.process_command('/funnel_report', 222)
check("کاربر عادی نمی‌تواند", sent and 'گزارش قیف' not in sent[0][1])
print("\nALL PASS" if ok else "\nSOME FAILED")
raise SystemExit(0 if ok else 1)
