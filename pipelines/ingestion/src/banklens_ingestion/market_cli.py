"""Land real EOD price history for banks the crosswalk has matched to a real
ticker — the quant terminal's candlestick data source.

Requires TIINGO_API_KEY (env var or .env) — get a free key (no card) at
https://api.tiingo.com/account/api/token. This is the ONE thing in the whole
pipeline that genuinely cannot be run without the user's own key; every other
BankLens data source (FDIC, SEC, Fed) is keyless.

Respects the free tier (250 calls/day, 50 symbols/hour): defaults to a small batch
and a real per-call delay; re-running skips tickers already landed within
--refresh-days (default 1) so you don't burn quota re-fetching the same data.

    powershell -File scripts/land_market_data.ps1              # first ~20 banks
    powershell -File scripts/land_market_data.ps1 -Limit 50
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .sources.tiingo import MissingApiKey, TiingoSource


def _load_crosswalk(data_dir: Path) -> list[dict]:
    path = data_dir / "silver" / "crosswalk.json"
    if not path.exists():
        raise SystemExit(
            f"No crosswalk found at {path} — run scripts/crosswalk.ps1 first "
            "(it's what supplies real tickers for this step)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _already_fresh(path: Path, refresh_days: int) -> bool:
    if not path.exists():
        return False
    age = datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    return age < timedelta(days=refresh_days)


def run(data_dir: Path, limit: int, refresh_days: int, start_date: str) -> None:
    rows = _load_crosswalk(data_dir)
    candidates = [r for r in rows if r["match_type"] in ("exact", "high_confidence") and r.get("ticker")]
    print(f"{len(candidates)} high-confidence ticker matches available in the crosswalk; "
          f"landing up to {limit} (free tier: 250 calls/day, 50 symbols/hour).")

    src = TiingoSource()
    out_root = data_dir / "bronze" / "source=tiingo" / "daily"
    landed, skipped, failed = 0, 0, 0

    try:
        for r in candidates[:limit]:
            ticker = r["ticker"]
            out_dir = out_root / f"ticker={ticker}"
            out_path = out_dir / "records.json"
            if _already_fresh(out_path, refresh_days):
                skipped += 1
                continue
            try:
                print(f"  fetching {ticker} ({r['name'][:40]})...")
                raw = src.fetch_daily_prices(ticker, start_date=start_date)
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
                landed += 1
                print(f"    -> {len(raw)} bars")
            except Exception as e:
                failed += 1
                print(f"    FAILED: {e}")
    except MissingApiKey as e:
        print(f"\n{e}")
        # `from None`: the message is already printed for the user, so a chained
        # traceback would add noise, not information, to a clean config-error exit.
        raise SystemExit(1) from None

    print(f"\nLanded {landed}, skipped {skipped} (already fresh), failed {failed}.")
    print(f"Data under {out_root}")


def main() -> None:
    p = argparse.ArgumentParser(description="Land real EOD prices for crosswalk-matched banks")
    p.add_argument("--limit", type=int, default=20, help="max tickers to fetch this run")
    p.add_argument("--refresh-days", type=int, default=1,
                   help="skip a ticker if already landed within this many days")
    p.add_argument("--start-date", default="2023-01-01", help="earliest date to pull")
    p.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parents[4] / "data")
    args = p.parse_args()
    run(args.data_dir, args.limit, args.refresh_days, args.start_date)


if __name__ == "__main__":
    main()
