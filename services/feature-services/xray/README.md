# xray — Feature 11, Balance-Sheet X-Ray (concentration & structural risk)

Surfaces hidden risk that headline ratios mask: single-sector loan concentration,
CRE-vs-capital, uninsured-deposit reliance, thin liquidity, and eroding capital.

## Status: logic implemented (Phase 1b), service wrapper pending (Phase 3)

The pure, auditable scoring logic lives in
[`pipelines/transforms/src/banklens_transforms/xray.py`](../../../pipelines/transforms/src/banklens_transforms/xray.py)
and reads Gold features. This gRPC service will wrap that exact function unchanged.

Rule-based (no ML) by design — an examiner can read every threshold. Each rule
compares a Gold metric to a supervisory-informed threshold and, if breached, emits
a flag with value, threshold, severity, and a plain-English reason. Overall risk =
the worst severity among the flags.

### Proven on real data
- **Wells Fargo (CERT 3511):** diversified, well-capitalized → ELEVATED (only ~48% uninsured deposits).
- **Dime Community Bank (CERT 6976):** CET1 14.6% looks healthy, but **73.8% of loans are CRE** and CRE is **471% of capital** (>300% supervisory flag) → HIGH. Exactly the hidden concentration the X-Ray exists to catch.

### Run it
```powershell
# after landing the bank's Bronze data:
powershell -File scripts/run_vertical_slice.ps1 -Cert 6976
```

### Next (Phase 2/3)
Peer-percentile ranking (`percentile_rank_*`, needs the peer population); wrap as
a gRPC service; expose via the `get_bank_xray` MCP tool.
