import os
BASE=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..')  # project folder
import pandas as pd, numpy as np, matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, matplotlib.dates as mdates
W=os.path.join(BASE,'work',''); O=os.path.join(BASE,'charts','')
C1,C2,C3,C4,GR='#2a78d6','#eb6834','#1baf7a','#eda100','#9a9893'
INK,INK2,GRID='#0b0b0b','#52514e','#e6e5e1'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.edgecolor':GRID,'axes.labelcolor':INK2,'xtick.color':INK2,'ytick.color':INK2,
 'axes.grid':True,'grid.color':GRID,'grid.linewidth':0.8,'axes.spines.top':False,'axes.spines.right':False,'axes.titleweight':'bold','axes.titlesize':13,
 'axes.titlelocation':'left','figure.facecolor':'white','axes.facecolor':'white','legend.frameon':False,'savefig.dpi':200,'axes.axisbelow':True})
def sub(ax,t): ax.text(0,1.02,t,transform=ax.transAxes,color=INK2,fontsize=10,va='bottom')
Q=pd.read_parquet(W+'q15_units.parquet'); P=Q[Q.enduse!='Temp'].copy()
day=pd.read_csv(W+'day_table.csv',parse_dates=['date']).set_index('date')
P['date']=P.ts.dt.normalize(); P=P[P.date.map(day.working)==True]
B=P.groupby('ts').v.sum(); tod=B.index.hour*60+B.index.minute
# 1 AM vs PM monthly max
am=B[(tod>=450)&(tod<540)]; pm=B[(tod>=765)&(tod<855)]
mm=pd.DataFrame({'AM':am.groupby(am.index.to_period('M')).max(),'PM':pm.groupby(pm.index.to_period('M')).max()})
fig,ax=plt.subplots(figsize=(11,4.6)); x=np.arange(len(mm)); w=0.36
ax.bar(x-w/2-0.01,mm.AM,w,color=C2,label='Morning start-up (07:30–09:00)')
ax.bar(x+w/2+0.01,mm.PM,w,color=C1,label='Post-lunch restart (12:45–14:15)')
ax.set_xticks(x,[p.strftime('%b\n%y') for p in mm.index]); ax.set_ylim(400,700); ax.set_ylabel('Highest 15-min demand, kW')
ax.axvline(5.5,color=INK2,lw=1); ax.text(2.5,690,'2018 holdout',ha='center',color=INK2,fontsize=10); ax.text(10.5,690,'2019 (train)',ha='center',color=INK2,fontsize=10)
ax.legend(loc='upper center',bbox_to_anchor=(0.5,-0.2),ncol=2); ax.set_title('The post-lunch restart sets the monthly peak',pad=22)
sub(ax,'Floors 3–7, working days. Under MEA TOU billing only 09:00–22:00 counts, so the morning start never bills.')
fig.tight_layout(); fig.savefig(O+'01_peak_timing_AM_vs_PM.png'); plt.close()
# 2 typical day stacked by end-use
p19=P[P.ts.dt.year==2019]; e=p19.groupby(['ts','enduse']).v.sum().unstack()
prof=e.groupby(e.index.strftime('%H:%M')).median()
fig,ax=plt.subplots(figsize=(11,4.6)); xx=np.arange(len(prof))
ax.stackplot(xx,prof.AC,prof.Light,prof.Plug,colors=[C1,C4,C3],labels=['AC','Lighting','Plug loads'],edgecolor='white',linewidth=0.6)
ax.axvspan(36,88,color='#f2f1ee',zorder=0); ax.text(62,615,'TOU on-peak 09:00–22:00 (billed)',ha='center',color=INK2,fontsize=10)
for i,t in ((32,'07:46 AC start\n(all zones at once)'),(53,'13:01 restart\n(all zones at once)')): ax.annotate(t,(i,prof.sum(axis=1).iloc[i]),xytext=(i-11 if i==32 else i+3,560),fontsize=9.5,color=INK,arrowprops=dict(arrowstyle='-',color=INK2,lw=0.8))
ax.set_xticks(xx[::8],prof.index[::8]); ax.set_xlim(0,95); ax.set_ylim(0,650); ax.set_ylabel('kW (median 15-min)')
ax.legend(loc='upper right'); ax.set_title('A typical 2019 working day: two synchronised AC spikes',pad=22)
sub(ax,'Floors 3–7, median of 171 working days. AC is ~85% of load at every monthly peak.')
fig.tight_layout(); fig.savefig(O+'02_typical_day_by_enduse.png'); plt.close()
# 3 start-time spread
E=pd.read_csv(W+'startup_events.csv')
fig,axs=plt.subplots(1,2,figsize=(11,4.2),sharey=False)
for ax,(ev,lo,hi,c) in zip(axs,(('AM',455,475,C2),('PM',770,790,C1))):
    s=E[E.event==ev].start_min.clip(lo,hi); v=s.value_counts().reindex(range(lo,hi+1),fill_value=0)
    ax.bar(v.index,v.values,0.8,color=c); ax.set_xticks(range(lo,hi+1,5),[f'{m//60:02d}:{m%60:02d}' for m in range(lo,hi+1,5)])
    ax.set_title(('Morning' if ev=='AM' else 'Post-lunch')+' start time, every zone-day',fontsize=12); ax.set_ylabel('zone-days')
    q5,q95=np.percentile(E[E.event==ev].start_min,[5,95]); ax.text(0.02,0.92,f'90% of starts within {int(q95-q5)} min\nSame-floor zones: identical minute',transform=ax.transAxes,fontsize=9.5,color=INK,va='top')
fig.suptitle('Start times barely vary in the data → offsets beyond ±10 min are extrapolation',x=0.01,ha='left',fontweight='bold',fontsize=13)
fig.tight_layout(); fig.savefig(O+'03_start_time_spread.png'); plt.close()
# 4 drivers at peak
SH=pd.read_csv(W+'peak_shares.csv'); s=SH[(SH.peak=='TOU')]
z=s[s.enduse=='AC_zone'].groupby(['floor','zone']).kW.mean().unstack(); nac=s[s.enduse.isin(['Light','Plug'])].groupby(['month','floor']).kW.sum().groupby('floor').mean()
fig,ax=plt.subplots(figsize=(11,4.4)); left=np.zeros(5); cols={1:C1,2:C2,4:C3,5:C4}
for zz in (1,2,4,5):
    ax.barh(z.index.astype(str),z[zz],left=left,height=0.55,color=cols[zz],label=f'AC zone {zz}',edgecolor='white',linewidth=2); left+=z[zz].values
ax.barh(z.index.astype(str),nac,left=left,height=0.55,color=GR,label='Lighting + plug',edgecolor='white',linewidth=2)
for i,t in enumerate(left+nac.values): ax.text(t+2,i,f'{t:.0f} kW',va='center',color=INK,fontsize=10)
ax.set_xlabel('kW at the monthly billing peak (average of 16 months)'); ax.set_ylabel('Floor'); ax.invert_yaxis(); ax.set_xlim(0,160)
ax.legend(ncol=5,loc='upper center',bbox_to_anchor=(0.5,-0.18)); ax.set_title('What makes up the peak: zones 1 and 4 lead on every floor',pad=22)
sub(ax,'Zone 3 has no AC on any floor. Floor 6 zone 1 is one unit; its 4-unit cluster sits in zone 4.')
fig.tight_layout(); fig.savefig(O+'04_peak_drivers_by_zone.png'); plt.close()
# 5 baseline
bh=pd.read_csv(W+'baseline_hourly.csv',parse_dates=['ts']).set_index('ts'); g=pd.read_csv(W+'g14_results.csv',index_col=0)
wk=bh.loc['2018-09-03':'2018-09-14']; wk=wk.reindex(pd.date_range(wk.index.min(),wk.index.max(),freq='h'))
fig,ax=plt.subplots(figsize=(11,4.2)); ax.plot(wk.index,wk.kW,color=C1,lw=2,label='Actual'); ax.plot(wk.index,wk.baseline_kW,color=C2,lw=2,label='Baseline model')
ax.xaxis.set_major_formatter(mdates.DateFormatter('%a %d %b')); ax.set_ylabel('Hourly kW'); ax.legend(loc='upper right',ncol=2)
h=g.loc['holdout_2018']; t=g.loc['train_2019']
ax.set_title('Weather + calendar baseline passes ASHRAE Guideline 14 on unseen 2018 data',pad=22)
sub(ax,f"Holdout CV(RMSE) {h.CVRMSE_pct:.1f}% (limit 30%), NMBE {h.NMBE_pct:.1f}% (limit ±10%). Train: {t.CVRMSE_pct:.1f}% / {t.NMBE_pct:.1f}%. Two holdout weeks shown.")
fig.tight_layout(); fig.savefig(O+'05_baseline_G14.png'); plt.close()
# 6 stagger
pr=pd.read_csv(W+'stagger_profile.csv'); pr['t']=pd.to_timedelta(pr.minute); pr=pr[(pr.t>=pd.Timedelta('12:30:00'))&(pr.t<pd.Timedelta('14:30:00'))]
sm=pd.read_csv(W+'stagger_monthly.csv'); bs=pd.read_csv(W+'stagger_bootstrap.csv')
fig,axs=plt.subplots(1,2,figsize=(12,4.6),gridspec_kw={'width_ratios':[1.1,1]})
ax=axs[0]; tm=pr.t.dt.total_seconds()/60
ax.plot(tm,pr.today_kW,color=GR,lw=2,label='Today (all zones restart together)'); ax.plot(tm,pr.staggered_kW,color=C1,lw=2,label='Staggered (±10 min by zone)')
ax.set_xticks(range(750,871,15),[f'{m//60:02d}:{m%60:02d}' for m in range(750,871,15)]); ax.set_ylabel('kW, Floors 3–7 (median 2019 day)'); ax.legend(loc='lower right',fontsize=9.5)
ax.set_title('Spreading the restart flattens the spike',fontsize=12)
ax=axs[1]; cc=[C2 if m.startswith('2018') else C1 for m in sm.month]
ax.bar(range(len(sm)),sm.cut_kW,0.6,color=cc); ax.set_xticks(range(len(sm)),[pd.Period(m).strftime('%b\n%y') for m in sm.month],fontsize=8.5)
ax.set_ylabel('Monthly billing-peak cut, kW'); ax.set_title('Cut per month (blue 2019, orange 2018 holdout)',fontsize=12)
lo19,hi19=np.percentile(bs.train_2019,[2.5,97.5]); lo18,hi18=np.percentile(bs.holdout_2018,[2.5,97.5])
ax.text(0.02,0.97,f'2019: {sm[sm.month.str.startswith("2019")].cut_kW.mean():.0f} kW avg (95% CI {lo19:.0f}–{hi19:.0f})\n2018 holdout: {sm[sm.month.str.startswith("2018")].cut_kW.mean():.0f} kW avg (95% CI {lo18:.0f}–{hi18:.0f})\nDaily kWh: unchanged (delays offset advances)',transform=ax.transAxes,va='top',fontsize=9.5,color=INK)
fig.suptitle('First-cut stagger simulation (time-shifted real profiles, no ML) sets the KPI target range',x=0.01,ha='left',fontweight='bold',fontsize=13)
fig.tight_layout(); fig.savefig(O+'06_stagger_simulation.png'); plt.close()
# 7 schedule table
sc=pd.read_csv(W+'stagger_schedule.csv'); tab=sc.pivot(index='floor',columns='zone',values='offset_min')
fig,ax=plt.subplots(figsize=(7.5,4)); ax.grid(False)
cmap=matplotlib.colors.LinearSegmentedColormap.from_list('d',['#2a78d6','#f2f1ee','#eb6834'])
ax.imshow(tab.values,cmap=cmap,vmin=-12,vmax=12,aspect='auto')
for i in range(tab.shape[0]):
    for j in range(tab.shape[1]):
        v=int(tab.values[i,j]); base=13*60+1+v; ax.text(j,i,f'{base//60:02d}:{base%60:02d}\n({v:+d} min)',ha='center',va='center',fontsize=10,color=INK)
ax.set_xticks(range(4),[f'Zone {z}' for z in tab.columns]); ax.set_yticks(range(5),[f'Floor {f}' for f in tab.index])
for s in ax.spines.values(): s.set_visible(False)
ax.set_title('Draft BMS post-lunch restart schedule (today: all 13:01)',pad=10,fontsize=12)
fig.text(0.01,0.01,'Blue = start earlier (pre-cool), orange = start later. Placeholder until the ML optimiser replaces it.',fontsize=9,color=INK2)
fig.tight_layout(rect=(0,0.04,1,1)); fig.savefig(O+'07_draft_bms_schedule.png'); plt.close()
print('ok')
