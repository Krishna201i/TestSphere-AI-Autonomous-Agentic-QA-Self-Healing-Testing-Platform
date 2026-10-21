"""Test-wide settings, applied before any test module imports the app."""

import os

# Keep agent healing memory in-process so tests never write to the dev database
os.environ.setdefault("AGENT_MEMORY_BACKEND", "memory")
