"""Land the Federal Reserve NIC holding-company data to Bronze: active bank
holding companies, their open/controlling ownership relationships, and one
quarter of FR Y-9C financials. Real, live data, no API key.

docs/audit/04-remediation-prompts.md B4. See sources/fed_nic.py for exactly
what's captured (and why the full ~2,200-column BHCF schema is curated down
to a dozen headline fields, same discipline as sources/fdic.py).

    python -m banklens_ingestion.fed_nic_land_cli
    python -m banklens_ingestion.fed_nic_land_cli --period 20250930
    powershell -File scripts/land_fed_nic.ps1
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .bronze.writer import write_partition
from .provenance import Provenance
from .sources.fed_nic import FedNicSource


def run(period: str, data_dir: Path) -> None:
    src = FedNicSource()

    print("Landing Fed NIC active bank-holding-company attributes...")
    attrs, attrs_url = src.fetch_attributes()
    prov = Provenance.create(source=src.name, endpoint=attrs_url, license=src.license, payload=attrs)
    write_partition(attrs, prov, base_dir=data_dir / "bronze", source="fed_nic", parts=("attributes",))
    print(f"  {len(attrs)} active bank holding companies   checksum {prov.checksum[:12]}...")

    print("Landing Fed NIC ownership relationships (open, controlling stakes only)...")
    rels, rels_url = src.fetch_relationships()
    prov2 = Provenance.create(source=src.name, endpoint=rels_url, license=src.license, payload=rels)
    write_partition(rels, prov2, base_dir=data_dir / "bronze", source="fed_nic", parts=("relationships",))
    print(f"  {len(rels)} relationships   checksum {prov2.checksum[:12]}...")

    print(f"Landing FR Y-9C financials for {period}...")
    fin, fin_url = src.fetch_financials(period)
    prov3 = Provenance.create(source=src.name, endpoint=fin_url, license=src.license, payload=fin)
    write_partition(fin, prov3, base_dir=data_dir / "bronze", source="fed_nic",
                    parts=("financials", f"period={period}"))
    reporting = sum(1 for r in fin if r.get("total_assets") is not None)
    print(f"  {len(fin)} holding companies ({reporting} with total_assets reported)   "
          f"checksum {prov3.checksum[:12]}...")


def main() -> None:
    p = argparse.ArgumentParser(description="Land Fed NIC holding-company data to Bronze")
    p.add_argument("--period", default="20251231", help="FR Y-9C quarter-end (YYYYMMDD)")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.period, args.data_dir)


if __name__ == "__main__":
    main()
