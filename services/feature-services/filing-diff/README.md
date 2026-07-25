# filing-diff — Feature 12, Filing Diff Tool

Auto-diffs a bank's filings between two quarters and flags **material** line-item
shifts — judged against *that bank's own* historical volatility (a z-score on its
quarter-over-quarter moves), not an absolute cutoff. Output: a structured
"what changed and why it matters" summary.

## Status: logic implemented (Phase 1f), service wrapper pending (Phase 4)

Engine: [`pipelines/transforms/src/banklens_transforms/filing_diff.py`](../../../pipelines/transforms/src/banklens_transforms/filing_diff.py).
A move is flagged when it is a statistical outlier (|z| ≥ threshold) vs the bank's
same-span history **and** clears a small materiality floor. The evaluated transition
is excluded from its own baseline so it can't damp its own z. Falls back to an
absolute threshold when history is too short for a volatility baseline.

### Proven on real data (per-bank 6-quarter Bronze)
- **Wells Fargo:** C&I loans +7.3% flagged (z=+3.0) — the one notable move vs WF's steady norm.
- **Dime Community Bank:** HTM securities +4.7% flagged at **z=+21** — a small absolute change that's a massive outlier for Dime (its HTM is normally flat). Absolute cutoffs miss this.

### Run
```powershell
powershell -File scripts/filing_diff.ps1 -Cert 3511                        # newest vs prior
powershell -File scripts/filing_diff.ps1 -Cert 6976 -QuarterA 2024Q4 -QuarterB 2026Q1
```

### Next (Phase 2/4)
Deeper history for tighter z baselines; add new-risk-disclosure text diffs (SEC
10-K/10-Q narrative); wrap as gRPC; expose via the `diff_filings` MCP tool.
