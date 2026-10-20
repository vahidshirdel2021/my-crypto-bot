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
  gate_on=lambda s,k:False, USER_SESSIONS={}, ASSIST_SHADOW_HORIZON_SECONDS=86400, _assist_queue_signal=lambda *a,**k:(calls.append(('assist',a[5],a[3],k)) or 'assist_sent'))
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
g['fav_confirm_tick'](1); print(rec['status'],rec.get('overran')); assert rec['status']=='waiting' and rec.get('overran') is True
# pullback into band -> confirm (after having overrun)
state['df']=mkdf([100.0,100.5,100.2,100.2]); state['live']=100.2
g['fav_confirm_tick'](1); print(rec['status']); assert rec['status']=='opened'
# overrun and never returns -> timeout with why=overrun
S['fav_wait']={}; S['fav_wait_seen']={}
g['_fav_confirm_hold'](1,'OVR','BUY',plan,100,99,102,'r'); rec=list(S['fav_wait'].values())[0]
state['df']=mkdf([100.0,100.6,100.6]); state['live']=100.7
g['fav_confirm_tick'](1); assert rec['status']=='waiting'
rec['expires_at']=now-1
g['fav_confirm_tick'](1); print(rec['status'],rec.get('why')); assert rec['status']=='expired' and rec['why']=='overrun'
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
# ---- V3.44.23: رد شدن در صف تایید => رفتن به لیست انتظار در جهت مخالف (فقط یک بار) ----
flips=[]
g['_touch_register']=lambda chat_id,symbol,sig,reason,tf,plan=None,flip_from=None:(flips.append((symbol,sig,reason,tf,flip_from)) or ('touch_wait','ok'))
S['assist_mode_enabled']=False
def newrec(sym,sig,e,sl,tp):
    S['fav_wait']={}; S['fav_wait_seen']={}
    g['_fav_confirm_hold'](1,sym,sig,plan,e,sl,tp,'HVL=100.0 SCN=2'); return list(S['fav_wait'].values())[0]
# 1) خلاف جهت رفت (cancel با قیمت لحظه‌ای) => برعکس
flips.clear(); rec=newrec('F1','BUY',100,99,102)
state['df']=mkdf([100,100,100]); state['live']=99.4
g['fav_confirm_tick'](1); assert rec['status']=='cancelled' and flips and flips[0][:2]==('F1','SELL') and flips[0][4]=='BUY' and 'معکوس‌شده' in flips[0][2] and 'HVL=100.0' in flips[0][2], flips
# 2) رسیدن به TP => برعکس نمی‌شود
flips.clear(); rec=newrec('F2','BUY',100,99,102)
state['df']=mkdf([100,100,100]); state['live']=102.1
g['fav_confirm_tick'](1); assert rec['status']=='cancelled' and not flips
# 3) مهلت تمام شد و تایید نگرفت (حرکت نکرد) => برعکس
flips.clear(); rec=newrec('F3','SELL',100,101,98); rec['expires_at']=now-1
state['df']=mkdf([100,100,100]); state['live']=100.0
g['fav_confirm_tick'](1); assert rec['status']=='expired' and flips and flips[0][:2]==('F3','BUY')
# 4) ورود دیرهنگام (overrun به نفع سیگنال) => برعکس نمی‌شود
flips.clear(); rec=newrec('F4','BUY',100,99,102)
state['df']=mkdf([100.0,100.6,100.6]); state['live']=100.7
g['fav_confirm_tick'](1); rec['expires_at']=now-1; g['fav_confirm_tick'](1)
assert rec['status']=='expired' and rec['why']=='overrun' and not flips
# 5) سیگنالی که خودش برعکس‌شده بود دوباره برعکس نمی‌شود
flips.clear(); S['fav_wait']={}; S['fav_wait_seen']={}
g['_fav_confirm_hold'](1,'F5','SELL',plan,100,101,98,'🔁 معکوس‌شده از صف تایید حرکت | HVL=100.0'); rec=list(S['fav_wait'].values())[0]
state['df']=mkdf([100,100,100]); state['live']=101.2
g['fav_confirm_tick'](1); assert rec['status']=='cancelled' and not flips
# 6) کلید محیطی خاموش
flips.clear(); g['FAV_REVERSE_TO_TOUCH']=False; rec=newrec('F6','BUY',100,99,102)
state['df']=mkdf([100,100,100]); state['live']=99.4
g['fav_confirm_tick'](1); assert rec['status']=='cancelled' and not flips
g['FAV_REVERSE_TO_TOUCH']=True
print('flip to touch OK')
# ---- V3.44.26: هر سیگنال صف تایید حرکت یک کارت مستقل (⚡ ورود سریع + 📈 TradingView کنار هم) ----
import threading
tgc=[]; qt=[]
def _tg(m,pl=None,t=10):
    tgc.append((m,pl)); return {'ok':True,'result':{'message_id':len(tgc)+500}}
g.update(tg=_tg, is_allowed=lambda c:True, TF_DISPLAY={'5min':'5م','15min':'15م'}, tradingview_chart_url=lambda sym,tf:f'https://tv/{sym}/{tf}',
         miniapp_chart_url=lambda sym,tf:None, _CB_CTX=threading.local(),
         quick_channel_trade=lambda c,sym,side,skip_trend=False:(qt.append((sym,side)) or S['paper_positions'].append({'symbol':sym})))
S['fav_wait']={}; S['fav_wait_seen']={}; S['paper_positions']=[]; sent.clear(); flips.clear()
g['FAV_REVERSE_TO_TOUCH']=False
for i,(sym,sg) in enumerate([('AAA','BUY'),('BBB','SELL'),('CCC','BUY')]):
    g['_fav_confirm_hold'](1,sym,sg,plan,100,99 if sg=='BUY' else 101,102 if sg=='BUY' else 98,'HVL=100.0'); time.sleep(0.01)
state['live']=100.0
g['fav_queue_list'](1)
cards=[(m,p) for m,p in tgc if m=='sendMessage']
assert len(cards)==3, len(cards)
assert [re.search(r'`([A-Z]{3})`',p['text']).group(1) for m,p in cards]==['AAA','BBB','CCC']     # قدیمی‌تر اول، جدیدترین آخر
for m,p in cards:
    kb=p['reply_markup']['inline_keyboard']; sym=re.search(r'`([A-Z]{3})`',p['text']).group(1)
    assert len(kb[0])==2 and kb[0][0]['callback_data'].startswith('/fq_qe_') and kb[0][1]['url'].startswith(f'https://tv/{sym}/'), kb
    assert any(b.get('callback_data','').startswith('/fq_ref_') for row in kb for b in row)
    assert ('خرید' if kb[0][0]['callback_data'].startswith('/fq_qe_buy') else 'فروش') in kb[0][0]['text'] and sym in kb[0][0]['text']
# لمس دوباره‌ی لیست: کارت قبلیِ هر سیگنال پاک می‌شود، تکراری نمی‌ماند
tgc.clear(); g['fav_queue_list'](1)
assert len([1 for m,p in tgc if m=='deleteMessage'])==3 and len([1 for m,p in tgc if m=='sendMessage'])==3
# ورود سریع روی BBB (فروش)
rb=[r for r in S['fav_wait'].values() if r['symbol']=='BBB'][0]
tgc.clear(); g['fav_quick_entry'](1,rb['id'],'SELL')
assert qt==[('BBB','SELL')] and rb['status']=='entered_manual'
ed=[p for m,p in tgc if m=='editMessageText']; assert ed and ed[-1]['reply_markup']['inline_keyboard']==[] and 'ورود سریع دستی' in ed[-1]['text']
# مورد تمام‌شده
sent.clear(); g['fav_quick_entry'](1,rb['id'],'SELL'); assert 'دیگر در صف نیست' in sent[-1]
# پایان خودکار (لغو) کارت را درجا می‌بندد
ra=[r for r in S['fav_wait'].values() if r['symbol']=='AAA'][0]
tgc.clear(); state['df']=mkdf([100,100,100]); state['live']=99.4
g['fav_confirm_tick'](1)
assert ra['status']=='cancelled' and any(m=='editMessageText' and 'لغو شد' in p['text'] for m,p in tgc)
# 🔄 همان کارت را ویرایش می‌کند
rc=[r for r in S['fav_wait'].values() if r['symbol']=='CCC'][0]
g['_CB_CTX'].data={'chat_id':1,'message_id':777,'used':False,'cmd':'/fq_ref_x'}
tgc.clear(); g['fav_card_refresh'](1,rc['id'])
assert rc['fq_msg_id']==777 and g['_CB_CTX'].data['used'] and tgc and tgc[-1][0]=='editMessageText' and tgc[-1][1]['message_id']==777
# ---- V3.44.27: دکمه‌ی ⏳ تمدید مهلت؛ هر لمس ۳۰ دقیقه به مهلت همان سیگنال اضافه می‌کند ----
assert g['FAV_EXTEND_SECONDS']==1800
state['live']=100.0; g['_fav_confirm_hold'](1,'DDD','BUY',plan,100,99,102,'HVL=100.0'); rc=[r for r in S['fav_wait'].values() if r['symbol']=='DDD'][0]
kb=g['_fav_card_payload'](rc)[1]['inline_keyboard']
assert any(b.get('callback_data')==f"/fq_ext_{rc['id']}" and '30' in b['text'] for row in kb for b in row), kb
e0=float(rc['expires_at']); g['_CB_CTX'].data={'chat_id':1,'message_id':778,'used':False,'cmd':'/fq_ext_x'}
tgc.clear(); g['fav_extend'](1,rc['id'])
assert abs(float(rc['expires_at'])-(e0+1800))<1 and rc['ext']==1 and rc['fq_msg_id']==778 and tgc and tgc[-1][0]=='editMessageText'
g['fav_extend'](1,rc['id']); assert abs(float(rc['expires_at'])-(e0+3600))<1 and rc['ext']==2      # لمس‌های پشت‌سرهم جمع می‌شوند
rc['expires_at']=time.time()-5; g['fav_extend'](1,rc['id']); assert float(rc['expires_at'])>time.time()+1700    # مهلت گذشته‌ی هنوز-منتظر از «الان» ۳۰ دقیقه می‌شود
sent.clear(); g['fav_extend'](1,rb['id']); assert 'دیگر در صف نیست' in sent[-1]                       # مورد تمام‌شده
kb=g['_fav_card_payload'](rc)[1]['inline_keyboard']
last=[b['callback_data'] for b in kb[-2]]; assert last==[f"/fq_ref_{rc['id']}", f"/fq_ext_{rc['id']}"], kb      # بروزرسانی و تمدید کنار هم
assert [b['callback_data'] for b in kb[-1]]==[f"/fq_rej_{rc['id']}", f"/fq_flt_{rc['id']}"], kb      # V3.44.38/39: ردیف آخر = ❌ رد سیگنال + 🔍 فیلترها
print('fav extend OK')
# ---- V3.44.39: دکمه‌ی 🔍 فیلترها (پنجره‌ی بازشو؛ حداکثر ۲۰۰ کاراکتر تلگرام) ----
import copy
_ALL=['btceth','h4','tf','rsi','macd','adx','vol','level','ylevel']
def _mkv(k, vote, detail): return {'key':k,'label':k,'vote':vote,'detail':detail}
_long=[_mkv('btceth','SELL','ETH نزولی، BTC نزولی'),_mkv('h4','SELL','نزولی'),_mkv('tf','SELL','5 دقیقه نزولی، 15 دقیقه نزولی'),
       _mkv('rsi','BUY','45'),_mkv('macd','SELL','منفی'),_mkv('adx',None,'ADX 18'),_mkv('vol',None,'1.2x (لازم 1.5x)'),
       _mkv('level','SELL','آخرین کلوز پایین سطح'),_mkv('ylevel','SELL','برخورد به سقف دیروز (5.9770) و عبور نکرده')]
g.update(_touch_enabled_keys=lambda s_:list(_ALL), _touch_votes=lambda sym,tf,reason,keys,ind_df=None:copy.deepcopy(_long),
         _final_regime_check=lambda tf,sig:(False,'x'), TIMEFRAME_REGIME_CACHE={'5min':{'gate':'RANGE'}},
         gate_on=lambda s_,k:True if k=='gate_final_regime_enabled' else False)
state['live']=99.9
state['df']=mkdf([100.0,99.95,99.9])
rz=[r for r in S['fav_wait'].values() if r['symbol']=='DDD'][0]
rz['sig']='SELL'; rz['entry']=100.0; rz['sl']=101.0; rz['tp']=98.0; rz['min_r']=0.3; rz['max_r']=0.38; rz['status']='waiting'; rz['created_at']=now-30
before=copy.deepcopy(rz)
txt=g['fav_filters_popup'](1,rz['id']); print(txt); print(len(txt), g['_tg_len'](txt))
assert g['_tg_len'](txt)<=200, g['_tg_len'](txt)
assert 'DDD' in txt and 'RSI' in txt and 'MACD' in txt and '✅' in txt and '❌' in txt and '⏳' in txt and 'رنج' in txt
assert rz==before, 'popup must not modify the queue record'
# فقط چند فیلتر روشن → جزئیات بیشتر (کلوز آخر و مقدارها) جا می‌شود
g['_touch_enabled_keys']=lambda s_:['rsi','macd']
g['_touch_votes']=lambda sym,tf,reason,keys,ind_df=None:[copy.deepcopy(_long[3]),copy.deepcopy(_long[4])]
g['gate_on']=lambda s_,k:False
txt=g['fav_filters_popup'](1,rz['id']); print(txt)
assert 'کلوز آخر' in txt and 'RSI 45' in txt and g['_tg_len'](txt)<=200
# هیچ فیلتری روشن نیست
g['_touch_enabled_keys']=lambda s_:[]
txt=g['fav_filters_popup'](1,rz['id']); print(txt); assert 'فیلتر دیگری روشن نیست' in txt
# مورد تمام‌شده
rz['status']='expired'; assert 'دیگر در صف نیست' in g['fav_filters_popup'](1,rz['id']); assert 'دیگر در صف نیست' in g['fav_filters_popup'](1,'nope')
print('fav filters popup OK')
print('fav independent cards OK')
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
