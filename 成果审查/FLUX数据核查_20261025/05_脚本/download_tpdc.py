import json, urllib.request, urllib.error, hashlib, os, sys, csv, io, zipfile

META = "5b09afd1-d11b-4150-a291-50f0484dddf1"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
ROOT = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(ROOT, "raw")
os.makedirs(RAW, exist_ok=True)

def req(path, data=None, method=None, timeout=180):
    url = "https://data.tpdc.ac.cn/file/file" + path
    body = None
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
        method = method or "POST"
    r = urllib.request.Request(url, data=body, headers=headers, method=method or "GET")
    return urllib.request.urlopen(r, timeout=timeout)

def get_root():
    with req(f"/getRootFileDataList?metadataId={META}") as r:
        raw = r.read()
    return json.loads(raw.decode("utf-8"))

def main():
    j = get_root()
    files = j["data"]
    files.sort(key=lambda x: x["name"])
    with open(os.path.join(ROOT, "tpdc_file_list.json"), "w", encoding="utf-8") as f:
        json.dump(j, f, ensure_ascii=False, indent=2)
    print(f"code={j['code']} n={len(files)}")
    for x in files:
        print(f"{x['name']}\t{x['size']}\t{x['id']}\t{x.get('tsCreated')}\t{x.get('path')}")
    # download all as one zip through the normal dataset download entry
    out = os.path.join(RAW, f"TPDC_{META}_all.zip")
    if os.path.exists(out) and os.path.getsize(out) > 0:
        print("EXISTS", out, os.path.getsize(out))
        return
    with req(f"/batchDownloadFile?metadataId={META}", {"noToken": True}) as r:
        ctype = r.headers.get("Content-Type")
        disp = r.headers.get("Content-Disposition")
        data = r.read()
        print("BATCH", r.status, ctype, disp, len(data))
    with open(out, "wb") as f:
        f.write(data)
    print("SAVED", out, len(data), hashlib.sha256(data).hexdigest())

if __name__ == "__main__":
    main()
