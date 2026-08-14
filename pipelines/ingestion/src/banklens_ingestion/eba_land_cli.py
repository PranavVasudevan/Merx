"""Land the EBA EU-wide Transparency Exercise (institutions + financials +
credit risk) to Bronze.

Real, live data — ~120 significant EU/EEA banks, no API key. See
`sources/eba.py` for exactly what's captured from the credit-risk cube
(`tr_cre.csv`) and what's deliberately still unparsed.

    python -m banklens_ingestion.eba_land_cli
    powershell -File scripts/land_eba.ps1
"""

from __future__ import annotations

import argparse
from pathlib import Path

from banklens_transforms.silver_eba import synthetic_cert_number

from .bronze.writer import write_partition
from .provenance import Provenance
from .sources.eba import EbaSource
from .sources.fx import FxSource


def run(data_dir: Path) -> None:
    fx = FxSource()
    print("Landing EUR->USD reference rate (ECB, via Frankfurter)...")
    rate = fx.fetch_eur_usd()
    fx_prov = Provenance.create(source=fx.name, endpoint=rate["source_url"],
                                license=fx.license, payload=[rate])
    write_partition([rate], fx_prov, base_dir=data_dir / "bronze", source="fx",
                    parts=("eur_usd",))
    print(f"  EUR->USD = {rate['rate']} (as of {rate['date']})")

    src = EbaSource()
    print("Landing EBA EU-wide Transparency Exercise institutions...")
    institutions, inst_url = src.fetch_institutions()
    prov = Provenance.create(source=src.name, endpoint=inst_url,
                             license=src.license, payload=institutions)
    write_partition(institutions, prov, base_dir=data_dir / "bronze", source="eba",
                    parts=("institutions",))
    print(f"  {len(institutions)} institutions   checksum {prov.checksum[:12]}...")

    # silver_eba.synthetic_cert_number's collision odds are astronomically low at
    # this population size (~120 banks in a 90M-wide range) — verified, not just
    # assumed, on every real land so a future larger exercise can't silently merge
    # two banks under one cert_number.
    synthetic_certs = [synthetic_cert_number(i["lei"]) for i in institutions]
    if len(set(synthetic_certs)) != len(synthetic_certs):
        dupes = {c for c in synthetic_certs if synthetic_certs.count(c) > 1}
        raise RuntimeError(
            f"synthetic_cert_number collision across {len(dupes)} cert(s) in this "
            f"landing — widen _CERT_RANGE in silver_eba.py before proceeding.")

    print("Landing EBA financials (Assets/Liabilities/Capital/Leverage/P&L)...")
    financials, fin_url = src.fetch_financials()
    prov2 = Provenance.create(source=src.name, endpoint=fin_url,
                              license=src.license, payload=financials)
    write_partition(financials, prov2, base_dir=data_dir / "bronze", source="eba",
                    parts=("financials",))
    periods = sorted({r["period"] for r in financials})
    print(f"  {len(financials)} bank-period rows across {len(periods)} period(s) "
          f"{periods}   checksum {prov2.checksum[:12]}...")

    print("Landing EBA credit risk (tr_cre.csv — NPL + NACE sector, two Item "
          "codes decoded of 89; see sources/eba.py)...")
    credit_risk, cre_url = src.fetch_credit_risk()
    prov3 = Provenance.create(source=src.name, endpoint=cre_url,
                              license=src.license, payload=credit_risk)
    write_partition(credit_risk, prov3, base_dir=data_dir / "bronze", source="eba",
                    parts=("credit_risk",))
    print(f"  {len(credit_risk)} bank-period rows   checksum {prov3.checksum[:12]}...")


def main() -> None:
    p = argparse.ArgumentParser(
        description="Land the EBA EU-wide Transparency Exercise to Bronze")
    p.add_argument("--data-dir", type=Path,
                   default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.data_dir)


if __name__ == "__main__":
    main()
