"""
TestSphere-AI — Day 5: Test Planner Pipeline Tests

Comprehensive unit and integration tests for the Test Planner
generation pipeline.

Tests cover:
  - Input validation (valid / invalid / empty ApplicationContext)
  - Generation flow (valid mock → valid TestPlan)
  - Response handling (empty, malformed, invalid responses)
  - Validation (unsupported action, invalid assertion/category/priority)
  - Element reference validation (hallucinated elements)
  - Duplicate detection
  - Error handling (provider error, timeout)
  - Full integration test (ApplicationContext → TestPlan)

All tests run offline, without API keys, models, or internet.
"""

from __future__ import annotations

import json

import pytest

from agents.llm.client import LLMClientSession
from agents.llm.config import LLMConfig
from agents.llm.exceptions import (
    LLMProviderError,
    LLMResponseError,
    LLMTimeoutError,
)
from agents.llm.providers.mock import MockLLMProvider
from agents.llm.schemas import LLMRequest
from agents.planner.mock_scenarios import (
    DUPLICATE_TEST_RESPONSE,
    EMPTY_TEST_PLAN_RESPONSE,
    HALLUCINATED_ELEMENT_RESPONSE,
    INVALID_CATEGORY_RESPONSE,
    INVALID_MALFORMED_RESPONSE,
    INVALID_PRIORITY_RESPONSE,
    MISSING_REQUIRED_FIELD_RESPONSE,
    UNSUPPORTED_ACTION_RESPONSE,
    VALID_TEST_PLAN_RESPONSE,
    register_planner_scenarios,
)
from agents.planner.planner import LLMTestPlanner
from agents.planner.schemas import (
    ApplicationContext,
    ElementContext,
    PageContext,
    TestCase,
    TestPlan,
    TestStep,
)
from agents.planner.validation import (
    TestPlanValidationError,
    detect_duplicate_test_cases,
    validate_element_references,
)
from agents.schemas.enums import (
    AssertionType,
    TestAction,
    TestCategory,
    TestPriority,
)
from tests.test_fixtures import (
    create_llm_session,
    create_mock_config,
    create_mock_provider,
    create_sample_login_context,
    create_test_planner,
)


# ── Fixtures ─────────────────────────────────────────────────


@pytest.fixture
def mock_config():
    return create_mock_config()


@pytest.fixture
def sample_context():
    return create_sample_login_context()


@pytest.fixture
def planner_with_valid_response(sample_context):
    """Return a planner whose mock returns a valid test plan."""
    planner, provider = create_test_planner()
    provider.register_response("Generate up to", VALID_TEST_PLAN_RESPONSE)
    return planner


@pytest.fixture
def planner_with_provider(mock_config):
    """Return a (planner, provider) tuple for custom configuration."""
    provider = MockLLMProvider(mock_config)
    session = LLMClientSession(provider, mock_config)
    planner = LLMTestPlanner(session)
    return planner, provider


# ════════════════════════════════════════════════════════════════
#  INPUT VALIDATION TESTS
# ════════════════════════════════════════════════════════════════


class TestInputValidation:
    """Tests for ApplicationContext validation before generation."""

    @pytest.mark.asyncio
    async def test_valid_context_accepted(
        self, planner_with_valid_response, sample_context
    ):
        """Valid context should not raise during validation."""
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_empty_app_name_rejected(self, planner_with_valid_response):
        ctx = ApplicationContext(app_name="", app_url="http://localhost")
        with pytest.raises(TestPlanValidationError) as exc_info:
            await planner_with_valid_response.generate_tests(ctx)
        assert "app_name" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_app_url_rejected(self, planner_with_valid_response):
        ctx = ApplicationContext(app_name="App", app_url="")
        with pytest.raises(TestPlanValidationError) as exc_info:
            await planner_with_valid_response.generate_tests(ctx)
        assert "app_url" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_whitespace_app_name_rejected(
        self, planner_with_valid_response
    ):
        ctx = ApplicationContext(app_name="   ", app_url="http://localhost")
        with pytest.raises(TestPlanValidationError):
            await planner_with_valid_response.generate_tests(ctx)

    @pytest.mark.asyncio
    async def test_context_with_empty_page_url_rejected(
        self, planner_with_valid_response
    ):
        ctx = ApplicationContext(
            app_name="App",
            app_url="http://localhost",
            pages=[
                PageContext(url="", name="Bad Page"),
            ],
        )
        with pytest.raises(TestPlanValidationError):
            await planner_with_valid_response.generate_tests(ctx)

    @pytest.mark.asyncio
    async def test_context_with_empty_element_tag_rejected(
        self, planner_with_valid_response
    ):
        ctx = ApplicationContext(
            app_name="App",
            app_url="http://localhost",
            pages=[
                PageContext(
                    url="/page",
                    name="Page",
                    elements=[ElementContext(tag="")],
                ),
            ],
        )
        with pytest.raises(TestPlanValidationError):
            await planner_with_valid_response.generate_tests(ctx)


# ════════════════════════════════════════════════════════════════
#  GENERATION FLOW TESTS
# ════════════════════════════════════════════════════════════════


class TestGenerationFlow:
    """Tests for the main generation pipeline."""

    @pytest.mark.asyncio
    async def test_valid_mock_produces_valid_test_cases(
        self, planner_with_valid_response, sample_context
    ):
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        assert isinstance(result, list)
        assert len(result) > 0
        for tc in result:
            assert isinstance(tc, TestCase)

    @pytest.mark.asyncio
    async def test_test_cases_have_valid_ids(
        self, planner_with_valid_response, sample_context
    ):
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        for tc in result:
            assert tc.test_id
            assert tc.test_id.strip()

    @pytest.mark.asyncio
    async def test_test_cases_have_valid_names(
        self, planner_with_valid_response, sample_context
    ):
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        for tc in result:
            assert tc.name
            assert tc.name.strip()

    @pytest.mark.asyncio
    async def test_test_cases_have_steps(
        self, planner_with_valid_response, sample_context
    ):
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        for tc in result:
            assert len(tc.steps) > 0

    @pytest.mark.asyncio
    async def test_planner_uses_llm_client(
        self, sample_context
    ):
        """Verify the planner actually calls the LLM client."""
        planner, provider = create_test_planner()
        provider.register_response("Generate up to", VALID_TEST_PLAN_RESPONSE)
        assert provider.call_count == 0
        await planner.generate_tests(sample_context)
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_mock_provider_returns_deterministic_results(
        self, sample_context
    ):
        """Same input should produce the same output."""
        planner, provider = create_test_planner()
        provider.register_response("Generate up to", VALID_TEST_PLAN_RESPONSE)

        result1 = await planner.generate_tests(sample_context)
        result2 = await planner.generate_tests(sample_context)

        assert len(result1) == len(result2)
        for tc1, tc2 in zip(result1, result2):
            assert tc1.test_id == tc2.test_id

    @pytest.mark.asyncio
    async def test_generate_test_plan_returns_test_plan(
        self, sample_context
    ):
        """generate_test_plan() should return a TestPlan object."""
        planner, provider = create_test_planner()
        provider.register_response("Generate up to", VALID_TEST_PLAN_RESPONSE)

        plan = await planner.generate_test_plan(sample_context)
        assert isinstance(plan, TestPlan)
        assert plan.application_name == sample_context.app_name
        assert plan.base_url == sample_context.app_url
        assert len(plan.test_cases) > 0
        assert plan.metadata["provider"] == "mock"


# ════════════════════════════════════════════════════════════════
#  RESPONSE HANDLING TESTS
# ════════════════════════════════════════════════════════════════


class TestResponseHandling:
    """Tests for LLM response processing."""

    @pytest.mark.asyncio
    async def test_empty_response_raises(self, sample_context):
        """Provider returning empty content should raise."""
        planner, provider = create_test_planner(
            create_mock_provider(simulate="empty")
        )
        with pytest.raises(LLMResponseError):
            await planner.generate_tests(sample_context)

    @pytest.mark.asyncio
    async def test_malformed_json_response_raises(self, sample_context):
        """Malformed JSON should raise LLMResponseError."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", INVALID_MALFORMED_RESPONSE
        )
        with pytest.raises(LLMResponseError):
            await planner.generate_tests(sample_context)

    @pytest.mark.asyncio
    async def test_empty_test_plan_returns_empty_list(self, sample_context):
        """Empty test plan (valid JSON, no test cases) → empty list."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", EMPTY_TEST_PLAN_RESPONSE
        )
        result = await planner.generate_tests(sample_context)
        assert result == []

    @pytest.mark.asyncio
    async def test_non_json_response_raises(self, sample_context):
        """Plain text response should raise LLMResponseError."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to",
            "This is just plain text, not JSON.",
        )
        with pytest.raises(LLMResponseError):
            await planner.generate_tests(sample_context)


# ════════════════════════════════════════════════════════════════
#  VALIDATION TESTS
# ════════════════════════════════════════════════════════════════


class TestOutputValidation:
    """Tests for generated test case validation."""

    @pytest.mark.asyncio
    async def test_unsupported_action_rejected(self, sample_context):
        """Test cases with unsupported actions should be rejected.

        Pydantic's enum validation rejects invalid action values at
        parse time, raising TestPlanValidationError. This is the
        correct behavior — the pipeline does not silently accept
        invalid actions.
        """
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", UNSUPPORTED_ACTION_RESPONSE
        )
        try:
            result = await planner.generate_tests(sample_context)
            # If parsing succeeded, the invalid case must be filtered
            assert len(result) == 0
        except TestPlanValidationError:
            # Pydantic rejected the invalid action at parse time — correct
            pass

    @pytest.mark.asyncio
    async def test_invalid_category_rejected(self, sample_context):
        """Test cases with invalid categories should be rejected."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", INVALID_CATEGORY_RESPONSE
        )
        try:
            result = await planner.generate_tests(sample_context)
            assert len(result) == 0
        except TestPlanValidationError:
            pass

    @pytest.mark.asyncio
    async def test_invalid_priority_rejected(self, sample_context):
        """Test cases with invalid priorities should be rejected."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", INVALID_PRIORITY_RESPONSE
        )
        try:
            result = await planner.generate_tests(sample_context)
            assert len(result) == 0
        except TestPlanValidationError:
            pass

    @pytest.mark.asyncio
    async def test_missing_required_fields_filtered(self, sample_context):
        """Test cases with missing required fields should be filtered out."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", MISSING_REQUIRED_FIELD_RESPONSE
        )
        # This may raise during Pydantic parsing (missing test_id)
        # or be filtered during validation — either is acceptable
        try:
            result = await planner.generate_tests(sample_context)
            # If parsing succeeded, the invalid case must be filtered
            assert len(result) == 0
        except (TestPlanValidationError, LLMResponseError):
            # Pydantic rejected the missing fields — also acceptable
            pass

    @pytest.mark.asyncio
    async def test_valid_categories_accepted(
        self, planner_with_valid_response, sample_context
    ):
        """Valid categories in mock response should pass validation."""
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        valid_categories = {c.value for c in TestCategory}
        for tc in result:
            cat_val = (
                tc.category.value
                if isinstance(tc.category, TestCategory)
                else tc.category
            )
            assert cat_val in valid_categories

    @pytest.mark.asyncio
    async def test_valid_priorities_accepted(
        self, planner_with_valid_response, sample_context
    ):
        """Valid priorities in mock response should pass validation."""
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        valid_priorities = {p.value for p in TestPriority}
        for tc in result:
            pri_val = (
                tc.priority.value
                if isinstance(tc.priority, TestPriority)
                else tc.priority
            )
            assert pri_val in valid_priorities

    @pytest.mark.asyncio
    async def test_valid_actions_accepted(
        self, planner_with_valid_response, sample_context
    ):
        """Valid actions in mock response should pass validation."""
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        valid_actions = {a.value for a in TestAction}
        for tc in result:
            for step in tc.steps:
                action_val = (
                    step.action.value
                    if isinstance(step.action, TestAction)
                    else step.action
                )
                assert action_val in valid_actions

    @pytest.mark.asyncio
    async def test_valid_assertion_types_accepted(
        self, planner_with_valid_response, sample_context
    ):
        """Valid assertion types in mock response should pass validation."""
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        valid_types = {at.value for at in AssertionType}
        for tc in result:
            for assertion in tc.assertions:
                at_val = (
                    assertion.type.value
                    if isinstance(assertion.type, AssertionType)
                    else assertion.type
                )
                assert at_val in valid_types


# ════════════════════════════════════════════════════════════════
#  ELEMENT REFERENCE VALIDATION TESTS
# ════════════════════════════════════════════════════════════════


class TestElementReferenceValidation:
    """Tests for hallucinated element detection."""

    @pytest.mark.asyncio
    async def test_hallucinated_elements_filtered(self, sample_context):
        """Test cases referencing unknown elements should be filtered out."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", HALLUCINATED_ELEMENT_RESPONSE
        )
        result = await planner.generate_tests(sample_context)
        # The hallucinated test case targets #username and #submit-form
        # which don't exist in the sample context
        assert len(result) == 0

    @pytest.mark.asyncio
    async def test_known_elements_accepted(
        self, planner_with_valid_response, sample_context
    ):
        """Test cases referencing known elements should pass."""
        result = await planner_with_valid_response.generate_tests(
            sample_context
        )
        # The valid response uses #email, #password, #login-button
        # which are in the sample context
        assert len(result) > 0

    def test_validate_element_references_function(self, sample_context):
        """Direct test of the validate_element_references function."""
        # Valid reference
        valid_tc = TestCase(
            test_id="TC001",
            name="Valid",
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.CLICK,
                    target="#login-button",
                ),
            ],
        )
        errors = validate_element_references(valid_tc, sample_context)
        assert len(errors) == 0

    def test_validate_unknown_reference_detected(self, sample_context):
        """Unknown element target should produce an error."""
        bad_tc = TestCase(
            test_id="TC001",
            name="Bad",
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.CLICK,
                    target="#nonexistent-element",
                ),
            ],
        )
        errors = validate_element_references(bad_tc, sample_context)
        assert len(errors) > 0
        assert "nonexistent-element" in errors[0]

    def test_navigate_action_skipped(self, sample_context):
        """Navigate steps should not be checked for element references."""
        tc = TestCase(
            test_id="TC001",
            name="Navigate",
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.NAVIGATE,
                    value="http://example.com",
                ),
            ],
        )
        errors = validate_element_references(tc, sample_context)
        assert len(errors) == 0

    def test_wait_action_skipped(self, sample_context):
        """Wait steps should not be checked for element references."""
        tc = TestCase(
            test_id="TC001",
            name="Wait",
            steps=[
                TestStep(
                    step_number=1,
                    action=TestAction.WAIT,
                ),
            ],
        )
        errors = validate_element_references(tc, sample_context)
        assert len(errors) == 0


# ════════════════════════════════════════════════════════════════
#  DUPLICATE DETECTION TESTS
# ════════════════════════════════════════════════════════════════


class TestDuplicateDetection:
    """Tests for duplicate test case detection."""

    @pytest.mark.asyncio
    async def test_duplicates_removed_in_pipeline(self, sample_context):
        """Duplicate test cases should be removed during generation."""
        planner, provider = create_test_planner()
        provider.register_response(
            "Generate up to", DUPLICATE_TEST_RESPONSE
        )
        result = await planner.generate_tests(sample_context)
        # Two duplicate cases with same name+category+steps → only one kept
        assert len(result) == 1

    def test_detect_duplicates_function(self):
        """Direct test of detect_duplicate_test_cases function."""
        cases = [
            TestCase(
                test_id="TC001",
                name="Login Test",
                category=TestCategory.FUNCTIONAL,
                steps=[
                    TestStep(
                        step_number=1,
                        action=TestAction.CLICK,
                        target="#btn",
                    ),
                ],
            ),
            TestCase(
                test_id="TC002",
                name="Login Test",
                category=TestCategory.FUNCTIONAL,
                steps=[
                    TestStep(
                        step_number=1,
                        action=TestAction.CLICK,
                        target="#btn",
                    ),
                ],
            ),
        ]
        dup_indices = detect_duplicate_test_cases(cases)
        assert dup_indices == [1]

    def test_no_duplicates_returns_empty(self):
        """No duplicates should return empty list."""
        cases = [
            TestCase(
                test_id="TC001",
                name="Test A",
                category=TestCategory.FUNCTIONAL,
                steps=[
                    TestStep(
                        step_number=1,
                        action=TestAction.CLICK,
                        target="#btn",
                    ),
                ],
            ),
            TestCase(
                test_id="TC002",
                name="Test B",
                category=TestCategory.NEGATIVE,
                steps=[
                    TestStep(
                        step_number=1,
                        action=TestAction.FILL,
                        target="#input",
                        value="text",
                    ),
                ],
            ),
        ]
        dup_indices = detect_duplicate_test_cases(cases)
        assert dup_indices == []

    def test_different_category_not_duplicate(self):
        """Same name but different category should not be duplicate."""
        cases = [
            TestCase(
                test_id="TC001",
                name="Login Test",
                category=TestCategory.FUNCTIONAL,
                steps=[
                    TestStep(
                        step_number=1,
                        action=TestAction.CLICK,
                        target="#btn",
                    ),
                ],
            ),
            TestCase(
                test_id="TC002",
                name="Login Test",
                category=TestCategory.NEGATIVE,
                steps=[
                    TestStep(
                        step_number=1,
                        action=TestAction.CLICK,
                        target="#btn",
                    ),
                ],
            ),
        ]
        dup_indices = detect_duplicate_test_cases(cases)
        assert dup_indices == []


# ════════════════════════════════════════════════════════════════
#  ERROR HANDLING TESTS
# ════════════════════════════════════════════════════════════════


class TestErrorHandling:
    """Tests for provider error handling."""

    @pytest.mark.asyncio
    async def test_provider_error_propagated(self, sample_context):
        """LLMProviderError should propagate to the caller."""
        planner, _ = create_test_planner(
            create_mock_provider(simulate="error")
        )
        with pytest.raises(LLMProviderError):
            await planner.generate_tests(sample_context)

    @pytest.mark.asyncio
    async def test_timeout_error_propagated(self, sample_context):
        """LLMTimeoutError should propagate to the caller."""
        planner, _ = create_test_planner(
            create_mock_provider(simulate="timeout")
        )
        with pytest.raises(LLMTimeoutError):
            await planner.generate_tests(sample_context)

    @pytest.mark.asyncio
    async def test_empty_provider_response_handled(self, sample_context):
        """Empty provider response should raise LLMResponseError."""
        planner, _ = create_test_planner(
            create_mock_provider(simulate="empty")
        )
        with pytest.raises(LLMResponseError):
            await planner.generate_tests(sample_context)

    @pytest.mark.asyncio
    async def test_invalid_provider_response_handled(self, sample_context):
        """Invalid provider response should raise LLMResponseError."""
        planner, _ = create_test_planner(
            create_mock_provider(simulate="invalid")
        )
        with pytest.raises(LLMResponseError):
            await planner.generate_tests(sample_context)


# ════════════════════════════════════════════════════════════════
#  PROMPT CONSTRUCTION TESTS
# ════════════════════════════════════════════════════════════════


class TestPromptConstruction:
    """Verify prompt construction in the pipeline context."""

    @pytest.mark.asyncio
    async def test_prompt_includes_context_data(self, sample_context):
        """The generated prompt should include the application context."""
        planner, provider = create_test_planner()
        # Capture what prompt is sent
        captured_prompts: list[str] = []
        original_generate = provider.generate

        async def capturing_generate(request: LLMRequest):
            captured_prompts.append(request.prompt)
            # Return a valid response so the pipeline continues
            from agents.llm.schemas import LLMResponse, LLMUsage

            return LLMResponse(
                content=VALID_TEST_PLAN_RESPONSE,
                model="mock-model",
                provider="mock",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=10),
            )

        provider.generate = capturing_generate

        await planner.generate_tests(sample_context)
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]

        # Verify context info is in the prompt
        assert "Demo Application" in prompt
        assert "localhost:3000" in prompt
        assert "email" in prompt
        assert "password" in prompt
        assert "login" in prompt.lower()

    @pytest.mark.asyncio
    async def test_prompt_includes_action_vocabulary(self, sample_context):
        """The prompt should include the supported action vocabulary."""
        planner, provider = create_test_planner()
        captured_prompts: list[str] = []
        original_generate = provider.generate

        async def capturing_generate(request: LLMRequest):
            captured_prompts.append(request.prompt)
            from agents.llm.schemas import LLMResponse, LLMUsage

            return LLMResponse(
                content=VALID_TEST_PLAN_RESPONSE,
                model="mock-model",
                provider="mock",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=10),
            )

        provider.generate = capturing_generate

        await planner.generate_tests(sample_context)
        prompt = captured_prompts[0]

        for action in TestAction:
            assert action.value in prompt

    @pytest.mark.asyncio
    async def test_max_tests_parameter_in_prompt(self, sample_context):
        """The max_tests parameter should be reflected in the prompt."""
        planner, provider = create_test_planner()
        captured_prompts: list[str] = []

        async def capturing_generate(request: LLMRequest):
            captured_prompts.append(request.prompt)
            from agents.llm.schemas import LLMResponse, LLMUsage

            return LLMResponse(
                content=VALID_TEST_PLAN_RESPONSE,
                model="mock-model",
                provider="mock",
                usage=LLMUsage(prompt_tokens=10, completion_tokens=10),
            )

        provider.generate = capturing_generate

        await planner.generate_tests(sample_context, max_tests=5)
        assert "5" in captured_prompts[0]


# ════════════════════════════════════════════════════════════════
#  RESPONSE PARSING TESTS
# ════════════════════════════════════════════════════════════════


class TestResponseParsing:
    """Tests for the _parse_response method."""

    def test_parse_valid_response(self):
        """Valid JSON dict should parse into TestPlan."""
        data = json.loads(VALID_TEST_PLAN_RESPONSE)
        plan = LLMTestPlanner._parse_response(data)
        assert isinstance(plan, TestPlan)
        assert plan.application_name == "Demo Application"
        assert len(plan.test_cases) == 2

    def test_parse_invalid_structure_raises(self):
        """Dict with wrong structure should raise TestPlanValidationError."""
        with pytest.raises(TestPlanValidationError):
            LLMTestPlanner._parse_response({"invalid": "structure"})

    def test_parse_empty_dict_raises(self):
        """Empty dict (missing application_name) should raise."""
        with pytest.raises(TestPlanValidationError):
            LLMTestPlanner._parse_response({})


# ════════════════════════════════════════════════════════════════
#  MOCK SCENARIO REGISTRATION TESTS
# ════════════════════════════════════════════════════════════════


class TestMockScenarioRegistration:
    """Tests for the updated mock scenario registration."""

    def test_register_all_scenarios(self, mock_config):
        """Should register 9 scenarios (7 original + 2 new)."""
        provider = MockLLMProvider(mock_config)
        register_planner_scenarios(provider)
        assert len(provider._response_registry) == 9

    def test_hallucinated_response_is_valid_json(self):
        """Hallucinated element response should be valid JSON."""
        data = json.loads(HALLUCINATED_ELEMENT_RESPONSE)
        assert "test_cases" in data
        assert len(data["test_cases"]) > 0

    def test_duplicate_response_has_duplicates(self):
        """Duplicate response should have test cases with same name."""
        data = json.loads(DUPLICATE_TEST_RESPONSE)
        names = [tc["name"] for tc in data["test_cases"]]
        assert len(names) > len(set(names))


# ════════════════════════════════════════════════════════════════
#  FULL INTEGRATION TEST
# ════════════════════════════════════════════════════════════════


class TestFullIntegration:
    """Complete integration test: ApplicationContext → valid TestPlan."""

    @pytest.mark.asyncio
    async def test_end_to_end_pipeline(self):
        """Full pipeline: context → planner → LLMClient → mock → parse → validate → TestPlan."""
        # 1. Create the sample application context
        context = create_sample_login_context()

        # 2. Set up the planner with mock provider
        planner, provider = create_test_planner()
        provider.register_response("Generate up to", VALID_TEST_PLAN_RESPONSE)

        # 3. Generate test plan
        plan = await planner.generate_test_plan(context)

        # 4. Verify the TestPlan structure
        assert isinstance(plan, TestPlan)
        assert plan.application_name == "Demo Application"
        assert plan.base_url == "http://localhost:3000"
        assert len(plan.test_cases) > 0

        # 5. Verify each test case
        for tc in plan.test_cases:
            # Valid IDs
            assert tc.test_id
            assert tc.test_id.strip()

            # Valid categories
            assert isinstance(tc.category, TestCategory)

            # Valid priorities
            assert isinstance(tc.priority, TestPriority)

            # Has at least one step
            assert len(tc.steps) > 0

            # Valid actions
            for step in tc.steps:
                assert isinstance(step.action, TestAction)

            # Valid assertion types
            for assertion in tc.assertions:
                assert isinstance(assertion.type, AssertionType)

        # 6. Verify element targets correspond to the context
        for tc in plan.test_cases:
            ref_errors = validate_element_references(tc, context)
            assert len(ref_errors) == 0, (
                f"Test case '{tc.test_id}' has unknown element "
                f"references: {ref_errors}"
            )

        # 7. Verify no duplicates
        dup_indices = detect_duplicate_test_cases(plan.test_cases)
        assert len(dup_indices) == 0, (
            f"Duplicate test cases found at indices: {dup_indices}"
        )

        # 8. Verify provider was actually called
        assert provider.call_count == 1

    @pytest.mark.asyncio
    async def test_end_to_end_with_minimal_context(self):
        """Pipeline works with minimal context (no pages/elements)."""
        from tests.test_fixtures import create_minimal_context

        context = create_minimal_context()
        planner, provider = create_test_planner()

        # Return a simple valid response
        simple_response = json.dumps({
            "application_name": "Minimal App",
            "base_url": "http://localhost:8080",
            "test_cases": [
                {
                    "test_id": "TC_SMOKE_001",
                    "name": "App Loads",
                    "description": "Verify the application loads.",
                    "category": "smoke",
                    "priority": "HIGH",
                    "steps": [
                        {
                            "step_number": 1,
                            "action": "navigate",
                            "value": "http://localhost:8080",
                            "description": "Navigate to app",
                        },
                    ],
                    "assertions": [
                        {
                            "type": "url_equals",
                            "expected": "http://localhost:8080",
                            "description": "URL should match",
                        },
                    ],
                },
            ],
        })

        provider.register_response("Generate up to", simple_response)
        plan = await planner.generate_test_plan(context)

        assert isinstance(plan, TestPlan)
        assert plan.application_name == "Minimal App"
        assert len(plan.test_cases) == 1
        assert plan.test_cases[0].test_id == "TC_SMOKE_001"
