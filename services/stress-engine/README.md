# services/stress-engine — Capital Buffer Simulator (Feature 16, Rust)

Deterministic, auditable stress testing of a bank's real filed balance sheet.
No ML — transparent Basel-style math, because stress-test logic must be auditable.
Property-tested (zero shock ⇒ unchanged ratios; monotonic in loss severity).
C++/QuantLib bridged in for duration/curve analytics.

**Status:** the Python **reference is implemented** in
[`pipelines/transforms/src/banklens_transforms/stress.py`](../../pipelines/transforms/src/banklens_transforms/stress.py)
(loan losses, duration-based rate marks, the deposit-outflow → HTM-firesale SVB chain;
baseline reproduces reported ratios exactly). This Rust crate will port that logic and
bridge QuantLib for proper duration/curve analytics. Reads starting numbers from Gold.

Run the reference: `powershell -File scripts/stress_test.ps1 -Cert 3511 -Outflow 70 -RateBps 450`
