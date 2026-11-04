import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np, holidays
W=os.path.join(BASE,'work','')
th=holidays.TH(years=[2018,2019],language='en_US')
Q=pd.read_parquet(W+'q15_units.parquet'); P=Q[Q.enduse!='Temp']
dq=pd.read_parquet(W+'floor_dq.parquet')
B=P.groupby('ts').v.sum(min_count=1)  # building F3-7 15-min kW
day=pd.DataFrame({'kWh':B.groupby(B.index.date).sum()/4})
AC=P[P.enduse=='AC'].groupby('ts').v.sum(); day['AC_kWh']=AC.groupby(AC.index.date).sum()/4
# AC on-hours: 15-min intervals with building AC > 20 kW
day['AC_on_h']=(AC>20).groupby(AC.index.date).sum()/4
day.index=pd.to_datetime(day.index); day.index.name='date'
mm=dq.pivot(index='date',columns='floor',values='major_miss_pct')
day['worst_floor_miss_pct']=mm.max(axis=1); day['floors_ok']=(mm<=5).sum(axis=1)
day['weekday']=day.index.dayofweek<5
day['holiday']=[th.get(x.date()) for x in day.index]
# Chula calendar (2019: chula.ac.th/en/news/18302; AY2018 dates ASSUMED to follow same pattern -> flagged)
def term(dt):
    d=dt.date(); import datetime as D
    t=lambda s: D.date.fromisoformat(s)
    if t('2019-08-13')<=d<=t('2019-11-29'): return 'teaching'
    if t('2019-12-02')<=d<=t('2019-12-17'): return 'exam'
    if t('2018-08-13')<=d<=t('2018-11-30'): return 'teaching'   # assumed
    if t('2018-12-03')<=d<=t('2018-12-18'): return 'exam'       # assumed
    if t('2019-01-07')<=d<=t('2019-05-03'): return 'teaching'   # assumed (AY2018 sem 2)
    if t('2019-05-06')<=d<=t('2019-05-21'): return 'exam'       # assumed
    if t('2019-06-03')<=d<=t('2019-07-19'): return 'summer'     # assumed
    return 'break'
day['chula_term']=[term(x) for x in day.index]
day['gappy']=day.worst_floor_miss_pct>5
wk=day.weekday&day.holiday.isna()&~day.gappy
med=day[wk].groupby(day[wk].index.to_period('M')).kWh.transform('median')
day['near_empty']=False
day.loc[wk,'near_empty']=(day.loc[wk,'kWh']<0.6*med)|(day.loc[wk,'AC_on_h']<4)
day['working']=wk&~day.near_empty
day['set']=np.where(day.index.year==2019,'train_2019','holdout_2018')
day.to_csv(W+'day_table.csv')
for y in (2018,2019):
    s=day[day.index.year==y]; wd=s.weekday
    print(y,'calendar days',len(s),'| weekdays',wd.sum(),'| holidays on weekdays',(wd&s.holiday.notna()).sum(),
      '| gappy weekdays',(wd&s.holiday.isna()&s.gappy).sum(),'| near-empty',s.near_empty.sum(),'| WORKING',s.working.sum())
print(day[day.near_empty][['kWh','AC_on_h','chula_term']])
print(day[day.working].groupby(day[day.working].index.to_period('M')).size())
