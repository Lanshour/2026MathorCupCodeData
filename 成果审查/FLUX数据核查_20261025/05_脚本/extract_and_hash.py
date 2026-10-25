import os, zipfile, hashlib, json, csv, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, "raw")
TPDC_ZIP = os.path.join(RAW, "TPDC_5b09afd1-d11b-4150-a291-50f0484dddf1_all.zip")
LOCAL_ZIP = os.path.abspath(os.path.join(ROOT, "..", "..", "2026年MathorCup大数据挑战赛-赛道B初赛", "附件", "（1）西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）.zip"))
TPDC_DIR = os.path.join(RAW, "TPDC_extracted")
LOCAL_DIR = os.path.join(RAW, "local_attachment_extracted")

def sha256(path, bufsize=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b: break
            h.update(b)
    return h.hexdigest()

def safe_extract_flat(z, dest):
    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(dest, exist_ok=True)
    for info in z.infolist():
        name = info.filename
        if name.endswith("/"):
            continue
        parts = name.replace("\\", "/").split("/")
        if name.startswith("/") or ".." in parts:
            raise ValueError("unsafe zip member: " + name)
        out = os.path.join(dest, parts[-1])
        with z.open(info) as src, open(out, "wb") as dst:
            shutil.copyfileobj(src, dst)

for zp, dest, label in [(TPDC_ZIP, TPDC_DIR, "TPDC"), (LOCAL_ZIP, LOCAL_DIR, "LOCAL")]:
    print("=" * 70)
    print(label, zp)
    print("zip size", os.path.getsize(zp), "sha256", sha256(zp))
    with zipfile.ZipFile(zp) as z:
        bad = z.testzip()
        print("members", len(z.infolist()), "testzip", bad)
        for i in z.infolist():
            print(f"  {i.filename}\t{i.file_size}\t{i.date_time}\tCRC={i.CRC:08x}")
        safe_extract_flat(z, dest)
    print("extracted to", dest)

print("\n" + "=" * 70)
print("FILE HASH COMPARISON")
print("name,website_size,website_sha256,local_size,local_sha256,same")
rows = []
for name in sorted(set(os.listdir(TPDC_DIR)) | set(os.listdir(LOCAL_DIR))):
    p1 = os.path.join(TPDC_DIR, name); p2 = os.path.join(LOCAL_DIR, name)
    s1 = sha256(p1) if os.path.isfile(p1) else ""
    s2 = sha256(p2) if os.path.isfile(p2) else ""
    z1 = os.path.getsize(p1) if os.path.isfile(p1) else ""
    z2 = os.path.getsize(p2) if os.path.isfile(p2) else ""
    same = "YES" if s1 and s2 and s1 == s2 else ("NO" if s1 and s2 else "ONLY_ONE")
    print(f"{name},{z1},{s1},{z2},{s2},{same}")
    rows.append(dict(name=name, website_size=z1, website_sha256=s1, local_size=z2, local_sha256=s2, same=same))
with open(os.path.join(ROOT, "file_hash_comparison.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    w.writeheader(); w.writerows(rows)
