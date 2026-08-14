"""Feature 12 (C13) runner — population-level multiple-testing context for
filing_diff: at a raw z>=2.0 threshold applied independently to every (bank,
tracked line item) pair, chance alone produces a real number of false
positives. This computes every landed bank's diff for its own two most
recent landed quarters, then reports the expected false-positive count at
the current threshold alongside a Benjamini-Hochberg FDR-controlled
alternative flag set (banklens_transforms.filing_diff.population_flag_summary).

Builds Silver rows directly from Bronze (same pattern as deposit_flight_cli/
ma_weights_cli) rather than via banklens_mcp.data.population(), which would
also pay for the full Gold percentile + k-means clustering pipeline on every
one of ~20 landed quarters just to get financials — unnecessary work for a
diff that only needs each bank's own quarterly history.

    powershell -File scripts/filing_diff_population.ps1
    python -m banklens_ingestion.filing_diff_population_cli
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from banklens_transforms.filing_diff import build_quarters, diff, population_flag_summary
from banklens_transforms.silver import to_bank_financials

RESULT_PATH = Path(__file__).resolve().parents[4] / "ml" / "filing_diff" / "population_summary.json"

# Same reduced-field training-only partitions deposit_flight_cli/data.py
# exclude from analytical use.
_TRAINING_ONLY_QUARTERS = {"20221231", "20080331"}


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _latest_landed(partition_dir: Path) -> Path | None:
    snaps = sorted(p for p in partition_dir.glob("landed=*") if (p / "records.json").exists())
    return (snaps[-1] / "records.json") if snaps else None


def run(data_dir: Path, z_threshold: float = 2.0, fdr_alpha: float = 0.05) -> None:
    pop_dir = data_dir / "bronze" / "source=fdic" / "population"
    repdtes = sorted(
        (p.name.split("=", 1)[1] for p in pop_dir.glob("repdte=*")
         if p.is_dir() and p.name.split("=", 1)[1] not in _TRAINING_ONLY_QUARTERS),
        reverse=True,
    )
    if len(repdtes) < 2:
        raise RuntimeError(f"Need >= 2 landed analytical quarters under {pop_dir}, found {len(repdtes)}.")

    history_by_cert: dict[int, list[dict]] = defaultdict(list)
    for repdte in repdtes:
        path = _latest_landed(pop_dir / f"repdte={repdte}")
        if path is None:
            continue
        for r in _load(path):
            s = to_bank_financials(r)
            cert = s.get("cert_number")
            if cert is not None:
                history_by_cert[cert].append(s)   # repdtes iterated newest-first -> stays newest-first

    diffs = []
    skipped = 0
    for cert, rows_desc in history_by_cert.items():
        if len(rows_desc) < 2:
            skipped += 1
            continue
        diffs.append(diff(build_quarters(rows_desc)))

    summary = population_flag_summary(diffs, z_threshold=z_threshold, fdr_alpha=fdr_alpha)
    payload = {
        "quarters_available": repdtes[:2],
        "n_banks_diffed": len(diffs),
        "n_banks_skipped_insufficient_history": skipped,
        **summary,
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("=" * 78)
    print(f"  Banks diffed: {len(diffs)} (skipped {skipped} with < 2 landed quarters)")
    print(f"  Total (bank x item) tests with a computed z: {summary['n_tests']}")
    print(f"  Raw flags at z>={z_threshold}: {summary['raw_flag_count']}  "
          f"(expected false positives by chance: {summary['expected_false_positives_at_threshold']})")
    print(f"  FDR-controlled flags at alpha={fdr_alpha}: {summary['fdr_flag_count']}")
    print(f"  Saved to {RESULT_PATH.relative_to(data_dir.parent)}")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens Feature 12 (C13) — filing-diff multiple-testing summary")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    p.add_argument("--z-threshold", type=float, default=2.0)
    p.add_argument("--fdr-alpha", type=float, default=0.05)
    args = p.parse_args()
    run(args.data_dir, args.z_threshold, args.fdr_alpha)


if __name__ == "__main__":
    main()
