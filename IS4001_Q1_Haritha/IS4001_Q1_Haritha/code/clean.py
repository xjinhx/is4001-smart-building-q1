import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np, holidays, json
W=os.path.join(BASE,'work','')
log=[]; days=[]
for y in (2018,2019):
  for f in range(3,8):
    d=pd.read_parquet(f'{W}F{f}_{y}.parquet')
    raw_missing=d.isna()
    for c in d.columns:
        s=d[c]
        if c.endswith('_T'):
            bad=(s<15)|(s>40); kind='T_range'
        elif '_AC' in c:
            q=s.quantile(.9999); nb=pd.concat([s.shift(1),s.shift(-1)],axis=1).max(axis=1)
            bad=(s>1.25*q)&(s>1.5*nb); kind='AC_isolated'
        else:
            q=s.quantile(.999); rm=s.rolling(31,center=True,min_periods=5).median()
            bad=(s>3*q)&(s>3*rm+0.5); kind='LP_spike'
        bad=bad.fillna(False); n=int(bad.sum())
        if n: log.append(dict(year=y,floor=f,col=c,rule=kind,n=n))
        s=s.mask(bad)
        lim=30 if c.endswith('_T') else 15
        d[c]=s.interpolate(limit=lim,limit_area='inside')
    d.to_parquet(f'{W}C_F{f}_{y}.parquet')
    kw=[c for c in d.columns if not c.endswith('_T')]
    work=d.between_time('06:00','19:00')
    q=pd.DataFrame({'miss_pct':work[kw].isna().any(axis=1).groupby(work.index.date).mean()*100})
    for eu,pat in (('AC','_AC'),('Light','_Light'),('Plug','_Plug')):
        cols=[c for c in kw if pat in c]
        q[f'{eu}_kWh']=d[cols].sum(axis=1,min_count=1).groupby(d.index.date).sum()/60
    q['floor']=f; q['year']=y; days.append(q)
pd.DataFrame(log).to_csv(W+'spike_log.csv',index=False)
D=pd.concat(days).rename_axis('date').reset_index(); D['date']=pd.to_datetime(D['date'])
D.to_parquet(W+'floor_days.parquet')
L=pd.DataFrame(log); print(L.groupby(['year','floor']).n.sum()); print('total spikes',L.n.sum()); print(L.groupby('rule').n.sum())
