"""Drive the BankLens MCP server over real stdio and pretty-print the exchange.

Spawns `python -m banklens_mcp.server`, performs the MCP handshake, lists tools, and
calls several — proving the same feature logic is now agent/-client-callable.

    python scripts/mcp_demo.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([
        str(REPO / "services" / "mcp-server" / "src"),
        str(REPO / "pipelines" / "transforms" / "src"),
    ])
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "banklens_mcp.server"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env, cwd=str(REPO),
    )

    def send(obj):
        proc.stdin.write(json.dumps(obj) + "\n")
        proc.stdin.flush()

    def recv():
        return json.loads(proc.stdout.readline())

    def call(mid, name, args):
        send({"jsonrpc": "2.0", "id": mid, "method": "tools/call",
              "params": {"name": name, "arguments": args}})
        r = recv()
        text = r["result"]["content"][0]["text"]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    # handshake
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2025-06-18", "capabilities": {}}})
    init = recv()
    print(f"initialize -> {init['result']['serverInfo']}")
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = recv()["result"]["tools"]
    print(f"tools/list -> {len(tools)} tools: {', '.join(t['name'] for t in tools)}\n")

    print("list_banks(state=NY, max_assets_b=20, limit=3):")
    for b in call(3, "list_banks", {"state": "NY", "max_assets_b": 20, "limit": 3})["banks"]:
        print(f"   {b['cert']:>6}  {b['name'][:34]:<34} ${b['assets_b']}B  [{b['cluster']}]")

    print("\nget_bank_xray(6976 Dime):")
    x = call(4, "get_bank_xray", {"cert": 6976})
    print(f"   overall risk: {x['overall_risk'].upper()}  ({x['flag_count']} flags)")
    for f in x["flags"]:
        peer = f"  {f['peer_percentile']}th pctile" if "peer_percentile" in f else ""
        print(f"     [{f['severity']}] {f['factor']}: {f['value']}{peer}")

    print("\nget_peer_cluster(6976):")
    pc = call(5, "get_peer_cluster", {"cert": 6976})
    print(f"   {pc['cluster_label']} ({pc['cluster_size']} banks); peers e.g. "
          f"{', '.join(n[:20] for n in pc['sample_peers'][:3])}")

    print("\nrun_stress_test(6976, outflow=60%, +400bps):")
    s = call(6, "run_stress_test", {"cert": 6976, "deposit_outflow_pct": 60, "rate_shock_bps": 400})
    print(f"   CET1 {s['before']['cet1']}% -> {s['after']['cet1']}%   "
          f"overall {'PASS' if s['passes_all'] else 'FAIL'}")

    print("\nfind_ma_matches(6976, top_n=3):")
    for c in call(7, "find_ma_matches", {"cert": 6976, "top_n": 3})["candidates"]:
        print(f"   {c['fit_score']}  {c['name'][:34]}")

    print("\ndiff_filings(3511 Wells Fargo):")
    d = call(8, "diff_filings", {"cert": 3511})
    print(f"   {d['from_quarter']}->{d['to_quarter']}: {d['n_flags']} flag(s)")
    for f in d["flags"]:
        print(f"     {f['item']} {f['change']}{f['unit']} (z={f['z']})")

    proc.stdin.close()
    proc.wait(timeout=5)
    print("\nAudit log: mcp_audit_log table in Postgres (docker compose up -d postgres), "
          "or data/mcp_audit.jsonl if Postgres is unreachable")


if __name__ == "__main__":
    main()
