import os, sys, math, types
os.environ.setdefault('TELEGRAM_BOT_TOKEN','123:abc')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import bot
except SystemExit as e:
    print("bot import exited", e); raise
except Exception as e:
    import traceback; traceback.print_exc(); raise
print("bot imported OK")

ok=True
def check(n,c,i=""):
    global ok; ok&=bool(c); print(("PASS " if c else "FAIL ")+n,i)

# ---- ladder pure function ----
fee=bot.TAKER_FEE_PCT/100*2
st,sl=bot.halving_ladder_target_sl(100.0,110.0,True,0.40,fee,0); check("لانگ: زیر ۵۰٪ هیچ‌کاری نمی‌کند", st is None)
st,sl=bot.halving_ladder_target_sl(100.0,110.0,True,0.55,fee,0); check("لانگ ۵۵٪ → پله ۱، SL کمی بالای ورود", st==1 and 100<sl<101, sl)
st2,sl2=bot.halving_ladder_target_sl(100.0,110.0,True,0.80,fee,1); check("لانگ ۸۰٪ → پله ۲، SL=۱۰۵", st2==2 and abs(sl2-105)<1e-9, sl2)
st3,_=bot.halving_ladder_target_sl(100.0,110.0,True,0.80,fee,2); check("پله‌ی انجام‌شده تکرار نمی‌شود", st3 is None)
st4,sl4=bot.halving_ladder_target_sl(100.0,90.0,False,0.80,fee,0); check("شورت ۸۰٪ → پله ۲، SL=۹۵", st4==2 and abs(sl4-95)<1e-9, sl4)
st5,sl5=bot.halving_ladder_target_sl(100.0,90.0,False,0.55,fee,0); check("شورت ۵۵٪ → پله ۱، SL کمی زیر ورود", st5==1 and 99<sl5<100, sl5)

# ---- apply function on a paper position ----
msgs=[]
bot.send_message=lambda *a,**k: msgs.append(a[1] if len(a)>1 else '')
s={'halving_ladder_enabled':True}
p={'entry_price':100.0,'tp':110.0,'sl':97.0,'side':'BUY (Long)','symbol':'XUSDT','margin':50,'leverage':5,'is_real':False}
r=bot._apply_halving_ladder(1,s,p,106.0,105.5); check("apply: پله ۱ اعمال شد", r and p['ladder_stage']==1 and p['sl']>100, p['sl'])
r=bot._apply_halving_ladder(1,s,p,106.0,105.5); check("apply: تکراری اعمال نمی‌شود", not r)
r=bot._apply_halving_ladder(1,s,p,108.0,107.0); check("apply: پله ۲ اعمال شد (SL=۱۰۵)", r and p['ladder_stage']==2 and abs(p['sl']-105)<1e-9, p['sl'])
p2={'entry_price':100.0,'tp':110.0,'sl':97.0,'side':'BUY (Long)','symbol':'XUSDT','margin':50,'leverage':5,'is_real':False}
r=bot._apply_halving_ladder(1,s,p2,108.0,104.0); check("apply: قیمت برگشته زیر SL جدید → ثبت نمی‌شود", (not r) and p2.get('ladder_stage',0)==0 and p2['sl']==97.0)
s_off={'halving_ladder_enabled':False}
p3=dict(p2); r=bot._apply_halving_ladder(1,s_off,p3,108.0,107.0); check("خاموش: کاری نمی‌کند", not r)

check("registry: halving_ladder", bot._filter_info('halving_ladder')[0].startswith('نردبان'))
print("\nALL PASS" if ok else "\nSOME FAILED")
