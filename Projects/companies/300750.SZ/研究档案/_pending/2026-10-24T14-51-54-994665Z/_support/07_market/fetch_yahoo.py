import yfinance as yf,json,concurrent.futures,pathlib,datetime,hashlib
out=pathlib.Path("/Users/yuangzhou/Desktop/tideStone-root/Projects/companies/300750.SZ/研究档案/_pending/2026-10-24T14-51-54-994665Z")/"_evidence/07_market";out.mkdir(parents=True,exist_ok=True)
syms=["300014.SZ","3931.HK","373220.KS","006400.KS","002594.SZ"]
def get(s):
 row={"ticker":s,"fetched_utc":datetime.datetime.now(datetime.timezone.utc).isoformat()}
 t=yf.Ticker(s)
 try:row["info"]=t.info
 except Exception as e:row["info_error"]=str(e)
 try:
  h=t.history(start="2026-10-19",end="2026-10-24",auto_adjust=False)
  row["history"]=json.loads(h.reset_index().to_json(orient="records",date_format="iso"))
 except Exception as e:row["history_error"]=str(e)
 for key,fun in [("income",lambda:t.quarterly_income_stmt),("cashflow",lambda:t.quarterly_cashflow),("balance",lambda:t.quarterly_balance_sheet)]:
  try:row[key]=json.loads(fun().to_json(date_format="iso"))
  except Exception as e:row[key+"_error"]=str(e)
 p=out/(s+".json");p.write_text(json.dumps(row,ensure_ascii=False,indent=2,default=str))
 info=row.get("info",{})
 return {"ticker":s,**{k:info.get(k) for k in ["currentPrice","regularMarketTime","marketCap","sharesOutstanding","trailingPE","priceToSalesTrailing12Months","totalRevenue","netIncomeToCommon","revenueGrowth","freeCashflow","operatingCashflow","totalDebt","totalCash","beta","currency","financialCurrency"]},"income_cols":list(row.get("income",{}))}
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:r=list(ex.map(get,syms))
(out/"summary.json").write_text(json.dumps(r,ensure_ascii=False,indent=2))
print(json.dumps(r,ensure_ascii=False,indent=2))

