"""Build temporal and spatial model inputs following the supplied flowchart.

Raw archives are read only. IQR flags are recorded but not silently deleted.
Safety factor and debris-flow speed stay missing without required observations.
"""
from __future__ import annotations

import heapq
import io
import json
import math
import sys
import zipfile
from collections import deque
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent
sys.path[:0] = [str(ROOT / "数据分析/deps"), str(ROOT / "第一问重做_20261025/deps")]

import h5py
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.warp import calculate_default_transform, reproject, transform

OUT = BASE / "结果"
OUT.mkdir(exist_ok=True)
ARCHIVE = next((ROOT / "2026年MathorCup大数据挑战赛-赛道B初赛/附件").glob("（1）*.zip"))
DEM = next((ROOT / "数据分析/解压缓存").glob("（7）*/DEM.tif"))
GLACIER = next((ROOT / "数据分析/解压缓存").glob("（4）*/*.nc"))
LAND = next((ROOT / "数据分析/解压缓存").glob("（5）*/jilong_LUCD_2023.tif"))
EVENT_START = pd.Timestamp("2026-08-25 00:00")
EVENT_END = pd.Timestamp("2026-08-26 10:00")

SCHEMA: list[dict] = []


def register(name: str, domain: str, feature_class: str, unit: str, source: str,
             formula: str, availability: str = "available", caveat: str = "") -> None:
    SCHEMA.append(dict(feature=name, domain=domain, feature_class=feature_class,
                       unit=unit, source=source, formula=formula,
                       availability=availability, caveat=caveat))


def csv(data: pd.DataFrame, name: str, index: bool = False, compressed: bool = False) -> None:
    filename = name + (".csv.gz" if compressed else ".csv")
    data.to_csv(OUT / filename, index=index, index_label="Timestamp" if index else None,
                encoding="utf-8-sig", compression="gzip" if compressed else None)


def load_hourly() -> tuple[pd.DataFrame, pd.DataFrame, dict, pd.DataFrame]:
    groups: dict[str, list[pd.DataFrame]] = {}
    source_rows = []
    with zipfile.ZipFile(ARCHIVE) as z:
        files = sorted(n for n in z.namelist() if n.lower().endswith(".csv"))
        if len(files) != 24:
            raise ValueError(f"Expected 24 CSVs, found {len(files)}")
        for member in files:
            name = Path(member).name
            group = name.split("_")[0]
            raw = pd.read_csv(io.BytesIO(z.read(member)), na_values=["NaN", "NAN", "nan", "9999.9"])
            time = pd.to_datetime(raw.pop("Timestamp"), format="mixed", errors="raise")
            if time.duplicated().any():
                raise ValueError(f"Duplicate times in {name}")
            raw = raw.apply(pd.to_numeric, errors="coerce")
            raw.index = pd.DatetimeIndex(time, name="Timestamp")
            groups.setdefault(group, []).append(raw)
            source_rows.append(dict(file=name, group=group, rows=len(raw),
                                    source="比赛附件（1）", website_status=(
                                        "网站公开包无此年FLUX" if group == "FLUX" and name[-8:-4] in {"2024", "2025", "2026"}
                                        else "同名文件与网站公开包SHA256已核对一致")))
    data = {group: pd.concat(frames).sort_index() for group, frames in groups.items()}
    common = pd.date_range("2021-01-01", "2026-12-31 23:00", freq="h", name="Timestamp")
    data = {group: frame.reindex(common) for group, frame in data.items()}
    # The original files contain calendar placeholders before/after observations.
    measured = pd.concat([frame.loc[:, ~frame.columns.str.startswith("QC_")] for frame in data.values()], axis=1)
    active = measured.notna().any(axis=1)
    start, end = active[active].index[[0, -1]]
    data = {group: frame.loc[start:end] for group, frame in data.items()}
    index = data["MET"].index
    quality_rows = []
    invalid_rows = []

    def measure(group: str, field: str, validity=None) -> pd.Series:
        frame = data[group]
        raw = frame[field].copy()
        base = field.split("(")[0]
        qc_name = next((c for c in frame if c.lower() == f"qc_{base}".lower()), None)
        qc_rejected = raw.notna() & ~frame[qc_name].eq(0) if qc_name else pd.Series(False, index=index)
        val = raw.mask(qc_rejected)
        bad = validity(val) if validity else pd.Series(False, index=index)
        val = val.mask(bad)
        quality_rows.append(dict(group=group, field=field, qc_field=qc_name or "无", source_numeric=int(raw.notna().sum()),
                                 qc_rejected=int(qc_rejected.sum()), hard_invalid=int(bad.sum()),
                                 retained_numeric=int(val.notna().sum())))
        if bad.any():
            invalid_rows.extend(dict(Timestamp=t, group=group, field=field, raw_value=raw.at[t],
                                     reason="基本物理范围不成立") for t in index[bad])
        return val

    m = {"T2": measure("MET", "Ta_2m(degree C)"),
         "RH2": measure("MET", "RH_2m(%)", lambda s: s.lt(0) | s.gt(100)),
         "P": measure("MET", "Pressure(hPa)", lambda s: s.le(0)),
         "U10": measure("MET", "WS_10m(m/s)", lambda s: s.lt(0)),
         "Rain1": measure("MET", "Precip(mm)", lambda s: s.lt(0)),
         "Rsd": measure("RADM", "Rsd(W/m2)"), "Rsu": measure("RADM", "Rsu(W/m2)"),
         "Rld": measure("RADM", "Rld(W/m2)"), "Rlu": measure("RADM", "Rlu(W/m2)"),
         "VWC01": measure("SOIL", "VWC_0.1m(m3/m3)", lambda s: s.lt(0) | s.gt(1)),
         "SoilT01": measure("SOIL", "soilT_0.1m(degree C)"),
         "LE": measure("FLUX", "LE(W/m2)"), "H": measure("FLUX", "H(W/m2)"),
         "USTAR": measure("FLUX", "USTAR(m/s)", lambda s: s.lt(0)),
         "TKE": measure("FLUX", "TKE(m2/s2)", lambda s: s.lt(0)),
         "VPD": measure("FLUX", "VPD(hPa)")}
    m["soil_layers"] = [m["SoilT01"]] + [measure("SOIL", f"soilT_{depth}m(degree C)")
                                           for depth in ["0.2", "0.4", "0.8", "1.6"]]
    out = pd.DataFrame(index=index)

    def put(name, series, category, unit, source, formula, caveat=""):
        out[name] = series
        register(name, "time", category, unit, source, formula, caveat=caveat)

    put("net_radiation_Wm2", m["Rsd"] - m["Rsu"] + m["Rld"] - m["Rlu"],
        "能量条件", "W/m2", "RADM 四分量", "Rsd−Rsu+Rld−Rlu")
    put("air_temperature_2m_C", m["T2"], "能量条件", "degree C", "MET 2m", "直接观测")
    put("positive_degree_hours_24_C_h", m["T2"].clip(lower=0).rolling(24, min_periods=24).sum(),
        "能量条件", "degree C h", "MET 2m", "过去24个时标 max(T2,0) 之和",
        "仅为站点潜在融化代理，不是冰川实际融水量")
    put("soil_moisture_0p1m", m["VWC01"], "物质条件", "m3/m3", "SOIL 0.1m", "直接观测")
    put("soil_moisture_change_24h", m["VWC01"].diff(24), "物质条件", "m3/m3",
        "SOIL 0.1m", "VWC(t)−VWC(t−24h)")
    put("soil_temperature_0p1m_C", m["SoilT01"], "物质条件", "degree C", "SOIL 0.1m", "直接观测")
    layer_frame = pd.concat(m["soil_layers"], axis=1)
    frozen = layer_frame.le(0).sum(axis=1).where(layer_frame.notna().all(axis=1))
    put("frozen_layer_count", frozen, "物质条件", "layers", "SOIL 五深度", "五层均有数值时 Σ1(T≤0)")
    for hours in [1, 6, 24, 72]:
        value = m["Rain1"] if hours == 1 else m["Rain1"].rolling(hours, min_periods=hours).sum()
        put(f"precip_{hours}h_mm", value, "触发条件", "mm", "MET Precip", f"过去{hours}个时标降水相加",
            "原始小时值的统计区间未在元数据中说明")
    for name, key, category, unit, source in [
        ("latent_heat_Wm2", "LE", "能量条件", "W/m2", "FLUX"),
        ("sensible_heat_Wm2", "H", "能量条件", "W/m2", "FLUX"),
        ("vpd_hPa", "VPD", "辅助条件", "hPa", "FLUX"),
        ("friction_velocity_ms", "USTAR", "辅助条件", "m/s", "FLUX"),
        ("turbulent_kinetic_energy_m2s2", "TKE", "辅助条件", "m2/s2", "FLUX"),
        ("relative_humidity_2m_pct", "RH2", "辅助条件", "%", "MET 2m"),
        ("wind_speed_10m_ms", "U10", "辅助条件", "m/s", "MET 10m"),
        ("pressure_hPa", "P", "辅助条件", "hPa", "MET")]:
        put(name, m[key], category, unit, source, "直接观测",
            "FLUX 无官方 QC 标记" if source == "FLUX" else "")
    quality = pd.DataFrame(quality_rows)
    invalid = pd.DataFrame(invalid_rows, columns=["Timestamp", "group", "field", "raw_value", "reason"])
    csv(quality, "01_观测字段质控计数")
    csv(invalid, "02_硬范围异常明细")
    csv(pd.DataFrame(source_rows), "03_来源清单")
    return out, quality, {"first_active": str(start), "last_active": str(end), "nominal_rows": len(common)}, invalid


def iqr_and_scale(data: pd.DataFrame, domain: str, calibration: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Flag 1.5×IQR tails, then fit both scalers on calibration observations."""
    flags = pd.DataFrame(False, index=data.index, columns=data.columns)
    z, robust = data.copy(), data.copy()
    params = []
    for col in data:
        x = data[col]
        fit = x.loc[calibration].dropna()
        usable_groups = np.nan
        sparse_or_zero_iqr_groups = np.nan
        if domain == "time":
            # Month and hour isolate seasonal and diurnal cycles before IQR review.
            key_fit = [fit.index.month, fit.index.hour]
            reference = fit.groupby(key_fit)
            q25 = reference.quantile(.25)
            q75 = reference.quantile(.75)
            n = reference.count()
            keys = pd.MultiIndex.from_arrays([data.index.month, data.index.hour])
            q25v = pd.Series(keys.map(q25).to_numpy(), index=data.index)
            q75v = pd.Series(keys.map(q75).to_numpy(), index=data.index)
            nv = pd.Series(keys.map(n).to_numpy(), index=data.index)
            spread = q75v - q25v
            flags[col] = (nv.ge(30) & spread.gt(0) &
                          (x.lt(q25v - 1.5 * spread) | x.gt(q75v + 1.5 * spread)))
            usable_groups = int((n.ge(30) & (q75 - q25).gt(0)).sum())
            sparse_or_zero_iqr_groups = int(len(n) - usable_groups)
            if col.startswith("precip_"):
                # Rainfall is zero-inflated. In groups where ordinary IQR is
                # zero, compare positive amounts within the calendar month.
                positive = fit[fit.gt(0)]
                if len(positive) >= 30:
                    by_month = positive.groupby(positive.index.month)
                    pm25, pm75, pn = by_month.quantile(.25), by_month.quantile(.75), by_month.count()
                    months = pd.Index(data.index.month)
                    upper = pd.Series((pm75 + 1.5 * (pm75 - pm25)).reindex(months).to_numpy(), index=data.index)
                    enough = pd.Series(pn.reindex(months).to_numpy(), index=data.index).ge(30)
                    fallback = ~nv.ge(30) | ~spread.gt(0)
                    flags[col] |= fallback & enough & x.gt(upper)
        else:
            q25, q75 = fit.quantile([.25, .75]) if len(fit) else (np.nan, np.nan)
            spread = q75 - q25
            flags[col] = x.lt(q25 - 1.5 * spread) | x.gt(q75 + 1.5 * spread) if spread > 0 else False
        mean, std = fit.mean(), fit.std(ddof=0)
        median = fit.median()
        q1, q3 = fit.quantile([.25, .75]) if len(fit) else (np.nan, np.nan)
        rscale = q3 - q1
        method = "IQR"
        if not np.isfinite(rscale) or rscale <= 0:
            positive = fit[fit.gt(0)]
            if len(positive) >= 20 and fit.ge(0).all():
                rscale = positive.median()
                method = "median_positive_for_zero_inflated"
            else:
                rscale = 1.4826 * (fit - median).abs().median()
                method = "MAD_fallback"
        z[col] = (x - mean) / std if np.isfinite(std) and std > 0 else np.nan
        robust[col] = (x - median) / rscale if np.isfinite(rscale) and rscale > 0 else np.nan
        params.append(dict(domain=domain, feature=col, calibration_n=len(fit), mean=mean,
                           population_std=std, median=median, q25=q1, q75=q3,
                           robust_scale=rscale, robust_scale_method=method,
                           iqr_flagged=int(flags[col].sum()),
                           iqr_usable_month_hour_groups=usable_groups,
                           iqr_sparse_or_zero_groups=sparse_or_zero_iqr_groups,
                           iqr_rule="按月×小时1.5IQR，n≥30且IQR>0" if domain == "time" else "区域有效像元1.5IQR"))
    return flags, z, robust, pd.DataFrame(params)


def temporal() -> dict:
    raw, quality, extent, invalid = load_hourly()
    calibration = raw.index.year <= 2025
    flags, z, robust, params = iqr_and_scale(raw, "time", calibration)
    csv(raw, "04_逐小时物理特征原值", index=True, compressed=True)
    csv(flags.astype("uint8"), "05_逐小时IQR异常标记", index=True, compressed=True)
    csv(z, "06_逐小时Zscore", index=True, compressed=True)
    csv(robust, "07_逐小时稳健标准化", index=True, compressed=True)
    # Plain CSV counterparts open directly in MATLAB/Excel without gunzip.
    csv(raw, "04_逐小时物理特征原值", index=True)
    csv(flags.astype("uint8"), "05_逐小时IQR异常标记", index=True)
    csv(z, "06_逐小时Zscore", index=True)
    csv(robust, "07_逐小时稳健标准化", index=True)
    csv(params, "08_时间特征标准化参数")
    event = raw.loc[EVENT_START:EVENT_END].copy()
    event["iqr_flag_count"] = flags.loc[EVENT_START:EVENT_END].sum(axis=1)
    csv(event.reset_index(), "09_事件35小时物理特征")
    csv(flags.loc[EVENT_START:EVENT_END].astype("uint8").reset_index(), "09a_事件35小时IQR标记")
    csv(z.loc[EVENT_START:EVENT_END].reset_index(), "09b_事件35小时Zscore")
    csv(robust.loc[EVENT_START:EVENT_END].reset_index(), "09c_事件35小时稳健标准化")
    coverage = []
    for year, part in raw.groupby(raw.index.year):
        for col in raw:
            s = part[col]
            coverage.append(dict(domain="time", year=year, feature=col, active_hour_slots=len(part),
                                 numeric=int(s.notna().sum()), missing=int(s.isna().sum()),
                                 missing_rate=float(s.isna().mean()),
                                 iqr_flagged=int(flags.loc[part.index, col].sum())))
    csv(pd.DataFrame(coverage), "10_逐年缺失率与IQR计数")
    return {**extent, "features": len(raw.columns), "rows": len(raw),
            "event_rows": len(event), "event_feature_coverage": event.notna().sum().to_dict(),
            "invalid_count": len(invalid), "iqr_flagged_cells": int(flags.to_numpy().sum()),
            "parameters": params}


def flood_fill_priority(dem: np.ndarray, valid: np.ndarray, epsilon: float = .01) -> np.ndarray:
    """Priority flood; epsilon enforces a unique downslope path across flats."""
    h, w = dem.shape
    filled = dem.copy()
    seen = np.zeros((h, w), dtype=np.bool_)
    border = valid.copy()
    border[1:-1, 1:-1] &= (valid[:-2, 1:-1] & valid[2:, 1:-1] &
                           valid[1:-1, :-2] & valid[1:-1, 2:] &
                           valid[:-2, :-2] & valid[:-2, 2:] &
                           valid[2:, :-2] & valid[2:, 2:]) == False
    border[0, :] = valid[0, :]
    border[-1, :] = valid[-1, :]
    border[:, 0] = valid[:, 0]
    border[:, -1] = valid[:, -1]
    by, bx = np.nonzero(border)
    heap = [(float(dem[y, x]), int(y * w + x)) for y, x in zip(by, bx)]
    heapq.heapify(heap)
    seen[border] = True
    offsets = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
               (0, 1), (1, -1), (1, 0), (1, 1)]
    while heap:
        height, pos = heapq.heappop(heap)
        y, x = divmod(pos, w)
        for dy, dx in offsets:
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and valid[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                height_next = max(float(dem[ny, nx]), height + epsilon)
                filled[ny, nx] = height_next
                heapq.heappush(heap, (height_next, ny * w + nx))
    if not np.array_equal(seen, valid):
        raise RuntimeError("Priority flood did not visit all valid DEM cells")
    return filled


def d8_accumulation(filled: np.ndarray, valid: np.ndarray) -> np.ndarray:
    h, w = filled.shape
    dest = np.full((h, w), -1, dtype=np.int32)
    best = np.zeros((h, w), dtype=np.float32)
    ids = np.arange(h * w, dtype=np.int32).reshape(h, w)
    for dy, dx in [(-1,-1),(-1,0),(-1,1),(0,-1),(0,1),(1,-1),(1,0),(1,1)]:
        y0, y1 = max(0, -dy), min(h, h-dy)
        x0, x1 = max(0, -dx), min(w, w-dx)
        src = (slice(y0, y1), slice(x0, x1))
        dst = (slice(y0+dy, y1+dy), slice(x0+dx, x1+dx))
        gain = (filled[src] - filled[dst]) / math.hypot(dy, dx)
        improve = valid[src] & valid[dst] & (gain > best[src])
        best[src][improve] = gain[improve]
        dest[src][improve] = ids[dst][improve]
    flat = dest.ravel()
    donors = np.bincount(flat[flat >= 0], minlength=h*w).astype(np.int32)
    acc = np.zeros(h*w, dtype=np.float32)
    acc[valid.ravel()] = 1
    queue = deque(np.flatnonzero(valid.ravel() & (donors == 0)).tolist())
    processed = 0
    while queue:
        cell = queue.popleft()
        processed += 1
        downstream = flat[cell]
        if downstream >= 0:
            acc[downstream] += acc[cell]
            donors[downstream] -= 1
            if donors[downstream] == 0:
                queue.append(int(downstream))
    if processed != int(valid.sum()):
        raise RuntimeError(f"D8 cycle or unresolved flat: {processed}/{int(valid.sum())}")
    return acc.reshape(h, w)


def write_raster(path: Path, arr: np.ndarray, affine) -> None:
    with rasterio.open(path, "w", driver="GTiff", width=arr.shape[1], height=arr.shape[0],
                       count=1, dtype="float32", crs="EPSG:32645", transform=affine,
                       nodata=-9999, compress="deflate", predictor=3) as dst:
        dst.write(np.where(np.isfinite(arr), arr, -9999).astype("float32"), 1)


def spatial() -> dict:
    with rasterio.open(DEM) as src:
        affine, width, height = calculate_default_transform(
            src.crs, "EPSG:32645", src.width, src.height, *src.bounds, resolution=30)
        dem = np.full((height, width), np.nan, dtype=np.float32)
        reproject(source=rasterio.band(src, 1), destination=dem, src_transform=src.transform,
                  src_crs=src.crs, src_nodata=src.nodata, dst_transform=affine,
                  dst_crs="EPSG:32645", dst_nodata=np.nan, resampling=Resampling.bilinear)
    valid = np.isfinite(dem)
    gy, gx = np.gradient(dem, 30, 30)
    slope = np.rad2deg(np.arctan(np.hypot(gx, gy))).astype("float32")
    slope[~valid] = np.nan
    print(f"DEM projected {height}x{width}; priority flood on {int(valid.sum())} cells", flush=True)
    filled = flood_fill_priority(dem, valid)
    fill_depth = (filled - dem).astype("float32")
    accumulation = d8_accumulation(filled, valid)
    tangent = np.maximum(np.hypot(gx, gy), .001)
    # a = contributing area / grid width = contributing cells × 30 m.
    twi = np.log((accumulation * 30) / tangent).astype("float32")
    twi[~valid] = np.nan
    accumulation[~valid] = np.nan
    for name, arr in [("11_坡度_度_UTM30m.tif", slope),
                      ("12_TWI近似_D8_UTM30m.tif", twi),
                      ("13_汇流累计像元数_UTM30m.tif", accumulation),
                      ("14_填洼深度_m_UTM30m.tif", fill_depth)]:
        write_raster(OUT / name, arr, affine)

    with h5py.File(GLACIER) as f:
        x, y = f["x"][:], f["y"][:]
        mask = np.isfinite(f["glacier_mask"][:]) & (f["glacier_mask"][:] > .5)
        nc = {name: f[name][:] for name in ["dem", "slope", "thickness", "v"]}
    nx, ny = np.meshgrid(x, y)
    rr = np.floor((affine.f - ny) / 30).astype(int)
    cc = np.floor((nx - affine.c) / 30).astype(int)
    inside = (rr >= 0) & (rr < height) & (cc >= 0) & (cc < width)
    rr_safe, cc_safe = rr.clip(0, height-1), cc.clip(0, width-1)
    def sample(array):
        values = array[rr_safe, cc_safe].copy()
        values[~inside] = np.nan
        return values
    nc_affine = from_origin(float(x[0]-15), float(y[0]+15), 30, 30)
    land = np.zeros(mask.shape, dtype=np.uint8)
    with rasterio.open(LAND) as src:
        reproject(source=rasterio.band(src,1), destination=land, src_transform=src.transform,
                  src_crs=src.crs, src_nodata=src.nodata, dst_transform=nc_affine,
                  dst_crs="EPSG:32645", dst_nodata=0, resampling=Resampling.nearest)
    xx, yy = nx[mask], ny[mask]
    lon, lat = transform("EPSG:32645", "EPSG:4326", xx.tolist(), yy.tolist())
    frame = pd.DataFrame({"x_utm45_m": xx, "y_utm45_m": yy, "lon": lon, "lat": lat,
                          "terrain_slope_dem_deg": sample(slope)[mask],
                          "terrain_slope_nc_deg": nc["slope"][mask],
                          "wetness_index_twi_proxy": sample(twi)[mask],
                          "elevation_dem_m": sample(dem)[mask],
                          "elevation_nc_m": nc["dem"][mask],
                          "ice_thickness_m": nc["thickness"][mask],
                          "glacier_surface_speed_m_per_year": nc["v"][mask],
                          "landcover_code_2023": land[mask].astype(float)})
    frame.loc[frame.landcover_code_2023.eq(0), "landcover_code_2023"] = np.nan
    # Explicitly unavailable, so downstream code cannot mistake proxy fields.
    frame["factor_of_safety"] = np.nan
    frame["debris_flow_speed_m_per_s"] = np.nan
    register("terrain_slope_dem_deg", "space", "能量条件", "degree", "附件（7）DEM", "UTM30m DEM 中央差分坡度")
    register("terrain_slope_nc_deg", "space", "能量条件", "degree", "附件（4）NetCDF", "原附带坡度")
    register("wetness_index_twi_proxy", "space", "能量条件", "log(m)", "附件（7）DEM",
             "ln((D8汇流像元数×30m)/max(tan(坡度),0.001))", caveat="填洼与DEM来源未知；为地形湿润指数近似，非实测土壤湿度")
    register("elevation_dem_m", "space", "辅助条件", "m", "附件（7）DEM", "UTM30m重投影")
    register("elevation_nc_m", "space", "辅助条件", "m", "附件（4）NetCDF", "原附带高程")
    register("ice_thickness_m", "space", "物质条件", "m", "附件（4）NetCDF", "历史冰厚产品")
    register("glacier_surface_speed_m_per_year", "space", "物质条件", "m/year", "附件（4）NetCDF",
             "2014–2024冰川表面速度气候态", caveat="不是2026实时速度，更不是泥石流流速")
    register("landcover_code_2023", "space", "辅助条件", "category", "附件（5）土地覆盖",
             "最近邻重采样原始类别代码", caveat="包内缺类别代码说明；不得把类别编号当连续物理量")
    register("factor_of_safety", "space", "物质条件", "1", "无可用参数", "未计算",
             availability="unavailable", caveat="需要抗剪强度、摩擦角、黏聚力、孔压/含水条件、滑动面等")
    register("debris_flow_speed_m_per_s", "space", "触发条件", "m/s", "无实测泥石流速度", "未计算",
             availability="unavailable", caveat="冰川表面速度不可替代泥石流速度")
    csv(frame, "15_冰川源区空间物理特征")
    numeric = frame.drop(columns=["x_utm45_m", "y_utm45_m", "lon", "lat", "landcover_code_2023"])
    flags, z, robust, params = iqr_and_scale(numeric, "space", pd.Series(True, index=numeric.index))
    csv(flags.astype("uint8"), "16_空间IQR异常标记")
    csv(z, "17_空间Zscore")
    csv(robust, "18_空间稳健标准化")
    csv(params, "19_空间特征标准化参数")
    cover = pd.DataFrame([dict(domain="space", feature=col, pixels=len(frame),
                               numeric=int(frame[col].notna().sum()),
                               missing=int(frame[col].isna().sum()),
                               missing_rate=float(frame[col].isna().mean()),
                               iqr_flagged=int(flags[col].sum()) if col in flags else 0)
                          for col in [*numeric.columns, "landcover_code_2023"]])
    csv(cover, "20_源区缺失率与IQR计数")
    delta = (frame.elevation_nc_m - frame.elevation_dem_m).dropna()
    return {"projected_DEM_shape": [height,width], "projected_DEM_valid": int(valid.sum()),
            "glacier_pixels": len(frame), "landcover_valid": int(frame.landcover_code_2023.notna().sum()),
            "twi_valid": int(frame.wetness_index_twi_proxy.notna().sum()),
            "depression_fill_pixels": int(np.count_nonzero(fill_depth[valid] > .01)),
            "max_fill_depth_m": float(np.nanmax(fill_depth)),
            "nc_minus_dem_elevation_median_m": float(delta.median()) if len(delta) else None,
            "nc_minus_dem_elevation_p95_abs_m": float(delta.abs().quantile(.95)) if len(delta) else None}


def main() -> None:
    t = temporal()
    print(f"Temporal completed: {t['rows']} hours, {t['features']} features", flush=True)
    s = spatial()
    csv(pd.DataFrame(SCHEMA), "00_指标分类与可用性")
    data = {"workflow": "分类→物理特征→缺失率→IQR异常标记→Z-score及稳健标准化→分尺度建模输入",
            "time": {k:v for k,v in t.items() if k != "parameters"}, "space": s,
            "normalization": "时间标定仅用2021–2025；2026只变换不参与拟合。空间标定使用源区有效像元。异常仅标记，未静默删除或插值。",
            "blocked": ["安全系数缺物性与孔压参数", "泥石流流速无实测值", "站点纬度元数据冲突，未将时间表复制到冰川网格"],
            "source_files": {"hourly_zip": str(ARCHIVE.relative_to(ROOT)),
                             "DEM": str(DEM.relative_to(ROOT)), "glacier_nc": str(GLACIER.relative_to(ROOT)),
                             "landcover": str(LAND.relative_to(ROOT))}}
    (OUT / "21_运行摘要.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"time_rows":t["rows"], "time_features":t["features"],
                      "event_rows":t["event_rows"], **s}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
