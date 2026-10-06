"""
TestSphere-AI — Inter-Member Contract Converters.

Converts data models between Member 1 (AI Agent Layer) and Member 2 (Execution Engine).
Maintains bidirectional fidelity without modifying shared models or third-party contracts.
"""

from typing import List, Optional
from agents.analyzer.schemas import FailureContext
from agents.orchestration.workflow_schemas import (
    ExecutionResult,
    ExecutionResultStatus,
)
from agents.planner.schemas import (
    Assertion,
    TestCase as Member1TestCase,
    TestStep as Member1TestStep,
)
from agents.schemas.enums import AssertionType, TestAction
from engine.schemas import (
    ActionType,
    Step as EngineStep,
    StepStatus,
    Target as EngineTarget,
    TestPlan as EngineTestPlan,
    TestResult as EngineTestResult,
    TestStatus,
)


def create_engine_target(
    selector: Optional[str],
    description: str = "Target element",
) -> Optional[EngineTarget]:
    """Create an EngineTarget conforming to Member 2 schema."""
    if not selector:
        return None
    return EngineTarget(
        description=description,
        primary_locator=selector,
    )


def map_action_to_engine(action: TestAction) -> ActionType:
    """Map Member 1 TestAction enum to Member 2 ActionType enum."""
    mapping = {
        TestAction.NAVIGATE: ActionType.GOTO,
        TestAction.CLICK: ActionType.CLICK,
        TestAction.FILL: ActionType.FILL,
        TestAction.PRESS: ActionType.PRESS,
        TestAction.SELECT: ActionType.SELECT,
        TestAction.WAIT: ActionType.WAIT_FOR,
    }
    return mapping.get(action, ActionType.CLICK)


def map_assertion_to_engine(assertion: Assertion) -> EngineStep:
    """Map Member 1 Assertion to Member 2 assertion EngineStep."""
    target = create_engine_target(
        assertion.target,
        description=f"Assertion target for {assertion.type.value}",
    )

    if assertion.type in (
        AssertionType.ELEMENT_CONTAINS_TEXT,
        AssertionType.ELEMENT_HAS_TEXT,
    ):
        return EngineStep(
            step_id=f"assert-{assertion.type.value}",
            action=ActionType.ASSERT_TEXT,
            target=target,
            expected=assertion.expected,
        )

    # Default to ASSERT_VISIBLE for visibility assertions
    return EngineStep(
        step_id=f"assert-{assertion.type.value}",
        action=ActionType.ASSERT_VISIBLE,
        target=target,
        expected=assertion.expected or "",
    )


def test_case_to_engine_plan(
    test_case: Member1TestCase,
    base_url: str,
) -> EngineTestPlan:
    """Convert Member 1 TestCase into Member 2 EngineTestPlan.

    Transforms planned atomic actions and assertions into sequential Playwright steps.
    """
    engine_steps: List[EngineStep] = []

    # If test has steps, convert each
    for step in test_case.steps:
        target = create_engine_target(
            step.target,
            description=step.description or f"Step {step.step_number} element",
        )
        engine_action = map_action_to_engine(step.action)

        engine_step = EngineStep(
            step_id=f"step-{step.step_number}",
            action=engine_action,
            target=target,
            value=step.value,
            timeout_ms=step.timeout if step.timeout is not None else 5000,
        )
        engine_steps.append(engine_step)

        # Include inline assertions belonging to this step
        for idx, assertion in enumerate(step.assertions):
            assert_step = map_assertion_to_engine(assertion)
            assert_step.step_id = f"step-{step.step_number}-assert-{idx + 1}"
            engine_steps.append(assert_step)

    # Include top-level test case assertions
    for idx, assertion in enumerate(test_case.assertions):
        assert_step = map_assertion_to_engine(assertion)
        assert_step.step_id = f"case-assert-{idx + 1}"
        engine_steps.append(assert_step)

    # Ensure at least one step exists (e.g. goto root URL)
    if not engine_steps:
        engine_steps.append(
            EngineStep(
                step_id="step-1-init",
                action=ActionType.GOTO,
                value=base_url,
            )
        )

    return EngineTestPlan(
        test_id=test_case.test_id,
        name=test_case.name,
        base_url=base_url,
        steps=engine_steps,
    )


def engine_result_to_execution_result(
    engine_result: EngineTestResult,
    workflow_id: str,
    test_case_id: str,
    engine_plan: Optional[EngineTestPlan] = None,
) -> ExecutionResult:
    """Convert Member 2 EngineTestResult into Member 1 ExecutionResult.

    Builds rich FailureContext on failure to feed Member 1's FailureAnalyzerAgent.
    """
    if engine_result.status in (TestStatus.PASSED, TestStatus.HEALED):
        return ExecutionResult(
            workflow_id=workflow_id,
            test_case_id=test_case_id,
            status=ExecutionResultStatus.SUCCESS,
        )

    # Locate failed step
    failed_step_index = 1
    failed_step_action = "click"
    failed_target_selector = ""
    error_msg = "Execution step failed"

    for idx, step_res in enumerate(engine_result.steps):
        if step_res.status == StepStatus.FAILED:
            failed_step_index = idx + 1
            error_msg = step_res.error or error_msg
            if engine_plan and idx < len(engine_plan.steps):
                plan_step = engine_plan.steps[idx]
                failed_step_action = plan_step.action.value
                if plan_step.target:
                    failed_target_selector = plan_step.target.primary_locator
            break

    failure_context = FailureContext(
        test_id=test_case_id,
        execution_id=workflow_id,
        failed_step=failed_step_index,
        action=failed_step_action,
        target_selector=failed_target_selector,
        error_message=error_msg,
        page_url=engine_plan.base_url if engine_plan else None,
    )

    return ExecutionResult(
        workflow_id=workflow_id,
        test_case_id=test_case_id,
        status=ExecutionResultStatus.FAILED,
        failure_context=failure_context,
    )
