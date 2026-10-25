import os, csv, math, datetime, statistics, json, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
LOCAL = os.path.join(ROOT, "raw", "local_attachment_extracted")
OUT = os.path.join(ROOT, "audit")
FIELDS = ["LE(W/m2)", "H(W/m2)", "USTAR(m/s)", "TKE(m2/s2)", "VPD(hPa)"]
EVENT_START = datetime.datetime(2026, 8, 25, 0, 0)
EVENT_END = datetime.datetime(2026, 8, 26, 10, 0)

def parse_ts(s):
    return datetime.datetime.strptime(s.strip(), "%Y/%m/%d %H:%M")

def load(year):
    p = os.path.join(LOCAL, f"FLUX_Gyirong_{year}.csv")
    with open(p, encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f); h = next(r); rows = [x for x in r if x and any(c.strip() for c in x)]
    return h, rows

def num(s):
    s = s.strip()
    if s == "" or s.lower() == "nan": return None
    try: v = float(s)
    except: return None
    if not math.isfinite(v) or v == 9999.9: return None
    return v

anoms = []
vpd_err = []
cutoff = []
coverage = []
for year in range(2021, 2027):
    h, rows = load(year)
    idx = {k: i for i, k in enumerate(h)}
    ts = [parse_ts(r[0]) for r in rows]
    d = dict(year=year, records=len(rows))
    # extremes / anomalies
    for fld, cond, label in [
        ("VPD(hPa)", lambda v: v < 0, "VPD<0"),
        ("VPD(hPa)", lambda v: v > 100, "VPD>100hPa"),
        ("LE(W/m2)", lambda v: abs(v) > 1000, "abs(LE)>1000"),
        ("H(W/m2)", lambda v: abs(v) > 800, "abs(H)>800"),
        ("USTAR(m/s)", lambda v: v == 0, "USTAR==0"),
        ("TKE(m2/s2)", lambda v: v == 0, "TKE==0"),
        ("USTAR(m/s)", lambda v: v < 0, "USTAR<0"),
        ("TKE(m2/s2)", lambda v: v < 0, "TKE<0"),
    ]:
        j = idx[fld]
        hits = [(t, num(r[j])) for t, r in zip(ts, rows) if num(r[j]) is not None and cond(num(r[j]))]
        anoms.append(dict(year=year, field=fld, rule=label, count=len(hits),
                          first=hits[0][0] if hits else "", last=hits[-1][0] if hits else "",
                          min=min(v for _, v in hits) if hits else "", max=max(v for _, v in hits) if hits else ""))
    # VPD consistency
    if all(k in idx for k in ["e(kPa)", "e_sat(kPa)", "VPD(hPa)"]):
        errs = []
        for t, r in zip(ts, rows):
            e, es, vpd = num(r[idx["e(kPa)"]]), num(r[idx["e_sat(kPa)"]]), num(r[idx["VPD(hPa)"]])
            if None not in (e, es, vpd):
                errs.append((abs((es - e) * 10 - vpd), t, vpd, (es - e) * 10))
        errs.sort(reverse=True)
        vpd_err.append(dict(year=year, n=len(errs), max_abs_error=errs[0][0] if errs else None,
                            max_error_time=errs[0][1] if errs else None,
                            vpd_at_max=errs[0][2] if errs else None,
                            computed_at_max=errs[0][3] if errs else None,
                            n_error_gt_0_01=sum(1 for x in errs if x[0] > 0.01),
                            n_error_gt_0_1=sum(1 for x in errs if x[0] > 0.1)))
    # trailing NaN / cutoff
    if year == 2026:
        for fld in FIELDS:
            j = idx[fld]
            ok = [t for t, r in zip(ts, rows) if num(r[j]) is not None]
            last = ok[-1] if ok else None
            after = sum(1 for t, r in zip(ts, rows) if last and t > last and num(r[j]) is None)
            cutoff.append(dict(field=fld, first_valid=min(ok) if ok else None, last_valid=last,
                               n_numeric=len(ok), trailing_missing_after_last=after))
        # coverage within Jan 1 - Aug 27 08:00 nominal window
        nominal_end = datetime.datetime(2026, 8, 27, 8, 0)
        for fld in FIELDS:
            j = idx[fld]
            sub = [(t, num(r[j])) for t, r in zip(ts, rows) if t <= nominal_end]
            nn = sum(1 for _, v in sub if v is not None)
            coverage.append(dict(year=2026, window=f"2026-01-01 00:00..2026-08-27 08:00", field=fld,
                                 slots=len(sub), numeric=nn, coverage=round(nn/len(sub), 4)))
    if year == 2022:
        # last valid across LE/H/VPD and gap
        pass

# 2022 gap details
h, rows = load(2022); idx = {k:i for i,k in enumerate(h)}; ts=[parse_ts(r[0]) for r in rows]
for fld in ["LE(W/m2)", "H(W/m2)", "USTAR(m/s)", "VPD(hPa)"]:
    ok=[t for t,r in zip(ts,rows) if num(r[idx[fld]]) is not None]
    anoms.append(dict(year=2022, field=fld, rule="last_valid_in_year", count=1, first="", last=ok[-1] if ok else "",
                      min="", max=""))
    anoms.append(dict(year=2022, field=fld, rule="numeric_after_last_valid", count=sum(1 for t,r in zip(ts,rows) if ok and t>ok[-1] and num(r[idx[fld]]) is not None),
                      first="", last="", min="", max=""))

# 2021 first valid vs metadata start
h, rows = load(2021); idx = {k:i for i,k in enumerate(h)}; ts=[parse_ts(r[0]) for r in rows]
for fld in FIELDS:
    ok=[t for t,r in zip(ts,rows) if num(r[idx[fld]]) is not None]
    anoms.append(dict(year=2021, field=fld, rule="first_valid_in_year", count=1, first=ok[0] if ok else "", last="", min="", max=""))

# event window physical range
h, rows = load(2026); idx = {k:i for i,k in enumerate(h)}
by = {parse_ts(r[0]): r for r in rows}
print("=== EVENT PHYSICAL SCREEN ===")
for fld in FIELDS:
    vals=[num(by[t][idx[fld]]) for t in sorted(by) if EVENT_START <= t <= EVENT_END]
    vals=[v for v in vals if v is not None]
    print(fld, "n", len(vals), "min", min(vals), "max", max(vals), "mean", statistics.fmean(vals))

print("\n=== CUTOFF 2026 ===")
for x in cutoff: print(x)
print("\n=== COVERAGE 2026 NOMINAL ===")
for x in coverage: print(x)
print("\n=== VPD CONSISTENCY ===")
for x in vpd_err: print(x)
print("\n=== ANOMALIES ===")
for x in anoms: print(x)

with open(os.path.join(OUT, "flux_quality_anomalies.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w=csv.DictWriter(f, fieldnames=list(anoms[0].keys())); w.writeheader(); w.writerows(anoms)
with open(os.path.join(OUT, "flux_vpd_consistency.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w=csv.DictWriter(f, fieldnames=list(vpd_err[0].keys())); w.writeheader(); w.writerows(vpd_err)
with open(os.path.join(OUT, "flux_2026_cutoff.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w=csv.DictWriter(f, fieldnames=list(cutoff[0].keys())); w.writeheader(); w.writerows(cutoff)
with open(os.path.join(OUT, "flux_2026_nominal_coverage.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w=csv.DictWriter(f, fieldnames=list(coverage[0].keys())); w.writeheader(); w.writerows(coverage)
