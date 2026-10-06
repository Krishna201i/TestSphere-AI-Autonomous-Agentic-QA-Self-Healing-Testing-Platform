"""
TestSphere-AI — LLM Healing Evaluator

AI-assisted candidate evaluation for ambiguous healing decisions.

This module provides optional LLM-based disambiguation when
deterministic scoring cannot clearly separate candidates.

Day 11: Implementation.

Pipeline
--------
1. Build structured prompt with observable evidence only
2. Send to LLM via existing LLMClientSession.generate_json()
3. Response Normalization (LLMClientSession handles this)
4. Schema Validation (required fields + types)
5. Business Validation (grounding check: selected_candidate
   MUST be one of the supplied candidate selectors)

SAFETY RULES
------------
- The LLM CANNOT invent selectors, pages, elements, roles,
  text, or attributes.
- Every recommendation MUST be grounded in the supplied context.
- If the LLM returns an invalid or ungrounded response, the
  recommendation is rejected and None is returned.
- No chain-of-thought is stored or exposed.

IMPORTANT: This module does NOT execute browser actions.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from agents.healer.healing_schemas import (
    LLMEvaluationResult,
    ScoredCandidate,
)

logger = logging.getLogger(__name__)


class LLMHealingEvaluator:
    """LLM-assisted candidate evaluator with strict validation.

    Uses the existing LLM abstraction (LLMClientSession) to evaluate
    ambiguous healing candidates.  All LLM responses are validated
    against the supplied candidate list — the LLM cannot invent
    selectors.

    Parameters
    ----------
    llm_client:
        An LLMClientSession instance (from agents.llm.client).
        Must support ``generate_json(request)`` method.
    """

    def __init__(self, llm_client: object) -> None:
        self._llm_client = llm_client

    async def evaluate_candidates(
        self,
        candidates: list[ScoredCandidate],
        original_selector: str,
        failure_type: str,
    ) -> Optional[LLMEvaluationResult]:
        """Evaluate ambiguous candidates using the LLM.

        Parameters
        ----------
        candidates:
            Ranked candidates to evaluate (at least 2).
        original_selector:
            The original selector that failed.
        failure_type:
            The classified failure type string.

        Returns
        -------
        Optional[LLMEvaluationResult]
            A validated evaluation result, or None if the LLM
            fails or returns an invalid/ungrounded response.
        """
        if len(candidates) < 2:
            logger.debug(
                "LLM evaluation skipped — fewer than 2 candidates",
            )
            return None

        # Build the valid selector set for grounding validation
        valid_selectors = {c.selector for c in candidates}

        # Build structured prompt
        prompt_data = self._build_prompt(
            candidates, original_selector, failure_type,
        )

        try:
            from agents.llm.schemas import LLMRequest

            request = LLMRequest(
                prompt=json.dumps(prompt_data, indent=2),
                system_instruction=(
                    "You are a test healing evaluation engine. "
                    "Select the best replacement selector from the "
                    "provided candidates based ONLY on the supplied "
                    "evidence. Respond ONLY with a JSON object "
                    "containing: selected_candidate (string), "
                    "confidence (float 0.0-1.0), "
                    "reason (concise string). "
                    "Do not include any other text. "
                    "Do not invent selectors."
                ),
                response_format="json",
                temperature=0.1,
            )

            # Step 1-3: Generate via LLMClientSession
            # (response normalization is handled by the session)
            response_data = await self._llm_client.generate_json(request)

            # Step 4: Schema validation
            result = self._validate_schema(response_data)
            if result is None:
                return None

            # Step 5: Business validation (grounding check)
            if not self._validate_grounding(result, valid_selectors):
                return None

            logger.info(
                "LLM evaluation selected: selector=%s, "
                "confidence=%.4f, reason=%s",
                result.selected_selector,
                result.confidence,
                result.reason,
            )
            return result

        except Exception as exc:
            logger.warning(
                "LLM evaluation failed: %s: %s",
                type(exc).__name__,
                exc,
            )
            return None

    # ── Prompt Building ──────────────────────────────────────

    @staticmethod
    def _build_prompt(
        candidates: list[ScoredCandidate],
        original_selector: str,
        failure_type: str,
    ) -> dict:
        """Build a structured prompt with observable evidence only.

        No chain-of-thought instructions. Only structured evidence
        is provided to the LLM.
        """
        candidates_data = []
        for c in candidates[:5]:  # Limit to top 5
            candidate_info: dict = {
                "selector": c.selector,
                "evidence": c.evidence[:5],  # Limit evidence lines
            }
            # Include similarity scores for transparency
            scores = {}
            if c.text_similarity > 0.0:
                scores["text"] = c.text_similarity
            if c.role_similarity > 0.0:
                scores["role"] = c.role_similarity
            if c.type_similarity > 0.0:
                scores["type"] = c.type_similarity
            if c.page_similarity > 0.0:
                scores["page"] = c.page_similarity
            if c.name_similarity > 0.0:
                scores["name"] = c.name_similarity
            if c.stable_attribute_similarity > 0.0:
                scores["stable_attribute"] = c.stable_attribute_similarity
            if scores:
                candidate_info["similarity_scores"] = scores
            candidates_data.append(candidate_info)

        return {
            "task": "Select the best replacement selector candidate.",
            "failure_type": failure_type,
            "original_selector": original_selector,
            "candidates": candidates_data,
            "instruction": (
                "Return a JSON object with: "
                "'selected_candidate' (one of the candidate selectors above), "
                "'confidence' (float 0.0-1.0), "
                "'reason' (concise explanation). "
                "You must select from the provided candidates only."
            ),
        }

    # ── Schema Validation ────────────────────────────────────

    @staticmethod
    def _validate_schema(
        response_data: dict,
    ) -> Optional[LLMEvaluationResult]:
        """Validate the LLM response matches the expected schema.

        Checks that required fields exist and have correct types.
        Returns None if validation fails.
        """
        # Check required field: selected_candidate
        selected = response_data.get("selected_candidate")
        if not isinstance(selected, str) or not selected.strip():
            logger.warning(
                "LLM response missing or invalid 'selected_candidate': %s",
                selected,
            )
            return None

        # Check required field: confidence
        confidence = response_data.get("confidence")
        if not isinstance(confidence, (int, float)):
            logger.warning(
                "LLM response missing or invalid 'confidence': %s",
                confidence,
            )
            return None

        confidence = min(max(float(confidence), 0.0), 1.0)

        # Optional field: reason
        reason = response_data.get("reason", "")
        if not isinstance(reason, str):
            reason = ""

        try:
            return LLMEvaluationResult(
                selected_selector=selected.strip(),
                confidence=confidence,
                reason=reason,
            )
        except Exception as exc:
            logger.warning(
                "LLM evaluation result validation failed: %s", exc,
            )
            return None

    # ── Grounding Validation ─────────────────────────────────

    @staticmethod
    def _validate_grounding(
        result: LLMEvaluationResult,
        valid_selectors: set[str],
    ) -> bool:
        """Validate that the LLM's selection is grounded in context.

        The LLM CANNOT invent selectors. The selected_selector
        MUST be one of the supplied candidate selectors.

        Returns True if grounded, False if the LLM invented a selector.
        """
        if result.selected_selector not in valid_selectors:
            logger.warning(
                "LLM recommendation REJECTED — selector '%s' not in "
                "supplied candidates: %s",
                result.selected_selector,
                valid_selectors,
            )
            return False

        return True
