"""第一问：整理逐小时观测并生成可复核的质量报告，不进行特征排名。

依赖 pandas。运行：python 第一问/scripts/prepare_data.py
输出保存在 第一问/output；原始压缩包不修改。
"""
from pathlib import Path
import io
import json
import re
import zipfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / '第一问' / 'output'
EVENT = pd.Timestamp('2026-08-26 10:30')
SENTINELS = [9999.9]  # 本批文件中已观察到；其他编码先统计，不擅自解释。


def meaning(group, name):
    mappings = {
        'WS': '风速', 'WD': '风向', 'Ta': '空气温度', 'RH': '相对湿度',
        'Pressure': '气压', 'Precip': '降水量（累计方式待确认）',
        'Rsd': '向下短波辐射', 'Rsu': '向上短波辐射',
        'Rld': '向下长波辐射', 'Rlu': '向上长波辐射',
        'soilT': '土壤温度', 'VWC': '土壤体积含水率', 'G': '土壤热通量',
        'H': '感热通量（正负方向待确认）', 'LE': '潜热通量（正负方向待确认）',
        'USTAR': '摩擦速度', 'TKE': '湍流动能',
    }
    key = name.split('(')[0].split('_')[0]
    return mappings.get(key, '需结合站点说明确认定义')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    archive = next((ROOT / '2026年MathorCup大数据挑战赛-赛道B初赛' / '附件').glob('（1）*.zip'))
    groups = {}
    manifests, dictionaries, quality, qc_counts, event_quality = [], [], [], [], []
    with zipfile.ZipFile(archive) as z:
        for group in ['MET', 'RADM', 'SOIL', 'FLUX']:
            frames = []
            for name in sorted(z.namelist()):
                if not name.startswith(group + '_') or not name.endswith('.csv'):
                    continue
                df = pd.read_csv(io.BytesIO(z.read(name)), encoding='utf-8-sig',
                                 na_values=['NaN', 'NAN', 'nan'])
                t = pd.to_datetime(df.pop('Timestamp'), format='mixed', errors='raise')
                if t.duplicated().any():
                    raise ValueError(f'{name} 有重复时间，需人工核对，不自动去重')
                numeric = df.apply(pd.to_numeric, errors='coerce')
                bad_parse = df.notna() & numeric.isna()
                if bad_parse.any().any():
                    raise ValueError(f'{name} 出现未识别的非数值，需核对')
                numeric.index = pd.DatetimeIndex(t, name='Timestamp')
                measures = [c for c in numeric if not c.startswith('QC_')]
                qc_map = {c.lower(): c for c in numeric if c.startswith('QC_')}
                cleaned = numeric.copy()
                cleaned[measures] = cleaned[measures].replace(SENTINELS, float('nan'))
                valid = cleaned[measures].notna().any(axis=1)
                manifests.append(dict(file=name, rows=len(df),
                    grid_start=str(t.min()), grid_end=str(t.max()),
                    first_any_numeric=str(cleaned.index[valid].min()),
                    last_any_numeric=str(cleaned.index[valid].max())))
                event_mask = (cleaned.index >= EVENT - pd.Timedelta(days=7)) & (cleaned.index < EVENT)
                for col in numeric:
                    if col.startswith('QC_'):
                        for code, count in numeric[col].value_counts(dropna=False).items():
                            qc_counts.append(dict(file=name, field=col, code=str(code), count=int(count)))
                        continue
                    base = col.split('(')[0]
                    qc = qc_map.get(('QC_' + base).lower())
                    values = cleaned[col]
                    present = values.notna()
                    quality.append(dict(file=name, field=col, rows=len(values),
                        source_na=int(numeric[col].isna().sum()),
                        sentinel_9999_9=int(numeric[col].eq(9999.9).sum()),
                        other_suspect_minus9999=int(numeric[col].isin([-9999, -9999.9]).sum()),
                        missing_fraction=float(values.isna().mean()),
                        qc_nonzero_with_value=int((present & numeric[qc].ne(0)).sum()) if qc else None,
                        first_numeric=str(values.first_valid_index()), last_numeric=str(values.last_valid_index()),
                        min=values.min(), max=values.max()))
                    if event_mask.any():
                        s = values.loc[event_mask]
                        event_quality.append(dict(file=name, field=col, hours=len(s),
                            numeric_hours=int(s.notna().sum()), missing_fraction=float(s.isna().mean()),
                            qc0_hours=int((s.notna() & numeric.loc[event_mask, qc].eq(0)).sum()) if qc else None))
                    if name.endswith('2026.csv'):
                        height = re.search(r'_(\d+(?:\.\d+)?m)', col)
                        dictionaries.append(dict(column=group + '__' + col, group=group,
                            source_field=col, meaning=meaning(group, col),
                            unit=col.split('(', 1)[1].rsplit(')', 1)[0] if '(' in col else '',
                            height_or_depth=height.group(1) if height else '',
                            qc_column=group + '__' + qc if qc else '',
                            definition_status='按字段名识别，待源文档核对'))
                frames.append(cleaned)
            merged = pd.concat(frames).sort_index()
            if not merged.index.is_unique:
                raise ValueError(f'{group} 跨文件时间重复')
            groups[group] = merged.add_prefix(group + '__')
    hourly = pd.concat(groups.values(), axis=1).sort_index()
    expected = pd.date_range(hourly.index.min(), hourly.index.max(), freq='h', name='Timestamp')
    absent_hours = len(expected.difference(hourly.index))
    hourly = hourly.reindex(expected)
    hourly.to_csv(OUT / 'hourly_clean_with_qc.csv', encoding='utf-8-sig', na_rep='')
    # QC=0 仅为待确认的敏感性版本，不认定其他代码全部无效。
    qc0 = hourly[[d['column'] for d in dictionaries]].copy()
    for d in dictionaries:
        if d['qc_column']:
            qc0.loc[hourly[d['qc_column']].ne(0), d['column']] = float('nan')
    qc0.to_csv(OUT / 'hourly_qc0_provisional.csv', encoding='utf-8-sig', na_rep='')
    for filename, rows in [('source_inventory.csv', manifests), ('field_dictionary.csv', dictionaries),
                           ('quality_by_year.csv', quality), ('qc_code_counts.csv', qc_counts),
                           ('event_7day_coverage.csv', event_quality)]:
        pd.DataFrame(rows).to_csv(OUT / filename, index=False, encoding='utf-8-sig')
    summary = dict(source=str(archive), rows=len(hourly), columns=len(hourly.columns),
                   measurement_fields=len(dictionaries), inserted_absent_hours=absent_hours,
                   timezone='unknown; source timestamps retained without timezone conversion',
                   event_reference=str(EVENT), event_reference_status='题面事件时刻，不等同已核实的源区触发时刻',
                   missing_sentinels=SENTINELS, interpolation=False,
                   qc_policy='main table preserves codes; qc0 version is provisional only')
    (OUT / 'run_summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
