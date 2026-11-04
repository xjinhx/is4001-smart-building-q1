import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np
W=os.path.join(BASE,'work','')
day=pd.read_csv(W+'day_table.csv',parse_dates=['date']).set_index('date')
wx=pd.read_csv(W+'weather_hourly.csv',parse_dates=['ts']).set_index('ts').out_temp_C
wx_m=wx.resample('min').interpolate()
ev=[]; arr=[]
for y in (2018,2019):
  for f in range(3,8):
    d=pd.read_parquet(f'{W}C_F{f}_{y}.parquet')
    if f==5: d['z1_S1_T']=np.nan
    zones=sorted({int(c[1]) for c in d.columns if '_AC' in c})
    for z in zones:
        ac=d[[c for c in d.columns if c.startswith(f'z{z}_AC')]].sum(axis=1,min_count=1)
        T=d[f'z{z}_S1_T'] if f'z{z}_S1_T' in d else pd.Series(np.nan,index=d.index)
        on=ac>3; off=ac<1
        for dt,g in ac.groupby(ac.index.normalize()):
            if not day.loc[dt,'working']: continue
            o=on.loc[g.index]; fz=off.loc[g.index]
            # off-run length ending at each minute
            run=fz.groupby((~fz).cumsum()).cumsum()
            for ev_name,(lo,hi,minoff) in {'AM':('05:00','10:30',30),'PM':('11:45','15:00',10)}.items():
                w=o.between_time(lo,hi)
                cand=[t for t in w[w].index if run.get(t-pd.Timedelta(minutes=1),0)>=minoff]
                if not cand: continue
                t0=cand[0]; offmin=int(run.get(t0-pd.Timedelta(minutes=1),0))
                seg=g.loc[t0:t0+pd.Timedelta(minutes=29)]
                ev.append(dict(date=dt,set=day.loc[dt,'set'],floor=f,zone=z,event=ev_name,start=t0,
                    start_min=t0.hour*60+t0.minute, minutes_off_before=offmin,
                    indoor_T_at_start=T.get(t0-pd.Timedelta(minutes=1)), indoor_T_lowest_after_45min=T.loc[t0:t0+pd.Timedelta(minutes=45)].min(),
                    indoor_T_at_0800=T.get(dt+pd.Timedelta(hours=8)) if ev_name=='AM' else T.get(t0+pd.Timedelta(minutes=30)),
                    out_T_at_start=wx_m.get(t0), peak_kW_first30=seg.max(), mean_kW_first30=seg.mean(), steady_kW_60_90=g.loc[t0+pd.Timedelta(minutes=60):t0+pd.Timedelta(minutes=90)].mean()))
            # lunch warming: indoor T change during the PM off period
    lp=d[[c for c in d.columns if '_Light' in c or '_Plug' in c]].sum(axis=1,min_count=1)
    for dt,g in lp.groupby(lp.index.normalize()):
        if not day.loc[dt,'working']: continue
        base=g.between_time('03:00','05:00').median(); mid=g.between_time('09:00','11:00').median()
        if not np.isfinite(base) or not np.isfinite(mid) or mid-base<0.5: continue
        w=g.between_time('05:00','11:00'); hit=w[w>base+0.5*(mid-base)]
        if len(hit): arr.append(dict(date=dt,floor=f,arrival_50pct=hit.index[0],arr_min=hit.index[0].hour*60+hit.index[0].minute))
E=pd.DataFrame(ev); A=pd.DataFrame(arr)
E.to_csv(W+'startup_events.csv',index=False); A.to_csv(W+'arrival_proxy.csv',index=False)
fmt=lambda m: f'{int(m//60):02d}:{int(m%60):02d}'
print(len(E)); 
s=E.groupby(['event']).start_min.describe(percentiles=[.05,.25,.5,.75,.95]); print(s.map(lambda v: v))
for e in ('AM','PM'):
    x=E[E.event==e]
    sync=x.groupby(['date','floor']).start_min.agg(lambda v:v.max()-v.min())
    print(e,'median start',fmt(x.start_min.median()),'P5-P95',fmt(x.start_min.quantile(.05)),fmt(x.start_min.quantile(.95)),
      '| within-floor spread median',sync.median(),'min, P90',sync.quantile(.9))
    print(x.groupby('floor').start_min.median().map(fmt).to_dict())
    bld=x.groupby('date').start_min.agg(lambda v:v.max()-v.min()); print(' across-building spread median',bld.median(),'P90',bld.quantile(.9))
print('arrival median',fmt(A.arr_min.median()), 'P25-P75',fmt(A.arr_min.quantile(.25)),fmt(A.arr_min.quantile(.75)))
