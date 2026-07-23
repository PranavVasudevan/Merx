# services/stress-engine — Capital Buffer Simulator (Feature 16, Rust)

Deterministic, auditable stress testing of a bank's real filed balance sheet.
No ML — transparent Basel-style math, because stress-test logic must be auditable.
Property-tested (zero shock ⇒ unchanged ratios; monotonic in loss severity).
C++/QuantLib bridged in for duration/curve analytics.

**Status:** skeleton (Phase 3). Reads starting numbers from the Gold layer.
