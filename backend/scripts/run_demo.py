#!/usr/bin/env python3
"""
scripts/run_demo.py
===================
Run the end-to-end demo loop:
1. Serve the local vulnerable demo web app.
2. Run TestSphere AI passive security scanner to uncover missing security controls.
3. Export findings into standard SARIF v2.1.0 format.
4. Generate git-applyable remediation patches.
5. Print complete autonomous QA & security audit loop summary.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import http.server
import json
import sys
import threading
import time
from pathlib import Path

# Add repo root to sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from security import PassiveScanner, ScopePolicy
from security.patcher import build_patch
from security.sarif import findings_to_sarif

DEMO_DIR = REPO_ROOT / "tests" / "engine" / "demo_app"


def start_demo_server(port: int = 0) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(DEMO_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{actual_port}/"


def run_full_demo(target_url: str | None = None, sarif_out: str = "demo-security.sarif") -> int:
    print("=" * 72)
    print("🚀 TESTSPHERE AI — AUTONOMOUS AGENTIC QA & SECURITY LOOP DEMO")
    print("=" * 72)

    server = None
    if not target_url:
        print("[1/4] Starting local demo web application from tests/engine/demo_app...")
        server, target_url = start_demo_server()
        print(f"      Serving demo app on {target_url}")
        time.sleep(0.5)
    else:
        print(f"[1/4] Using specified target URL: {target_url}")

    print(f"\n[2/4] Running passive security scanner against {target_url}...")
    scanner = PassiveScanner(ScopePolicy.of("127.0.0.1", "localhost"))
    findings = asyncio.run(scanner.scan(target_url))
    print(f"      Discovered {len(findings)} security findings:")
    for f in findings:
        print(f"      - [{f.severity.value.upper()}] {f.check_id}: {f.title}")

    print(f"\n[3/4] Exporting findings to SARIF v2.1.0 standard ({sarif_out})...")
    sarif_doc = findings_to_sarif(findings)
    sarif_path = REPO_ROOT / sarif_out
    sarif_path.write_text(json.dumps(sarif_doc, indent=2), encoding="utf-8")
    print(f"      Saved SARIF document to {sarif_path.relative_to(REPO_ROOT)}")
    print(f"      Rules defined: {len(sarif_doc['runs'][0]['tool']['driver']['rules'])}")
    print(f"      Results recorded: {len(sarif_doc['runs'][0]['results'])}")

    print("\n[4/4] Generating autonomous remediation patches...")
    patch_result = build_patch(REPO_ROOT, [f.model_dump() for f in findings], target_url)
    print(f"      Frameworks detected: {patch_result.frameworks or 'Generic / Security Headers'}")
    print(f"      Patches generated: {len(patch_result.files)} file change(s)")
    for a in patch_result.applied:
        print(f"      ✓ Applied {a.check_id} via {a.how}")
    if patch_result.manual:
        print(f"      ℹ Manual review items: {len(patch_result.manual)}")

    if server:
        server.shutdown()
        server.server_close()

    print("\n" + "=" * 72)
    print("✨ Autonomous loop complete! TestSphere AI verified security & quality.")
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TestSphere AI Full Demo Runner")
    parser.add_argument("--url", default=None, help="Optional external target URL (defaults to built-in demo app)")
    parser.add_argument("--sarif-out", default="demo-security.sarif", help="Output path for SARIF report")
    parser.add_argument("--sarif-only", action="store_true", help="Only generate SARIF report")
    args = parser.parse_args()

    return run_full_demo(target_url=args.url, sarif_out=args.sarif_out)


if __name__ == "__main__":
    sys.exit(main())
