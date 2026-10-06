"""
TestSphere-AI — Context Comparator

Compares previous and current element states to produce structured
change reports.  The output is designed for consumption by the
future Self-Healing Agent and Failure Analyzer.

Day 8: Context comparison foundation.
"""

from __future__ import annotations

from agents.memory.memory_schemas import (
    ContextComparisonResult,
    ElementRecord,
    FieldChange,
)
from agents.schemas.enums import ChangeType


# Fields to compare directly between two ElementRecord instances.
_COMPARABLE_FIELDS: list[str] = [
    "selector",
    "text",
    "role",
    "page_url",
    "page_name",
]


class ContextComparator:
    """Compares previous and current element contexts.

    Produces a structured ``ContextComparisonResult`` that lists
    every field-level change detected.  Does NOT perform any
    automatic healing or modification — it only reports differences.

    Usage
    -----
    >>> comparator = ContextComparator()
    >>> result = comparator.compare_elements(previous, current)
    >>> if not result.is_identical:
    ...     for change in result.changes:
    ...         print(f"{change.field_name}: {change.old_value} -> {change.new_value}")
    """

    def compare_elements(
        self,
        previous: ElementRecord,
        current: ElementRecord,
    ) -> ContextComparisonResult:
        """Compare two element snapshots and report differences.

        Parameters
        ----------
        previous:
            The element state from a previous (successful) execution.
        current:
            The element state from the current execution.

        Returns
        -------
        ContextComparisonResult
            Structured comparison with all detected changes.
        """
        changes: list[FieldChange] = []

        # Compare simple fields
        for field_name in _COMPARABLE_FIELDS:
            old_val = getattr(previous, field_name, None)
            new_val = getattr(current, field_name, None)
            change = self._compare_field(field_name, old_val, new_val)
            if change is not None:
                changes.append(change)

        # Compare attributes dict
        attr_changes = self.compare_attributes(
            previous.attributes, current.attributes
        )
        changes.extend(attr_changes)

        return ContextComparisonResult(
            element_id=previous.element_id,
            previous_selector=previous.selector,
            current_selector=current.selector,
            changes=changes,
            is_identical=len(changes) == 0,
        )

    def compare_attributes(
        self,
        old_attrs: dict[str, str],
        new_attrs: dict[str, str],
    ) -> list[FieldChange]:
        """Compare two attribute dictionaries.

        Detects attributes that were added, removed, or modified.

        Parameters
        ----------
        old_attrs:
            Attributes from the previous element snapshot.
        new_attrs:
            Attributes from the current element snapshot.

        Returns
        -------
        list[FieldChange]
            Changes detected in the attributes.
        """
        changes: list[FieldChange] = []
        all_keys = set(old_attrs.keys()) | set(new_attrs.keys())

        for key in sorted(all_keys):
            old_val = old_attrs.get(key)
            new_val = new_attrs.get(key)
            field_name = f"attributes.{key}"

            if old_val is None and new_val is not None:
                changes.append(
                    FieldChange(
                        field_name=field_name,
                        old_value=None,
                        new_value=new_val,
                        change_type=ChangeType.ADDED,
                    )
                )
            elif old_val is not None and new_val is None:
                changes.append(
                    FieldChange(
                        field_name=field_name,
                        old_value=old_val,
                        new_value=None,
                        change_type=ChangeType.REMOVED,
                    )
                )
            elif old_val != new_val:
                changes.append(
                    FieldChange(
                        field_name=field_name,
                        old_value=old_val,
                        new_value=new_val,
                        change_type=ChangeType.MODIFIED,
                    )
                )
            # If equal, no change to report

        return changes

    # ── Private Helpers ───────────────────────────────────────

    @staticmethod
    def _compare_field(
        field_name: str,
        old_value: object,
        new_value: object,
    ) -> FieldChange | None:
        """Compare a single field and return a FieldChange if different.

        Returns ``None`` when values are identical.
        """
        if old_value is None and new_value is None:
            return None

        if old_value is None and new_value is not None:
            return FieldChange(
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                change_type=ChangeType.ADDED,
            )

        if old_value is not None and new_value is None:
            return FieldChange(
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                change_type=ChangeType.REMOVED,
            )

        if old_value != new_value:
            return FieldChange(
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                change_type=ChangeType.MODIFIED,
            )

        return None
