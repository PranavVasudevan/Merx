# pipelines/transforms — Silver & Gold (Python reference)

The canonical, hand-verifiable definitions of the medallion transforms.

- `silver.py` — normalise one raw FDIC record into the `bank_financials` shape:
  map codes → canonical columns, convert **thousands → USD**, parse `REPDTE` →
  ISO date + quarter, derive uninsured deposits (`total − insured`).
- `gold.py` — derived features every downstream consumer reads:
  `uninsured_deposit_pct`, `loan_to_deposit_pct`, `equity_to_assets_pct`, QoQ deltas.
  (Phase 2 adds `concentration_ratio_*`, `percentile_rank_*`, `funding_stability_score`.)

## Contract
Definitions are pinned to **real Wells Fargo figures** in `tests/test_gold_metrics.py`.
When these move to dbt/Spark (Phase 2), the new implementation must reproduce the
same numbers — the tests are the acceptance criteria.

```powershell
python tests/test_gold_metrics.py
```
