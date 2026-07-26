# Data contract — CERT↔CIK↔RSSD crosswalk

The join key unifying FDIC (bank-level, `CERT`), the Fed (holding-company, `RSSD`),
and SEC EDGAR (public filer, `CIK`). Built by
[`pipelines/transforms/src/banklens_transforms/crosswalk.py`](../../pipelines/transforms/src/banklens_transforms/crosswalk.py),
run via `scripts/crosswalk.ps1`, output at `data/silver/crosswalk.json`.

## Why holding-company name, not bank name

SEC filers are almost always the **public holding company**, not the bank
subsidiary — so matching joins on FDIC's `NAMEHCR` (holding-company name), falling
back to the bank's own name when `NAMEHCR` is blank (some banks, e.g. **Zions** and
**Flagstar**, eliminated their separate holding-company structure and report to SEC
at the bank level directly — a real structural fact discovered while building this).

## Matching method — and why it's more than naive fuzzy string matching

1. Normalize both sides: uppercase, strip corporate/banking suffixes symmetrically
   (`INC`, `CORP`, `BANCORP`, `BANK`, `TRUST`, `NATIONAL ASSOCIATION`, SEC's `/MN`-style
   state tags, punctuation).
2. Exact match on the normalized string → `exact` (score 1.0).
3. Otherwise, fuzzy match via stdlib `difflib.SequenceMatcher` — but **only against
   candidates sharing the same first token** (`first_token`). Generic banking words
   (COMMUNITY, TRUST, BANCORP) get stripped, so the first surviving token is almost
   always the actual distinguishing brand name (DIME, WELLS, ZIONS).

### A real bug this caught
Without first-token blocking, "DIME COMMUNITY BANCSHARES" fuzzy-matched **"Community
Trust Bancorp Inc /KY/"** — an unrelated Kentucky bank — over the real match ("Dime
Commercial Bancshares", ticker DCOM), because the impostor scored *higher* on raw
character overlap (0.78 vs 0.69) purely from sharing the generic word "COMMUNITY".
Blocking by first token ("DIME" vs "COMMUNITY") excludes the impostor before scoring
ever happens. See `test_first_token_blocking_avoids_false_positive`.

### A real naming discrepancy this surfaces (not hides)
FDIC's `NAMEHCR` for Dime is "DIME COMMUNITY BANCSHARES"; SEC's registered title is
"Dime **Commercial** Bancshares" — same real company (ticker DCOM confirms it), but a
genuine one-word discrepancy between two "authoritative" sources. Fuzzy matching
correctly can't promote this above 0.69 — it's surfaced as `low_confidence`, not
silently trusted or silently dropped.

## Confidence tiers (never a silent binary match/no-match)

| Tier | Score | Meaning |
|---|---|---|
| `exact` | 1.0 | identical after normalization |
| `high_confidence` | ≥ 0.85 | trust automatically |
| `low_confidence` | 0.60–0.85 | surfaced for human review, not dropped |
| `none` | no candidate shares a first token | genuinely no match found |

## Real result (1,049-bank MVP slice, 2026Q1)

1,002 unique holding companies vs 8,017 unique SEC filers → **52.5% match rate**
(234 exact + 21 high-confidence + 271 low-confidence). This is a large drop from an
earlier unblocked version's 88.7% — that drop is **correct**, not a regression: most
of the difference was false positives like the Dime/Community-Trust case above. A
sub-100% rate is also expected on its own terms: many community banks are held by
private, non-SEC-reporting companies with no CIK to find.

## Verified cross-source (live SEC fetch, `scripts/crosswalk.ps1 -Verify ZIONS`)
Zions: FDIC bank-level assets ($87.96B, 2026Q1) exactly equals SEC holding-company
assets ($87.96B, 2026-03-31) — expected, since Zions has no separate holding company.
Wells Fargo's SEC figure ($2.15T) exceeds its FDIC bank-subsidiary figure ($1.85T) —
also expected, since the holding company is a superset including non-bank units.

## Known limitations (Phase 2 upgrade path)
Pure fuzzy name matching has a real ceiling — production should use (or cross-check
against) an authoritative source (the Fed NIC's own crosswalk, or an academic
CIK↔RSSD↔PERMCO link table) rather than name similarity alone. `low_confidence` rows
should not be trusted for anything beyond exploratory joins without review.
