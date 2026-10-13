import re, time, os, hashlib, logging, pandas as pd
src=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'bot.py'),encoding='utf-8').read()
a=src.index("FAV_CONFIRM_MIN_RR = float")
b=src.index("def _auto_trend_gate(")
block=src[a:b]
sent=[]; calls=[]
S={'paper_positions':[],'timeframe':'5min','trading_mode':'PAPER','fav_confirm_enabled':True}
state={'live':100.15,'df':None,'gate':False,'exec_ok':True}
g=dict(os=os,time=time,hashlib=hashlib,logger=logging.getLogger('t'),pd=pd,
  ASSIST_SEEN_TTL_SECONDS=21600,_TF_SECONDS={'5min':300},_LAST_BLOCK_REASON={},
  get_session=lambda c:S, save_session=lambda c:None, fmt=lambda v:str(v),
  extract_setup_level=lambda r:('t','L','1.0'),
  send_message=lambda c,t,*a,**k:sent.append(t),
  latest_price=lambda sym:state['live'], exchange_latest_price=lambda c,sym:state['live'],
  get_klines=lambda sym,tf,n:state['df'],
  _auto_trend_gate=lambda *a,**k:state['gate'],
  execute_trade=lambda *a,**k:(calls.append(k) or state['exec_ok']),
  USER_SESSIONS={}, ASSIST_SHADOW_HORIZON_SECONDS=86400, _assist_queue_signal=lambda *a,**k:(calls.append(('assist',a[5],a[3],k)) or 'assist_sent'))
exec(block,g)
D=g['_fav_decide']
# BUY entry 100, sl 99 (R=1), tp 102 (2R)
for px,exp in [(100.05,'wait'),(100.10,'wait'),(100.15,'confirm'),(100.30,'confirm'),(100.31,'overrun'),(99.4,'cancel'),(98.9,'cancel'),(102.0,'cancel')]:
    r=D('BUY',100,99,102,px,0.15,0.30); print('BUY',px,r); assert r==exp,(px,r,exp)
# SELL entry 100 sl 101 tp 98
for px,exp in [(99.9,'wait'),(99.85,'confirm'),(99.69,'overrun'),(100.6,'cancel')]:
    r=D('SELL',100,101,98,px,0.15,0.30); print('SELL',px,r); assert r==exp,(px,r,exp)
# TP close (1.5R): x=.3 -> rr=(1.5-.3)/1.3=.92 <1.3 -> overrun
print('rr guard', D('BUY',100,99,101.5,100.2,0.15,0.30)); assert D('BUY',100,99,101.5,100.2,0.15,0.30)=='overrun'
# hold + process flow
now=time.time()
plan={'rr':2.0}
assert g['_fav_confirm_hold'](1,'ABC','BUY',plan,100,99,102,'r')==True
rid=list(S['fav_wait'])[0]; rec=S['fav_wait'][rid]
assert g['_fav_confirm_hold'](1,'ABC','BUY',plan,100,99,102,'r')==True and len(S['fav_wait'])==1
def mkdf(closes):
    t0=now-60
    rows=[{'timestamp':t0+i*300,'close':c,'open':c,'high':c,'low':c} for i,c in enumerate(closes)]
    return pd.DataFrame(rows)
# candle1 closes 100.05 (wait), forming candle last
state['df']=mkdf([100.0,100.05,100.1]); state['live']=100.05
g['fav_confirm_tick'](1); print(rec['status']); assert rec['status']=='waiting'
# next candle close 100.2 -> confirm
state['df']=mkdf([100.0,100.05,100.2,100.2]); state['live']=100.2
g['fav_confirm_tick'](1); print(rec['status'], calls[-1].get('keep_levels')); assert rec['status']=='opened' and calls[-1]['keep_levels'] is True
# overrun case
S['fav_wait']={}; S['fav_wait_seen']={}
g['_fav_confirm_hold'](1,'XYZ','BUY',plan,100,99,102,'r'); rec=list(S['fav_wait'].values())[0]
state['df']=mkdf([100.0,100.5,100.5]); state['live']=100.5
g['fav_confirm_tick'](1); print(rec['status']); assert rec['status']=='expired'
# cancel by live SL
S['fav_wait']={}; S['fav_wait_seen']={}
g['_fav_confirm_hold'](1,'XYZ','SELL',plan,100,101,98,'r'); rec=list(S['fav_wait'].values())[0]
state['df']=mkdf([100,100,100]); state['live']=101.2
g['fav_confirm_tick'](1); print(rec['status']); assert rec['status']=='cancelled'
# timeout
S['fav_wait']={}; S['fav_wait_seen']={}
g['_fav_confirm_hold'](1,'XYZ','BUY',plan,100,99,102,'r'); rec=list(S['fav_wait'].values())[0]; rec['expires_at']=now-1
state['df']=mkdf([100,100,100]); state['live']=100.0
g['fav_confirm_tick'](1); print(rec['status']); assert rec['status']=='expired'
# disabled
S['fav_confirm_enabled']=False; assert g['_fav_confirm_hold'](1,'Q','BUY',plan,100,99,102,'r')==False
# dedup after finish within TTL
S['fav_confirm_enabled']=True
assert g['_fav_confirm_hold'](1,'XYZ','BUY',plan,100,99,102,'r')==True
# assist mode: card instead of trade
S['fav_wait']={}; S['fav_wait_seen']={}; S['assist_mode_enabled']=True; sent.clear(); calls.clear()
g['_fav_confirm_hold'](1,'AST','BUY',plan,100,99,102,'r'); rec=list(S['fav_wait'].values())[0]
state['df']=mkdf([100.0,100.2,100.2]); state['live']=100.2
g['fav_confirm_tick'](1); print(rec['status'],calls[-1][:3])
assert rec['status']=='card_sent' and calls[-1][0]=='assist' and calls[-1][1]==99 and sent==[]
# ---- shadow + stats ----
g['USER_SESSIONS'][1]=S
def mkhl(rows):
    t0=now-60
    return pd.DataFrame([{'timestamp':t0+i*300,'high':h,'low':l,'close':(h+l)/2,'open':(h+l)/2} for i,(h,l) in enumerate(rows)])
S['fav_wait']={
 # confirmed, entry 100 sl 99 tp 102, confirm at 100.2 -> then TP hit
 'c1':{'id':'c1','symbol':'A','sig':'BUY','entry':100,'sl':99,'tp':102,'status':'opened','why':'opened','created_at':now,'confirmed_at':now+300,'confirm_px':100.2,'tf':'5min'},
 # expired overrun; would have hit TP if immediate
 'e1':{'id':'e1','symbol':'B','sig':'BUY','entry':100,'sl':99,'tp':102,'status':'expired','why':'overrun','created_at':now,'tf':'5min'},
 # cancelled; would have hit SL
 'x1':{'id':'x1','symbol':'C','sig':'BUY','entry':100,'sl':99,'tp':102,'status':'cancelled','why':'cancelled','created_at':now,'tf':'5min'},
}
dfs={'A':mkhl([(100.3,99.9),(100.5,100.0),(102.1,100.4),(101,100)]),
     'B':mkhl([(100.5,99.9),(102.2,100.0),(101,100)]),
     'C':mkhl([(100.2,98.9),(100,99),(100,99)])}
g['get_klines']=lambda sym,tf,n:dfs[sym]
g['fav_shadow_once']()
for k,r in S['fav_wait'].items(): print(k,r.get('imm'),r.get('flt'),r.get('shadow_done'))
assert S['fav_wait']['c1']['imm']['outcome']=='tp' and S['fav_wait']['c1']['flt']['outcome']=='tp'
assert abs(S['fav_wait']['c1']['flt']['r']-(1.8/1.2))<1e-9 and abs(S['fav_wait']['c1']['imm']['r']-2.0)<1e-9
assert S['fav_wait']['e1']['imm']['outcome']=='tp' and S['fav_wait']['x1']['imm']['outcome']=='sl'
assert all(r['shadow_done'] for r in S['fav_wait'].values())
txt=g['fav_stats_text'](S); print(txt)
assert 'مقایسه‌ی نهایی' in txt and '\\n' not in txt
print('ALL OK')
