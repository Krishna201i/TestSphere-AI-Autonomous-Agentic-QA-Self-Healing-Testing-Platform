"""
Run a passive scan from the command line.

    python -m security http://127.0.0.1:8000/
    python -m security https://staging.example.test/ --allow staging.example.test
    python -m security http://127.0.0.1:8000/ --json
    python -m security http://127.0.0.1:8000/search?q=x --active --allow 127.0.0.1:8000

Loopback hosts are always in scope; anything else needs an explicit --allow.
--active also runs the DAST scanner (sends test inputs); use it only on apps you own.
Exit code: 0 = no medium+ findings, 1 = medium+ findings, 2 = scan refused/failed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from security.active_scanner import ActiveScanError, ActiveScanner
from security.findings import Severity
from security.passive_scanner import PassiveScanner, ScanError
from security.scope import LOOPBACK_HOSTS, OutOfScopeError, ScopePolicy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m security", description="Passive security scan")
    parser.add_argument("url", help="Page to scan")
    parser.add_argument(
        "--allow", action="append", default=[], metavar="HOST[:PORT]",
        help="Authorize an additional host (repeatable). Only scan hosts you own or may test.",
    )
    parser.add_argument("--json", action="store_true", help="Print findings as JSON")
    parser.add_argument("--active", action="store_true",
                        help="Also run the active (DAST) scanner. Sends test inputs; only for apps you own.")
    args = parser.parse_args(argv)

    scope = ScopePolicy.of(*LOOPBACK_HOSTS, *args.allow)
    try:
        findings = asyncio.run(PassiveScanner(scope).scan(args.url))
        if args.active:
            findings += asyncio.run(ActiveScanner(scope).scan(args.url))
    except (OutOfScopeError, ScanError, ActiveScanError) as exc:
        print(f"Scan refused/failed: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([f.model_dump(mode="json") for f in findings], indent=2))
    else:
        print(f"{len(findings)} finding(s) for {args.url}\n")
        for f in findings:
            print(f"[{f.severity.value.upper():8}] {f.check_id:20} {f.title}")
            for line in f.evidence:
                print(f"{'':32}- {line}")

    return 1 if any(f.severity.rank <= Severity.MEDIUM.rank for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())
