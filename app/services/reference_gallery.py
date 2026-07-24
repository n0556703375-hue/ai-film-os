"""Pure helpers for organizing approved asset references for presentation.

This module is intentionally storage-agnostic: it accepts repository dictionaries,
does not mutate them, and never changes approval or lock state.
"""

from collections import defaultdict


DEFAULT_VIEW = "unspecified"
DEFAULT_EXPRESSION = "neutral"


def _label(value, default):
    if not isinstance(value, str):
        return default
    value = value.strip()
    return value or default


def group_approved_references(references):
    """Return approved references grouped by view and expression.

    Expression is read from the existing ``metadata`` dictionary, avoiding a
    destructive schema migration. Unapproved references are excluded.
    """
    grouped = defaultdict(lambda: defaultdict(list))

    for reference in references or []:
        if not reference.get("approved"):
            continue

        metadata = reference.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}

        view = _label(reference.get("view_type"), DEFAULT_VIEW)
        expression = _label(metadata.get("expression"), DEFAULT_EXPRESSION)
        grouped[view][expression].append(dict(reference))

    return {
        view: {expression: items for expression, items in sorted(expressions.items())}
        for view, expressions in sorted(grouped.items())
    }
