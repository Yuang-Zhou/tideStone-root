import pathlib,json,hashlib,datetime,subprocess,concurrent.futures
out=pathlib.Path("/Users/yuangzhou/Desktop/tideStone-root/Projects/companies/300750.SZ/研究档案/_pending/2026-10-24T14-51-54-994665Z")/"_evidence/07_market";out.mkdir(parents=True,exist_ok=True)
sources=[["eve_stats.html","https://stockanalysis.com/quote/she/300014/statistics/"],["eve_income.html","https://stockanalysis.com/quote/she/300014/financials/"],["eve_cash.html","https://stockanalysis.com/quote/she/300014/financials/cash-flow-statement/"],["calb_stats.html","https://stockanalysis.com/quote/hkg/3931/statistics/"],["calb_income.html","https://stockanalysis.com/quote/hkg/3931/financials/"],["calb_cash.html","https://stockanalysis.com/quote/hkg/3931/financials/cash-flow-statement/"],["lges_stats.html","https://stockanalysis.com/quote/krx/373220/statistics/"],["lges_income.html","https://stockanalysis.com/quote/krx/373220/financials/"],["lges_cash.html","https://stockanalysis.com/quote/krx/373220/financials/cash-flow-statement/"],["sdi_stats.html","https://stockanalysis.com/quote/krx/006400/statistics/"],["sdi_income.html","https://stockanalysis.com/quote/krx/006400/financials/"],["sdi_cash.html","https://stockanalysis.com/quote/krx/006400/financials/cash-flow-statement/"],["catl_stats.html","https://stockanalysis.com/quote/she/300750/statistics/"],["sdi_ir_quote.html","https://ir.gsifn.io/samsungsdi/ir3_current_daily.html?koreng=1"],["sdi_q1_2026.pdf","https://www.samsungsdi.co.kr/upload/download/ir/SDI_Report_01_2026.05.15_kor.pdf"],["eve_q3_2026.pdf","https://static.cninfo.com.cn/finalpage/2026-10-24/1225620235.PDF"],["lges_annual_2025.pdf","https://www.lgensol.com/upload/file/download/2025_LGES_Annual_Report.pdf"]]
def f(x):
 n,u=x
 try:
  subprocess.run(["curl","-L","--fail","--silent","--show-error","--max-time","30",u,"-o",str(out/n)],check=True,capture_output=True)
  d=(out/n).read_bytes()
  return {"file":n,"url":u,"retrieved_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"bytes":len(d),"sha256":hashlib.sha256(d).hexdigest(),"transport":"curl TLS verification enabled"}
 except Exception as e:return {"file":n,"url":u,"error":str(e)}
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex: rows=list(ex.map(f,sources))
(out/"sources.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2))
print(json.dumps([{"file":r["file"],"error":r.get("error")} for r in rows],ensure_ascii=False))

