import pathlib,json,hashlib,datetime,concurrent.futures,subprocess
base=pathlib.Path("/Users/yuangzhou/Desktop/tideStone-root/Projects/companies/300750.SZ/研究档案/_pending/2026-10-24T14-51-54-994665Z")
out=base/"_evidence/03_A3"
sources=[["sne_2026_08.html","https://www.sneresearch.com/en/insight/release_view/744/page/0?s_cat=%7C&s_keyword="],["calb_2025.pdf","https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0429/2026042900020_c.pdf"],["eve_2025.pdf","https://static.cninfo.com.cn/finalpage/2026-03-28/1225045391.PDF"],["eve_2026h1.pdf","https://disc.static.szse.cn/download/disc/disk03/finalpage/2026-08-20/65c64f9e-abde-4f3f-af3e-3239b8975341.PDF"],["byd_2025.pdf","https://static.cninfo.com.cn/finalpage/2026-03-28/1225045351.PDF"],["sdi_2025.pdf","https://www.samsungsdi.com/upload/download/ir/2025.4Q_IR_Final_En.pdf"],["lges_2025.html","https://kind.krx.co.kr/external/2026/02/13/001136/20260213002784/00591.htm"],["lges_2026q2.html","https://lgcorp.com/media/release/30412"],["iea_2026_battery.html","https://www.iea.org/reports/global-ev-outlook-2026/electric-vehicle-batteries"],["infolink_2026h1.html","https://www.infolink-group.com/energy-article/cn/energy-storage-topic-global-battery-shipment-ranking-1H26"],["bmw_solid.html","https://www.press.bmwgroup.com/global/article/detail/T0453689EN/bmw-group-and-solid-power-take-next-step-in-assb-development-path%3A-new-partner-samsung-sdi-joins-the-effort?language=en"],["iea_flexibility.html","https://www.iea.org/reports/electricity-2026/flexibility"],["byd_about.html","https://www.byd.com/en/about-byd"],["lges_mercedes.html","https://www.lg.com/global/newsroom/news/corporate/lg-and-mercedes-benz-discuss-expanding-one-lg-solution-collaboration/"],["catl_bmw.html","https://www.catl.com/en/news/1016.html"],["sdi_2026q2.html","https://www.samsungsdi.co.kr/sdi-now/sdi-news/4941.html"]]
def fetch(x):
 name,url=x
 try:
  subprocess.run(["curl","-L","--fail","--silent","--show-error","--max-time","35",url,"-o",str(out/name)],check=True,capture_output=True)
  data=(out/name).read_bytes()
  return {"file":name,"url":url,"retrieved_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest(),"transport":"curl TLS verification enabled"}
 except Exception as e:return {"file":name,"url":url,"error":str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex: rows=list(ex.map(fetch,sources))
(out/"sources.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps(rows,ensure_ascii=False,indent=2))

