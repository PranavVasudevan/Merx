"""Build the CERT<->CIK<->RSSD crosswalk over the landed population and SEC ticker
directory, print match-rate stats and samples, and save it to Silver.

    powershell -File scripts/crosswalk.ps1
    python -m banklens_ingestion.crosswalk_cli
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from banklens_transforms.crosswalk import build_crosswalk, crosswalk_stats
from banklens_transforms.silver import to_bank_financials

from .sources.sec import SecSource


def _load(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _latest_usd(company_facts: dict, concept: str) -> tuple[str, float] | None:
    try:
        points = company_facts["facts"]["us-gaap"][concept]["units"]["USD"]
    except KeyError:
        return None
    filed = [p for p in points if p.get("form") in ("10-K", "10-Q")]
    if not filed:
        return None
    latest = sorted(filed, key=lambda p: p["end"])[-1]
    return latest["end"], latest["val"]


def verify_one(rows: list[dict], silver: list[dict], cert_hint: str) -> None:
    """Cross-source proof: fetch the matched SEC filer's real Assets and compare to
    the FDIC bank-level figure for the same real-world institution. LIVE network call."""
    hit = next((r for r in rows if r["cik"] and cert_hint in r["name"].upper()), None)
    if not hit:
        print(f"  (no matched crosswalk row for '{cert_hint}' to verify)")
        return
    fdic_bank = next((s for s in silver
                      if (s.get("holding_company_rssd") or s.get("rssd_id")) == hit["rssd"]), None)
    print(f"\n  VERIFY — {hit['name']} (CIK {hit['cik']}, ticker {hit['ticker']}) "
          f"vs FDIC CERT {fdic_bank['cert_number'] if fdic_bank else '?'}")
    try:
        facts = SecSource().fetch_company_facts(hit["cik"])
        sec_point = _latest_usd(facts, "Assets")
        if sec_point and fdic_bank:
            sec_end, sec_val = sec_point
            print(f"    SEC  (holding-co, {sec_end}):  ${sec_val/1e9:.2f}B")
            print(f"    FDIC (bank-level, {fdic_bank['quarter']}):  "
                  f"${fdic_bank['total_assets']/1e9:.2f}B")
            ratio = sec_val / fdic_bank["total_assets"]
            note = ("exact match — this bank has no separate holding company"
                    if abs(ratio - 1) < 0.02 else
                    "SEC > FDIC as expected — the holding co. is a superset of the bank subsidiary"
                    if ratio > 1 else "SEC < FDIC — unexpected, worth a closer look")
            print(f"    -> {note}")
    except Exception as e:
        print(f"    (live SEC fetch failed: {e})")


def run(repdte: str, data_dir: Path, verify: str | None) -> None:
    fdic_path = data_dir / "bronze" / "source=fdic" / "population" / f"repdte={repdte}" / "records.json"
    sec_path = data_dir / "bronze" / "source=sec" / "tickers" / "records.json"

    print("[1/3] LOAD  — FDIC population + SEC ticker directory")
    fdic_raw = _load(fdic_path)
    sec_raw = _load(sec_path)
    silver = [to_bank_financials(r) for r in fdic_raw]
    print(f"        {len(silver)} banks, {len(sec_raw)} SEC filers")

    # unique holding companies by RSSD (many bank CERTs can share one holding co).
    # Some banks have NO separate holding company (e.g. Zions, Flagstar both
    # eliminated their BHC structure and report to SEC at the bank level directly) —
    # for those, fall back to the bank's own name/RSSD as the crosswalk unit.
    holding_companies: dict[int, str] = {}
    for s in silver:
        rssd = s.get("holding_company_rssd") or s.get("rssd_id")
        name = s.get("holding_company_name") or s.get("name")
        if rssd and name and rssd not in holding_companies:
            holding_companies[rssd] = name
    # First occurrence per CIK wins — SEC lists the primary common-stock ticker
    # before preferred-share/note variants (e.g. WFC before WFC-PZ) for the same filer.
    sec_tickers: dict[int, dict] = {}
    for row in sec_raw:
        sec_tickers.setdefault(row["cik_str"], {"ticker": row["ticker"], "title": row["title"]})

    print(f"[2/3] MATCH — {len(holding_companies)} unique holding companies vs "
          f"{len(sec_tickers)} SEC filers (dependency-free fuzzy match)")
    rows = build_crosswalk(holding_companies, sec_tickers)
    stats = crosswalk_stats(rows)

    print("[3/3] SAVE  — writing crosswalk to Silver\n")
    out_dir = data_dir / "silver"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "crosswalk.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    W = 78
    print("=" * W)
    print("  CERT <-> CIK <-> RSSD CROSSWALK")
    print("=" * W)
    print(f"  {stats['total']} holding companies | match rate {stats['match_rate_pct']}%")
    print(f"    exact ............. {stats['exact']}")
    print(f"    high_confidence ... {stats['high_confidence']}  (score >= 0.85)")
    print(f"    low_confidence .... {stats['low_confidence']}  (0.60-0.85, needs review)")
    print(f"    none .............. {stats['none']}")

    print("\n  Sample matches:")
    for label, cert_hint in [("Wells Fargo & Company", "WELLS FARGO"),
                              ("Zions", "ZIONS"), ("Flagstar", "FLAGSTAR"),
                              ("Dime Community", "DIME")]:
        hit = next((r for r in rows if cert_hint in r["name"].upper()), None)
        if hit:
            print(f"    {hit['name']:<38} -> CIK {hit['cik']} ({hit['ticker']})  "
                  f"[{hit['match_type']}, score={hit['match_score']}]")
        else:
            print(f"    {label}: not in this population slice")

    print(f"\n  Wrote {len(rows)} rows to {out_dir}\\crosswalk.json")

    if verify:
        verify_one(rows, silver, verify)
    print("=" * W)


def main() -> None:
    p = argparse.ArgumentParser(description="BankLens CERT<->CIK<->RSSD crosswalk builder")
    p.add_argument("--repdte", default="20260331")
    p.add_argument("--verify", default=None,
                   help="cross-source validation: live-fetch SEC assets for a matched "
                        "bank (name substring) and compare to FDIC's figure")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.repdte, args.data_dir, args.verify)


if __name__ == "__main__":
    main()
