"""Population builder — the peer set that gives Feature 11 its percentile context.

Loads a landed population (all US banks in the MVP size band for one quarter) from
Bronze, runs Silver -> Gold cross-sectionally, attaches peer percentile ranks, and
prints a peer report: slice stats, leaderboards, and one bank's standing vs peers.

Run (after landing the population to Bronze)::

    powershell -File scripts/population_report.ps1
    # or:
    $env:PYTHONPATH = "pipelines/ingestion/src;pipelines/transforms/src"
    python -m banklens_ingestion.population --highlight-cert 6976
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.gold import gold_features
from banklens_transforms.peers import add_percentile_ranks, summary_stats
from banklens_transforms.silver import to_bank_financials
from banklens_transforms.xray import evaluate_xray


def _pct(v) -> str:
    return "n/a" if v is None else f"{v:.1f}%"


def _leaderboard(gold: list[dict], metric: str, n: int, ascending: bool = False) -> list[dict]:
    rows = [g for g in gold if g.get(metric) is not None]
    rows.sort(key=lambda g: g[metric], reverse=not ascending)
    return rows[:n]


def run(repdte: str, data_dir: Path, highlight_cert: int) -> None:
    bronze = data_dir / "bronze" / "source=fdic" / "population" / f"repdte={repdte}" / "records.json"
    print(f"[1/3] LOAD   — population Bronze  {bronze}")
    raw = json.loads(bronze.read_text(encoding="utf-8-sig"))
    print(f"        {len(raw)} banks")

    print("[2/3] SILVER+GOLD — cross-sectional (one quarter, many banks)")
    silver = [to_bank_financials(r) for r in raw]
    gold = [gold_features(s) for s in silver]     # prev=None: no QoQ across different banks

    print("[3/3] PEERS  — percentile ranks across the population\n")
    add_percentile_ranks(gold)
    out = data_dir / "gold" / "population" / f"repdte={repdte}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gold.json").write_text(json.dumps(gold, indent=2), encoding="utf-8")

    W = 78
    print("=" * W)
    print(f"  MVP PEER SET — US banks $1B-$250B assets — {silver[0]['quarter']}   (n={len(gold)})")
    print("=" * W)
    print("  Distribution of key metrics (median / p90 / max):")
    for m, lbl in [("uninsured_deposit_pct", "Uninsured deposit %"),
                   ("concentration_ratio_cre", "CRE concentration %"),
                   ("cre_to_equity_pct", "CRE / equity %"),
                   ("loan_to_deposit_pct", "Loan-to-deposit %"),
                   ("cet1_ratio", "CET1 %")]:
        s = summary_stats(gold, m)
        print(f"    {lbl:<22} {s.get('median','-'):>8} / {s.get('p90','-'):>8} / {s.get('max','-'):>8}")

    def show_board(title: str, metric: str, ascending: bool = False):
        print(f"\n  {title}")
        for g in _leaderboard(gold, metric, 8, ascending):
            name = (g["name"] or "")[:38]
            print(f"    {_pct(g[metric]):>7}  (pctile {g.get('percentile_rank_' + metric, '-'):>5})  {name}")

    show_board("Most CRE-concentrated (CRE % of loans):", "concentration_ratio_cre")
    show_board("Highest uninsured-deposit reliance:", "uninsured_deposit_pct")
    show_board("Thinnest capital (lowest CET1):", "cet1_ratio", ascending=True)

    # ---- highlight one bank vs its peers -----------------------------------
    hi = next((g for g in gold if g.get("cert_number") == highlight_cert), None)
    if hi:
        print("\n  " + "-" * (W - 4))
        print(f"  PEER STANDING — {hi['name']}  (CERT {highlight_cert})")
        for m, lbl in [("concentration_ratio_cre", "CRE concentration"),
                       ("cre_to_equity_pct", "CRE / capital"),
                       ("uninsured_deposit_pct", "Uninsured deposits"),
                       ("loan_to_deposit_pct", "Loan-to-deposit"),
                       ("cet1_ratio", "CET1")]:
            pr = hi.get(f"percentile_rank_{m}")
            print(f"    {lbl:<20} {_pct(hi.get(m)):>8}   -> {pr:>5}th percentile vs peers"
                  if pr is not None else f"    {lbl:<20} {_pct(hi.get(m)):>8}")
        x = evaluate_xray(hi)   # gold row now carries percentile_rank_* -> flags get peer context
        print(f"\n  X-RAY: {x['overall_risk'].upper()} ({x['flag_count']} flag(s))")
        for f in x["flags"]:
            peer = f"  [{f['peer_percentile']}th pctile]" if "peer_percentile" in f else ""
            print(f"    [{f['severity'].upper():>4}] {f['factor']}: {f['value']}{peer}")
    print("=" * W)
    print(f"  Wrote population Gold ({len(gold)} banks) to {out}\\gold.json\n")


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens population peer report")
    p.add_argument("--repdte", default="20260331", help="report date (YYYYMMDD)")
    p.add_argument("--highlight-cert", type=int, default=6976,
                   help="bank to profile vs peers (default 6976 = Dime Community Bank)")
    p.add_argument("--data-dir", type=Path,
                   default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.repdte, args.data_dir, args.highlight_cert)


if __name__ == "__main__":
    main()
