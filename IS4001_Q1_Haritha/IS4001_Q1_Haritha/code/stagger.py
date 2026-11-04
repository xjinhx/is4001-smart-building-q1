import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np, itertools
W=os.path.join(BASE,'work','')
day=pd.read_csv(W+'day_table.csv',parse_dates=['date']).set_index('date')
wd=day[day.working].index
# minute-level zone AC + non-AC per floor for window 11:30-15:30 on working days
LO,HI=pd.Timedelta('11:30:00'),pd.Timedelta('15:30:00'); n=int((HI-LO)/pd.Timedelta('1min'))
zones=[]; ac={}; other={}
for y in (2018,2019):
  for f in range(3,8):
    d=pd.read_parquet(f'{W}C_F{f}_{y}.parquet')
    kw=[c for c in d.columns if not c.endswith('_T')]
    for z in sorted({int(c[1]) for c in d.columns if '_AC' in c}):
        if (f,z) not in zones: zones.append((f,z))
        s=d[[c for c in kw if c.startswith(f'z{z}_AC')]].sum(axis=1,min_count=1)
        for dt in wd[wd.year==y]: ac[(dt,f,z)]=s.loc[dt+LO:dt+HI-pd.Timedelta('1min')].to_numpy()
    nac=d[[c for c in kw if '_AC' not in c]].sum(axis=1,min_count=1)
    for dt in wd[wd.year==y]: other[(dt,f)]=nac.loc[dt+LO:dt+HI-pd.Timedelta('1min')].to_numpy()
# whole-building 15-min series outside the window (for TOU peak elsewhere in the day)
Q=pd.read_parquet(W+'q15_units.parquet'); P=Q[Q.enduse!='Temp']; B=P.groupby('ts').v.sum()
tod=B.index.hour*60+B.index.minute; tou=(tod>=540)&(tod<1320); inwin=(tod>=690)&(tod<930)
outside=B[tou&~inwin].groupby(B[tou&~inwin].index.normalize()).max()
days=[dt for dt in wd if all(np.isfinite(ac[(dt,f,z)]).all() for f,z in zones) and dt in outside.index]
A=np.stack([np.stack([ac[(dt,f,z)] for f,z in zones]) for dt in days])        # D x Z x n
O=np.stack([sum(other[(dt,f)] for f in range(3,8)) for dt in days])            # D x n
O=np.nan_to_num(O); OUT=outside.reindex(days).to_numpy()
steady=np.nanmedian(A[:,:,int((pd.Timedelta('14:15:00')-LO).total_seconds()//60):int((pd.Timedelta('14:45:00')-LO).total_seconds()//60)],axis=(0,2))
months=np.array([d.to_period('M') for d in days]); year=np.array([d.year for d in days])
def shift(x,k):   # x: D x n ; k>0 delay
    if k==0: return x
    y=np.empty_like(x)
    if k>0: y[:,k:]=x[:,:-k]; y[:,:k]=x[:,:1]
    else: y[:,:k]=x[:,-k:]; y[:,k:]=x[:,-1:]
    return y
def day_peaks(offs):
    tot=O.copy()
    for j,k in enumerate(offs): tot=tot+shift(A[:,j,:],k)
    q=tot.reshape(len(days),n//15,15).mean(axis=2)          # clock-aligned 15-min
    return np.maximum(q.max(axis=1),OUT)
def billing(pk,mask):  # mean of monthly maxima
    s=pd.Series(pk[mask],index=months[mask]); return s.groupby(level=0).max()
base=day_peaks([0]*len(zones))
tr=year==2019; te=year==2018
print('days',len(days),'train',tr.sum(),'holdout',te.sum(),'zones',len(zones))
fl=sorted({f for f,_ in zones})
def kwh(offs): return -sum(k*steady[j] for j,k in enumerate(offs))/60   # + = extra kWh per day
best=[]
opts=[-10,-5,0,5,10]
for combo in itertools.product(opts,repeat=len(fl)):
    offs=[combo[fl.index(f)] for f,z in zones]
    if kwh(offs)>0: continue
    m=billing(day_peaks(offs),tr).mean(); best.append((m,combo))
best.sort(); b0=billing(base,tr).mean()
print('baseline mean monthly peak 2019',round(b0,1))
for m,c in best[:5]: print(dict(zip(fl,c)), round(m,1), round(b0-m,1))
# zone-level local search starting from best floor combo
cur=[best[0][1][fl.index(f)] for f,z in zones]; curv=best[0][0]
zopts=[-10,-5,0,5,10]
improved=True
while improved:
    improved=False
    for j in range(len(zones)):
        for k in zopts:
            t=cur.copy(); t[j]=k
            if kwh(t)>0: continue
            v=billing(day_peaks(t),tr).mean()
            if v<curv-0.05: cur,curv,improved=t,v,True
sched=pd.DataFrame({'floor':[f for f,z in zones],'zone':[z for f,z in zones],'offset_min':cur,'steady_kW':steady.round(1)})
print(sched.pivot(index='floor',columns='zone',values='offset_min'))
pk=day_peaks(cur)
res=pd.DataFrame({'month':[str(x) for x in billing(base,np.ones(len(days),bool)).index],
  'today_kW':billing(base,np.ones(len(days),bool)).values,'staggered_kW':billing(pk,np.ones(len(days),bool)).values})
res['cut_kW']=res.today_kW-res.staggered_kW; res['cut_pct']=100*res.cut_kW/res.today_kW
print(res.round(1).to_string()); print('kWh/day change',round(kwh(cur),1))
# bootstrap by day within month (train & holdout)
rng=np.random.default_rng(1); bs={'train_2019':[],'holdout_2018':[]}
for _ in range(1000):
    for nm,mask in (('train_2019',tr),('holdout_2018',te)):
        idx=np.where(mask)[0]; s=[]
        for mth in np.unique(months[idx]):
            ii=idx[months[idx]==mth]; pick=rng.choice(ii,len(ii))
            s.append(base[pick].max()-pk[pick].max())
        bs[nm].append(np.mean(s))
for k,v in bs.items(): print(k,'mean monthly cut kW',round(np.mean(v),1),'95% CI',np.percentile(v,[2.5,97.5]).round(1))
sched.to_csv(W+'stagger_schedule.csv',index=False); res.to_csv(W+'stagger_monthly.csv',index=False)
pd.DataFrame(bs).to_csv(W+'stagger_bootstrap.csv',index=False)
np.save(W+'stagger_base_pk.npy',base); np.save(W+'stagger_new_pk.npy',pk)
pd.Series([str(d.date()) for d in days]).to_csv(W+'stagger_days.csv',index=False)
# average profile for chart
tot0=O+A.sum(axis=1); tot1=O+sum(shift(A[:,j,:],k) for j,k in enumerate(cur))
pd.DataFrame({'minute':pd.timedelta_range(LO,periods=n,freq='min').astype(str),'today_kW':np.nanmedian(tot0[tr],axis=0),'staggered_kW':np.nanmedian(tot1[tr],axis=0)}).to_csv(W+'stagger_profile.csv',index=False)

# --- robustness: floor-level schedule vs zone-level, and what binds after stagger
fbest=[best[0][1][fl.index(f)] for f,z in zones]
for nm,offs in (('floor-level',fbest),('zone-level',cur)):
    p=day_peaks(offs)
    for lab,mask in (('2019',tr),('2018 holdout',te)):
        print(nm,lab,'mean monthly cut',round((billing(base,mask)-billing(p,mask)).mean(),1),'kW')
p=day_peaks(cur)
for lab,mask in (('2019',tr),('2018',te)):
    s=pd.DataFrame({'pk':p[mask],'out':OUT[mask],'m':months[mask]})
    mx=s.loc[s.groupby('m').pk.idxmax()]; print(lab,'months where new peak is outside PM window:',int((mx.pk<=mx.out+1e-6).sum()),'of',len(mx))
