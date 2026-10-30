"""
Store the backend's secrets in SSM Parameter Store, encrypted, for the EC2 server.

    python deploy/aws-ec2/store-secrets.py                 # from the repository root
    python deploy/aws-ec2/store-secrets.py --env-file path/to/.env
    python deploy/aws-ec2/store-secrets.py --env-file render.env --all   # every setting in the file

Reads the keys below from the .env file (FIREBASE_CREDENTIALS may be a path to
the service-account JSON or the JSON itself) and writes each one as a
SecureString under /testsphere/.  With --all, every setting in the file is
stored except those the server sets itself (SERVER_SET) and hosting-specific
ones, e.g. to move a previous host's environment over.  Values are handed to
the AWS CLI in a temporary file, never on its command line, and are never
printed.  Run it again after changing a key; then rerun fetch-env.sh on the server.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KEYS = ["FIREBASE_CREDENTIALS", "FIREBASE_WEB_API_KEY", "LLM_PROVIDER", "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"]
# Set by docker-compose.yml (or meaningless on EC2): never copied with --all
SERVER_SET = {"APP_ENV", "PORT", "PIPELINE_EXECUTION", "ENGINE_MAX_BROWSERS", "CORS_ORIGINS", "DASHBOARD_URL",
              "LOG_FORMAT", "DATABASE_BACKEND", "LOCAL_DB_PATH", "ARTIFACTS_DIR", "PYTHON_VERSION", "NODE_VERSION",
              "VITE_API_URL", "BACKEND_HOST", "BACKEND_PORT", "DEBUG"}
STANDARD_TIER_LIMIT = 4096


def read_env(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)", line)
        if m:
            values[m.group(1)] = m.group(2).strip().strip('"').strip("'")
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--profile", default="testsphere")
    parser.add_argument("--region", default="ap-southeast-2")
    parser.add_argument("--all", action="store_true", help="store every setting in the file, not only KEYS")
    args = parser.parse_args()

    aws = shutil.which("aws") or str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Amazon/AWSCLIV2/aws.exe")
    env = read_env(Path(args.env_file))
    creds = env.get("FIREBASE_CREDENTIALS", "")
    if creds and not creds.lstrip().startswith("{"):
        if Path(creds).is_file():
            creds = Path(creds).read_text(encoding="utf-8")
        else:  # e.g. a Render Secret File name: nothing here to copy
            print(f"FIREBASE_CREDENTIALS: {creds!r} is not a file here, skipped")
            env.pop("FIREBASE_CREDENTIALS")
            creds = ""
    if creds:
        env["FIREBASE_CREDENTIALS"] = json.dumps(json.loads(creds), separators=(",", ":"))

    keys = KEYS
    if args.all:
        keys = [k for k in env if k not in SERVER_SET and not k.startswith("RENDER")]
        skipped = sorted(k for k in env if k not in keys)
        if skipped:
            print("not copied (set by the server or host-specific):", ", ".join(skipped))
    failed = 0
    for key in keys:
        value = env.get(key)
        if not value:
            print(f"{key}: not in {args.env_file}, skipped")
            continue
        fd, tmp = tempfile.mkstemp()
        try:
            os.write(fd, value.encode("utf-8"))
            os.close(fd)
            result = subprocess.run(
                [aws, "ssm", "put-parameter", "--profile", args.profile, "--region", args.region,
                 "--name", f"/testsphere/{key}", "--type", "SecureString", "--overwrite",
                 "--tier", "Advanced" if len(value) > STANDARD_TIER_LIMIT else "Standard",
                 "--value", f"file://{tmp}", "--query", "Version", "--output", "text"],
                capture_output=True, text=True, check=False)
        finally:
            os.remove(tmp)
        if result.returncode == 0:
            print(f"{key}: stored (version {result.stdout.strip()})")
        else:
            failed += 1
            print(f"{key}: FAILED: {result.stderr.strip()[:300]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
