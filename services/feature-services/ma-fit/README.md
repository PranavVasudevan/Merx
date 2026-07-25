# ma-fit — Feature 15, M&A Fit Finder

Given a target bank, ranks best-fit acquirers/partners on funding complementarity
(a deposit-rich bank fills a loan-heavy one's funding gap), business similarity
(cosine on loan mix — integration/strategic fit), size compatibility, and
geographic overlap. Output: a ranked list with a short rationale per match.

## Status: logic implemented (Phase 1g), service wrapper pending (Phase 4)

Engine: [`pipelines/transforms/src/banklens_transforms/ma_fit.py`](../../../pipelines/transforms/src/banklens_transforms/ma_fit.py)
— pure functions over Gold feature vectors. Runner: `banklens_ingestion.ma_fit_cli` /
`scripts/ma_fit.ps1`, ranking across the peer population.

### Proven on real data
- Target **Dime Community Bank** (NY, 74% CRE, $15B): top fit **Flagstar** (former NYCB, a 5.8×-larger NY multifamily/CRE lender), then other NY CRE banks (Apple, NBT, Popular, Ponce). Textbook in-market consolidation, derived from the feature vectors.

### Run
```powershell
powershell -File scripts/ma_fit.ps1 -TargetCert 6976 -TopN 8
```

### Known limitation / next (Phase 2/4)
Geography is a **home-state proxy** today (all same-state banks score geo=1.0). Upgrade
to branch-level footprints from the FDIC **Summary of Deposits** for true overlap and
distance. Then wrap as gRPC and expose via the `find_ma_matches` MCP tool.
