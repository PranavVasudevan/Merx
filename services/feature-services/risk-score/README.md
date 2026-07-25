# risk-score — Feature 13, Deposit-Flight Early-Warning (the showcase)

Classifies banks by structural resemblance to real bank-run cases, with an
interpretable risk score and its drivers. Validated against actual history.

## Status: model + validation implemented (Phase 1i), gRPC serving pending (Phase 4)

Engine: [`pipelines/transforms/src/banklens_transforms/deposit_flight.py`](../../../pipelines/transforms/src/banklens_transforms/deposit_flight.py)
+ `logreg.py`. Trained on the **2022Q4 cross-section** (the quarter before the March-2023
failures); positives = SVB / Signature / First Republic (from the FDIC failures list).

Model choice is deliberate: with only a handful of labeled failures, L2-regularized
**logistic regression** is the statistically honest baseline and its coefficients are
the interpretability (the plan's alternative to SHAP). XGBoost + SHAP is the upgrade
once there's more labeled history.

### Validated against real history
- In-sample ROC-AUC **0.992**.
- **Leave-one-out (the honest test):** trained *without* SVB, SVB still ranks 13/986
  (98.8th pctile); Signature 99.7th; First Republic 95.9th.
- Dominant signal: uninsured-deposit reliance, then loan/deposit and HTM/equity — the
  right economics (SVB: 86% uninsured, HTM 591% of equity).
- **Honest limitation:** high score = structural *resemblance*, not certainty. Some
  all-uninsured specialists (captive-finance / bankers' banks) score high without being
  run-prone.

### Run
```powershell
powershell -File scripts/deposit_flight.ps1        # train + validate, saves model card
```
The trained model card (`ml/deposit_flight/model_card.json`) is loaded by the
`get_risk_score` MCP tool to score current banks.

### Next (Phase 4)
XGBoost challenger + calibration; add 2008 failures (WaMu/IndyMac) for a bigger,
multi-era labeled set; temporal deposit-growth-volatility features; gRPC serving; MLflow.
