import os, sys, numpy as np, pandas as pd
os.environ.setdefault('TELEGRAM_BOT_TOKEN','123:abc')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bot, halving_levels as hv
ok=True
def check(n,c,i=""):
    global ok; ok&=bool(c); print(("PASS " if c else "FAIL ")+n,i)

H,L=126148.0,2816.0
D=8; step=(H-L)/2**D
level=L+int((83400-L)/step+1)*step
rng=np.random.default_rng(7); n=700
ts0=pd.Timestamp("2026-10-05 00:00",tz="UTC")
close=83000+np.cumsum(rng.normal(0,55,n)); close=close-(close[-3]-(level-60))
rows=[]
for i in range(n):
    c=close[i]; o=close[i-1] if i else c
    rows.append([int((ts0+pd.Timedelta(minutes=5*i)).timestamp()*1000),o,max(o,c)+abs(rng.normal(0,40)),min(o,c)-abs(rng.normal(0,40)),c,100+abs(rng.normal(0,10))])
df=pd.DataFrame(rows,columns=["timestamp","open","high","low","close","volume"])
df.loc[n-2,["open","high","low","close"]]=[level-70,level+45,level-130,level-115]; df.loc[n-2,"volume"]=220
df.loc[n-1,["open","high","low","close"]]=[level-115,level-55,level-125,level-70]

bot.get_klines=lambda symbol,tf,limit=200: df.copy()
bot.get_halving_range_sync=lambda symbol:(H,L)
bot._SIGNAL_CHANNEL_PATTERNS=['rejection','touch']
bot._SIGNAL_CHANNEL_LEVEL_TAGS=['Daily']
bot.SIGNAL_CHANNEL_TF_CHAT_ID=1
bot.USER_SESSIONS[1]={'timeframe':'5min','strategy_config':{'halving_model_enabled':True,'halving_k_atr':3.0,'halving_max_depth':10}}

hits=bot._signal_channel_touch_scan_symbol('BTCUSDT','5min')
print("hits (halving ON):",[(h[0],h[1],round(h[2],2),h[4]) for h in hits])
check("کانال: حداقل یک سیگنال روی سطوح نصف‌کردن", len(hits)>0)
check("کانال: همه‌ی تگ‌ها نصف‌کردن‌اند (نه Daily و ...)", all(h[0] in bot._HV_CH_TAGS for h in hits))
levels_all=[x['price'] for x in hv.levels_near(H,L,10,level-6000,level+6000)]
check("کانال: قیمت هر سیگنال روی یک سطح درخت است", all(any(abs(h[2]-x)<1e-6*x for x in levels_all) for h in hits))
hit_lvl=[h for h in hits if abs(h[2]-level)<1e-6*level]
check("کانال: سطح ۸۳٬۵۵۲ (عمق ۸ در این رنج) تشخیص داده شد", len(hit_lvl)>0, round(level,2))
if hit_lvl:
    d_=bot._HV_CH_DEPTH.get(('BTCUSDT',f"{level:.10g}")); print("depth label:",bot._hv_depth_label(d_))

# range missing -> no signals (not fallback to old levels)
bot.get_halving_range_sync=lambda symbol:None
check("بدون سقف/کف: کانال به سطوح قدیمی برنمی‌گردد", bot._signal_channel_touch_scan_symbol('BTCUSDT','5min')==[])
bot.get_halving_range_sync=lambda symbol:(H,L)

# halving OFF -> old behavior, no HV tags
bot.USER_SESSIONS[1]['strategy_config']['halving_model_enabled']=False
hits_off=bot._signal_channel_touch_scan_symbol('BTCUSDT','5min')
check("خاموش: هیچ تگ نصف‌کردنی ظاهر نمی‌شود", all(h[0] not in bot._HV_CH_TAGS for h in hits_off), [h[0] for h in hits_off])
bot.USER_SESSIONS[1]['strategy_config']['halving_model_enabled']=True

# quick plan targets
cfg=bot._signal_channel_halving_cfg_for('BTCUSDT','5min')
plan,_=bot.build_quick_plan_with_fallback('BTCUSDT','SELL',cfg,level-70,'5min')
print("quick plan:",{k:plan[k] for k in ('sl','tp','rr','tp_level_name')})
check("پلن کانال: هدف از سطح نصف‌کردن است", 'نصف‌کردن' in plan['tp_level_name'])
# user quick trade path: session cfg without range -> injected automatically
plan2,_=bot.build_quick_plan_with_fallback('BTCUSDT','SELL',{'halving_model_enabled':True,'halving_k_atr':3.0},level-70,'5min')
check("ورود سریع کاربر: هدف از سطح نصف‌کردن است", 'نصف‌کردن' in plan2['tp_level_name'], plan2['tp_level_name'])

# keyboard (exit section) with mocked session
bot.get_session=lambda cid:{'profit_lock_enabled':False,'swing_trailing_enabled':True,'halving_ladder_enabled':True,'strategy_config':{}, 'filters':{}}
try:
    kb=bot.trade_filter_management_keyboard(1,'exit')
    cbs=[r[0]['callback_data'] for r in kb['inline_keyboard']]
    print("exit keyboard:",cbs)
    check("منوی خروج: دکمه‌ی نردبان سود هست", '/toggle_halving_ladder' in cbs)
except Exception as e:
    import traceback; traceback.print_exc(); ok=False
print("\nALL PASS" if ok else "\nSOME FAILED")
