import os, shutil, hashlib, csv, json, datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.abspath(os.path.join(ROOT, "..", ".."))
DELIV = os.path.join(WORK, "成果审查", "FLUX数据核查_20261025")
TPDC_ZIP = os.path.join(ROOT, "raw", "TPDC_5b09afd1-d11b-4150-a291-50f0484dddf1_all.zip")
TPDC_DIR = os.path.join(ROOT, "raw", "TPDC_extracted")
LOCAL_DIR = os.path.join(ROOT, "raw", "local_attachment_extracted")
LOCAL_ZIP = os.path.join(WORK, "2026年MathorCup大数据挑战赛-赛道B初赛", "附件", "（1）西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）.zip")
URL = "https://www.tpdc.ac.cn/zh-hans/data/5b09afd1-d11b-4150-a291-50f0484dddf1"
DOWNLOAD_DATE = "2026-10-25"

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def copy(src, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)

for d in ["01_网站原始下载", "02_本地比赛附件", "03_清单与哈希", "04_核查结果", "05_脚本"]:
    os.makedirs(os.path.join(DELIV, d), exist_ok=True)

# raw zips
copy(TPDC_ZIP, os.path.join(DELIV, "01_网站原始下载", os.path.basename(TPDC_ZIP)))
copy(LOCAL_ZIP, os.path.join(DELIV, "02_本地比赛附件", os.path.basename(LOCAL_ZIP)))

# extracted files
for src_dir, dst_dir in [
    (TPDC_DIR, os.path.join(DELIV, "01_网站原始下载", "TPDC_21文件")),
    (LOCAL_DIR, os.path.join(DELIV, "02_本地比赛附件", "全部24文件")),
]:
    os.makedirs(dst_dir, exist_ok=True)
    for name in sorted(os.listdir(src_dir)):
        p = os.path.join(src_dir, name)
        if os.path.isfile(p):
            copy(p, os.path.join(dst_dir, name))

# FLUX 2021-2026 convenience copy
flux_dst = os.path.join(DELIV, "02_本地比赛附件", "FLUX_2021-2026")
os.makedirs(flux_dst, exist_ok=True)
for y in range(2021, 2027):
    name = f"FLUX_Gyirong_{y}.csv"
    copy(os.path.join(LOCAL_DIR, name), os.path.join(flux_dst, name))

# analysis results
for name in [
    "metadata_summary.json", "metadata_summary.md", "metadata_detail.json", "tpdc_file_list.json",
    "file_hash_comparison.csv", "audit/flux_field_summary.csv", "audit/flux_event_window_35h.csv",
    "audit/flux_sign_diurnal.csv", "audit/flux_quality_anomalies.csv", "audit/flux_vpd_consistency.csv",
    "audit/flux_2026_cutoff.csv", "audit/flux_2026_nominal_coverage.csv",
]:
    src = os.path.join(ROOT, name)
    if os.path.exists(src):
        copy(src, os.path.join(DELIV, "04_核查结果", os.path.basename(name)))

# scripts
for name in ["download_tpdc.py", "extract_and_hash.py", "audit_flux.py", "quality_checks.py", "make_summary.py", "make_delivery.py"]:
    src = os.path.join(ROOT, name)
    if os.path.exists(src):
        copy(src, os.path.join(DELIV, "05_脚本", name))

# build unified file manifest
rows = []
for y in range(2021, 2027):
    for product in ["FLUX", "MET", "RADM", "SOIL"]:
        name = f"{product}_Gyirong_{y}.csv"
        wp = os.path.join(TPDC_DIR, name); lp = os.path.join(LOCAL_DIR, name)
        w = os.path.exists(wp); l = os.path.exists(lp)
        if not (w or l):
            continue
        sw = sha256(wp) if w else ""
        sl = sha256(lp) if l else ""
        size = os.path.getsize(wp) if w else os.path.getsize(lp)
        if w and l:
            src = "TPDC网站 + 本地比赛附件"
            note = "网站与本地附件 SHA256 完全一致" if sw == sl else "网站与本地附件 SHA256 不一致"
            identical = "是" if sw == sl else "否"
        elif w:
            src = "TPDC网站"
            note = "仅网站提供"
            identical = "不适用"
        else:
            src = "本地比赛附件（1）"
            note = "网站文件列表中无此文件；本地附件独有"
            identical = "不适用"
        rows.append({
            "产品": product, "年份": y, "文件名": name,
            "网站是否提供": "是" if w else "否",
            "本地附件是否提供": "是" if l else "否",
            "来源页面/文件": URL if w else "2026年MathorCup大数据挑战赛-赛道B初赛/附件/（1）西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）.zip",
            "下载日期": DOWNLOAD_DATE if w else "不适用（本地附件）",
            "大小(字节)": size,
            "SHA256(网站)": sw, "SHA256(本地)": sl,
            "两者一致": identical, "备注": note,
        })

with open(os.path.join(DELIV, "03_清单与哈希", "文件清单_网站与本地对照.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)

# zip manifest
zip_rows = [
    {"压缩包": os.path.basename(TPDC_ZIP), "来源": URL,
     "获取方式": "页面“免登录下载”公开接口 /file/file/batchDownloadFile?metadataId=5b09afd1-d11b-4150-a291-50f0484dddf1",
     "下载日期": DOWNLOAD_DATE, "大小(字节)": os.path.getsize(TPDC_ZIP), "SHA256": sha256(TPDC_ZIP),
     "成员数": 21, "说明": "网站正常下载入口；未使用账号、未绕过登录/授权"},
    {"压缩包": os.path.basename(LOCAL_ZIP), "来源": "本地比赛附件（1）",
     "获取方式": "比赛附件原件（未改动）", "下载日期": "不适用（本地附件）",
     "大小(字节)": os.path.getsize(LOCAL_ZIP), "SHA256": sha256(LOCAL_ZIP),
     "成员数": 24, "说明": "含 FLUX 2021–2026；ZIP 内文件时间为 2026-09-30 20:05–20:07"},
]
with open(os.path.join(DELIV, "03_清单与哈希", "压缩包清单.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(zip_rows[0].keys())); w.writeheader(); w.writerows(zip_rows)

# README
with open(os.path.join(DELIV, "README_文件说明.md"), "w", encoding="utf-8") as f:
    f.write("# FLUX 数据核查交付包\n\n")
    f.write(f"核查日期：{DOWNLOAD_DATE}（北京时间）\n\n")
    f.write("## 结论先行\n\n")
    f.write("- TPDC 网站元数据标题确为“西藏吉隆高寒山区地气相互作用逐小时综合观测数据集（2021–2026）”，DOI 10.11888/Atmos.tpdc.303600。\n")
    f.write("- 但网站文件列表只有 21 个文件；FLUX 仅 2021、2022、2023 三年，**没有 FLUX 2024、2025、2026**。\n")
    f.write("- 网站 21 个文件与本地比赛附件（1）中的同名文件 SHA256 全部一致；本地附件另有 FLUX 2024–2026 三个文件，为网站未提供的部分。\n")
    f.write("- 2026-08-25 00:00 至 2026-08-26 10:00 的 35 个时标内，LE、H、USTAR、TKE、VPD 均为 35/35 有数值（100%），无 9999.9/NaN；但 FLUX 文件没有 QC 列，不能据此认定质量全部合格。\n\n")
    f.write("## 目录\n\n")
    f.write("- `01_网站原始下载/`：网站下载的原始 ZIP（21 文件）及其解压副本。\n")
    f.write("- `02_本地比赛附件/`：比赛附件（1）原始 ZIP、全部 24 个解压文件、六个 FLUX 文件的便捷副本。\n")
    f.write("- `03_清单与哈希/`：文件清单、网站/本地对照、压缩包 SHA256。\n")
    f.write("- `04_核查结果/`：元数据原文与摘要、字段统计、35 小时窗口、质量异常、VPD 一致性、2026 截止位置。\n")
    f.write("- `05_脚本/`：获取、解压、哈希与统计脚本（可复现）。\n\n")
    f.write("## 重要提醒\n\n")
    f.write("- CSV 内容、时间标签、缺测符号均未清洗、未插值、未改动。解压副本的文件系统修改时间为解压时间，不代表数据时间。\n")
    f.write("- 网站没有提供 FLUX 2024–2026；这三个文件来自本地比赛附件，不能写成“网站下载”。\n")
    f.write("- 2026 年文件按全年 8760 个时标给出，但 8 月 27 日之后为 NaN；不能把全年时标数当作有效观测数。\n")

print("DELIV", DELIV)
for r in rows:
    print(r["产品"], r["年份"], r["网站是否提供"], r["本地附件是否提供"], r["大小(字节)"], r["两者一致"])
print("zip hashes:")
for z in zip_rows:
    print(z["压缩包"], z["大小(字节)"], z["SHA256"])
