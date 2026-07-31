# services/stress-engine — Capital Buffer Simulator (Feature 16, Rust)

**Status: real, not a skeleton.** A line-for-line Rust port of
[`pipelines/transforms/src/banklens_transforms/stress.py`](../../pipelines/transforms/src/banklens_transforms/stress.py)
— same math, same field names, same Basel-style minimums. Not a
reinterpretation: verified in `CHANGELOG.md` against the Python reference on
real landed bank data (loan losses, duration-based rate marks, the
deposit-outflow -> HTM-firesale SVB chain; baseline reproduces reported
ratios exactly).

Property-tested with `proptest` (see `src/lib.rs`'s `tests` module): zero
shock leaves ratios unchanged, capital ratios never go negative, the
HTM-sold fraction always stays in `[0, 1]`, ratios move monotonically with
loan-loss severity.

## Scope

This ports the Feature 16 math only. It reads the ~13 raw FDIC fields it
needs directly from Bronze using the same unit-conversion rules as
`banklens_transforms.silver.to_bank_financials` (see `src/main.rs`'s
top-of-file comment) — that is a scoped extraction for this feature, **not**
a full port of `silver.py` (loan composition, the CRE aggregate, and the
CIK/RSSD crosswalk fields still live only in Python).

**QuantLib update:** the linear modified-duration approximation this Rust
engine ports is now genuinely upgradeable — see
`pipelines/transforms/src/banklens_transforms/quantlib_pricing.py` and
`stress.py::run_stress_test_quantlib()` (Python only, via QuantLib's real
compiled C++ library through its official bindings). Verified on real Wells
Fargo data that the linear approximation this Rust crate uses overstates the
capital hit vs. a real DCF re-price (convexity) — see `CHANGELOG.md` for the
actual numbers. This Rust engine has **not** been updated to match — it still
implements the linear approximation on purpose, to stay in verified lock-step
with `run_stress_test()` (not `run_stress_test_quantlib()`). Porting QuantLib's
C++ core into Rust (rather than calling back into Python) is a further,
not-yet-started step.

## Run

```powershell
cargo run --release --bin banklens-stress -- --cert 3511 --loan-loss 4 --outflow 25 --rate-bps 250
cargo run --release --bin banklens-stress -- --cert 3511 --loan-loss 4 --outflow 25 --rate-bps 250 --json
cargo test
```

Compare directly against the Python reference for the same bank/scenario:
`powershell -File ../../scripts/stress_test.ps1 -Cert 3511 -LoanLoss 4 -Outflow 25 -RateBps 250`
