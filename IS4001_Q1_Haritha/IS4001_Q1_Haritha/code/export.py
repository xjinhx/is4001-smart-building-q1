import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np, shutil
W=os.path.join(BASE,'work',''); D=os.path.join(BASE,'data',''); R=os.path.join(BASE,'results','')
day=pd.read_csv(W+'day_table.csv',parse_dates=['date']).set_index('date')
wx=pd.read_csv(W+'weather_hourly.csv',parse_dates=['ts']).set_index('ts')
wx15=wx.resample('15min').interpolate()
Q=pd.read_parquet(W+'q15_units.parquet')
Q['date']=Q.ts.dt.normalize()
# zone level wide, working days only
Z=Q[Q.date.map(day.working)==True].pivot_table(index=['ts','floor','zone'],columns='enduse',values='v',aggfunc='sum',dropna=False).reset_index()
Z.columns.name=None; Z=Z.rename(columns={'AC':'AC_kW','Light':'Light_kW','Plug':'Plug_kW','Temp':'indoor_T_C'})
Z=Z.dropna(subset=['Light_kW','Plug_kW'],how='all')
Z.loc[~Z.zone.isin(Z[Z.AC_kW>0].zone.unique()) | Z.AC_kW.isna(),'AC_kW']=Z.AC_kW  # leave NaN for zone 3 (no AC)
Z=Z.join(wx15,on='ts'); Z['date']=Z.ts.dt.date; Z['set']=Z.ts.dt.year.map({2018:'holdout_2018',2019:'train_2019'})
Z=Z[['ts','date','set','floor','zone','AC_kW','Light_kW','Plug_kW','indoor_T_C','out_temp_C','out_rh_pct']]
Z.round(3).to_csv(D+'zone_15min_workingdays.csv',index=False)
# building level, all days, with flags
P=Q[Q.enduse!='Temp']
b=P.groupby(['ts','enduse']).v.sum(min_count=1).unstack().rename(columns=lambda c:c+'_kW')
f=P.groupby(['ts','floor']).v.sum(min_count=1).unstack(); f.columns=[f'F{c}_kW' for c in f.columns]
Bd=b.join(f); Bd.insert(0,'total_kW',b.sum(axis=1,min_count=1)); Bd=Bd.join(wx15)
m=Bd.index.hour*60+Bd.index.minute
Bd['tou_onpeak']=((m>=540)&(m<1320)); Bd['window']=np.select([(m>=450)&(m<540),(m>=765)&(m<855)],['AM_startup','PM_restart'],'other')
Bd['date']=Bd.index.date; dd=pd.to_datetime(Bd.date)
for c in ('working','set','chula_term','holiday'): Bd[c]=dd.map(day[c]).values
Bd.index.name='ts'; Bd.round(3).to_csv(D+'building_15min_alldays.csv')
day.to_csv(D+'day_table.csv')
wx.to_csv(D+'weather_hourly_openmeteo.csv')
E=pd.read_csv(W+'startup_events.csv'); E.loc[E.event=='AM','minutes_off_before']=np.nan
E['surge_ratio']=(E.peak_kW_first30/E.steady_kW_60_90).round(3)
E.round(3).to_csv(D+'startup_events.csv',index=False)
shutil.copy(W+'arrival_proxy.csv',D)
for fn in ('monthly_peaks.csv','peak_shares.csv','g14_results.csv','baseline_hourly.csv','stagger_schedule.csv','stagger_monthly.csv','stagger_bootstrap.csv','spike_log.csv','impute_log.csv'): shutil.copy(W+fn,R)
shutil.copy(W+'baseline_summary.txt',R)
print(len(Z),len(Bd))
