import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np
W=os.path.join(BASE,'work','')
Q=pd.read_parquet(W+'q15_units.parquet'); P=Q[Q.enduse!='Temp'].copy()
day=pd.read_csv(W+'day_table.csv',parse_dates=['date']).set_index('date')
P['date']=P.ts.dt.normalize(); P=P[P.date.map(day.working)==True]
B=P.groupby('ts').v.sum().rename('kW')
tod=B.index.hour*60+B.index.minute
def win(m):  # interval-start minute
    if 7*60+30<=m<9*60: return 'AM start-up'
    if 12*60+45<=m<14*60+15: return 'PM restart'
    return 'other'
S=pd.DataFrame({'kW':B,'win':[win(m) for m in tod],'tou_onpeak':(tod>=9*60)&(tod<22*60)})
S['month']=S.index.to_period('M')
rows=[]
for mth,g in S.groupby('month'):
    a=g.kW.idxmax(); b=g[g.tou_onpeak].kW.idxmax()
    dmx=g.groupby(g.index.normalize()).apply(lambda x: pd.Series({'am':x[x.win=='AM start-up'].kW.max(),'pm':x[x.win=='PM restart'].kW.max()}))
    rows.append(dict(month=str(mth),working_days=g.index.normalize().nunique(),
        peak_any_kW=round(g.kW.max(),1),peak_any_time=a.strftime('%d %b %H:%M'),peak_any_event=g.loc[a,'win'],
        peak_TOU_kW=round(g[g.tou_onpeak].kW.max(),1),peak_TOU_time=b.strftime('%d %b %H:%M'),peak_TOU_event=g.loc[b,'win'],
        avg_kW=round(g.kW.mean(),1), avg_occupied_kW=round(g.between_time('08:00','18:00').kW.mean(),1),
        pct_days_PM_gt_AM=round(100*(dmx.pm>dmx.am).mean()),med_AM_peak=round(dmx.am.median(),1),med_PM_peak=round(dmx.pm.median(),1)))
M=pd.DataFrame(rows); M['peak_to_avg']=(M.peak_any_kW/M.avg_kW).round(2)
pd.set_option('display.width',250); print(M.to_string())
M.to_csv(W+'monthly_peaks.csv',index=False)
# shares at each month's peak interval (any-time peak)
sh=[]
for _,r in M.iterrows():
    for col in ('peak_any','peak_TOU'):
        t=pd.Timestamp(f"{r[col+'_time']} {r.month[:4]}",) if False else None
for mth,g in S.groupby('month'):
    for kind,gg in (('any',g),('TOU',g[g.tou_onpeak])):
        t=gg.kW.idxmax(); x=P[P.ts==t]
        tot=x.v.sum()
        for (fl,eu),v in x.groupby(['floor','enduse']).v.sum().items():
            sh.append(dict(month=str(mth),peak=kind,ts=t,floor=fl,enduse=eu,kW=v,share=v/tot))
        for (fl,z),v in x[x.enduse=='AC'].groupby(['floor','zone']).v.sum().items():
            sh.append(dict(month=str(mth),peak=kind,ts=t,floor=fl,zone=z,enduse='AC_zone',kW=v,share=v/tot))
SH=pd.DataFrame(sh); SH.to_csv(W+'peak_shares.csv',index=False)
e=SH[SH.enduse.isin(['AC','Light','Plug'])].groupby(['peak','month','enduse']).share.sum().unstack().round(3)
print(e); print(e.groupby('peak').mean().round(3))
z=SH[SH.enduse=='AC_zone'].groupby(['peak','floor','zone']).kW.mean().round(1); print(z.unstack())
