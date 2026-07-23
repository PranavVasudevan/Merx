# Data dictionary — FDIC financial field codes

The FDIC BankFind `financials` endpoint uses short codes. These are the ones the
Phase-1 slice uses (verified live). Full list: https://banks.data.fdic.gov/docs/

| Code | Meaning | Unit | Canonical Silver column |
|---|---|---|---|
| `CERT` | FDIC certificate number | id | `cert_number` |
| `REPDTE` | Report date | YYYYMMDD | → `filing_date`, `quarter` |
| `NAMEFULL` | Institution legal name | text | `name` |
| `STALP` | State (2-letter) | text | `state` |
| `ASSET` | Total assets | $ thousands | `total_assets` (×1000) |
| `DEP` | Total deposits | $ thousands | `total_deposits` |
| `DEPDOM` | Deposits in domestic offices | $ thousands | `domestic_deposits` |
| `DEPINS` | Estimated insured deposits | $ thousands | `insured_deposits` |
| `LNLSGR` | Total loans & leases, gross | $ thousands | `total_loans_gross` |
| `LNLSNET` | Total loans & leases, net | $ thousands | `total_loans_net` |
| `EQ` | Total equity capital | $ thousands | `total_equity` |

**Reminder:** all FDIC dollar amounts are in **thousands** — Silver multiplies by 1,000.

## Phase-2 additions (codes to map next)
Loan composition (e.g. `LNRECONS`, `LNCI`, `LNCONOTH`, `LNRERES`, `LNAG`),
securities (`SCAF`, `SCHTMV`/`SCHTM`), capital ratios (`RBCT1J`, `RBC1RWAJ`,
`RBCRWAJ`), brokered deposits (`DEPBK`/`BRO`), FHLB advances. Confirm each code
against the FDIC dictionary before use — do not assume.
