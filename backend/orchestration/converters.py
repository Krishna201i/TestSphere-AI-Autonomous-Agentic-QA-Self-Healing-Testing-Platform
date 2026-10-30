"""
TestSphere-AI — Inter-Member Contract Converters.

Converts data models between Member 1 (AI Agent Layer) and Member 2 (Execution Engine).
Maintains bidirectional fidelity without modifying shared models or third-party contracts.
"""


import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from agents.analyzer.schemas import FailureContext
from agents.memory.memory_schemas import ElementRecord
from agents.orchestration.workflow_schemas import (
    ExecutionResult,
    ExecutionResultStatus,
)
from agents.planner.schemas import (
    Assertion,
)
from agents.planner.schemas import (
    TestCase as Member1TestCase,
)
from agents.schemas.enums import AssertionType, TestAction
from engine.schemas import (
    ActionType,
    ElementFingerprint,
    StepStatus,
    TestStatus,
)
from engine.schemas import (
    Step as EngineStep,
)
from engine.schemas import (
    Target as EngineTarget,
)
from engine.schemas import (
    TestPlan as EngineTestPlan,
)
from engine.schemas import (
    TestResult as EngineTestResult,
)

logger = logging.getLogger("testsphere.orchestration")

# Learned fallback locators kept per target (the engine ranks them, most stable first)
MAX_LEARNED_FALLBACKS = 10


def create_engine_target(
    selector: str | None,
    description: str = "Target element",
    learned: dict[str, dict[str, Any]] | None = None,
) -> EngineTarget | None:
    """Create an EngineTarget conforming to Member 2 schema.

    *learned* maps a primary locator to what earlier runs learned about its
    element (``fallback_locators``, ``fingerprint``); the engine's healer
    needs both to repair the locator when it breaks.
    """
    if not selector:
        return None
    target = EngineTarget(
        description=description,
        primary_locator=selector,
    )
    entry = (learned or {}).get(selector)
    if entry:
        try:
            target.fallback_locators = [
                str(loc) for loc in entry.get("fallback_locators") or [] if loc and loc != selector
            ][:MAX_LEARNED_FALLBACKS]
            if entry.get("fingerprint"):
                target.fingerprint = ElementFingerprint.model_validate(entry["fingerprint"])
        except (TypeError, ValueError) as exc:  # stored data from an older schema: start afresh
            logger.warning("Ignoring unreadable learned target for %r: %s", selector, exc)
            target.fallback_locators, target.fingerprint = [], None
    return target


def learned_targets_by_locator(rows: Any) -> dict[str, dict[str, Any]]:
    """Index a test case's stored ``healing_targets`` by primary locator."""
    if not isinstance(rows, list):
        return {}
    return {row["locator"]: row for row in rows if isinstance(row, dict) and row.get("locator")}


def collect_learned_targets(
    original_plan: EngineTestPlan,
    executed_plan: EngineTestPlan,
    result: EngineTestResult,
) -> list[dict[str, Any]]:
    """What the engine learned about each target, keyed by the stored locator.

    *executed_plan* is the plan that produced *result*: *original_plan*
    itself, or a copy with a validated replacement selector.  The runner
    enriches targets in place (fingerprint + ranked fallbacks) after each
    passing step.  A locator that healed this run (the engine's pick or a
    validated replacement) goes first, so the next run heals at once.
    """
    healed = {
        step_res.step_id: step_res.healing.selected_locator
        for step_res in result.steps
        if step_res.status == StepStatus.HEALED and step_res.healing and step_res.healing.selected_locator
    }
    entries: dict[str, dict[str, Any]] = {}
    for original, executed in zip(original_plan.steps, executed_plan.steps, strict=True):
        if original.target is None or executed.target is None:
            continue
        locator = original.target.primary_locator
        first = [healed[executed.step_id]] if executed.step_id in healed else []
        if executed.target.primary_locator != locator:
            first.append(executed.target.primary_locator)
        fallbacks = list(dict.fromkeys([*first, *executed.target.fallback_locators]))
        fallbacks = [loc for loc in fallbacks if loc != locator][:MAX_LEARNED_FALLBACKS]
        fingerprint = executed.target.fingerprint
        if not fallbacks and fingerprint is None:
            continue
        entries[locator] = {
            "locator": locator,
            "fallback_locators": fallbacks,
            "fingerprint": fingerprint.model_dump(mode="json") if fingerprint else None,
        }
    return list(entries.values())


# ── Elements of a page (for the AI healer) ───────────────────

_INTERACTIVE_TAGS = frozenset({"button", "a", "input", "select", "textarea"})
_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr",
})
_SKIP_CONTENT_TAGS = frozenset({"script", "style", "template", "noscript"})
_RECORDED_ATTRS = ("id", "name", "type", "data-testid", "aria-label", "placeholder", "href")
_CSS_IDENT = re.compile(r"^[A-Za-z_][\w-]*$")
MAX_PAGE_ELEMENTS = 200


def element_role(tag: str | None, attributes: dict[str, str]) -> str | None:
    """An element's ARIA role: its explicit ``role`` or the implicit one of its tag."""
    if attributes.get("role"):
        return attributes["role"]
    tag = (tag or "").lower()
    if tag == "input":
        kind = (attributes.get("type") or "text").lower()
        if kind in ("submit", "button", "reset", "image"):
            return "button"
        if kind in ("checkbox", "radio"):
            return kind
        return "textbox"
    return {"button": "button", "a": "link", "select": "combobox", "textarea": "textbox"}.get(tag)


def element_record_from_fingerprint(
    fingerprint: ElementFingerprint,
    selector: str,
    *,
    element_id: str,
    page_url: str | None = None,
    execution_id: str | None = None,
) -> ElementRecord:
    """The healing-memory record of an element the engine located and fingerprinted."""
    attributes = {"tag": fingerprint.tag or ""}
    for key, value in (("id", fingerprint.id), ("name", fingerprint.name), ("aria-label", fingerprint.aria_label),
                       ("placeholder", fingerprint.placeholder)):
        if value:
            attributes[key] = value
    for key in ("type", "data-testid", "href"):
        if fingerprint.attributes.get(key):
            attributes[key] = fingerprint.attributes[key]
    attributes = {k: v for k, v in attributes.items() if v}
    return ElementRecord(
        element_id=element_id,
        selector=selector,
        text=_squash(fingerprint.text),
        role=element_role(fingerprint.tag, {**attributes, "role": fingerprint.role or ""}),
        page_url=page_url,
        attributes=attributes,
        last_successful_execution_id=execution_id,
    )


class _ElementCollector(HTMLParser):
    """Collects the interactive elements of an HTML document with their text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[dict[str, Any]] = []
        self._open: list[tuple[str, dict[str, Any] | None]] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: (v or "") for k, v in attrs}
        element = None
        hidden = "hidden" in values or values.get("aria-hidden") == "true" or (
            tag == "input" and values.get("type", "").lower() == "hidden")
        interactive = tag in _INTERACTIVE_TAGS or any(k in values for k in ("role", "data-testid", "aria-label"))
        if interactive and not hidden and not self._skip and not (tag == "a" and "href" not in values):
            element = {"tag": tag, "attrs": values, "text": []}
            self.elements.append(element)
        if tag in _VOID_TAGS:
            return
        if tag in _SKIP_CONTENT_TAGS:
            self._skip += 1
        self._open.append((tag, element))

    def handle_endtag(self, tag: str) -> None:
        for idx in range(len(self._open) - 1, -1, -1):
            if self._open[idx][0] == tag:
                for closed, _ in self._open[idx:]:
                    if closed in _SKIP_CONTENT_TAGS:
                        self._skip = max(0, self._skip - 1)
                del self._open[idx:]
                return

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        for _, element in self._open:
            if element is not None:
                element["text"].append(data)


def _squash(text: str | None) -> str | None:
    """Collapse whitespace; ``None`` for empty text."""
    squashed = " ".join((text or "").split())[:200]
    return squashed or None


def _quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _unique_selector(element: dict[str, Any], everyone: list[dict[str, Any]]) -> str | None:
    """A CSS selector that matches *element* and no other collected element."""
    tag, attrs = element["tag"], element["attrs"]
    same_tag = [e for e in everyone if e["tag"] == tag]

    def only(pool: list[dict[str, Any]], key: str) -> bool:
        return sum(1 for e in pool if e["attrs"].get(key) == attrs[key]) == 1

    if attrs.get("id") and only(everyone, "id"):
        ident = attrs["id"]
        return f"#{ident}" if _CSS_IDENT.match(ident) else f'[id="{_quote(ident)}"]'
    if attrs.get("data-testid") and only(everyone, "data-testid"):
        return f'[data-testid="{_quote(attrs["data-testid"])}"]'
    for key in ("name", "aria-label", "placeholder"):
        if attrs.get(key) and only(same_tag, key):
            return f'{tag}[{key}="{_quote(attrs[key])}"]'
    text = element["text"]
    if text:
        # :has-text matches case-insensitively on a substring: the text must
        # occur in no other element of the same tag
        needle = text.casefold()
        if sum(1 for e in same_tag if e["text"] and needle in e["text"].casefold()) == 1:
            return f'{tag}:has-text("{_quote(text)}")'
    return None


def page_elements_from_dom(
    html: str,
    page_url: str | None = None,
    *,
    tag: str | None = None,
    limit: int = MAX_PAGE_ELEMENTS,
) -> list[ElementRecord]:
    """Interactive elements of a page snapshot as healing-memory records.

    Each gets a selector unique on that page; an element without one is
    left out (an ambiguous selector could act on the wrong element).  With
    *tag*, only elements of that tag are kept (healing never swaps a
    button for a link).
    """
    collector = _ElementCollector()
    try:
        collector.feed(html)
        collector.close()
    except Exception as exc:  # noqa: BLE001 - a malformed snapshot only means no candidates
        logger.warning("Could not read page snapshot: %s", exc)
    for element in collector.elements:
        element["text"] = _squash("".join(element["text"]))

    records: list[ElementRecord] = []
    for element in collector.elements:
        if tag and element["tag"] != tag.lower():
            continue
        selector = _unique_selector(element, collector.elements)
        if selector is None:
            continue
        attributes = {"tag": element["tag"]}
        attributes.update({k: element["attrs"][k] for k in _RECORDED_ATTRS if element["attrs"].get(k)})
        records.append(ElementRecord(
            element_id=f"dom:{selector}",
            selector=selector,
            text=element["text"],
            role=element_role(element["tag"], element["attrs"]),
            page_url=page_url,
            attributes=attributes,
        ))
        if len(records) >= limit:
            break
    return records


def _read_snapshot(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("DOM snapshot %s unreadable: %s", path, exc)
        return None


def map_action_to_engine(action: TestAction) -> ActionType:
    """Map Member 1 TestAction enum to Member 2 ActionType enum."""
    mapping = {
        TestAction.NAVIGATE: ActionType.GOTO,
        TestAction.CLICK: ActionType.CLICK,
        TestAction.FILL: ActionType.FILL,
        TestAction.PRESS: ActionType.PRESS,
        TestAction.SELECT: ActionType.SELECT,
        TestAction.CHECK: ActionType.CHECK,
        TestAction.UNCHECK: ActionType.UNCHECK,
        TestAction.HOVER: ActionType.HOVER,
        TestAction.UPLOAD: ActionType.UPLOAD,
        TestAction.DRAG: ActionType.DRAG,
        TestAction.WAIT: ActionType.WAIT_FOR,
    }
    if action not in mapping:
        # Never guess (a click instead of a check toggles the box the wrong way)
        raise ValueError(f"No engine action for planner action {action!r}")
    return mapping[action]


def map_assertion_to_engine(
    assertion: Assertion,
    learned: dict[str, dict[str, Any]] | None = None,
) -> EngineStep:
    """Map Member 1 Assertion to Member 2 assertion EngineStep."""
    # A written description ("the cart shows a count") reads better than the selector
    written = assertion.description if assertion.description and not re.fullmatch(r"Assert \d+", assertion.description) else None
    target = create_engine_target(
        assertion.target,
        description=f"Check: {written}" if written else f"Assertion target for {assertion.type.value}",
        learned=learned,
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
            exact=assertion.type == AssertionType.ELEMENT_HAS_TEXT,
        )

    if assertion.type == AssertionType.VALUE_EQUALS:
        return EngineStep(
            step_id=f"assert-{assertion.type.value}",
            action=ActionType.ASSERT_VALUE,
            target=target,
            expected=assertion.expected or "",
        )

    if assertion.type == AssertionType.ELEMENT_NOT_VISIBLE:
        return EngineStep(
            step_id=f"assert-{assertion.type.value}",
            action=ActionType.ASSERT_HIDDEN,
            target=target,
        )

    if assertion.type in (AssertionType.URL_CONTAINS, AssertionType.URL_EQUALS):
        return EngineStep(
            step_id=f"assert-{assertion.type.value}",
            action=ActionType.ASSERT_URL,
            expected=assertion.expected,
            exact=assertion.type == AssertionType.URL_EQUALS,
        )

    if assertion.type != AssertionType.ELEMENT_VISIBLE:
        raise ValueError(f"No engine check for assertion type {assertion.type!r}")
    return EngineStep(
        step_id=f"assert-{assertion.type.value}",
        action=ActionType.ASSERT_VISIBLE,
        target=target,
        expected=assertion.expected or "",
    )


def test_case_to_engine_plan(
    test_case: Member1TestCase,
    base_url: str,
    learned: dict[str, dict[str, Any]] | None = None,
) -> EngineTestPlan:
    """Convert Member 1 TestCase into Member 2 EngineTestPlan.

    Transforms planned atomic actions and assertions into sequential Playwright steps.
    *learned* (see ``learned_targets_by_locator``) restores the fallback
    locators and fingerprints earlier runs captured, so the engine can heal.
    """
    engine_steps: list[EngineStep] = []

    # If test has steps, convert each
    for step in test_case.steps:
        target = create_engine_target(
            step.target,
            description=step.description or f"Step {step.step_number} element",
            learned=learned,
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
            assert_step = map_assertion_to_engine(assertion, learned)
            assert_step.step_id = f"step-{step.step_number}-assert-{idx + 1}"
            engine_steps.append(assert_step)

    # Include top-level test case assertions
    for idx, assertion in enumerate(test_case.assertions):
        assert_step = map_assertion_to_engine(assertion, learned)
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
    engine_plan: EngineTestPlan | None = None,
) -> ExecutionResult:
    """Convert Member 2 EngineTestResult into Member 1 ExecutionResult.

    Builds rich FailureContext on failure to feed Member 1's FailureAnalyzerAgent:
    besides the error, the page the step failed on and its interactive
    elements (read from the engine's DOM snapshot) for the AI healer.
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
    failed_res = None
    target_tag = None

    for idx, step_res in enumerate(engine_result.steps):
        if step_res.status == StepStatus.FAILED:
            failed_step_index = idx + 1
            error_msg = step_res.error or error_msg
            failed_res = step_res
            if engine_plan and idx < len(engine_plan.steps):
                plan_step = engine_plan.steps[idx]
                failed_step_action = plan_step.action.value
                if plan_step.target:
                    failed_target_selector = plan_step.target.primary_locator
                    if plan_step.target.fingerprint:
                        target_tag = plan_step.target.fingerprint.tag
            break

    page_url = (failed_res.page_url if failed_res else None) or (engine_plan.base_url if engine_plan else None)
    dom_evidence = None
    if failed_res is not None and failed_target_selector:
        html = _read_snapshot(failed_res.dom_snapshot_path)
        if html:
            elements = [
                e for e in page_elements_from_dom(html, page_url, tag=target_tag)
                if e.selector != failed_target_selector
            ]
            dom_evidence = {
                "snapshot_path": failed_res.dom_snapshot_path,
                "elements": [e.model_dump(mode="json") for e in elements],
            }

    failure_context = FailureContext(
        test_id=test_case_id,
        execution_id=workflow_id,
        failed_step=failed_step_index,
        action=failed_step_action,
        target_selector=failed_target_selector,
        error_message=error_msg,
        current_page_url=page_url,
        dom_evidence=dom_evidence,
        screenshot_path=failed_res.screenshot_path if failed_res else None,
    )

    return ExecutionResult(
        workflow_id=workflow_id,
        test_case_id=test_case_id,
        status=ExecutionResultStatus.FAILED,
        failure_context=failure_context,
    )
