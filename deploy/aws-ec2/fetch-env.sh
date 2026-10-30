#!/bin/sh
# Write the secrets kept in SSM Parameter Store under /testsphere/ to
# /opt/testsphere/secrets.env (one NAME='value' per line), readable by root only.
# Runs on the instance with its own role; values never touch the repository.
set -eu
REGION="${AWS_REGION:-ap-southeast-2}"
OUT=/opt/testsphere/secrets.env
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

command -v aws >/dev/null || snap install aws-cli --classic

aws ssm get-parameters-by-path --region "$REGION" --path /testsphere/ --with-decryption \
  --query 'Parameters[].[Name,Value]' --output json \
  | python3 -c '
import json, sys
for name, value in json.load(sys.stdin):
    key = name.rsplit("/", 1)[-1]
    # env_file values are single-line: a JSON credential is compacted onto one line
    if value.lstrip().startswith("{"):
        value = json.dumps(json.loads(value), separators=(",", ":"))
    if "\x27" in value or "\n" in value:
        sys.exit(f"{key}: a value with a single quote or a newline cannot go in an env file")
    print(f"{key}=\x27{value}\x27")  # single quotes: Compose takes the value literally
' > "$TMP"

[ -s "$TMP" ] || { echo "no parameters found under /testsphere/" >&2; exit 1; }
install -m 600 "$TMP" "$OUT"
echo "wrote $(wc -l < "$OUT") settings to $OUT"
