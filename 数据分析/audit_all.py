"""Read all eight Track B attachments; preserve originals; export audit evidence."""
from pathlib import Path
import sys, io, zipfile, json, collections, re
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'deps'))
import numpy as np
import pandas as pd
import openpyxl, h5py, rasterio, shapefile, olefile
from rasterio.warp import transform_bounds

SRC = ROOT / '2026年MathorCup大数据挑战赛-赛道B初赛' / '附件'
OUT = BASE / '结果'
OUT.mkdir(exist_ok=True)
CACHE = BASE / '解压缓存'

def plain(x):
    if isinstance(x, bytes): return x.decode('utf-8', errors='replace')
    if isinstance(x, np.ndarray): return x.tolist()
    if isinstance(x, np.generic): return x.item()
    return str(x)

def stats(a):
    a = np.ma.asarray(a)
    v = np.asarray(a.compressed(),dtype=float)
    v = v[np.isfinite(v)]
    return dict(cells=int(a.size), valid=int(v.size), valid_fraction=float(len(v)/a.size),
                min=float(v.min()) if len(v) else None, max=float(v.max()) if len(v) else None,
                mean=float(v.mean()) if len(v) else None, std=float(v.std()) if len(v) else None)

inventory=[]
for archive in sorted(SRC.glob('*.zip')):
    with zipfile.ZipFile(archive) as z:
        for name in z.namelist():
            if name.endswith('/'): continue
            inventory.append(dict(archive=archive.name,file=name,bytes=z.getinfo(name).file_size))
            if not archive.name.startswith(('（1）','（2）')):
                # Only known local attachment paths; reject any path escaping cache.
                dest=(CACHE/archive.stem/name).resolve()
                if not dest.is_relative_to(CACHE.resolve()): raise ValueError(name)
                dest.parent.mkdir(parents=True,exist_ok=True)
                dest.write_bytes(z.read(name))

# Attachment 1: full per-field checks already generated, plus physical flags.
hourly=pd.read_csv(ROOT/'第一问/output/hourly_clean_with_qc.csv')
t=pd.to_datetime(hourly.Timestamp)
weather=[]
for col in hourly:
    if col=='Timestamp' or '__QC_' in col:continue
    s=hourly[col]
    lo,hi=None,None
    if '__RH_' in col:lo,hi=0,100
    elif '__VWC_' in col:lo,hi=0,1
    elif '__WD_' in col:lo,hi=0,360
    elif '__WS_' in col or '__Precip(' in col:lo=0
    flags=((s<lo) if lo is not None else pd.Series(False,index=s.index)) | ((s>hi) if hi is not None else False)
    weather.append(dict(field=col,rows=len(s),numeric=int(s.notna().sum()),missing_fraction=float(s.isna().mean()),
        min=s.min(),max=s.max(),physical_flag_count=int(flags.sum()),flag_lower=lo,flag_upper=hi))
pd.DataFrame(weather).to_csv(OUT/'01_气象数值审计.csv',index=False,encoding='utf-8-sig')

# Attachment 2: every workbook, every date and county.
temps=[]; temp_inventory=[]
with zipfile.ZipFile(next(SRC.glob('（2）*.zip'))) as z:
    for name in z.namelist():
        if not name.endswith('.xlsx'):continue
        wb=openpyxl.load_workbook(io.BytesIO(z.read(name)),read_only=True,data_only=True)
        for ws in wb:
            rows=list(ws.values);df=pd.DataFrame(rows[1:],columns=rows[0]);df['时间']=pd.to_datetime(df['时间'])
            temp_inventory.append(dict(file=Path(name).name,rows=len(df),start=str(df['时间'].min()),end=str(df['时间'].max()),
                duplicate_dates=int(df['时间'].duplicated().sum()),missing_values=int(df.iloc[:,1:].isna().sum().sum())))
            temps.append(df)
    # Extract source notes from Word binary, do not interpret it as instructions.
    for name in z.namelist():
        if name.endswith('.doc'):
            with olefile.OleFileIO(io.BytesIO(z.read(name))) as doc:
                b=doc.openstream('WordDocument').read()
                strings=re.findall(r'[\u4e00-\u9fffA-Za-z0-9:/._()（）—\-，。\s]{8,}',b.decode('utf-16le',errors='ignore'))
                (OUT/'02_来源说明提取.txt').write_text('\n'.join(strings),encoding='utf-8')
temp=pd.concat(temps).sort_values('时间');temp.to_csv(OUT/'02_五县逐日气温.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(temp_inventory).to_csv(OUT/'02_气温文件审计.csv',index=False,encoding='utf-8-sig')

# All shapefiles: spatial extent, full attributes, missingness and categories.
vectors=[]
for p in sorted(CACHE.rglob('*.shp')):
    cpg=p.with_suffix('.cpg')
    encoding=cpg.read_text().strip() if cpg.exists() else 'gb18030'
    if encoding=='65001':encoding='utf-8'
    r=shapefile.Reader(str(p),encoding=encoding,encodingErrors='replace')
    names=[f[0] for f in r.fields[1:]]
    records=[x.as_dict() for x in r.records()]
    stem=p.stem
    pd.DataFrame(records).to_csv(OUT/(stem+'_属性.csv'),index=False,encoding='utf-8-sig')
    prj=p.with_suffix('.prj').read_text(errors='replace') if p.with_suffix('.prj').exists() else ''
    categories={}
    for col in names:
        vals=[str(x.get(col,'')) for x in records];c=collections.Counter(vals)
        if len(c)<=25:categories[col]=dict(c)
    vectors.append(dict(file=str(p.relative_to(CACHE)),features=len(r),geometry=r.shapeTypeName,
        bbox=list(r.bbox),projection=prj,fields=r.fields[1:],categories=categories,
        blank_counts={col:sum(x.get(col) in [None,''] for x in records) for col in names}))

# Attachment 4: NetCDF4/HDF5 complete variable arrays and metadata.
nc=[];ncmeta={}
for p in CACHE.rglob('*.nc'):
    with h5py.File(p,'r') as f:
        ncmeta['global']={k:plain(v) for k,v in f.attrs.items()}
        for key in f:
            ds=f[key];a=ds[()]
            attrs={k:plain(v) for k,v in ds.attrs.items() if k not in ['DIMENSION_LIST','REFERENCE_LIST']}
            nc.append(dict(variable=key,shape=list(ds.shape),dtype=str(ds.dtype),attrs=attrs,**stats(a)))
        ncmeta['x_range']=[float(f['x'][0]),float(f['x'][-1])]
        ncmeta['y_range']=[float(f['y'][0]),float(f['y'][-1])]
        ncmeta['mask_values']={str(x):int(n) for x,n in zip(*np.unique(f['glacier_mask'][()],return_counts=True))}
        mask=f['glacier_mask'][()]==1
        ncmeta['within_mask']={k:stats(f[k][()][mask]) for k in ['dem','slope','thickness','v']}
        ncmeta['crs']={k:plain(v) for k,v in f['spatial_ref'].attrs.items()}

# Every base GeoTIFF, including all glacier tiles, full valid-cell statistics.
rasters=[];classes=[]
for p in sorted(CACHE.rglob('*.tif')):
    with rasterio.open(p) as ds:
        row=dict(file=str(p.relative_to(CACHE)),width=ds.width,height=ds.height,bands=ds.count,
            crs=str(ds.crs),resolution=list(ds.res),bounds=list(ds.bounds),nodata=ds.nodata,
            dtype=ds.dtypes[0],tags=ds.tags(),**stats(ds.read(1,masked=True)))
        if ds.crs:row['bounds_wgs84']=list(transform_bounds(ds.crs,'EPSG:4326',*ds.bounds))
        rasters.append(row)
        if 'LUCD' in p.name:
            a=ds.read(1,masked=True).compressed();values,counts=np.unique(a,return_counts=True)
            for v,n in zip(values,counts):classes.append(dict(file=p.name,code=int(v),pixels=int(n),fraction=float(n/len(a))))
        if p.name=='DEM.tif':
            (OUT/'07_DEM元数据.json').write_text(json.dumps(row,ensure_ascii=False,default=plain,indent=2),encoding='utf-8')

# Extract docx and metadata XML text for provenance review.
for p in CACHE.rglob('*.docx'):
    with zipfile.ZipFile(p) as z:
        tree=ET.fromstring(z.read('word/document.xml'))
        text='\n'.join(''.join(x.itertext()) for x in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
        (OUT/'03_冰川数据说明.txt').write_text(text,encoding='utf-8')

pd.DataFrame(inventory).to_csv(OUT/'附件ZIP清单.csv',index=False,encoding='utf-8-sig')
pd.DataFrame(classes).to_csv(OUT/'05_土地覆盖类别统计.csv',index=False,encoding='utf-8-sig')
pd.DataFrame([{k:v for k,v in r.items() if k!='tags'} for r in rasters]).to_csv(OUT/'全部栅格审计.csv',index=False,encoding='utf-8-sig')
report=dict(temperature_files=temp_inventory,temperature_count=len(temp),temperature_summary=temp.iloc[:,1:].describe().to_dict(),
    vectors=vectors,netcdf_variables=nc,netcdf_metadata=ncmeta,rasters=rasters,landcover_classes=classes,
    weather=weather)
(OUT/'完整审计.json').write_text(json.dumps(report,ensure_ascii=False,default=plain,indent=2),encoding='utf-8')
print('Temperature',len(temp),temp['时间'].min(),temp['时间'].max())
print('Vectors',[(v['file'],v['features'],v['geometry']) for v in vectors])
print('Rasters',len(rasters))
for r in rasters:
    if 'LUCD' in r['file'] or r['file'].endswith('/DEM.tif'):print('RASTER',r)
print('NC',ncmeta)
print('LAND',classes)
print('WEATHER_FLAGS',[(x['field'],x['physical_flag_count']) for x in weather if x['physical_flag_count']])
print('Audit saved',OUT)
