"""TestSphere-AI — Failure Analyzer subpackage.

Day 1: Placeholder ABC and skeletal schemas.
Day 9: Full concrete implementation with structured schemas.
Member 1 Enhancements:
  - FailureClassifier: Deterministic rule-based classification.
  - FailureAnalysisAgent (new): High-level analysis agent.
"""

from agents.analyzer.analyzer import FailureAnalyzerAgent
from agents.analyzer.failure_analysis_agent import (
    FailureAnalysisAgent as FailureAnalysisAgentV2,
    FailureAnalysisResult,
    Severity,
)
from agents.analyzer.failure_classifier import (
    ClassificationResult,
    FailureClassifier,
)
from agents.analyzer.schemas import (
    FailureAnalysis,
    FailureContext,
    FailureEvidence,
    HistoricalContext,
    TestFailure,
)

__all__ = [
    # Original (Day 9)
    "FailureAnalyzerAgent",
    "FailureAnalysis",
    "FailureContext",
    "FailureEvidence",
    "HistoricalContext",
    "TestFailure",
    # New — Member 1 enhancements
    "FailureClassifier",
    "ClassificationResult",
    "FailureAnalysisAgentV2",
    "FailureAnalysisResult",
    "Severity",
]
