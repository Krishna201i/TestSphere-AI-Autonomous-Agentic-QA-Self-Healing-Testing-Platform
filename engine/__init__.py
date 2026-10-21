"""TestSphere-AI QA Execution Engine — Member 2 scope."""

import os
from pathlib import Path

# build.sh / render-build.sh install Chromium into <project>/.playwright-browsers
# because hosts like Render drop ~/.cache between build and runtime.  Point
# Playwright there unless the environment already chose a location.
_PROJECT_BROWSERS = Path(__file__).resolve().parent.parent / ".playwright-browsers"
if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ and _PROJECT_BROWSERS.is_dir():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_PROJECT_BROWSERS)
