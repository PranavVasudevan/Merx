# ml/deposit_flight

`model_card.json` here is the trained, saved Feature 13 model (weights, standardization,
imputation means, in-sample AUC) — regenerate it with `scripts/deposit_flight.ps1`.

For the full story (training method, real validated results including the honest
IndyMac finding, and current limitations), see
[`services/feature-services/risk-score/README.md`](../../services/feature-services/risk-score/README.md).
The training/scoring logic itself lives in
[`pipelines/transforms/src/banklens_transforms/deposit_flight.py`](../../pipelines/transforms/src/banklens_transforms/deposit_flight.py).
