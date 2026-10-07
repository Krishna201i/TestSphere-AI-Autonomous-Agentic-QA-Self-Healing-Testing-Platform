#!/usr/bin/env bash
# TestSphere-AI — Build Script
set -o errexit

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

echo "=== Installing Playwright Chromium browser ==="
python -m playwright install --with-deps chromium || python -m playwright install chromium || true

echo "=== Building Frontend React SPA ==="
if [ -d "frontend" ]; then
  cd frontend
  npm install
  npm run build
  cd ..
fi

echo "=== Build completed! ==="
