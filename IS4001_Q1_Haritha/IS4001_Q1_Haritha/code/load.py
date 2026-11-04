import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
os.makedirs(os.path.join(BASE,'work'),exist_ok=True)
import pandas as pd, numpy as np
R=os.path.join(BASE,'raw',''); W=os.path.join(BASE,'work','')
for y,fl in ((2019,(6,7)),):
    for f in fl:
        d=pd.read_csv(f'{R}{y}Floor{f}.csv')
        d['Date']=pd.to_datetime(d['Date'],errors='coerce'); d=d.dropna(subset=['Date'])
        d=d.drop_duplicates('Date').set_index('Date').sort_index()
        full=pd.date_range('2018-07-01' if y==2018 else '2019-01-01', f'{y}-12-31 23:59', freq='min')
        n=len(d); d=d.reindex(full)
        d=d[[c for c in d.columns if '(kW)' in c or '(degC)' in c]].astype('float32')
        d.columns=[c.replace('(kW)','').replace('(degC)','_T') for c in d.columns]
        d.to_parquet(f'{W}F{f}_{y}.parquet'); print(y,f,n,len(full),d.shape)
