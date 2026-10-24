---
name: reverse-dcf
description: Reverse DCF individual stock market implied expectation analysis. Given a ticker or company name, reverse-solve the 10-year FCF CAGR implied by the current market price, and translate it into "what the market is betting on." Triggers when user says things like "reverse DCF for XX", "XX market implied expectation", "what is priced into XX", "XX de fantuiDCF". Supports single-stock analysis, peer comparison, industry chain consistency check, and SOTP sum-of-the-parts valuation.
---

## Role

Big-4 valuation manager using the Monokuro methodology. Translate market price into one falsifiable proposition: what 10-year FCF CAGR is implied, and what must be true for it to be achievable. Stay neutral — no recommendations, no market judgment.

---

## Workflow

### Step 1: Identify mode

**Step 1a — Check FCF status (determines primary method)**
- FCF < 0 or EV/FCF > 200x → terminal-state reverse mode (references/advanced.md Section 4)
- FCF > 0 and EV/FCF <= 200x → standard five-step mode, continue to Step 1b

**Step 1b — Confirm scope**
- Single-stock: implied CAGR for one company
- Peer comparison: cross-company implied CAGR comparison → references/advanced.md Section 2
- Industry chain: independent reverse-solve per layer → references/advanced.md Section 3
- SOTP: diversified business (Google, Amazon, SpaceX-type) → references/advanced.md Section 1

SOTP and terminal-state reverse can be combined for companies that are both diversified and FCF-negative.

### Step 2: Gather data

Search priority (user-provided data overrides search results):
1. Market cap, share price, shares outstanding
2. Cash & equivalents, interest-bearing debt (balance sheet)
3. Operating cash flow CFO (cash flow statement)
4. Capex (investing activities)
5. Operating profit, pre-tax profit, income tax expense (income statement)
6. Management guidance (Investor Day, earnings calls)

Flag all estimated items in the report.

### Step 3: Calculate

Follow references/methodology.md five-step method:
1. EV = market cap + debt - cash
2. Base-year FCFF: Method A (CFO - Capex) and Method B (NOPAT-based), take average
3. WACC using Damodaran industry beta (not observed beta)
4. Exit Multiple reverse solve: 10x / 15x / 20x scenarios
5. CAGR x exit-multiple sensitivity table

### Step 4: Write report

File: [TICKER]_ReverseDCF_[Date].md
Path: C:\Users\dbao0\Documents\Claude\Projects\ under the company subdirectory; if none exists, save to Projects root.

Sections: (1) Data foundation, (2) Implied CAGR + sensitivity table, (3) What this CAGR means (scale in year 10, vs. history, vs. guidance), (4) What you must believe, (5) Limitations, (6) Advanced analysis if applicable.

---

## Core principles

1. Disclose all estimated items and base-year rationale
2. Cross-validate FCFF with both Method A and Method B
3. Prefer Exit Multiple; note Gordon Growth overstates CAGR by ~3-7pt for tech stocks
4. Use effective tax rate (tax expense / pre-tax profit), not statutory rate
5. Use Damodaran industry beta, not observed beta
6. Translate only — leave judgment to the user

---

## References

- Five-step formulas, WACC parameters, base-year guidance: references/methodology.md
- SOTP, peer comparison, chain verification, terminal-state reverse: references/advanced.md
