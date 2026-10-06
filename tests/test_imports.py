"""
TestSphere-AI — Import Validation Tests

Ensures all modules can be imported without errors.
This catches circular imports, missing dependencies,
and broken __init__.py files.
"""


class TestImports:
    """Validate that all modules import successfully."""

    def test_import_root_package(self):
        import agents  # noqa: F401

    def test_import_schemas_enums(self):
        from agents.schemas.enums import (  # noqa: F401
            FailureType,
            HealingStatus,
            TestCategory,
            TestPriority,
        )

    def test_import_schemas_contracts(self):
        from agents.schemas.contracts import (  # noqa: F401
            ApplicationContext,
            Assertion,
            FailureAnalysis,
            FailureType,
            HealingCandidate,
            HealingResult,
            HealingStatus,
            PageInfo,
            TestCase,
            TestCategory,
            TestFailure,
            TestPriority,
            TestStep,
        )

    def test_import_llm(self):
        from agents.llm import LLMClient, LLMConfig  # noqa: F401

    def test_import_planner(self):
        from agents.planner import (  # noqa: F401
            ApplicationContext,
            TestCase,
            TestPlannerAgent,
            TestStep,
        )

    def test_import_analyzer(self):
        from agents.analyzer import (  # noqa: F401
            FailureAnalysis,
            FailureAnalyzerAgent,
            TestFailure,
        )

    def test_import_healer(self):
        from agents.healer import (  # noqa: F401
            HealingCandidate,
            HealingResult,
            SelfHealingAgent,
        )

    def test_import_memory(self):
        from agents.memory import HealingMemory  # noqa: F401

    def test_import_orchestration(self):
        from agents.orchestration import AgentController  # noqa: F401
