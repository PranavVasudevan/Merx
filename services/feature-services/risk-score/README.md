# risk-score — Feature 13, Deposit-Flight Early-Warning (the showcase)

Classifies banks by structural resemblance to real bank-run cases, with an
interpretable risk score and its drivers. Validated against actual history —
**two** real financial crises, 15 years apart.

## Status: model + validation implemented, pooled across 2 crises (Phase 1n), gRPC serving pending (Phase 4)

Engine: [`pipelines/transforms/src/banklens_transforms/deposit_flight.py`](../../../pipelines/transforms/src/banklens_transforms/deposit_flight.py)
+ `logreg.py`. Trained on a **pooled cross-section**: 2022Q4 (n=986, the quarter before
the March-2023 failures) + 2008Q1 (n=669, the quarter before IndyMac's July-2008
failure) = 1,655 banks. Positives: SVB, Signature, First Republic (2023) + IndyMac
(2008) — all verified against the real FDIC failures list.

Model choice is deliberate: with only a handful of labeled failures, L2-regularized
**logistic regression** is the statistically honest baseline and its coefficients are
the interpretability (the plan's alternative to SHAP). XGBoost + SHAP is the upgrade
once there's more labeled history.

### Validated against real history — the full, honest result
- In-sample ROC-AUC **0.938** (down from 0.992 on the 2023-only model — an *expected*,
  informative drop once a genuinely different failure archetype joins the positive set;
  see below).
- **Leave-one-out (the honest test), against the FULL pooled 1,655-bank universe:**
  - SVB: rank 25/1655 (**98.5th** percentile)
  - Signature: rank 56/1655 (**96.7th** percentile)
  - First Republic: rank 102/1655 (**93.9th** percentile)
  - **IndyMac: rank 1499/1655 (9.5th percentile) — the model does NOT flag it.**
- Dominant signal: `deposit_growth_1yr` (rapid/hot-money funding growth), then
  `uninsured_deposit_pct` — the right economics for the 2023 cohort (SVB: 86%
  uninsured, HTM 591% of equity).

### Why IndyMac isn't flagged — a real, honest model limitation, not a bug
IndyMac's July-2008 failure is a **genuinely different archetype** from the 2023
cohort. Its 2008Q1 balance sheet: uninsured deposits ~13% (vs SVB's 86%), HTM/equity
~0% (vs SVB's 591%). IndyMac failed primarily from **subprime-mortgage credit
losses**, with a late-stage **retail** depositor panic (triggered by a public
senator's letter, not an institutional flight-to-quality) as the proximate trigger —
not the uninsured-institutional-deposit-flight pattern the other three positives
share and this feature set is tuned to detect. Its own top driver is
`deposit_growth_1yr` (+63% the year before failure, log-odds **+1.97**) — but its LOW
`uninsured_deposit_pct` actively pulls its score DOWN (log-odds **-1.38**), net
negative. **A model this size, trained on this feature set, generalizes across time
for the failure mode it was built around — but not across fundamentally different
failure modes.** That's a genuine, worth-knowing limitation, documented rather than
hidden.

**Washington Mutual** (also a real 2008 depositor run, ~$16.7B outflow in its final
10 days) is deliberately **excluded**: at ~$307B in assets it exceeds this platform's
$1B-$250B population band by 10-60x every other training example, which would risk
the model learning size confounds instead of structural risk signal. See
`EXCLUDED_CANDIDATES` in `deposit_flight.py`.

**Other honest limitations, still true:** high score = structural *resemblance*, not
certainty. Some all-uninsured specialists (captive-finance / bankers' banks) score
high without being run-prone.

### Run
```powershell
powershell -File scripts/deposit_flight.ps1        # train + validate on both crises, saves model card
```
The trained model card (`ml/deposit_flight/model_card.json`) is loaded by the
`get_risk_score` MCP tool to score current banks.

### Next (Phase 4)
XGBoost challenger + calibration; a credit-quality/asset-deterioration feature set
that could plausibly catch an IndyMac-style failure (this model's honest current
blind spot); temporal deposit-growth-volatility features; gRPC serving; MLflow.
