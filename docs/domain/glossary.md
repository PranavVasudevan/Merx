# Banking glossary (for BankLens contributors)

Enough vocabulary to read the data and the features. Deeper treatment:
[`BankLens-Domain-Study-Guide.md`](BankLens-Domain-Study-Guide.md).

| Term | Meaning | Why BankLens cares |
|---|---|---|
| **Deposits (liability)** | Money customers place with the bank; the bank *owes* it back. | It's on the liability side — the inversion that trips up newcomers. |
| **Loans (asset)** | Money the bank lent out; owed *to* it. | The asset side; loan mix drives concentration risk (F11). |
| **Insured deposits** | Deposits under the FDIC $250k limit. | Insured depositors rarely run. |
| **Uninsured deposits** | Deposits above the limit (corporates, VCs). | The #1 run-risk signal (F13). `DEP − DEPINS`. |
| **Brokered deposits** | Deposits sourced via brokers; flighty, rate-sensitive. | Funding-stability signal. |
| **AFS securities** | Available-for-sale; marked to market. | Rate moves hit equity via OCI. |
| **HTM securities** | Held-to-maturity; carried at cost. | Unrealised losses stay hidden — the SVB trap. |
| **CET1 / Tier 1 / Leverage ratio** | Capital adequacy measures. | The buffer that absorbs losses (F16). |
| **RWA** | Risk-weighted assets. | Denominator of capital ratios; risky assets weigh more. |
| **LCR / NSFR** | Liquidity coverage / net stable funding ratios. | Liquidity, distinct from solvency. |
| **NIM** | Net interest margin = interest earned − interest paid. | Core profitability. |
| **Loan-to-deposit** | Net loans / deposits. | Funding intensity / liquidity gauge. |
| **FHLB advances** | Borrowings from Federal Home Loan Banks. | Wholesale-funding reliance signal. |
| **Call Report** | FFIEC 031/041 quarterly regulatory filing. | Primary US bank data (via FDIC/FFIEC). |
| **FR Y-9C** | Fed holding-company consolidated financials. | Parent-level view FDIC lacks. |
| **UBPR** | Uniform Bank Performance Report — ratios + peer percentiles. | The regulator's own version of our Gold layer. |
| **CERT / CIK / RSSD** | FDIC / SEC / Fed identifiers. | The crosswalk that joins all sources. |
| **P/B ratio** | Price-to-book. | *The* bank valuation ratio; <1 signals distress. |
