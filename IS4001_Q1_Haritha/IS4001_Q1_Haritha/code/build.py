import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np, holidays
W=os.path.join(BASE,'work','')
th=holidays.TH(years=[2018,2019])
q15=[]; dq=[]; imp_log=[]
for y in (2018,2019):
  for f in range(3,8):
    d=pd.read_parquet(f'{W}C_F{f}_{y}.parquet')
    if f==5: d['z1_S1_T']=np.nan   # F5 z1 sensor reads 11-15 C for long stretches: unreliable, excluded
    kw=[c for c in d.columns if not c.endswith('_T')]
    major=[c for c in kw if '_AC' in c and d[c].quantile(.999)>=5]
    minor=[c for c in kw if c not in major]
    idx=d.index; wk=(idx.dayofweek<5)&~pd.Index(idx.date).map(lambda x:x in th)
    mod=idx.hour*60+idx.minute
    for c in minor:
        miss=d[c].isna()
        if not miss.any(): continue
        s=d[c]
        prof_m=s[wk].groupby([idx[wk].month,mod[wk]]).median()
        prof_y=s[wk].groupby(mod[wk]).median()
        prof_we=s[~wk].groupby(mod[~wk]).median()
        key_m=pd.MultiIndex.from_arrays([idx.month,mod])
        fill=np.where(wk, prof_m.reindex(key_m).values, prof_we.reindex(mod).values)
        fill=np.where(np.isnan(fill)&wk, prof_y.reindex(mod).values, fill)
        d[c]=s.fillna(pd.Series(fill,index=idx))
        imp_log.append(dict(year=y,floor=f,col=c,minutes_imputed=int(miss.sum())))
    work=d.between_time('06:00','19:00')
    mm=work[major].isna().any(axis=1).groupby(work.index.date).mean()*100
    tm=d.between_time('06:00','19:00')[[c for c in d.columns if c.endswith('_T')]].isna().mean(axis=1).groupby(work.index.date).mean()*100
    dq.append(pd.DataFrame({'date':pd.to_datetime(mm.index),'floor':f,'major_miss_pct':mm.values,'temp_miss_pct':tm.values}))
    # 15-min billing interval means, clock aligned (:00,:15,:30,:45)
    g=d.resample('15min').mean()
    ok=d[kw].notna().resample('15min').sum()>=10   # need >=10 of 15 minutes
    long=[]
    for c in d.columns:
        z=int(c[1:c.index('_')]); eu='Temp' if c.endswith('_T') else ('AC' if '_AC' in c else c.split('_')[1])
        v=g[c].where(ok[c]) if c in kw else g[c]
        long.append(pd.DataFrame({'ts':g.index,'floor':f,'zone':z,'enduse':eu,'unit':c.split('_',1)[1],'v':v.values.astype('float32')}))
    q15.append(pd.concat(long))
Q=pd.concat(q15,ignore_index=True)
Q.to_parquet(W+'q15_units.parquet')
pd.concat(dq).to_parquet(W+'floor_dq.parquet')
pd.DataFrame(imp_log).to_csv(W+'impute_log.csv',index=False)
print(Q.shape); print(pd.DataFrame(imp_log).sort_values('minutes_imputed',ascending=False).head(12))
