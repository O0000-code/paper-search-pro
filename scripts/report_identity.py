"""Report identity primitives for human-facing literature-search reports.

The original user request, the normalized search topic, and the display title
serve different purposes.  Keeping them separate prevents conversational or
operational text from becoming the report's visual H1 while preserving the
verbatim request for audit and reproducibility.

Title authorship is intentionally left to the main agent after it has seen the
final evidence.  This module only normalizes an authored title and provides a
safe localized fallback; it never tries to infer a scholarly title from an
arbitrary natural-language request.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

from .detect_language import detect_language


DEFAULT_DISPLAY_TITLES = {
    "en": "Literature Search Report",
    "zh": "文献检索报告",
}


def resolve_report_language(
    language: Optional[str], original_user_query: str = ""
) -> str:
    """Return the supported report language (``en`` or ``zh``).

    An explicit supported language wins.  Otherwise we reuse the Skill's
    deterministic UI-language detector, which routes unsupported UI locales to
    English.  This keeps Python, Markdown, and React fallbacks aligned.
    """

    if language in DEFAULT_DISPLAY_TITLES:
        return str(language)
    return detect_language(original_user_query or "")


def normalize_one_line(value: Any) -> str:
    """Normalize authored identity text without changing its semantics."""

    if value is None:
        return ""
    text = re.sub(r"\s+", " ", str(value)).strip()
    # A model may accidentally include Markdown heading syntax even though the
    # caller wants the title value, not a rendered heading.
    return re.sub(r"^#{1,6}\s*", "", text).strip()


def resolve_display_title(
    display_title: Any,
    *,
    language: Optional[str] = None,
    original_user_query: str = "",
) -> str:
    """Return an authored one-line title or a safe localized generic fallback.

    Crucially, ``original_user_query`` is used only to choose the fallback
    language.  It is never returned as the display title.
    """

    title = normalize_one_line(display_title)
    if title:
        return title
    lang = resolve_report_language(language, original_user_query)
    return DEFAULT_DISPLAY_TITLES[lang]


def build_report_identity(
    *,
    original_user_query: str = "",
    search_topic: Any = "",
    display_title: Any = "",
    language: Optional[str] = None,
) -> Dict[str, str]:
    """Build the canonical report-identity fields stored in metadata.

    ``query`` remains a legacy alias of the verbatim request for downstream
    compatibility.  New display surfaces must use ``display_title`` instead.
    """

    original = "" if original_user_query is None else str(original_user_query)
    lang = resolve_report_language(language, original)
    return {
        "query": original,  # legacy compatibility; never use as an H1
        "original_user_query": original,
        "search_topic": normalize_one_line(search_topic),
        "display_title": resolve_display_title(
            display_title,
            language=lang,
            original_user_query=original,
        ),
        "language": lang,
    }
