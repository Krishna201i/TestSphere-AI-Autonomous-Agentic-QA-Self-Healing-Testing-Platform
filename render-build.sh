#!/usr/bin/env bash
# TestSphere-AI — Render Build Script
# Exit on error
set -o errexit

echo "=== Installing Python dependencies ==="
pip install --upgrade pip
pip install -r requirements.txt
pip install -e .

echo "=== Installing Playwright Chromium browser ==="
# Install browsers inside the project directory: hosts such as Render only ship
# the project directory to the runtime, so the default ~/.cache/ms-playwright
# location is missing when the service starts.  engine/__init__.py points
# Playwright at this directory at runtime.
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$PWD/.playwright-browsers}"
# --with-deps needs root (apt); fall back to the browser alone when it is unavailable.
python -m playwright install --with-deps chromium || python -m playwright install chromium
python -c "import asyncio
from playwright.async_api import async_playwright
async def main():
    async with async_playwright() as pw:
        await (await pw.chromium.launch(headless=True)).close()
asyncio.run(main())"
echo "Chromium installed and launchable from $PLAYWRIGHT_BROWSERS_PATH"

echo "=== Building Frontend React SPA ==="
if [ -d "frontend" ]; then
  cd frontend
  npm install
  npm run build
  cd ..
fi

echo "=== Render build finished successfully! ==="
