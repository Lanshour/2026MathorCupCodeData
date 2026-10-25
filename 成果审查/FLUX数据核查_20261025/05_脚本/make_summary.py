import json, os

ROOT = os.path.dirname(os.path.abspath(__file__))
j = json.load(open(os.path.join(ROOT, "metadata_detail.json"), encoding="utf-8"))
c = j["context"]; m = c["metadataVO"]
authors = [{
    "name": a.get("name"), "nameEn": a.get("nameEn"), "unit": a.get("unit"),
    "unitEn": a.get("unitEn"), "email": a.get("email"), "orcid": a.get("orcid")
} for a in (c.get("authorVOList") or [])]
out = {
    "source_page": "https://www.tpdc.ac.cn/zh-hans/data/5b09afd1-d11b-4150-a291-50f0484dddf1",
    "api": "https://data.tpdc.ac.cn/view/metadataView/detail/",
    "id": m.get("id"), "title": m.get("title"), "titleEn": m.get("titleEn"),
    "doi": m.get("doi"), "cstr": m.get("cstr"),
    "publisher_platform": "国家青藏高原科学数据中心 / National Tibetan Plateau Data Center",
    "authors": authors,
    "project": c.get("projectVOList"),
    "fund": c.get("fundVOList"),
    "tsCreated": m.get("tsCreated"), "tsUpdated": m.get("tsUpdated"), "tsPublish": m.get("tsPublish"),
    "startTime": m.get("startTime"), "endTime": m.get("endTime"),
    "temporalResolution": m.get("temporalResolution"),
    "coordinates": {"west": m.get("west"), "east": m.get("east"), "south": m.get("south"), "north": m.get("north")},
    "fileSize": m.get("fileSize"), "shareType": m.get("shareType"), "sharePolicy": m.get("sharePolicy"),
    "instructions": m.get("instructions"),
    "description_zh": m.get("description"),
    "description_en": c.get("metadataWordVO", {}).get("description"),
    "metadataAttachments": c.get("metadataAttachments"),
}
with open(os.path.join(ROOT, "metadata_summary.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
with open(os.path.join(ROOT, "metadata_summary.md"), "w", encoding="utf-8") as f:
    f.write("# TPDC 元数据摘要\n\n")
    f.write(f"- 来源页面: {out['source_page']}\n- 数据集ID: {out['id']}\n- 标题: {out['title']}\n- 英文标题: {out['titleEn']}\n")
    f.write(f"- DOI: {out['doi']}\n- CSTR: {out['cstr']}\n- 平台: {out['publisher_platform']}\n")
    f.write(f"- 创建/更新/发布: {out['tsCreated']} / {out['tsUpdated']} / {out['tsPublish']}\n")
    f.write(f"- 声明时段: {out['startTime']} 至 {out['endTime']}，{out['temporalResolution']}\n")
    f.write(f"- 声明坐标: {out['coordinates']}\n- 文件总大小: {out['fileSize']}\n- 共享方式: {out['shareType']} / {out['sharePolicy']}\n\n")
    f.write("## 作者/单位\n\n")
    for a in authors:
        f.write(f"- {a['name']} ({a['nameEn']}) — {a['unit']} / {a['unitEn']} — {a['email']}\n")
    f.write("\n## 数据说明（中文原文）\n\n")
    f.write(out["description_zh"] or "")
    f.write("\n\n## 数据说明（英文原文）\n\n")
    f.write(out["description_en"] or "")
    f.write("\n\n## 文件命名与缺测说明（中文原文）\n\n")
    f.write(out["instructions"] or "")
    f.write("\n\n## 附件\n\n")
    f.write(json.dumps(out["metadataAttachments"], ensure_ascii=False))
    f.write("\n")
print("written")
