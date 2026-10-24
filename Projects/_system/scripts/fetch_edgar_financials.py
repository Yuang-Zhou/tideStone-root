#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EDGAR 财务底稿取数脚本 v0.4.0
用法:
  python3 fetch_edgar_financials.py COST
  python3 fetch_edgar_financials.py COST --out ./out --years 6

产出（写到 --out 目录，默认 ./out/{TICKER}/）:
  financials.json   统一底稿：records + annual + quarterly + ytd + ttm + checks + capital_allocation
  annual.csv        年度三张报表透视（人读）
  quarterly.csv     单季透视（人读）
  ttm.csv           近 12 个月（人读）
  capital_allocation.csv  资本配置台账（人读）

原则:
  - 数字全部来自 SEC XBRL companyfacts，每条带 tag/form/filed/accn 来源指针
  - 只取数与算术（TTM、勾稽、台账合计），不做任何判断；判断留给 02 财务分析
  - 同一 tag 同一期间多次申报取 filed 最新的一条；后一份申报的数与前一份不同才标 restated

v0.2 相对 v0.1:
  - 指标从 30 项扩到 54 项（应付、递延收入、固定资产、租赁、利息、期末股本、新增借款、少数股东等）
  - 新增 ytd 口径（半年/九个月累计不再丢弃），据此算 TTM = FY + 本年累计 − 去年同期累计
  - restated 只在同一 tag 同一期间数值变化时才标，并保留 prior_value
  - 勾稽从 2 条加到 5 条（净利润、税前、现金流三段之和）
  - 年度透视标 fiscal_year_end / weeks（53 周年份可识别）
  - 资本配置台账加新增借款、净还债、支付少数股东、经营现金流合计；输出格式向后兼容
v0.2.1:
  - 支持外国发行人：20-F/40-F 当年报、6-K 当季报；币种自动识别（--unit 可指定），meta.unit 写明
v0.3.0:
  - 自动识别 us-gaap / ifrs-full，也可用 --taxonomy 显式指定
  - 为 IFRS 标准标签增加指标映射，记录级保留 taxonomy 来源
  - EPS 单位随报告币种变化，不再写死 USD/shares
v0.4.0（2026-08-27，配合 02 财务分析 v4.0 第 1 步财务安全体检）:
  - 新增 13 项体检指标：坏账准备、存货跌价准备、固定资产原值、累计折旧、递延税资产、受限现金、
    融资租赁使用权资产、利息实付、债务到期分布（1 年内 / 第 2 / 3 / 4 / 5 年 / 5 年后）、经营租赁未来付款合计
  - 仍只取数不判断；到期分布为时点数，按最新 10-K 报告值
v0.4.1（2026-08-28）:
  - 版本号收敛为单一常量 SCRIPT_VERSION（此前 docstring 已是 0.4.0 而 meta 仍写死 0.3.0）
  - meta 新增 capabilities：本脚本会去找的全部指标名单。下游按字段清单校验能力，不再比对版本号字符串
  - meta 新增 suspect_metrics：命中的 tag 全是 "Other*" 残差科目时标出（如 cost_of_revenue 只命中
    OtherCostOfOperatingRevenue、accrued_liabilities 只命中 OtherLiabilitiesCurrent），
    这类数不是该科目全额，02 必须回原文核，不得直接用
"""
import os
import argparse
import json
import time
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

# 版本号只在这里定义一处，meta.script_version 直接引用，避免改功能忘了改号
SCRIPT_VERSION = "0.4.1"

UA = {"User-Agent": os.environ.get("SEC_USER_AGENT", "")}

# ---------------------------------------------------------------- 指标映射
# 每个指标给一串候选 tag，按顺序取第一个有数据的
# kind: flow=期间数(利润表/现金流) instant=时点数(资产负债表)
METRICS = {
    # ---- 利润表
    "revenue": {"kind": "flow", "stmt": "IS",
                "tags": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                         "RevenueFromContractWithCustomerIncludingAssessedTax",
                         "Revenues", "SalesRevenueNet"]},
    "cost_of_revenue": {"kind": "flow", "stmt": "IS",
                        "tags": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold",
                                 "CostOfServices", "OtherCostOfOperatingRevenue"]},
    "gross_profit": {"kind": "flow", "stmt": "IS", "tags": ["GrossProfit"]},
    "rnd_expense": {"kind": "flow", "stmt": "IS",
                    "tags": ["ResearchAndDevelopmentExpense",
                             "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"]},
    "sga_expense": {"kind": "flow", "stmt": "IS",
                    "tags": ["SellingGeneralAndAdministrativeExpense",
                             "GeneralAndAdministrativeExpense"]},
    "selling_expense": {"kind": "flow", "stmt": "IS",
                        "tags": ["SellingAndMarketingExpense", "SellingExpense", "MarketingExpense"]},
    "total_costs_and_expenses": {"kind": "flow", "stmt": "IS", "tags": ["CostsAndExpenses", "OperatingExpenses"]},
    "operating_income": {"kind": "flow", "stmt": "IS", "tags": ["OperatingIncomeLoss"]},
    "interest_expense": {"kind": "flow", "stmt": "IS",
                         "tags": ["InterestExpense", "InterestExpenseNonoperating",
                                  "InterestExpenseDebt"]},
    "interest_income": {"kind": "flow", "stmt": "IS",
                        "tags": ["InvestmentIncomeInterest", "InterestIncomeOther",
                                 "InvestmentIncomeInterestAndDividend", "InvestmentIncomeNonoperating",
                                 "InterestAndOtherIncome", "NonoperatingIncomeExpense"]},
    "pretax_income": {"kind": "flow", "stmt": "IS",
                      "tags": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"]},
    "income_tax": {"kind": "flow", "stmt": "IS", "tags": ["IncomeTaxExpenseBenefit"]},
    "net_income_incl_nci": {"kind": "flow", "stmt": "IS", "tags": ["ProfitLoss"]},
    "net_income": {"kind": "flow", "stmt": "IS", "tags": ["NetIncomeLoss"]},
    "nci_income": {"kind": "flow", "stmt": "IS",
                   "tags": ["NetIncomeLossAttributableToNoncontrollingInterest"]},
    "eps_diluted": {"kind": "flow", "stmt": "IS", "unit": "currency/shares",
                    "tags": ["EarningsPerShareDiluted"]},
    "shares_diluted": {"kind": "flow", "stmt": "IS", "unit": "shares",
                       "tags": ["WeightedAverageNumberOfDilutedSharesOutstanding"]},
    "impairment": {"kind": "flow", "stmt": "IS",
                   "tags": ["AssetImpairmentCharges", "GoodwillImpairmentLoss",
                            "ImpairmentOfLongLivedAssetsHeldForUse"]},
    "restructuring": {"kind": "flow", "stmt": "IS",
                      "tags": ["RestructuringCharges", "RestructuringSettlementAndImpairmentProvisions"]},
    # ---- 资产负债表
    "total_assets": {"kind": "instant", "stmt": "BS", "tags": ["Assets"]},
    "current_assets": {"kind": "instant", "stmt": "BS", "tags": ["AssetsCurrent"]},
    "cash_and_equivalents": {"kind": "instant", "stmt": "BS",
                             "tags": ["CashAndCashEquivalentsAtCarryingValue",
                                      "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]},
    "short_term_investments": {"kind": "instant", "stmt": "BS",
                               "tags": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                                        "AvailableForSaleSecuritiesDebtSecuritiesCurrent"]},
    "accounts_receivable": {"kind": "instant", "stmt": "BS",
                            "tags": ["AccountsReceivableNetCurrent", "ReceivablesNetCurrent"]},
    "inventory": {"kind": "instant", "stmt": "BS",
                  "tags": ["InventoryNet", "InventoryNetOfAllowancesCustomerAdvancesAndProgressBillings"]},
    "prepaid_and_other_current": {"kind": "instant", "stmt": "BS",
                                  "tags": ["PrepaidExpenseAndOtherAssetsCurrent", "OtherAssetsCurrent",
                                           "PrepaidExpenseCurrent"]},
    "ppe_net": {"kind": "instant", "stmt": "BS",
                "tags": ["PropertyPlantAndEquipmentNet",
                         "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"]},
    "operating_lease_rou": {"kind": "instant", "stmt": "BS", "tags": ["OperatingLeaseRightOfUseAsset"]},
    "goodwill": {"kind": "instant", "stmt": "BS", "tags": ["Goodwill"]},
    "intangibles": {"kind": "instant", "stmt": "BS",
                    "tags": ["IntangibleAssetsNetExcludingGoodwill", "FiniteLivedIntangibleAssetsNet"]},
    "total_liabilities": {"kind": "instant", "stmt": "BS", "tags": ["Liabilities"]},
    "current_liabilities": {"kind": "instant", "stmt": "BS", "tags": ["LiabilitiesCurrent"]},
    "accounts_payable": {"kind": "instant", "stmt": "BS",
                         "tags": ["AccountsPayableCurrent", "AccountsPayableAndAccruedLiabilitiesCurrent"]},
    "accrued_liabilities": {"kind": "instant", "stmt": "BS",
                            "tags": ["AccruedLiabilitiesCurrent", "OtherLiabilitiesCurrent"]},
    "employee_liabilities": {"kind": "instant", "stmt": "BS",
                             "tags": ["EmployeeRelatedLiabilitiesCurrent"]},
    "deferred_revenue": {"kind": "instant", "stmt": "BS",
                         "tags": ["ContractWithCustomerLiabilityCurrent", "DeferredRevenueCurrent",
                                  "ContractWithCustomerLiability", "DeferredRevenue"]},
    "short_term_debt": {"kind": "instant", "stmt": "BS",
                        "tags": ["LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
                                 "LongTermDebtAndCapitalLeaseObligationsCurrent"]},
    "long_term_debt": {"kind": "instant", "stmt": "BS",
                       "tags": ["LongTermDebtNoncurrent", "LongTermDebt",
                                "LongTermDebtAndCapitalLeaseObligations"]},
    "operating_lease_liab_current": {"kind": "instant", "stmt": "BS",
                                     "tags": ["OperatingLeaseLiabilityCurrent"]},
    "operating_lease_liab_noncurrent": {"kind": "instant", "stmt": "BS",
                                        "tags": ["OperatingLeaseLiabilityNoncurrent"]},
    "finance_lease_liab_current": {"kind": "instant", "stmt": "BS",
                                   "tags": ["FinanceLeaseLiabilityCurrent"]},
    "finance_lease_liab_noncurrent": {"kind": "instant", "stmt": "BS",
                                      "tags": ["FinanceLeaseLiabilityNoncurrent"]},
    "minority_interest": {"kind": "instant", "stmt": "BS", "tags": ["MinorityInterest"]},
    "total_equity": {"kind": "instant", "stmt": "BS",
                     "tags": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                              "StockholdersEquity"]},
    "liabilities_and_equity": {"kind": "instant", "stmt": "BS", "tags": ["LiabilitiesAndStockholdersEquity"]},
    "temporary_equity": {"kind": "instant", "stmt": "BS",
                         "tags": ["RedeemableNoncontrollingInterestEquityCarryingAmount",
                                  "TemporaryEquityCarryingAmountAttributableToParent",
                                  "TemporaryEquityCarryingAmountIncludingPortionAttributableToNoncontrollingInterest"]},
    "shares_outstanding": {"kind": "instant", "stmt": "BS", "unit": "shares",
                           "tags": ["CommonStockSharesOutstanding"]},
    # ---- 现金流量表
    "cfo": {"kind": "flow", "stmt": "CF",
            "tags": ["NetCashProvidedByUsedInOperatingActivities",
                     "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]},
    "cfi": {"kind": "flow", "stmt": "CF",
            "tags": ["NetCashProvidedByUsedInInvestingActivities",
                     "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"]},
    "cff": {"kind": "flow", "stmt": "CF",
            "tags": ["NetCashProvidedByUsedInFinancingActivities",
                     "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"]},
    "fx_effect_on_cash": {"kind": "flow", "stmt": "CF",
                          "tags": ["EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                                   "EffectOfExchangeRateOnCashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsIncludingDisposalGroupAndDiscontinuedOperations",
                                   "EffectOfExchangeRateOnCashAndCashEquivalents"]},
    "cash_change": {"kind": "flow", "stmt": "CF",
                    "tags": ["CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalentsPeriodIncreaseDecreaseIncludingExchangeRateEffect",
                             "CashAndCashEquivalentsPeriodIncreaseDecrease"]},
    "capex": {"kind": "flow", "stmt": "CF",
              "tags": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]},
    "capitalized_software": {"kind": "flow", "stmt": "CF",
                             "tags": ["PaymentsToDevelopSoftware", "PaymentsForSoftware"]},
    "depreciation_amortization": {"kind": "flow", "stmt": "CF",
                                  "tags": ["DepreciationDepletionAndAmortization",
                                           "DepreciationAmortizationAndAccretionNet", "Depreciation"]},
    "sbc": {"kind": "flow", "stmt": "CF", "tags": ["ShareBasedCompensation"]},
    "buyback": {"kind": "flow", "stmt": "CF", "tags": ["PaymentsForRepurchaseOfCommonStock"]},
    "dividends_paid": {"kind": "flow", "stmt": "CF",
                       "tags": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"]},
    "acquisitions": {"kind": "flow", "stmt": "CF",
                     "tags": ["PaymentsToAcquireBusinessesNetOfCashAcquired",
                              "PaymentsToAcquireBusinessesAndInterestInAffiliatesNetOfCashAcquired"]},
    "payments_to_nci": {"kind": "flow", "stmt": "CF",
                        "tags": ["PaymentsToMinorityShareholders",
                                 "PaymentsForRepurchaseOfRedeemableNoncontrollingInterest"]},
    "debt_issuance": {"kind": "flow", "stmt": "CF",
                      "tags": ["ProceedsFromIssuanceOfLongTermDebt", "ProceedsFromIssuanceOfDebt",
                               "ProceedsFromDebtNetOfIssuanceCosts"]},
    "debt_repayment": {"kind": "flow", "stmt": "CF",
                       "tags": ["RepaymentsOfLongTermDebt", "RepaymentsOfDebt"]},
    "income_taxes_paid": {"kind": "flow", "stmt": "CF",
                          "tags": ["IncomeTaxesPaidNet", "IncomeTaxesPaid"]},
    # ---- v0.4.0 财务安全体检（02 第 1 步用）
    "allowance_doubtful_accounts": {"kind": "instant", "stmt": "BS",
                                    "tags": ["AllowanceForDoubtfulAccountsReceivableCurrent",
                                             "AllowanceForDoubtfulAccountsReceivable",
                                             "AccountsReceivableAllowanceForCreditLossCurrent"]},
    "inventory_reserve": {"kind": "instant", "stmt": "BS",
                          "tags": ["InventoryValuationReserves", "InventoryLIFOReserve"]},
    "ppe_gross": {"kind": "instant", "stmt": "BS", "tags": ["PropertyPlantAndEquipmentGross"]},
    "accumulated_depreciation": {"kind": "instant", "stmt": "BS",
                                 "tags": ["AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment"]},
    "deferred_tax_assets": {"kind": "instant", "stmt": "BS",
                            "tags": ["DeferredIncomeTaxAssetsNet", "DeferredTaxAssetsNetNoncurrent",
                                     "DeferredTaxAssetsNet"]},
    "restricted_cash": {"kind": "instant", "stmt": "BS",
                        "tags": ["RestrictedCashAndCashEquivalents", "RestrictedCash",
                                 "RestrictedCashAndCashEquivalentsNoncurrent"]},
    "finance_lease_rou": {"kind": "instant", "stmt": "BS",
                          "tags": ["FinanceLeaseRightOfUseAsset"]},
    "interest_paid": {"kind": "flow", "stmt": "CF",
                      "tags": ["InterestPaidNet", "InterestPaid"]},
    "debt_due_1y": {"kind": "instant", "stmt": "BS",
                    "tags": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths"]},
    "debt_due_y2": {"kind": "instant", "stmt": "BS",
                    "tags": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearTwo"]},
    "debt_due_y3": {"kind": "instant", "stmt": "BS",
                    "tags": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearThree"]},
    "debt_due_y4": {"kind": "instant", "stmt": "BS",
                    "tags": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFour"]},
    "debt_due_y5": {"kind": "instant", "stmt": "BS",
                    "tags": ["LongTermDebtMaturitiesRepaymentsOfPrincipalInYearFive"]},
    "debt_due_after_y5": {"kind": "instant", "stmt": "BS",
                          "tags": ["LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive"]},
    "operating_lease_payments_due": {"kind": "instant", "stmt": "BS",
                                     "tags": ["LesseeOperatingLeaseLiabilityPaymentsDue"]},
}

# IFRS Accounting Taxonomy 的标准标签。这里与 METRICS 分开保存，避免破坏既有
# us-gaap 配置和下游指标名称。候选项按优先级排列；未列出的指标会明确记为 missing，
# 不会误把缺失值当作 0。不同年份 taxonomy 的少量命名差异用候选链兼容。
IFRS_TAGS = {
    # ---- 利润表
    "revenue": ["Revenue"],
    "cost_of_revenue": ["CostOfSales"],
    "gross_profit": ["GrossProfit"],
    "rnd_expense": ["ResearchAndDevelopmentExpense"],
    "sga_expense": ["SellingGeneralAndAdministrativeExpense", "AdministrativeExpense"],
    "selling_expense": ["DistributionCosts", "SellingExpense"],
    "total_costs_and_expenses": ["ExpensesByNature", "ExpensesByFunction"],
    "operating_income": ["ProfitLossFromOperatingActivities"],
    "interest_expense": ["InterestExpense", "FinanceCosts"],
    "interest_income": ["InterestIncome", "FinanceIncome"],
    "pretax_income": ["ProfitLossBeforeTax"],
    "income_tax": ["IncomeTaxExpenseContinuingOperations", "IncomeTaxExpense"],
    "net_income_incl_nci": ["ProfitLoss"],
    "net_income": ["ProfitLossAttributableToOwnersOfParent"],
    "nci_income": ["ProfitLossAttributableToNoncontrollingInterests"],
    "eps_diluted": ["DilutedEarningsLossPerShare"],
    "shares_diluted": ["WeightedAverageNumberOfSharesOutstandingDiluted"],
    "impairment": ["ImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
                   "ImpairmentLossRecognisedInProfitOrLoss"],
    "restructuring": ["RestructuringCosts"],
    # ---- 资产负债表
    "total_assets": ["Assets"],
    "current_assets": ["CurrentAssets"],
    "cash_and_equivalents": ["CashAndCashEquivalents"],
    "short_term_investments": ["OtherCurrentFinancialAssets", "CurrentFinancialAssetsAtFairValueThroughProfitOrLoss"],
    "accounts_receivable": ["TradeAndOtherCurrentReceivables", "CurrentTradeReceivables"],
    "inventory": ["Inventories"],
    "prepaid_and_other_current": ["OtherCurrentNonfinancialAssets", "CurrentPrepayments"],
    "ppe_net": ["PropertyPlantAndEquipment"],
    "operating_lease_rou": ["RightofuseAssets", "RightOfUseAssets"],
    "goodwill": ["Goodwill"],
    "intangibles": ["IntangibleAssetsOtherThanGoodwill"],
    "total_liabilities": ["Liabilities"],
    "current_liabilities": ["CurrentLiabilities"],
    "accounts_payable": ["TradeAndOtherCurrentPayables", "CurrentTradePayables"],
    "accrued_liabilities": ["OtherCurrentLiabilities", "CurrentAccruals"],
    "employee_liabilities": ["CurrentEmployeeBenefitObligations", "EmployeeBenefitsCurrent"],
    "deferred_revenue": ["CurrentContractLiabilities", "ContractLiabilitiesCurrent", "ContractLiabilities"],
    "short_term_debt": ["CurrentBorrowings", "CurrentInterestbearingLoansAndBorrowings"],
    "long_term_debt": ["NoncurrentBorrowings", "NoncurrentInterestbearingLoansAndBorrowings", "Borrowings"],
    "operating_lease_liab_current": ["CurrentLeaseLiabilities"],
    "operating_lease_liab_noncurrent": ["NoncurrentLeaseLiabilities"],
    "finance_lease_liab_current": ["CurrentFinanceLeaseLiabilities"],
    "finance_lease_liab_noncurrent": ["NoncurrentFinanceLeaseLiabilities"],
    "minority_interest": ["NoncontrollingInterests"],
    "total_equity": ["Equity"],
    "liabilities_and_equity": ["EquityAndLiabilities"],
    "temporary_equity": [],
    "shares_outstanding": ["NumberOfSharesOutstanding"],
    # ---- 现金流量表
    "cfo": ["CashFlowsFromUsedInOperatingActivities"],
    "cfi": ["CashFlowsFromUsedInInvestingActivities"],
    "cff": ["CashFlowsFromUsedInFinancingActivities"],
    "fx_effect_on_cash": ["EffectOfExchangeRateChangesOnCashAndCashEquivalents"],
    "cash_change": ["IncreaseDecreaseInCashAndCashEquivalents"],
    "capex": ["PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
              "PurchaseOfPropertyPlantAndEquipment"],
    "capitalized_software": ["PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"],
    "depreciation_amortization": ["DepreciationAmortisationAndImpairmentExpense",
                                  "DepreciationAndAmortisationExpense"],
    "sbc": ["SharebasedPaymentExpense"],
    "buyback": ["PaymentsToAcquireOrRedeemEntitysShares", "PurchaseOfTreasuryShares"],
    "dividends_paid": ["DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"],
    "acquisitions": ["CashFlowsUsedInObtainingControlOfSubsidiariesOrOtherBusinesses"],
    "payments_to_nci": ["PaymentsToAcquireNoncontrollingInterests"],
    "debt_issuance": ["ProceedsFromBorrowings"],
    "debt_repayment": ["RepaymentsOfBorrowings"],
    "income_taxes_paid": ["IncomeTaxesPaidRefundClassifiedAsOperatingActivities", "IncomeTaxesPaidRefund"],
    # ---- v0.4.0 体检指标（IFRS 无标准到期分布标签，留空→missing）
    "allowance_doubtful_accounts": ["AllowanceAccountForCreditLossesOfFinancialAssets"],
    "inventory_reserve": ["InventoryWritedown2011"],
    "ppe_gross": ["PropertyPlantAndEquipmentGross"],
    "accumulated_depreciation": ["AccumulatedDepreciationAmortisationAndImpairmentPropertyPlantAndEquipment"],
    "deferred_tax_assets": ["DeferredTaxAssets"],
    "restricted_cash": ["RestrictedCashAndCashEquivalents"],
    "finance_lease_rou": [],
    "interest_paid": ["InterestPaidClassifiedAsOperatingActivities", "InterestPaidClassifiedAsFinancingActivities"],
    "debt_due_1y": [], "debt_due_y2": [], "debt_due_y3": [], "debt_due_y4": [], "debt_due_y5": [], "debt_due_after_y5": [],
    "operating_lease_payments_due": [],
}

TOL = 0.005  # 勾稽容差 0.5%
ANNUAL_FORMS = ("10-K", "20-F", "40-F")
ALL_FORMS = ("10-", "20-F", "40-F", "6-K")
MONEY_UNIT = "USD"  # 运行时按 --unit 或自动识别覆盖
FLOW_METRICS = [m for m, s in METRICS.items() if s["kind"] == "flow"]
INSTANT_METRICS = [m for m, s in METRICS.items() if s["kind"] == "instant"]


def fetch_json(url, retries=3):
    if "@" not in UA["User-Agent"]:
        raise RuntimeError("SEC_USER_AGENT 未配置：请使用自己的应用名与联系邮箱")
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(1 + i)


def ticker_to_cik(ticker):
    data = fetch_json("https://www.sec.gov/files/company_tickers.json")
    t = ticker.upper()
    for row in data.values():
        if row["ticker"] == t:
            return f"{row['cik_str']:010d}", row["title"]
    raise SystemExit(f"[ERROR] EDGAR 找不到 ticker {t}（外国公司可能只有 ADR 主体，试试公司名搜 CIK）")


def metric_tags(metric, spec, taxonomy):
    """返回指定 taxonomy 的候选标签，顺序即优先级。"""
    if taxonomy == "us-gaap":
        return spec["tags"]
    if taxonomy == "ifrs-full":
        return IFRS_TAGS.get(metric, [])
    return []


def detect_taxonomy(facts, requested="auto"):
    """识别主要会计 taxonomy；混合披露时按已映射标准标签的命中数选择。"""
    supported = [t for t in ("us-gaap", "ifrs-full") if facts.get(t)]
    if requested != "auto":
        if requested not in supported:
            available = ", ".join(sorted(facts)) or "无"
            raise SystemExit(f"[ERROR] 指定 taxonomy {requested} 无数据；可用 namespace：{available}")
        return requested
    if not supported:
        available = ", ".join(sorted(facts)) or "无"
        raise SystemExit(f"[ERROR] 未找到 us-gaap 或 ifrs-full；可用 namespace：{available}")

    scores = {}
    for taxonomy in supported:
        namespace = facts[taxonomy]
        scores[taxonomy] = sum(
            1 for metric, spec in METRICS.items()
            if any(tag in namespace for tag in metric_tags(metric, spec, taxonomy))
        )
    return max(supported, key=lambda t: (scores[t], t == "us-gaap"))


def metric_unit(spec):
    unit = spec.get("unit", MONEY_UNIT)
    return f"{MONEY_UNIT}/shares" if unit == "currency/shares" else unit


def dur_days(item):
    try:
        s = datetime.strptime(item["start"], "%Y-%m-%d")
        e = datetime.strptime(item["end"], "%Y-%m-%d")
        return (e - s).days
    except Exception:
        return None


def classify(days):
    """期间长度 → 口径。quarterly 放宽到 120 天以容纳 16 周的 Q4（52/53 周财年公司）。"""
    if 340 <= days <= 380:
        return "annual"
    if 77 <= days <= 120:
        return "quarterly"
    if 160 <= days <= 200 or 250 <= days <= 295:
        return "ytd"
    return None


def extract_metric(facts, metric, spec, taxonomy="us-gaap"):
    """返回 (records, used_tags)。
    跨候选 tag 合并：同一 (basis, end, form) 优先级 = tag 在候选链里越靠前越优先。
    同 tag 内取 filed 最新；后一份申报的数与前一份不同才标 restated，并记 prior_value。"""
    want_unit = metric_unit(spec)
    best = {}
    used_tags = []
    for rank, tag in enumerate(metric_tags(metric, spec, taxonomy)):
        node = facts.get(taxonomy, {}).get(tag)
        if not node:
            continue
        items = node.get("units", {}).get(want_unit) or []
        hit = False
        for it in items:
            if it.get("val") is None or not it.get("form", "").startswith(ALL_FORMS):
                continue
            if spec["kind"] == "instant":
                basis, days = "instant", None
            else:
                days = dur_days(it)
                if days is None:
                    continue
                basis = classify(days)
                if basis is None:
                    continue
            key = (basis, it.get("start") or "", it["end"], (it.get("form") or "")[:4])
            prev = best.get(key)
            if prev is None:
                best[key] = (rank, dict(it, days=days), tag)
                hit = True
            elif rank < prev[0]:
                best[key] = (rank, dict(it, days=days), tag)   # 换更优先的 tag，不算重述
                hit = True
            elif rank == prev[0] and it.get("filed", "") > prev[1].get("filed", ""):
                new = dict(it, days=days)
                if it["val"] != prev[1]["val"]:
                    new["restated"] = True
                    new["prior_value"] = prev[1]["val"]
                    new["prior_filed"] = prev[1].get("filed")
                best[key] = (rank, new, tag)
                hit = True
        if hit:
            used_tags.append(tag)
    recs = []
    for (basis, start, end, _f), (rank, it, tag) in sorted(best.items(), key=lambda kv: (kv[0][2], kv[0][1])):
        r = {"metric": metric, "taxonomy": taxonomy, "basis": basis,
             "period_start": it.get("start"), "period_end": end,
             "days": it.get("days"), "fy": it.get("fy"), "fp": it.get("fp"),
             "value": it["val"], "unit": want_unit,
             "tag": tag, "form": it.get("form"), "filed": it.get("filed"), "accn": it.get("accn"),
             "restated": it.get("restated", False)}
        if r["restated"]:
            r["prior_value"] = it.get("prior_value")
            r["prior_filed"] = it.get("prior_filed")
        recs.append(r)
    return recs, used_tags


# ---------------------------------------------------------------- 透视
def pivot_annual(records, years):
    """metric -> {year_label: value}。流量取年度期间；时点数只认 10-K 期末值。
    年度标签 = 期末所在年份（1 月结账的公司标签会比公司自称的 FY 大 1，见 meta.fiscal_year_ends）。"""
    out = defaultdict(dict)
    fy_meta = {}
    for r in records:
        b, end, form = r["basis"], r["period_end"], (r.get("form") or "")
        label = end[:4]
        if b == "annual":
            cur = out[r["metric"]].get(label)
            if cur is None or end > cur["period_end"]:
                out[r["metric"]][label] = r
            if r.get("days"):
                fy_meta[label] = {"fiscal_year_end": end, "days": r["days"], "weeks": round(r["days"] / 7)}
        elif b == "instant" and form.startswith(ANNUAL_FORMS):
            cur = out[r["metric"]].get(label)
            if cur is None or end > cur["period_end"]:
                out[r["metric"]][label] = r
    all_keys = sorted({k for d in out.values() for k in d})
    window = all_keys[-years:]
    annual = {m: {k: d[k]["value"] for k in window if k in d} for m, d in out.items()}
    return annual, {k: v for k, v in fy_meta.items() if k in window}


def pivot_periodic(records, basis, years):
    """quarterly / ytd：metric -> {period_end: value}；时点数同一期末 10-Q 优先。"""
    out = defaultdict(dict)
    for r in records:
        b, end, form = r["basis"], r["period_end"], (r.get("form") or "")
        if b == basis:
            out[r["metric"]][end] = r
        elif b == "instant" and basis == "quarterly":
            cur = out[r["metric"]].get(end)
            if cur is None or (not form.startswith(ANNUAL_FORMS) and (cur.get("form") or "").startswith(ANNUAL_FORMS)):
                out[r["metric"]][end] = r
    all_keys = sorted({k for d in out.values() for k in d})
    window = all_keys[-years * 4:]
    return {m: {k: d[k]["value"] for k in window if k in d} for m, d in out.items()}


# ---------------------------------------------------------------- TTM
def compute_ttm(records):
    """TTM（近 12 个月）：
    流量 = 最近一份 10-K 年度值 + 本财年至今累计 − 去年同期累计。
      本财年至今累计 = 期末最新、期初 = 财年末次日 的 ytd 或 quarterly 记录（Q1 时是单季）
      去年同期累计   = 期初 = 上一财年初、天数相同（±10 天）的记录
      找不到去年同期时该指标 TTM 为 null，note 说明
    时点 = 最新一期（10-Q 或 10-K）期末值
    只做算术。若最新期末就是 10-K 期末，TTM = 该财年值。"""
    by_metric = defaultdict(list)
    for r in records:
        by_metric[r["metric"]].append(r)

    # 最新期末与最近 10-K 期末（用收入或总资产找）
    latest_end = max((r["period_end"] for r in records), default=None)
    annual_recs = [r for r in records if r["basis"] == "annual"]
    if not annual_recs or not latest_end:
        return {"period_end": latest_end, "flow": {}, "instant": {}, "notes": ["无年度记录"]}
    last_fy_end = max(r["period_end"] for r in annual_recs)
    prev_fy_end = max((r["period_end"] for r in annual_recs if r["period_end"] < last_fy_end), default=None)
    notes = []
    flow, instant = {}, {}

    if latest_end <= last_fy_end:
        for m in FLOW_METRICS:
            v = [r for r in by_metric[m] if r["basis"] == "annual" and r["period_end"] == last_fy_end]
            flow[m] = v[-1]["value"] if v else None
        notes.append(f"最新期末 {latest_end} 即财年末，TTM = FY{last_fy_end[:4]}")
    else:
        fy_start = (datetime.strptime(last_fy_end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        for m in FLOW_METRICS:
            recs = by_metric[m]
            fy = [r for r in recs if r["basis"] == "annual" and r["period_end"] == last_fy_end]
            cur = [r for r in recs if r["basis"] in ("ytd", "quarterly")
                   and r["period_end"] == latest_end and r["period_start"] == fy_start]
            if not fy or not cur:
                flow[m] = None
                continue
            cur = cur[-1]
            # 去年同期：期初 = 上一财年初，天数相同 ±10
            prev = None
            if prev_fy_end:
                prev_start = (datetime.strptime(prev_fy_end, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
                cands = [r for r in recs if r["basis"] in ("ytd", "quarterly")
                         and r["period_start"] == prev_start
                         and r.get("days") and abs(r["days"] - cur["days"]) <= 10]
                prev = cands[-1] if cands else None
            if prev is None:
                flow[m] = None
                notes.append(f"{m}: 缺去年同期累计，TTM 未算")
                continue
            flow[m] = fy[-1]["value"] + cur["value"] - prev["value"]
        notes.append(f"TTM 流量 = FY{last_fy_end[:4]} + 累计至 {latest_end} − 去年同期累计")

    for m in INSTANT_METRICS:
        v = [r for r in by_metric[m] if r["basis"] == "instant"]
        if v:
            v.sort(key=lambda r: (r["period_end"], r.get("filed", "")))
            instant[m] = v[-1]["value"]
            if v[-1]["period_end"] != latest_end:
                notes.append(f"{m}: 最新期末为 {v[-1]['period_end']}，非 {latest_end}")
        else:
            instant[m] = None
    return {"period_end": latest_end, "last_fy_end": last_fy_end, "flow": flow, "instant": instant, "notes": notes}


# ---------------------------------------------------------------- 勾稽
def run_checks(annual):
    """勾稽自检：只报告，不修数。"""
    checks = []

    def get(m, y):
        return annual.get(m, {}).get(y)

    def rel(a, b, base):
        return abs(a - b) / max(abs(base), 1)

    years = sorted(annual.get("total_assets", {}).keys())
    for y in years:
        a, l, e = get("total_assets", y), get("total_liabilities", y), get("total_equity", y)
        le = get("liabilities_and_equity", y)
        temp = get("temporary_equity", y) or 0
        if a and l and e:
            diff = rel(a, l + e + temp, a)
            checks.append({"check": "资产=负债+权益(含夹层)", "year": y, "pass": diff <= TOL,
                           "diff_pct": round(diff * 100, 3),
                           "note": f"夹层(可赎回NCI等)={temp:,}" if temp else ""})
        elif a and le:
            diff = rel(a, le, a)
            checks.append({"check": "资产=负债及权益合计", "year": y, "pass": diff <= TOL,
                           "diff_pct": round(diff * 100, 3)})
    for y in sorted(annual.get("gross_profit", {}).keys()):
        rev, cor, gp = get("revenue", y), get("cost_of_revenue", y), get("gross_profit", y)
        if rev and cor and gp:
            diff = rel(rev - cor, gp, gp)
            checks.append({"check": "收入-成本=毛利", "year": y, "pass": diff <= TOL,
                           "diff_pct": round(diff * 100, 3)})
    # 税前 − 所得税 = 净利润（含少数股东；没有 ProfitLoss 时用归母 + 少数股东损益）
    for y in sorted(annual.get("pretax_income", {}).keys()):
        pt, tax = get("pretax_income", y), get("income_tax", y)
        ni = get("net_income_incl_nci", y)
        if ni is None and get("net_income", y) is not None:
            ni = get("net_income", y) + (get("nci_income", y) or 0)
        if pt is not None and tax is not None and ni is not None:
            diff = rel(pt - tax, ni, ni)
            checks.append({"check": "税前-所得税=净利润", "year": y, "pass": diff <= TOL,
                           "diff_pct": round(diff * 100, 3),
                           "note": "" if diff <= TOL else "差额多为终止经营/权益法投资损益，需读原文"})
    # 营业利润 − 利息支出 + 利息收入 vs 税前：差额 = 其他损益（一次性项目的候选，给 02 用）
    for y in sorted(annual.get("operating_income", {}).keys()):
        oi, pt = get("operating_income", y), get("pretax_income", y)
        ie, ii = get("interest_expense", y) or 0, get("interest_income", y) or 0
        if oi is not None and pt is not None:
            other = pt - (oi - ie + ii)
            diff = abs(other) / max(abs(oi), 1)
            checks.append({"check": "营业利润-利息=税前(差额为其他损益)", "year": y,
                           "pass": diff <= 0.05, "diff_pct": round(diff * 100, 3),
                           "note": f"其他损益={other:,.0f}（超过营业利润 5% 时需读原文核性质）" if diff > 0.05 else f"其他损益={other:,.0f}"})
    # 现金流三段 + 汇率 = 现金变动
    for y in sorted(annual.get("cfo", {}).keys()):
        cfo, cfi, cff = get("cfo", y), get("cfi", y), get("cff", y)
        fx, chg = get("fx_effect_on_cash", y) or 0, get("cash_change", y)
        if None not in (cfo, cfi, cff, chg):
            diff = rel(cfo + cfi + cff + fx, chg, chg if chg else cfo)
            checks.append({"check": "经营+投资+筹资+汇率=现金变动", "year": y, "pass": diff <= TOL,
                           "diff_pct": round(diff * 100, 3)})
    return checks


# ---------------------------------------------------------------- 资本配置台账
CA_COLS = ("year", "cfo", "capex", "fcf", "acquisitions", "payments_to_nci", "buyback",
           "dividends_paid", "debt_issuance", "debt_repayment", "net_debt_repayment", "sbc")


def capital_allocation(annual):
    rows = []
    for y in sorted(annual.get("cfo", {}).keys()):
        cfo = annual.get("cfo", {}).get(y)
        row = {"year": y, "cfo": cfo}
        for m in ("capex", "acquisitions", "payments_to_nci", "buyback", "dividends_paid",
                  "debt_issuance", "debt_repayment", "sbc"):
            row[m] = annual.get(m, {}).get(y)
        row["fcf"] = cfo - row["capex"] if cfo is not None and row["capex"] is not None else None
        if row["debt_repayment"] is not None or row["debt_issuance"] is not None:
            row["net_debt_repayment"] = (row["debt_repayment"] or 0) - (row["debt_issuance"] or 0)
        else:
            row["net_debt_repayment"] = None
        rows.append(row)
    total = {"year": "total"}
    for k in CA_COLS[1:]:
        vals = [r[k] for r in rows if r.get(k) is not None]
        total[k] = sum(vals) if vals else None
    return rows, total


# ---------------------------------------------------------------- 输出
def to_csv(path, pivoted, order):
    cols = sorted({k for m in pivoted.values() for k in m.keys()})
    lines = ["metric," + ",".join(cols)]
    for m in order:
        if m not in pivoted:
            continue
        lines.append(m + "," + ",".join(str(pivoted[m].get(c, "")) for c in cols))
    path.write_text("\n".join(lines), encoding="utf-8")


def fmt(v):
    return "" if v is None else str(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ticker")
    ap.add_argument("--out", default="./out")
    ap.add_argument("--years", type=int, default=6)
    ap.add_argument("--unit", default="auto", help="货币单位，默认自动识别（按收入标签里最多的货币）")
    ap.add_argument("--taxonomy", choices=("auto", "us-gaap", "ifrs-full"), default="auto",
                    help="会计 taxonomy，默认按标准标签命中数自动识别")
    args = ap.parse_args()
    global MONEY_UNIT

    cik, title = ticker_to_cik(args.ticker)
    print(f"[1/4] {args.ticker.upper()} → CIK {cik} ({title})")
    data = fetch_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json")
    facts = data.get("facts", {})
    taxonomy = detect_taxonomy(facts, args.taxonomy)
    print(f"[2/4] companyfacts 拉取完成，{taxonomy} 标签数：{len(facts.get(taxonomy, {}))}")
    if args.unit == "auto":
        cnt = {}
        for tag in metric_tags("revenue", METRICS["revenue"], taxonomy):
            for u, items in facts.get(taxonomy, {}).get(tag, {}).get("units", {}).items():
                if "/" not in u and u not in ("shares", "pure"):
                    cnt[u] = cnt.get(u, 0) + len(items)
        MONEY_UNIT = max(cnt, key=cnt.get) if cnt else "USD"
    else:
        MONEY_UNIT = args.unit
    print(f"      taxonomy：{taxonomy}；货币单位：{MONEY_UNIT}")

    all_records, tag_map, missing = [], {}, []
    for metric, spec in METRICS.items():
        recs, tags = extract_metric(facts, metric, spec, taxonomy)
        if recs:
            all_records.extend(recs)
            tag_map[metric] = tags
        else:
            missing.append(metric)

    # XBRL 里 "OtherXxx" 按惯例是残差桶（其他XX），不是该科目全额。
    # 某指标命中的 tag 全是 Other* 时，取到的很可能只是一小项 —— 机械标出，判断留给 02。
    suspect = []
    for metric, tags in tag_map.items():
        if tags and all(str(t).startswith("Other") for t in tags):
            suspect.append({
                "metric": metric,
                "tags": tags,
                "reason": "命中的 tag 全是 XBRL 残差科目 Other*，取到的可能只是该科目的一小项，"
                          "不是全额；请回申报原文核对后再用，勿直接当总额",
            })

    annual, fy_meta = pivot_annual(all_records, args.years)
    quarterly = pivot_periodic(all_records, "quarterly", args.years)
    ytd = pivot_periodic(all_records, "ytd", args.years)
    ttm = compute_ttm(all_records)
    checks = run_checks(annual)
    capalloc, ca_total = capital_allocation(annual)
    n_restated = sum(1 for r in all_records if r.get("restated"))
    week53 = [y for y, m in fy_meta.items() if m["weeks"] == 53]

    n_fail = sum(1 for c in checks if not c["pass"])
    print(f"[3/4] 指标 {len(tag_map)}/{len(METRICS)} 命中；勾稽 {len(checks)} 项，{n_fail} 项未过；"
          f"重述记录 {n_restated} 条；TTM 期末 {ttm.get('period_end')}")
    if missing:
        print(f"      未命中指标（可能公司真没有 / 用了自定义标签 / 在附注里）：{', '.join(missing)}")
    if suspect:
        print("      [WARN] 以下指标只命中 Other* 残差科目，数偏小、口径不符，02 必须回原文核：")
        for it in suspect:
            print(f"        {it['metric']} ← {'/'.join(it['tags'])}")
    if week53:
        print(f"      53 周财年：{', '.join(week53)}")

    outdir = Path(args.out) / args.ticker.upper()
    outdir.mkdir(parents=True, exist_ok=True)
    doc = {
        "meta": {
            "ticker": args.ticker.upper(), "cik": cik, "company": title,
            "source": "SEC EDGAR companyfacts (XBRL)", "script_version": SCRIPT_VERSION,
            "taxonomy": taxonomy, "unit": MONEY_UNIT,
            "fetched_at": date.today().isoformat(),
            "currency_note": f"金额单位 {MONEY_UNIT}（自动识别，可用 --unit 指定）；shares/pure 除外",
            "fiscal_year_ends": fy_meta,
            "week53_years": week53,
            "tag_map": tag_map, "missing_metrics": missing,
            "capabilities": sorted(METRICS.keys()),
            "suspect_metrics": suspect,
            "caveats": [
                "annual 标签 = 财年期末所在年份；1 月结账的公司标签比公司自称的 FY 大 1，以 fiscal_year_ends 为准",
                "quarterly 含 77–120 天的单季（含 16 周 Q4）；ytd 含半年与九个月累计",
                "ttm.flow = 最近 10-K 年度值 + 本财年累计 − 去年同期累计；缺去年同期的指标为 null，见 ttm.notes",
                "restated=true 仅表示同一 tag 同一期间后一份申报的数与前一份不同，prior_value 为旧值",
                "missing_metrics 不等于 0：公司真没有 / 用了自定义标签 / 项目在附注里，由 02 逐条判",
                "capabilities = 本脚本会去找的全部指标；下游用它校验能力（需要的字段不在其中=脚本要升级），不要比对 script_version",
                "suspect_metrics 里的指标命中的是 Other* 残差科目，数偏小且口径不符，必须回原文核，不得直接使用",
                "ifrs-full 的 6-K 披露频率不统一，缺少季度/YTD 时无法机械计算 TTM，不会以 0 代替",
                "companyfacts 仅聚合标准 taxonomy 的整家公司事实；公司自定义扩展标签需另行解析申报原文",
                "附注类项目（分部收入、会员费等带维度的数、租赁明细、商誉减值明细）不在 XBRL 主表内，仍需读原文",
            ],
        },
        "records": all_records,
        "annual": annual,
        "quarterly": quarterly,
        "ytd": ytd,
        "ttm": ttm,
        "checks": checks,
        "capital_allocation": capalloc,
        "capital_allocation_total": ca_total,
    }
    (outdir / "financials.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    order = list(METRICS.keys())
    to_csv(outdir / "annual.csv", annual, order)
    to_csv(outdir / "quarterly.csv", quarterly, order)
    ttm_lines = ["metric,ttm"] + [f"{m},{fmt(ttm['flow'].get(m))}" for m in FLOW_METRICS] \
        + [f"{m},{fmt(ttm['instant'].get(m))}" for m in INSTANT_METRICS]
    (outdir / "ttm.csv").write_text("\n".join(ttm_lines), encoding="utf-8")
    ca_lines = [",".join(CA_COLS)]
    for r in capalloc + [ca_total]:
        ca_lines.append(",".join(fmt(r.get(k)) for k in CA_COLS))
    (outdir / "capital_allocation.csv").write_text("\n".join(ca_lines), encoding="utf-8")

    print(f"[4/4] 写入 {outdir}/ ：financials.json, annual.csv, quarterly.csv, ttm.csv, capital_allocation.csv")
    if n_fail:
        print("      [WARN] 勾稽未过明细：")
        for c in checks:
            if not c["pass"]:
                print(f"        {c['year']} {c['check']} 偏差 {c['diff_pct']}% {c.get('note', '')}")
    if ttm.get("notes"):
        for n in ttm["notes"][:6]:
            print(f"      TTM: {n}")


if __name__ == "__main__":
    main()

