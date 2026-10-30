"""The production image must ship the system tools the backend shells out to."""

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parent.parent / "Dockerfile"


def _runtime_stage() -> str:
    # Everything after the last FROM: the stage the server runs
    return re.split(r"(?m)^FROM ", DOCKERFILE.read_text(encoding="utf-8"))[-1]


def test_the_runtime_image_installs_git():
    # Ingestion clones with git; patches and deploy checks call it too
    assert re.search(r"apt-get install[^\n]*\bgit\b", _runtime_stage()), "git missing from the runtime image"


def test_the_runtime_image_installs_chromium():
    assert "playwright install --with-deps chromium" in _runtime_stage()
