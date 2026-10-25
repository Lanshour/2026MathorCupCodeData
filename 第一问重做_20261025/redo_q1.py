"""Rebuild official 24 CSVs; exploratory single-event effect analysis.

No source mutation. Outputs are independent from previous submissions.
Run with bundled Python. Additional analysis packages reside in ./deps.
"""
from pathlib import Path
import sys, io, json, zipfile, hashlib, sqlite3, platform, warnings
BASE=Path(__file__).resolve().parent
ROOT=BASE.parent
sys.path.insert(0,str(BASE/'deps'))
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score,average_precision_score
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties

OUT=BASE/'结果';FIG=BASE/'图'
OUT.mkdir(exist_ok=True);FIG.mkdir(exist_ok=True)
SEED=20261025
END=pd.Timestamp('2026-08-26 10:00')
ARCHIVE=next((ROOT/'2026年MathorCup大数据挑战赛-赛道B初赛/附件').glob('（1）*.zip'))
META=ROOT/'成果审查/FLUX数据核查_20261025/04_核查结果/metadata_summary.json'
FONT=FontProperties(fname='C:/Windows/Fonts/msyh.ttc')
plt.rcParams['font.family']=FONT.get_name();plt.rcParams['axes.unicode_minus']=False
FEATURES={}
def register(key,name,unit,group,formula,family=None):
    FEATURES[key]=dict(feature=key,name=name,unit=unit,group=group,formula=formula,family=family or key)

def write(df,name):df.to_csv(OUT/name,index=False,encoding='utf-8-sig')

def preprocess():
    parts={};source=[]
    with zipfile.ZipFile(ARCHIVE) as z:
        names=[n for n in z.namelist() if n.endswith('.csv')]
        assert len(names)==24
        for name in sorted(names):
            g=name.split('_')[0]
            b=z.read(name);a=pd.read_csv(io.BytesIO(b),na_values=['NaN','NAN','nan'])
            t=pd.to_datetime(a.pop('Timestamp'),format='mixed',errors='raise')
            if t.duplicated().any():raise ValueError(f'duplicate timestamp: {name}')
            v=a.apply(pd.to_numeric,errors='coerce')
            if (a.notna()&v.isna()).any().any():raise ValueError(f'unknown text: {name}')
            v.index=pd.DatetimeIndex(t,name='Timestamp')
            source.append(dict(file=name,group=g,year=int(name[-8:-4]),rows=len(v),
                sha256=hashlib.sha256(b).hexdigest(),origin='比赛附件（1）',
                website_status='网站公开包未含本文件' if g=='FLUX' and int(name[-8:-4])>=2024 else '已核查与网站公开同名文件一致'))
            parts.setdefault(g,[]).append(v.add_prefix(g+'__'))
    raw=pd.concat([pd.concat(v).sort_index() for v in parts.values()],axis=1).sort_index()
    assert raw.index.is_unique
    idx=pd.date_range(raw.index.min(),raw.index.max(),freq='h',name='Timestamp')
    assert len(idx)==52584 and len(raw.index.difference(idx))==0
    raw=raw.reindex(idx)
    measures=[c for c in raw if '__QC_' not in c]
    assert len(measures)==63
    values=raw[measures].replace(9999.9,np.nan)
    flagrows=[];quality=[];qcmap={}
    for c in measures:
        g,field=c.split('__',1);base=field.split('(')[0]
        match=[q for q in raw if q.lower()==(g+'__QC_'+base).lower()]
        qcmap[c]=match[0] if match else None
        bad=pd.Series(False,index=idx)
        if field.startswith('RH_'):bad=(values[c]<0)|(values[c]>100)
        elif field.startswith('VWC_'):bad=(values[c]<0)|(values[c]>1)
        elif field.startswith('WD_'):bad=(values[c]<0)|(values[c]>360)
        elif field.startswith(('WS_','Precip','USTAR','TKE')):bad=values[c]<0
        for ts in idx[bad]:flagrows.append(dict(Timestamp=ts,field=c,value=values.at[ts,c],reason='基本范围异常'))
        values.loc[bad,c]=np.nan
        if g=='FLUX':
            soft=pd.Series(False,index=idx)
            if field=='VPD(hPa)':soft=(values[c]<0)|(values[c]>100)
            elif field=='LE(W/m2)':soft=values[c].abs()>1000
            elif field=='H(W/m2)':soft=values[c].abs()>800
            elif field.startswith(('USTAR','TKE')):soft=values[c].eq(0)
            for ts in idx[soft]:flagrows.append(dict(Timestamp=ts,field=c,value=values.at[ts,c],reason='研究者可疑值阈值，非官方QC'))
    def policy(allow4=False,flux_strict=False):
        a=values.copy()
        for c,q in qcmap.items():
            if q:a.loc[~raw[q].isin([0,4] if allow4 else [0]),c]=np.nan
        if flux_strict:
            for r in flagrows:
                if r['reason'].startswith('研究者'):a.at[r['Timestamp'],r['field']]=np.nan
        return a
    clean=policy()
    for c in measures:
        q=qcmap[c]
        for year in range(2021,2027):
            m=idx.year==year;s=clean.loc[m,c]
            quality.append(dict(field=c,year=year,rows=len(s),raw_numeric=int(values.loc[m,c].notna().sum()),
                primary_numeric=int(s.notna().sum()),missing_fraction=float(s.isna().mean()),
                first_numeric=str(s.first_valid_index()),last_numeric=str(s.last_valid_index()),
                qc_column=q or '无QC列',qc_counts=json.dumps(raw.loc[m,q].value_counts().to_dict()) if q else ''))
    write(pd.DataFrame(source),'01_来源与哈希.csv');write(pd.DataFrame(quality),'02_逐年字段质量.csv')
    write(pd.DataFrame(flagrows),'03_显式异常标记.csv')
    return raw,clean,policy(True),policy(False,True),source

def derive(a):
    f=pd.DataFrame(index=a.index)
    def put(key,src,name,unit,group,formula=None,family=None):
        f[key]=src;register(key,name,unit,group,formula or key,family)
    for key,src,name,u,g in [
        ('T2','MET__Ta_2m(degree C)','2米气温','℃','MET'),
        ('RH2','MET__RH_2m(%)','2米相对湿度','%','MET'),
        ('P','MET__Pressure(hPa)','气压','hPa','MET'),
        ('U10','MET__WS_10m(m/s)','10米风速','m/s','MET'),
        ('U20','MET__WS_20m(m/s)','20米风速','m/s','MET'),
        ('Rsd','RADM__Rsd(W/m2)','下行短波辐射','W/m²','RADM'),
        ('Rld','RADM__Rld(W/m2)','下行长波辐射','W/m²','RADM'),
        ('SoilT','SOIL__soilT_0.1m(degree C)','0.1米土温','℃','SOIL'),
        ('VWC','SOIL__VWC_0.1m(m3/m3)','0.1米体积含水率','m³/m³','SOIL'),
        ('LE','FLUX__LE(W/m2)','潜热通量','W/m²','FLUX'),
        ('H','FLUX__H(W/m2)','感热通量','W/m²','FLUX'),
        ('USTAR','FLUX__USTAR(m/s)','摩擦速度','m/s','FLUX'),
        ('TKE','FLUX__TKE(m2/s2)','湍流动能','m²/s²','FLUX'),
        ('VPD_flux','FLUX__VPD(hPa)','FLUX水汽压亏缺','hPa','FLUX')]:put(key,a[src],name,u,g)
    t=a['MET__Ta_2m(degree C)'];p=a['MET__Pressure(hPa)'];rh=a['MET__RH_2m(%)']
    put('VPD_met',6.108*np.exp(17.27*t/(t+237.3))*(1-rh/100),'MET派生水汽压亏缺','hPa','MET','6.108exp(17.27T/(T+237.3))(1-RH/100)','VPD_flux')
    put('theta',(t+273.15)*(1000/p)**.286,'2米位温','K','MET','(T+273.15)(1000/P)^0.286')
    put('Tgrad',(a['MET__Ta_20m(degree C)']-a['MET__Ta_1m(degree C)'])/19,'1至20米温度梯度','℃/m','MET','(T20-T1)/19')
    put('Ushear',(a['MET__WS_20m(m/s)']-a['MET__WS_1m(m/s)'])/np.log(20),'1至20米对数风速梯度','m/s','MET','(U20-U1)/ln(20)')
    rad=np.deg2rad(a['MET__WD_10m(degree)'])
    put('WDsin',np.sin(rad),'10米风向正弦分量','1','MET','sin(WD10)','wind_direction')
    put('WDcos',np.cos(rad),'10米风向余弦分量','1','MET','cos(WD10)','wind_direction')
    put('P3',p.diff(3)/3,'3小时气压变化率','hPa/h','MET','[P(t)-P(t-3h)]/3')
    put('Rn',a['RADM__Rsd(W/m2)']-a['RADM__Rsu(W/m2)']+a['RADM__Rld(W/m2)']-a['RADM__Rlu(W/m2)'],'净辐射','W/m²','RADM','Rsd-Rsu+Rld-Rlu')
    put('dVWC24',a['SOIL__VWC_0.1m(m3/m3)'].diff(24),'0.1米含水率24小时变化','m³/m³','SOIL','VWC(t)-VWC(t-24h)')
    for h in [1,6,24,72]:
        s=a['MET__Precip(mm)'].rolling(h,min_periods=h).sum()
        put(f'Rain{h}',s,f'{h}小时累计降水','mm','MET',f'过去{h}个整点降水之和，小时增量口径待确认', 'rain_family')
    ts=a[[c for c in a if c.startswith('SOIL__soilT_')]]
    frozen=ts.le(0).sum(axis=1).astype(float).where(ts.notna().all(axis=1))
    put('Frozen',frozen,'有完整五层观测时的冻结层数','层','SOIL','五层均有值才计算ΣI(T≤0)')
    assert frozen.loc[ts.isna().any(axis=1)].isna().all()
    return f

def make_blocks(f,length=35,design='wide',end=END):
    start=end-pd.Timedelta(hours=length-1)
    e=f.reindex(pd.date_range(start,end,freq='h')).copy()
    blocks=[];catalog=[]
    hist_offsets=[0] if design=='exact' else [-15,-10,-5,0,5,10,15]
    years=[] if design=='sameyear' else list(range(2021,2026))
    for year in years:
        for offset in hist_offsets:
            st=start.replace(year=year)+pd.Timedelta(days=offset);en=st+pd.Timedelta(hours=length-1)
            bid=f'{year}_{offset:+d}'
            b=f.reindex(pd.date_range(st,en,freq='h')).copy();blocks.append((bid,b))
            catalog.append(dict(block=bid,year=year,start=st,end=en,source='历史季节对照',hours=length))
    if design!='exact':
        for offset in [-25,-20,-15,-10,-5]:
            st=start+pd.Timedelta(days=offset);en=st+pd.Timedelta(hours=length-1)
            assert en<start-pd.Timedelta(hours=72)
            bid=f'2026_{offset:+d}';blocks.append((bid,f.reindex(pd.date_range(st,en,freq='h')).copy()))
            catalog.append(dict(block=bid,year=2026,start=st,end=en,source='同年较早时段对照，未证实无灾害',hours=length))
    # All controls use same hour sequence. Five-day spacing avoids overlapping
    # 72h feature footprints plus the 35h sample span (maximum 106h).
    return e,blocks,pd.DataFrame(catalog)

def effect(e,blocks):
    rows=[];matrices={}
    for key in fcols:
        x=e[key].to_numpy();valid=np.isfinite(x)
        pairs=[];used=[]
        for bid,b in blocks:
            v=b[key].dropna().to_numpy()
            if len(v)/len(b)<.8:continue
            # Each event hour versus the control block: signed rank dominance.
            p=np.full(len(x),np.nan)
            p[valid]=(np.sign(x[valid,None]-v[None,:])).mean(axis=1)
            pairs.append(p);used.append(bid)
        matrix=np.array(pairs).T if pairs else np.full((len(e),0),np.nan)
        delta=float(np.nanmean(matrix)) if matrix.size and valid.mean()>=.85 else np.nan
        pooled=pd.concat([b[key] for _,b in blocks]).dropna()
        rows.append(dict(feature=key,**{k:v for k,v in FEATURES[key].items() if k!='feature'},
            event_coverage=float(valid.mean()),eligible_control_blocks=len(used),
            event_median=float(np.nanmedian(x)) if valid.any() else np.nan,
            control_median=pooled.median(),signed_delta=delta,
            effect_abs=abs(delta) if np.isfinite(delta) else np.nan,
            direction='事件窗口偏高' if delta>0 else '事件窗口偏低' if delta<0 else '无方向或不可计算'))
        matrices[key]=(matrix,used)
    return pd.DataFrame(rows).sort_values(['effect_abs','feature'],ascending=[False,True]),matrices

def select_order(scores,corr):
    selected=[];discard=[]
    for key in sorted(scores,key=lambda k:(-round(scores[k],12),k)):
        if not np.isfinite(scores[key]):continue
        match=next((j for j in selected if FEATURES[key]['family']==FEATURES[j]['family'] or
                    (pd.notna(corr.at[key,j]) and abs(corr.at[key,j])>=.9)),None)
        if match:discard.append(dict(feature=key,represented_by=match,abs_spearman=abs(corr.at[key,match])))
        else:selected.append(key)
    return selected,discard

def bootstrap(primary,matrices,corr,iterations=500):
    rng=np.random.default_rng(SEED);values={k:[] for k in fcols};hits=dict.fromkeys(fcols,0);n=35
    for _ in range(iterations):
        # Moving event blocks of length 6, and whole control blocks. This only
        # perturbs one known event, not a population of independent disasters.
        starts=rng.integers(0,n-6+1,int(np.ceil(n/6)))
        ei=np.concatenate([np.arange(i,i+6) for i in starts])[:n]
        scores={}
        for k,(m,_) in matrices.items():
            if m.shape[1]<3 or primary.set_index('feature').at[k,'event_coverage']<.85:
                scores[k]=np.nan;values[k].append(np.nan);continue
            ci=rng.integers(0,m.shape[1],m.shape[1]);v=float(np.nanmean(m[ei][:,ci]))
            values[k].append(v);scores[k]=abs(v)
        chosen,_=select_order(scores,corr)
        for k in chosen[:5]:hits[k]+=1
    rows=[]
    for k,vs in values.items():
        v=np.array(vs);v=v[np.isfinite(v)]
        rows.append(dict(feature=k,resample_low=np.quantile(v,.025) if len(v) else np.nan,
            resample_high=np.quantile(v,.975) if len(v) else np.nan,top5_frequency=hits[k]/iterations))
    return pd.DataFrame(rows)

def model_diagnostics(e,blocks):
    rows=[]
    for scenario,bs in [('expanded_with_flux',blocks),('expanded_without_flux',blocks)]:
        cols=[k for k in fcols if e[k].notna().mean()>=.85 and
              (scenario.endswith('with_flux') or FEATURES[k]['group']!='FLUX')]
        # Exclude all-empty controls, but do not invent absence-of-disaster labels.
        ds=pd.concat([e.assign(y=1)]+[b.assign(y=0) for _,b in bs],ignore_index=True)
        X=ds[cols];y=ds.y.to_numpy()
        for name in ['RF','Logistic']:
            for fold,(tr,te) in enumerate(StratifiedKFold(3,shuffle=True,random_state=SEED).split(X,y),1):
                if name=='RF':clf=RandomForestClassifier(n_estimators=160,max_depth=4,min_samples_leaf=4,class_weight='balanced',random_state=SEED+fold,n_jobs=2)
                else:clf=LogisticRegression(class_weight='balanced',max_iter=2000,random_state=SEED)
                pipe=make_pipeline(SimpleImputer(strategy='median'),StandardScaler(),clf)
                pipe.fit(X.iloc[tr],y[tr]);p=pipe.predict_proba(X.iloc[te])[:,1]
                rows.append(dict(scenario=scenario,model=name,fold=fold,roc_auc=roc_auc_score(y[te],p),
                    average_precision=average_precision_score(y[te],p),interpretation='随机小时划分，仅诊断窗口可分性，非泛化性能'))
    write(pd.DataFrame(rows),'12_分类诊断_非预报验证.csv')
    feasibility=[]
    for start in range(0,len(e),6):
        test=np.arange(start,min(start+6,len(e)))
        dist=np.min(abs(np.arange(len(e))[:,None]-test[None,:]),axis=1)
        keep=dist>72
        feasibility.append(dict(test_start=str(e.index[test[0]]),test_hours=len(test),
            embargo_hours=72,train_positive_hours_after_purge=int(keep.sum()),
            status='不可训练：净化后无正样本' if not keep.any() else '仅同事件子段'))
    write(pd.DataFrame(feasibility),'13_时间分块可行性.csv')
    return rows

def plot_results(f,top,scenario):
    event=f.loc['2026-08-19':'2026-08-26 10:00']
    fig,axes=plt.subplots(4,1,figsize=(11,10),sharex=True,layout='constrained')
    for ax,cols in zip(axes,[['T2','RH2'],['Rain1','Rain72'],['VWC','dVWC24'],['H','LE']]):
        for c in cols:ax.plot(event.index,event[c],label=FEATURES[c]['name'])
        ax.legend(loc='upper left',fontsize=9);ax.grid(alpha=.2)
    axes[0].set_title('灾前环境过程（同图双变量量纲不同，仅展示时间变化）')
    axes[-1].set_xlabel('北京时间；小时统计区间未明确')
    fig.savefig(FIG/'01_灾前过程.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
    a=top.iloc[::-1];ax.barh(a['name'],a.effect_abs,color='#167a8a')
    ax.set_xlim(0,1);ax.set_xlabel('历史与同年分块对照的 |平均有向秩效应量|（不是概率）')
    ax.set_title('第一问：本次事件窗口的五项描述性关联特征')
    fig.savefig(FIG/'02_五项特征.png',dpi=160);plt.close(fig)
    matrix=scenario.pivot(index='feature',columns='scenario',values='effect_abs').reindex(top.feature)
    fig,ax=plt.subplots(figsize=(12,4),layout='constrained')
    im=ax.imshow(matrix,aspect='auto',vmin=0,vmax=1,cmap='YlGnBu')
    ax.set_yticks(range(len(matrix)),[FEATURES[k]['name'] for k in matrix.index]);ax.set_xticks(range(len(matrix.columns)),matrix.columns,rotation=30,ha='right',fontsize=8)
    fig.colorbar(im,ax=ax,label='|平均有向秩效应量|');ax.set_title('基线、窗口和质量规则敏感性（不是独立验证）')
    fig.savefig(FIG/'03_敏感性.png',dpi=160);plt.close(fig)

if __name__=='__main__':
    raw,clean,allow4,fluxstrict,source=preprocess();print('PREPROCESS',len(raw),'rows',len(source),'files',flush=True)
    f=derive(clean);f4=derive(allow4);fs=derive(fluxstrict);fcols=list(f)
    write(pd.DataFrame(FEATURES.values()),'04_候选特征定义.csv')
    f.to_csv(OUT/'逐小时候选特征.csv.gz',encoding='utf-8-sig',compression='gzip')
    con=sqlite3.connect(OUT/'完整24文件_重建.sqlite')
    for table,df in [('raw_with_qc',raw),('clean_qc0',clean),('features_qc0',f)]:
        df.to_sql(table,con,if_exists='replace',index=True)
    pd.DataFrame(source).to_sql('source_manifest',con,if_exists='replace',index=False)
    assert con.execute('pragma integrity_check').fetchone()[0]=='ok';con.close()
    event,blocks,catalog=make_blocks(f)
    write(catalog,'05_主分析对照块.csv')
    primary,matrices=effect(event,blocks)
    control=pd.concat([b for _,b in blocks]);corr=control.corr(method='spearman',min_periods=80)
    corr.to_csv(OUT/'06_控制样本特征相关.csv',encoding='utf-8-sig')
    selected,redundant=select_order(primary.set_index('feature').effect_abs.to_dict(),corr)
    write(pd.DataFrame(redundant),'07_冗余特征代表关系.csv')
    print('EFFECTS',primary[['feature','effect_abs','eligible_control_blocks']].head(10).to_dict('records'),flush=True)
    boot=bootstrap(primary,matrices,corr);primary=primary.merge(boot,on='feature',how='left')
    write(primary,'08_全部特征效应与重采样.csv')
    scenarios=[]
    configs=[('main35',f,35,'wide',END),('exact35',f,35,'exact',END),('sameyear35',f,35,'sameyear',END),
             ('wide24',f,24,'wide',END),('wide12',f,12,'wide',END),
             ('allow_QC4',f4,35,'wide',END),('flux_strict',fs,35,'wide',END),
             ('end09',f,35,'wide',END-pd.Timedelta(hours=1))]
    for label,ff,n,design,end in configs:
        ee,bb,_=make_blocks(ff,n,design,end);rr,_=effect(ee,bb)
        ss,_=select_order(rr.set_index('feature').effect_abs.to_dict(),corr)
        rr['scenario']=label;rr['selected_top5']=rr.feature.isin(ss[:5]);scenarios.append(rr)
    sensitivity=pd.concat(scenarios);write(sensitivity,'09_八种设定敏感性.csv')
    top=primary.set_index('feature').loc[selected[:5]].reset_index();top.insert(0,'rank',range(1,len(top)+1))
    freq=sensitivity.groupby('feature').selected_top5.mean();top['scenario_top5_fraction']=top.feature.map(freq)
    write(top,'10_五项描述性关联特征.csv')
    sample=pd.concat([event.assign(window='event',y=1)]+[b.assign(window=bid,y=0) for bid,b in blocks])
    sample.to_csv(OUT/'11_主分析逐小时样本.csv',encoding='utf-8-sig')
    models=model_diagnostics(event,blocks);plot_results(f,top,sensitivity)
    metadata=json.loads(META.read_text(encoding='utf-8-sig'))
    summary=dict(seed=SEED,source_zip=str(ARCHIVE.relative_to(ROOT)),source_zip_sha256=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest(),
        rows=len(raw),files=len(source),measured_variables=len(clean.columns),candidate_features=len(fcols),
        source_timezone='Asia/Shanghai（网站说明）',event_reference='题面10:30，主窗口止于10:00，另做09:00敏感性；小时区间未知',
        qc_policy='主分析QC=0；敏感性QC=0或4；FLUX无QC，不作合格认证',
        primary_controls=len(blocks),positive_hours=len(event),negative_label='仅表示参考窗口，不表示已核实无灾害',
        score='abs(mean_control_blocks(mean_event_hours(sign(x_event-x_control))))，每块至少80%有值，事件至少85%',
        redundancy='同物理族或控制样本|Spearman|>=0.9只保留效应量较高代表',
        bootstrap='500次；事件6小时移动块与完整控制块重采样；区间为设定敏感性，不是独立事件总体95%置信区间',
        split_feasibility='全特征72小时净化后无训练正样本；独立事件数=1，未声称预报验证',
        dependencies={m:__import__(m).__version__ for m in ['numpy','pandas','scipy','sklearn','matplotlib']},
        station_coordinate_status='中文/元数据28.86N与英文28.26N冲突，未做源区空间插值',
        old_ift='不使用饱和消融指标或1e-16浮点差异参与排名',top5=top[['rank','feature','name','effect_abs','direction','top5_frequency','scenario_top5_fraction']].to_dict('records'))
    (OUT/'复现与口径.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
