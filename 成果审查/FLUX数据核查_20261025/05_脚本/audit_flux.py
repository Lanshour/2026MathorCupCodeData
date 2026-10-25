import os, csv, math, json, statistics, datetime, collections

ROOT = os.path.dirname(os.path.abspath(__file__))
TPDC = os.path.join(ROOT, "raw", "TPDC_extracted")
LOCAL = os.path.join(ROOT, "raw", "local_attachment_extracted")
OUT = os.path.join(ROOT, "audit")
os.makedirs(OUT, exist_ok=True)

FIELDS = ["LE(W/m2)", "H(W/m2)", "USTAR(m/s)", "TKE(m2/s2)", "VPD(hPa)"]
EVENT_START = datetime.datetime(2026, 8, 25, 0, 0)
EVENT_END = datetime.datetime(2026, 8, 26, 10, 0)
MISSING = 9999.9

def parse_ts(s):
    s = s.strip().replace("\\", "/")
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.datetime.strptime(s, fmt)
        except ValueError:
            pass
    raise ValueError("bad timestamp: " + repr(s))

def load(path):
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        r = csv.reader(f)
        header = next(r)
        rows = [row for row in r if row and any(c.strip() for c in row)]
    return header, rows

def numeric(s):
    """Return (is_numeric, value, flag). Numeric means parseable, finite, and not the 9999.9 missing sentinel."""
    s = s.strip()
    if s == "":
        return False, None, "blank"
    sl = s.lower()
    if sl in ("nan", "n/a", "na", "null", "none"):
        return False, None, "NaN/text"
    try:
        v = float(s)
    except ValueError:
        return False, None, "text"
    if not math.isfinite(v):
        return False, None, "non-finite"
    if v == MISSING:
        return False, v, "9999.9"
    return True, v, ""

def quartiles(vals):
    if not vals:
        return (None, None, None)
    vals = sorted(vals)
    n = len(vals)
    def q(p):
        k = (n - 1) * p
        f = math.floor(k); c = math.ceil(k)
        return vals[f] if f == c else vals[f] * (c - k) + vals[c] * (k - f)
    return q(0.05), q(0.5), q(0.95)

summary = []
event_rows = []
sign_stats = []
for year in range(2021, 2027):
    path = os.path.join(LOCAL, f"FLUX_Gyirong_{year}.csv")
    exists_local = os.path.exists(path)
    path_w = os.path.join(TPDC, f"FLUX_Gyirong_{year}.csv")
    exists_web = os.path.exists(path_w)
    print("=" * 80)
    print(f"YEAR {year} local={exists_local} website={exists_web} file={path if exists_local else path_w}")
    if not (exists_local or exists_web):
        print("NOT AVAILABLE")
        continue
    p = path if exists_local else path_w
    header, rows = load(p)
    print("columns", len(header))
    print("header", ",".join(header))
    print("records", len(rows))
    bad_width = sum(1 for row in rows if len(row) != len(header))
    print("rows_with_wrong_width", bad_width)
    ts = [parse_ts(row[0]) for row in rows]
    print("first_label", ts[0], "last_label", ts[-1])
    dup = len(ts) - len(set(ts))
    print("duplicate_timestamps", dup)
    # expected hourly labels between first and last
    exp = int((ts[-1] - ts[0]).total_seconds() // 3600) + 1
    labelset = set(ts)
    missing_labels = [ts[0] + datetime.timedelta(hours=i) for i in range(exp) if (ts[0] + datetime.timedelta(hours=i)) not in labelset]
    print("expected_hourly_slots", exp, "missing_slots", len(missing_labels))
    print("anomalous_order", sum(1 for a, b in zip(ts, ts[1:]) if b != a + datetime.timedelta(hours=1)))

    idx = {h: i for i, h in enumerate(header)}
    for fld in FIELDS:
        if fld not in idx:
            print("FIELD MISSING", fld)
            continue
        j = idx[fld]
        flags = collections.Counter()
        vals = []
        first_valid = last_valid = None
        for t, row in zip(ts, rows):
            ok, v, flag = numeric(row[j])
            flags[flag or "numeric"] += 1
            if ok:
                vals.append(v)
                if first_valid is None: first_valid = t
                last_valid = t
        q05, q50, q95 = quartiles(vals)
        rec = dict(year=year, field=fld, records=len(rows), numeric=len(vals), coverage=round(len(vals)/len(rows), 4),
                   sentinel_9999_9=flags["9999.9"], nan_text=flags["NaN/text"], blank=flags["blank"],
                   text=flags["text"], non_finite=flags["non-finite"],
                   min=min(vals) if vals else None, p05=q05, median=q50, mean=round(statistics.fmean(vals), 6) if vals else None,
                   p95=q95, max=max(vals) if vals else None,
                   first_valid=first_valid, last_valid=last_valid,
                   negative=sum(1 for v in vals if v < 0), positive=sum(1 for v in vals if v > 0), zero=sum(1 for v in vals if v == 0))
        summary.append(rec)
        print(f"{fld}: numeric={len(vals)}/{len(rows)} ({len(vals)/len(rows):.2%}) 9999.9={flags['9999.9']} NaN={flags['NaN/text']} blank={flags['blank']} "
              f"min={rec['min']} med={rec['median']} max={rec['max']} first={first_valid} last={last_valid} neg={rec['negative']} pos={rec['positive']}")

    # event window
    if year == 2026:
        by_ts = dict(zip(ts, rows))
        t = EVENT_START
        while t <= EVENT_END:
            row = by_ts.get(t)
            if row is None:
                event_rows.append(dict(timestamp=t, present="NO"))
            else:
                rec = dict(timestamp=t, present="YES")
                for fld in FIELDS:
                    ok, v, flag = numeric(row[idx[fld]])
                    rec[fld] = v if ok else ""
                    rec[fld + "_status"] = "numeric" if ok else flag
                event_rows.append(rec)
            t += datetime.timedelta(hours=1)
        # sign / diurnal inference
        for fld in ["LE(W/m2)", "H(W/m2)"]:
            j = idx[fld]
            day = []; night = []
            for t, row in zip(ts, rows):
                ok, v, flag = numeric(row[j])
                if not ok: continue
                if 10 <= t.hour <= 16: day.append(v)
                if t.hour <= 5 or t.hour >= 21: night.append(v)
            sign_stats.append(dict(field=fld, daytime_n=len(day), daytime_mean=round(statistics.fmean(day), 4) if day else None,
                                   night_n=len(night), night_mean=round(statistics.fmean(night), 4) if night else None,
                                   daytime_positive=sum(1 for v in day if v > 0), night_negative=sum(1 for v in night if v < 0)))

with open(os.path.join(OUT, "flux_field_summary.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(summary[0].keys())); w.writeheader(); w.writerows(summary)
with open(os.path.join(OUT, "flux_event_window_35h.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(event_rows[0].keys())); w.writeheader(); w.writerows(event_rows)
with open(os.path.join(OUT, "flux_sign_diurnal.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(sign_stats[0].keys())); w.writeheader(); w.writerows(sign_stats)

print("\n=== EVENT WINDOW SUMMARY ===")
for fld in FIELDS:
    n = sum(1 for r in event_rows if r.get(fld + "_status") == "numeric")
    print(fld, "numeric", n, "/", len(event_rows))
print("event rows", len(event_rows), event_rows[0]["timestamp"], event_rows[-1]["timestamp"])
print("\n=== EVENT DATA ===")
for r in event_rows:
    print(r["timestamp"].strftime("%Y-%m-%d %H:%M"), *(r.get(f, "") for f in FIELDS))
