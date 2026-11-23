"""TestSphere-AI — Goal explorer: an AI agent reaches a written goal in a live
browser once, and its verified steps are recorded as an ordinary test that
later runs replay without the model."""

from agents.explorer.explorer import ExplorationResult, GoalExplorer

__all__ = ["ExplorationResult", "GoalExplorer"]
