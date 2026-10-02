"""
TestSphere-AI — Test Planner Validation Layer

Business-rule validation that goes beyond Pydantic's structural
schema constraints.  These rules encode the execution requirements
of Member 2's engine — for example, which actions need a target
and which need a value.

Usage::

    from agents.planner.validation import (
        validate_test_step,
        validate_test_case,
        validate_test_plan,
        validate_application_context,
    )
"""

from __future__ import annotations

from agents.planner.schemas import (
    ApplicationContext,
    Assertion,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.schemas.enums import AssertionType, TestAction, TestCategory, TestPriority


# ── Custom Exception ─────────────────────────────────────────


class TestPlanValidationError(Exception):
    """Raised when a test plan or its components fail business-rule validation.

    Parameters
    ----------
    message:
        Human-readable description of the validation failure.
    field:
        The field or component that failed validation (optional).
    """

    def __init__(self, message: str, *, field: str = "") -> None:
        self.field = field
        super().__init__(message)


# ── Action Requirements ──────────────────────────────────────

# Maps each TestAction to (target_required, value_required).
ACTION_REQUIREMENTS: dict[TestAction, tuple[bool, bool]] = {
    TestAction.NAVIGATE: (False, True),   # value = URL
    TestAction.CLICK: (True, False),
    TestAction.FILL: (True, True),        # target + value = text
    TestAction.SELECT: (True, True),      # target + value = option
    TestAction.CHECK: (True, False),
    TestAction.UNCHECK: (True, False),
    TestAction.PRESS: (False, True),      # value = key name
    TestAction.WAIT: (False, False),
}

# Assertions that require a target element selector
ASSERTIONS_REQUIRING_TARGET: set[AssertionType] = {
    AssertionType.ELEMENT_VISIBLE,
    AssertionType.ELEMENT_NOT_VISIBLE,
    AssertionType.ELEMENT_CONTAINS_TEXT,
    AssertionType.ELEMENT_HAS_TEXT,
    AssertionType.VALUE_EQUALS,
}

# Assertions that require an expected value
ASSERTIONS_REQUIRING_EXPECTED: set[AssertionType] = {
    AssertionType.ELEMENT_CONTAINS_TEXT,
    AssertionType.ELEMENT_HAS_TEXT,
    AssertionType.URL_CONTAINS,
    AssertionType.URL_EQUALS,
    AssertionType.VALUE_EQUALS,
}


# ── Validation Functions ─────────────────────────────────────


def validate_assertion(assertion: Assertion) -> list[str]:
    """Validate a single assertion against business rules.

    Parameters
    ----------
    assertion:
        The assertion to validate.

    Returns
    -------
    list[str]
        A list of validation error messages (empty if valid).
    """
    errors: list[str] = []

    # Type must be a recognized AssertionType (Pydantic already enforces
    # the enum, but we guard against raw dicts during future parsing).
    valid_types = {at.value for at in AssertionType}
    raw_type = assertion.type if isinstance(assertion.type, str) else assertion.type.value
    if raw_type not in valid_types:
        errors.append(f"Unsupported assertion type: '{raw_type}'.")

    # Target required?
    if assertion.type in ASSERTIONS_REQUIRING_TARGET and not assertion.target:
        errors.append(
            f"Assertion type '{assertion.type.value}' requires a non-empty 'target'."
        )

    # Expected required?
    if assertion.type in ASSERTIONS_REQUIRING_EXPECTED and not assertion.expected:
        errors.append(
            f"Assertion type '{assertion.type.value}' requires a non-empty 'expected'."
        )

    return errors


def validate_test_step(step: TestStep) -> list[str]:
    """Validate a single test step against business rules.

    Parameters
    ----------
    step:
        The test step to validate.

    Returns
    -------
    list[str]
        A list of validation error messages (empty if valid).
    """
    errors: list[str] = []

    # Step number must be positive (Pydantic ge=1 handles this,
    # but we guard for programmatic construction).
    if step.step_number < 1:
        errors.append(f"Step number must be >= 1, got {step.step_number}.")

    # Action must be a recognized TestAction
    valid_actions = {ta.value for ta in TestAction}
    raw_action = step.action if isinstance(step.action, str) else step.action.value
    if raw_action not in valid_actions:
        errors.append(f"Unsupported action: '{raw_action}'.")
        return errors  # Can't check requirements for unknown action

    # Look up requirements
    action_enum = step.action if isinstance(step.action, TestAction) else TestAction(raw_action)
    target_required, value_required = ACTION_REQUIREMENTS[action_enum]

    if target_required and not step.target:
        errors.append(
            f"Action '{action_enum.value}' requires a non-empty 'target'."
        )

    if value_required and not step.value:
        errors.append(
            f"Action '{action_enum.value}' requires a non-empty 'value'."
        )

    # Validate inline assertions
    for assertion in step.assertions:
        errors.extend(validate_assertion(assertion))

    return errors


def validate_test_case(test_case: TestCase) -> list[str]:
    """Validate a test case against business rules.

    Parameters
    ----------
    test_case:
        The test case to validate.

    Returns
    -------
    list[str]
        A list of validation error messages (empty if valid).
    """
    errors: list[str] = []

    # Required fields
    if not test_case.test_id or not test_case.test_id.strip():
        errors.append("TestCase 'test_id' must not be empty.")

    if not test_case.name or not test_case.name.strip():
        errors.append("TestCase 'name' must not be empty.")

    # Category must be valid
    valid_categories = {tc.value for tc in TestCategory}
    raw_cat = (
        test_case.category
        if isinstance(test_case.category, str)
        else test_case.category.value
    )
    if raw_cat not in valid_categories:
        errors.append(f"Invalid test category: '{raw_cat}'.")

    # Priority must be valid
    valid_priorities = {tp.value for tp in TestPriority}
    raw_pri = (
        test_case.priority
        if isinstance(test_case.priority, str)
        else test_case.priority.value
    )
    if raw_pri not in valid_priorities:
        errors.append(f"Invalid test priority: '{raw_pri}'.")

    # Must have at least one step
    if not test_case.steps:
        errors.append("TestCase must contain at least one step.")

    # Step orders must be valid and non-duplicate
    seen_orders: set[int] = set()
    for step in test_case.steps:
        if step.step_number in seen_orders:
            errors.append(f"Duplicate step_number: {step.step_number}.")
        seen_orders.add(step.step_number)

        step_errors = validate_test_step(step)
        for err in step_errors:
            errors.append(f"Step {step.step_number}: {err}")

    # Validate top-level assertions
    for idx, assertion in enumerate(test_case.assertions):
        assertion_errors = validate_assertion(assertion)
        for err in assertion_errors:
            errors.append(f"Assertion {idx + 1}: {err}")

    return errors


def validate_test_plan(test_plan: TestPlan) -> list[str]:
    """Validate a complete test plan against business rules.

    Parameters
    ----------
    test_plan:
        The test plan to validate.

    Returns
    -------
    list[str]
        A list of validation error messages (empty if valid).
    """
    errors: list[str] = []

    if not test_plan.application_name or not test_plan.application_name.strip():
        errors.append("TestPlan 'application_name' must not be empty.")

    # Validate each test case
    seen_ids: set[str] = set()
    for tc in test_plan.test_cases:
        if tc.test_id in seen_ids:
            errors.append(f"Duplicate test_id: '{tc.test_id}'.")
        seen_ids.add(tc.test_id)

        tc_errors = validate_test_case(tc)
        for err in tc_errors:
            errors.append(f"TestCase '{tc.test_id}': {err}")

    return errors


def validate_application_context(context: ApplicationContext) -> list[str]:
    """Validate an application context against business rules.

    Parameters
    ----------
    context:
        The application context to validate.

    Returns
    -------
    list[str]
        A list of validation error messages (empty if valid).
    """
    errors: list[str] = []

    if not context.app_name or not context.app_name.strip():
        errors.append("ApplicationContext 'app_name' must not be empty.")

    if not context.app_url or not context.app_url.strip():
        errors.append("ApplicationContext 'app_url' must not be empty.")

    # Validate each page's elements have the required 'tag' field
    for page in context.pages:
        if not page.url or not page.url.strip():
            errors.append(
                f"Page '{page.name or '(unnamed)'}' has an empty URL."
            )
        for elem in page.elements:
            if not elem.tag or not elem.tag.strip():
                errors.append(
                    f"Page '{page.name}': element has an empty 'tag'."
                )

    return errors


# ── Element Reference Validation (Day 5) ────────────────────


def _extract_known_selectors(context: ApplicationContext) -> set[str]:
    """Extract all plausible CSS selectors from an ApplicationContext.

    Builds selectors from element IDs, names, tags, roles, text,
    placeholders, and data-testid attributes — the same identifiers
    the prompt instructs the model to use.

    Parameters
    ----------
    context:
        The application context.

    Returns
    -------
    set[str]
        A set of known selector strings (e.g. ``'#email'``, ``'button'``).
    """
    selectors: set[str] = set()

    for page in context.pages:
        for elem in page.elements:
            # ID-based selectors: #email
            if elem.id:
                selectors.add(f"#{elem.id}")
            # Name-based selectors: [name="email"]
            if elem.name:
                selectors.add(f'[name="{elem.name}"]')
            # Tag names: input, button, a
            if elem.tag:
                selectors.add(elem.tag)
            # Explicit selector provided by Member 2
            if elem.selector:
                selectors.add(elem.selector)
            # data-testid attribute
            if "data-testid" in elem.attributes:
                selectors.add(
                    f'[data-testid="{elem.attributes["data-testid"]}"]'
                )
            # Text content (for text-based selectors)
            if elem.text:
                selectors.add(elem.text)
            # Placeholder text
            if elem.placeholder:
                selectors.add(elem.placeholder)

    return selectors


def validate_element_references(
    test_case: TestCase,
    context: ApplicationContext,
) -> list[str]:
    """Validate that test step targets reference known elements.

    Compares each step's ``target`` against the selectors derivable
    from the ``ApplicationContext``.  Steps whose action does not
    require a target (e.g. ``navigate``, ``wait``, ``press``) are
    skipped.

    Strategy
    --------
    A target is considered valid if **any** known selector is a
    substring of the target, or the target is a substring of a
    known selector.  This keeps matching simple for Day 5 —
    advanced semantic matching is deferred.

    Parameters
    ----------
    test_case:
        The test case to check.
    context:
        The application context that was used for generation.

    Returns
    -------
    list[str]
        Validation error messages for unknown element references.
    """
    errors: list[str] = []
    known = _extract_known_selectors(context)

    if not known:
        # No elements in context → nothing to validate against
        return errors

    # Actions that do NOT require a target element
    no_target_actions = {TestAction.NAVIGATE, TestAction.PRESS, TestAction.WAIT}

    for step in test_case.steps:
        action_enum = (
            step.action
            if isinstance(step.action, TestAction)
            else TestAction(step.action)
        )
        if action_enum in no_target_actions:
            continue
        if not step.target:
            continue

        target = step.target
        # Check if any known selector matches the target
        matched = any(
            selector in target or target in selector
            for selector in known
        )
        if not matched:
            errors.append(
                f"Step {step.step_number}: target '{target}' does not "
                f"match any known element in the ApplicationContext."
            )

    return errors


# ── Duplicate Detection (Day 5) ─────────────────────────────


def _test_case_signature(test_case: TestCase) -> str:
    """Create a deduplication signature for a test case.

    The signature combines (lowercased):
    - test name
    - category
    - ordered list of (action, target) pairs

    This catches exact and near-identical duplicates without
    advanced AI similarity.
    """
    action_seq = "|".join(
        f"{s.action.value if isinstance(s.action, TestAction) else s.action}"
        f":{s.target or ''}"
        for s in test_case.steps
    )
    cat = (
        test_case.category.value
        if isinstance(test_case.category, TestCategory)
        else str(test_case.category)
    )
    return f"{test_case.name.strip().lower()}::{cat.lower()}::{action_seq.lower()}"


def detect_duplicate_test_cases(test_cases: list[TestCase]) -> list[int]:
    """Detect duplicate test cases based on name + category + action sequence.

    Parameters
    ----------
    test_cases:
        The list of test cases to check.

    Returns
    -------
    list[int]
        Indices (0-based) of test cases that are duplicates of an
        earlier entry in the list.  The first occurrence is kept.
    """
    seen: dict[str, int] = {}
    duplicate_indices: list[int] = []

    for idx, tc in enumerate(test_cases):
        sig = _test_case_signature(tc)
        if sig in seen:
            duplicate_indices.append(idx)
        else:
            seen[sig] = idx

    return duplicate_indices
