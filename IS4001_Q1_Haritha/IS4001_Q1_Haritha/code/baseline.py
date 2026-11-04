import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np, statsmodels.formula.api as smf
W=os.path.join(BASE,'work','')
Q=pd.read_parquet(W+'q15_units.parquet'); P=Q[Q.enduse!='Temp']
day=pd.read_csv(W+'day_table.csv',parse_dates=['date']).set_index('date')
wx=pd.read_csv(W+'weather_hourly.csv',parse_dates=['ts']).set_index('ts')
B=P.groupby('ts').v.sum(min_count=1).rename('kW').to_frame()
H=B.resample('h').mean().join(wx)
H['date']=H.index.normalize(); H=H.join(day[['working','chula_term','set']],on='date')
H=H[H.working==True].copy()
H['hour']=H.index.hour; H['dow']=H.index.dayofweek; H['occ']=((H.hour>=8)&(H.hour<18)).astype(int)
H['term']=(H.chula_term.isin(['teaching','exam'])).astype(int)
f='kW ~ C(hour) + C(dow) + out_temp_C:C(occ) + out_rh_pct:C(occ) + term:C(occ)'
tr=H[H.set=='train_2019']; te=H[H.set=='holdout_2018']
m=smf.ols(f,tr).fit()
def g14(y,yh,p):
    n=len(y); r=y-yh
    return dict(n_hours=n, NMBE_pct=100*r.sum()/((n-p)*y.mean()), CVRMSE_pct=100*np.sqrt((r**2).sum()/(n-p))/y.mean(), R2=1-(r**2).sum()/((y-y.mean())**2).sum())
p=len(m.params)
res={'train_2019':g14(tr.kW,m.predict(tr),p),'holdout_2018':g14(te.kW,m.predict(te),1)}
for k,v in res.items(): print(k,{a:round(b,2) for a,b in v.items()})
# occupied-hours only check (where the decision lives)
for nm,d in (('train_2019',tr),('holdout_2018',te)):
    o=d[d.occ==1]; print(nm,'occupied hrs', {a:round(b,2) for a,b in g14(o.kW,m.predict(o),1).items()})
print(m.params.filter(like='temp').round(2), m.params.filter(like='term').round(2))
H['baseline_kW']=m.predict(H)
H[['kW','baseline_kW','out_temp_C','out_rh_pct','chula_term','set']].to_csv(W+'baseline_hourly.csv')
pd.DataFrame(res).T.to_csv(W+'g14_results.csv')
open(W+'baseline_summary.txt','w').write(m.summary().as_text())
