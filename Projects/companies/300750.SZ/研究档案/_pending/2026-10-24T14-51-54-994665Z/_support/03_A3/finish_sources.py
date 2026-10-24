import pathlib,json,hashlib,datetime,subprocess,concurrent.futures
out=pathlib.Path("/Users/yuangzhou/Desktop/tideStone-root/Projects/companies/300750.SZ/研究档案/_pending/2026-10-24T14-51-54-994665Z")/"_evidence/03_A3"
sources=[["cnevpost_2025.html","https://cnevpost.com/2026/02/04/global-ev-battery-market-share-2025/"],["infolink_2025.html","https://www.infolink-group.com/latest-event/global_energy_Storage_surges_61_in_2025_infolink_forecasts_350_gwh_installation"],["iea_es_types.html","https://iea-es.org/electrical-storage/"]]
def f(x):
 n,u=x
 try:
  subprocess.run(["curl","-L","--fail","--silent","--show-error","--max-time","20",u,"-o",str(out/n)],check=True,capture_output=True)
  d=(out/n).read_bytes()
  return {"file":n,"url":u,"retrieved_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"bytes":len(d),"sha256":hashlib.sha256(d).hexdigest(),"transport":"curl TLS verification enabled"}
 except Exception as e:return {"file":n,"url":u,"error":str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex: rows=list(ex.map(f,sources))
old=json.loads((out/"sources.json").read_text());(out/"sources.json").write_text(json.dumps(old+rows,ensure_ascii=False,indent=2))
inv=[{"file":str(p.relative_to(out)),"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(out.iterdir()) if p.is_file() and p.name!="file_inventory.json"]
(out/"file_inventory.json").write_text(json.dumps(inv,ensure_ascii=False,indent=2))
print(json.dumps(rows,ensure_ascii=False))

