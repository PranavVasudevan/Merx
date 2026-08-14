"""Land real EOD price history for banks the crosswalk has matched to a real
ticker — the quant terminal's candlestick data source.

Requires TIINGO_API_KEY (env var or .env) — get a free key (no card) at
https://api.tiingo.com/account/api/token. This is the ONE thing in the whole
pipeline that genuinely cannot be run without the user's own key; every other
BankLens data source (FDIC, SEC, Fed) is keyless.

Respects the free tier (250 calls/day, 50 symbols/hour) with real, persisted
state rather than hoping a per-call delay is enough:

  - A CURSOR (data/bronze/source=tiingo/_land_state.json) advances through the
    full eligible ticker universe, sorted by ticker for a deterministic order,
    round-robin across runs — so successive daily/quarterly runs keep covering
    NEW tickers instead of always re-attempting the same head-of-list slice
    (which is what happened before: once the first `--limit` tickers were
    landed and still "fresh" within --refresh-days, every later run skipped
    all of them and landed nothing new, capping coverage at whatever --limit
    the very first run happened to use).
  - An HOURLY CALL BUDGET (same state file's call_log) tracks how many Tiingo
    calls happened in the trailing 60 minutes and stops landing new tickers
    once that hits tiingo.HOURLY_SYMBOL_CAP, rather than relying on Tiingo's
    own 429 + this connector's reactive backoff to discover the ceiling.
  - A COVERAGE RECORD (data/bronze/source=tiingo/_coverage.json) — tickers
    landed / tickers eligible / oldest bar age — written after every run, so
    the app can report real coverage instead of a caller having to infer it
    from "did my one candlestick request 404".

    powershell -File scripts/land_market_data.ps1              # first ~20 banks
    powershell -File scripts/land_market_data.ps1 -Limit 50
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .sources import tiingo
from .sources.tiingo import MissingApiKey, TiingoSource

_STATE_FILENAME = "_land_state.json"
_COVERAGE_FILENAME = "_coverage.json"


def _tiingo_root(data_dir: Path) -> Path:
    return data_dir / "bronze" / "source=tiingo"


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


def _load_state(data_dir: Path) -> dict:
    p = _tiingo_root(data_dir) / _STATE_FILENAME
    if not p.exists():
        return {"cursor": 0, "call_log": []}
    try:
        state = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"cursor": 0, "call_log": []}
    return {"cursor": int(state.get("cursor", 0)), "call_log": list(state.get("call_log", []))}


def _save_state(data_dir: Path, cursor: int, call_log: list[str]) -> None:
    p = _tiingo_root(data_dir) / _STATE_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"cursor": cursor, "call_log": call_log}, indent=2), encoding="utf-8")


def _recent_call_log(call_log: list[str]) -> list[str]:
    """The call_log trimmed to calls within the trailing hour — everything
    older is irrelevant to the rolling 50/hour ceiling and would otherwise
    grow the state file forever."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    out = []
    for ts in call_log:
        try:
            if datetime.fromisoformat(ts) > cutoff:
                out.append(ts)
        except ValueError:
            continue
    return out


def _write_coverage(data_dir: Path, candidates: list[dict]) -> dict:
    """Real, honest coverage over the FULL eligible universe (not just this
    run's slice) — tickers landed, coverage %, and how stale the oldest
    landed bar is. Persisted so get_market_coverage (banklens_mcp) can report
    it without rescanning the filesystem on every request."""
    out_root = _tiingo_root(data_dir) / "daily"
    eligible = {r["ticker"] for r in candidates}
    landed = set()
    oldest_mtime: float | None = None
    if out_root.exists():
        for p in out_root.glob("ticker=*"):
            ticker = p.name.split("=", 1)[1]
            records = p / "records.json"
            if ticker in eligible and records.exists():
                landed.add(ticker)
                mtime = records.stat().st_mtime
                if oldest_mtime is None or mtime < oldest_mtime:
                    oldest_mtime = mtime

    oldest_age_days = None
    if oldest_mtime is not None:
        oldest_age_days = (datetime.now(timezone.utc)
                           - datetime.fromtimestamp(oldest_mtime, tz=timezone.utc)).days

    summary = {
        "eligible": len(eligible), "landed": len(landed),
        "coverage_pct": round(len(landed) / len(eligible) * 100, 1) if eligible else 0.0,
        "oldest_bar_age_days": oldest_age_days,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    p = _tiingo_root(data_dir) / _COVERAGE_FILENAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    age = summary["oldest_bar_age_days"]
    print(f"\nCoverage: {summary['landed']}/{summary['eligible']} eligible tickers landed "
         f"({summary['coverage_pct']}%), oldest bar age: {age if age is not None else 'n/a'} days.")
    return summary


def run(data_dir: Path, limit: int, refresh_days: int, start_date: str) -> None:
    rows = _load_crosswalk(data_dir)
    # Sorted for a STABLE, deterministic order the cursor can advance through
    # run over run — crosswalk.json's own row order can change across a
    # re-crosswalk, which would silently shift what an unsorted cursor meant.
    candidates = sorted(
        (r for r in rows if r["match_type"] in ("exact", "high_confidence") and r.get("ticker")),
        key=lambda r: r["ticker"])
    total_eligible = len(candidates)
    if total_eligible == 0:
        print("No high-confidence ticker matches in the crosswalk yet.")
        return

    state = _load_state(data_dir)
    cursor = state["cursor"] % total_eligible
    call_log = _recent_call_log(state["call_log"])
    budget_remaining = max(0, tiingo.HOURLY_SYMBOL_CAP - len(call_log))

    print(f"{total_eligible} high-confidence ticker matches available in the crosswalk; "
          f"resuming from cursor {cursor}, up to {limit} this run "
          f"(hourly budget remaining: {budget_remaining}/{tiingo.HOURLY_SYMBOL_CAP}).")

    if budget_remaining == 0:
        print("Hourly Tiingo call budget already used by a recent run — landing nothing "
              "new this run. Re-run in under an hour, or just let the next scheduled "
              "refresh pick the cursor back up.")
        _save_state(data_dir, cursor, call_log)
        _write_coverage(data_dir, candidates)
        return

    src = TiingoSource()
    out_root = _tiingo_root(data_dir) / "daily"
    landed, skipped, failed, attempts = 0, 0, 0, 0
    to_try = min(limit, budget_remaining)
    idx = cursor

    for _ in range(total_eligible):   # at most one full lap of the ticker universe per run
        if attempts >= to_try:
            break
        r = candidates[idx]
        idx = (idx + 1) % total_eligible
        ticker = r["ticker"]
        out_dir = out_root / f"ticker={ticker}"
        out_path = out_dir / "records.json"
        if _already_fresh(out_path, refresh_days):
            skipped += 1
            continue
        attempts += 1
        try:
            print(f"  fetching {ticker} ({r['name'][:40]})...")
            raw = src.fetch_daily_prices(ticker, start_date=start_date)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")
            landed += 1
            call_log.append(datetime.now(timezone.utc).isoformat())
            print(f"    -> {len(raw)} bars")
        except MissingApiKey as e:
            print(f"\n{e}")
            _save_state(data_dir, idx, call_log)
            # `from None`: the message is already printed for the user, so a
            # chained traceback would add noise, not information, to a clean
            # config-error exit.
            raise SystemExit(1) from None
        except Exception as e:
            failed += 1
            print(f"    FAILED: {e}")

    _save_state(data_dir, idx, call_log)
    print(f"\nLanded {landed}, skipped {skipped} (already fresh), failed {failed}.")
    print(f"Data under {out_root}")
    _write_coverage(data_dir, candidates)


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
