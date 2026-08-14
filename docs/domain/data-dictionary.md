# FDIC field data dictionary

Every FDIC BankFind field code this project reads, with what it means and
which endpoint it comes from. Source: `pipelines/ingestion/src/
banklens_ingestion/sources/fdic.py`'s `FINANCIAL_FIELDS`/`INSTITUTION_FIELDS`/
`FAILURE_FIELDS` lists — every code here was verified live against the real
FDIC API (probed, not guessed from FDIC's own docs alone), per that module's
own comment. See `docs/data-contracts/bank_financials.silver.md` for how
these raw codes become the canonical Silver-layer schema.

## `financials` endpoint (`FINANCIAL_FIELDS`)

Reported in **thousands of USD** for dollar fields; ratio fields are already
percentages. Normalisation to actual dollars happens in the Silver layer, not
here — Bronze stays raw.

### Identity

| Code | Meaning |
|---|---|
| `CERT` | FDIC certificate number |
| `REPDTE` | Report date (YYYYMMDD) |
| `NAMEFULL` | Institution's full legal name |
| `STALP` | Institution's home-office state |
| `ASSET` | Total assets |
| `NAMEHCR` | Holding-company name (crosswalk join key to SEC filers) |
| `RSSDHCR` | Holding-company RSSD ID |
| `RSSDID` | Institution's own RSSD ID |

### Deposits

| Code | Meaning |
|---|---|
| `DEP` | Total deposits |
| `DEPDOM` | Domestic deposits |
| `DEPINS` | Insured deposits |
| `DEPUNINS` | **Uninsured deposits (FDIC's own reported estimate)** — used directly rather than derived as `DEP - DEPINS`, since the two estimates use a different base |
| `COREDEP` | Core deposits |

### Loans & leases (RC-C schedule)

| Code | Meaning |
|---|---|
| `LNLSGR` | Gross loans & leases |
| `LNLSNET` | Net loans & leases |
| `LNRE` | Total real estate loans |
| `LNRECONS` | Construction & land development |
| `LNREMULT` | Multifamily residential RE |
| `LNRENRES` | Nonfarm nonresidential (CRE core) |
| `LNRELOC` | Home-equity lines of credit |
| `LNRERES` | 1-4 family residential mortgages |
| `LNREAG` | Farmland (agricultural RE) |
| `LNAG` | Agricultural production loans |
| `LNCI` | Commercial & industrial |
| `LNCON` | Consumer loans (total) |
| `LNCRCD` | Consumer: credit card |
| `LNAUTO` | Consumer: auto |
| `LNCONOTH` | Consumer: other |

### Securities

| Code | Meaning |
|---|---|
| `SC` | Total securities |
| `SCAF` | Available-for-sale (AFS), fair value |
| `SCHA` | Held-to-maturity (HTM), amortized cost |

### Capital & balance-sheet dollars (Feature 16 stress simulator)

| Code | Meaning |
|---|---|
| `EQ` | Total equity capital |
| `RBCT1J` | Tier 1 capital |
| `RBC` | Total risk-based capital |
| `RWAJT` | Risk-weighted assets |
| `ASSET5` | Average assets |
| `CHBAL` | Cash & balances due |

### Capital & performance ratios (already percentages — never rescale)

| Code | Meaning |
|---|---|
| `IDT1CER` | Common Equity Tier 1 (CET1) ratio |
| `IDT1RWAJR` | Tier 1 risk-based capital ratio |
| `RBCRWAJ` | Total risk-based capital ratio |
| `RBC1AAJ` | Tier 1 leverage ratio |
| `EQV` | Equity / assets |
| `LNLSDEPR` | Net loans / deposits (FDIC's own computation) |
| `NIMY` | Net interest margin — **year-to-date annualized** |
| `ROA` | Return on assets — **year-to-date annualized** |
| `ROE` | Return on equity — **year-to-date annualized** |
| `EEFFR` | Efficiency ratio — **year-to-date annualized** |

### Income statement

| Code | Meaning |
|---|---|
| `NETINC` | Net income |
| `INTINC` | Total interest income |
| `EINTEXP` | Total interest expense |
| `NONII` | Total non-interest income |
| `NONIX` | Total non-interest expense |
| `ELNATR` | Provision for credit losses |

### Asset quality

| Code | Meaning |
|---|---|
| `NCLNLS` | Noncurrent loans & leases (90+ days past due or nonaccrual) |
| `NTLNLS` | Net charge-offs (all loans, blended) |
| `NTRECONS` / `NTREMULT` / `NTRENRES` / `NTRERES` / `NTREAG` / `NTAG` / `NTCI` / `NTCON` | Net charge-offs by the same 8-leaf disjoint loan category `gold.LOAN_CATEGORIES` uses for concentration ratios |
| `LNATRES` | Allowance for credit losses on loans & leases |
| `P3ASSET` / `P9ASSET` | Assets past due 30-89 / 90+ days — **asset-level**, not loan-level; never divide by a loan denominator |
| `ORE` | Other real estate owned (OREO) — the Texas Ratio numerator |
| `INTAN` | Intangible assets — for tangible common equity |
| `NPERFV` | (Noncurrent assets + OREO) / assets |

### Funding composition (the SVB/Signature story, quantified)

| Code | Meaning |
|---|---|
| `BRO` | Brokered deposits |
| `VOLIAB` | Volatile liabilities |
| `DEPLGAMT` | Deposits held in accounts over the insurance limit |
| `NTRTIME` | Total time deposits |
| `IDLNCORR` | Net loans & leases / core deposits |

## `institutions` endpoint (`INSTITUTION_FIELDS`)

`NAME`, `CERT`, `STALP`, `CITY`, `ACTIVE`, `ASSET`, `DEP`, `ESTYMD` (charter
establishment date).

## `failures` endpoint (`FAILURE_FIELDS`)

The full field set the endpoint returns (not a curated subset — every field
appeared on a real landed row, verified live 2026-08-13):

`CERT`, `NAME`, `FAILDATE`, `FAILYR`, `CITY`, `PSTALP`, `CHCLASS`/`CHCLASS1`
(charter class at failure / at resolution), `QBFASSET`/`QBFDEP` (assets /
deposits at failure), `RESTYPE`/`RESTYPE1` (resolution type / sub-type),
`SAVR` (resolving fund, e.g. "DIF"), `BIDNAME`/`BIDCITY`/`BIDSTATE`
(acquiring institution), `COST`/`COSTMOSTRECENTASOF` (resolution cost to the
DIF, as-of date), `UNINSDEP` (uninsured deposits at failure, where
disclosed), `RESDATE`/`BRDATE` (resolution / bridge-bank date), `FIN`, `ID`.

Real examples verified live: SVB → CERT 24735, `FAILDATE` 3/10/2023;
Signature Bank → CERT 57053, `FAILDATE` 3/12/2023; IndyMac → CERT 29730,
`FAILDATE` 7/11/2008.
