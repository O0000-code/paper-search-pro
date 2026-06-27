"""Detect the UI language for the final HTML report from the user's query.

This is the deterministic logic that STEP 1 of SKILL.md used to inline as ~27
lines of bash regex. It lives here so the agent composes one command instead of
reconstructing the Unicode-range heuristic every run (and so the routing rule has
a single, testable source of truth).

Contract — returns exactly one of two values, printed to stdout with no newline
noise beyond a trailing "\\n":

  zh  — the query is Chinese (CJK Han with no Japanese kana)
  en  — everything else (English / European / Korean / Japanese)

Why this exact order (first match wins):

  1. Japanese kanji share the CJK Unified Ideographs block (U+4E00–U+9FFF) with
     Chinese Han characters, so a kanji-only Japanese query is indistinguishable
     from Chinese at the codepoint level. Real Japanese text almost always also
     carries hiragana (U+3041–U+309F) or katakana (U+30A0–U+30FF); detecting kana
     FIRST routes such queries to EN reliably.
  2. Otherwise, a CJK Unified Ideograph means Chinese → ZH.
  3. Otherwise (Latin, Hangul, Cyrillic, digits-only, …) → EN, the international
     academic default. A Korean researcher reading an English UI is friendlier
     than confronting a Chinese UI they cannot parse.

Only the report's UI chrome is affected. Paper titles / abstracts / authors /
venues are never translated.

This mirrors the previous bash heuristic byte-for-byte in behaviour:
    [[ "$Q" =~ [ぁ-ヿ] ]]      -> en   # U+3041–U+30FF (kana)
    [[ "$Q" =~ [一-鿿] ]]      -> zh   # U+4E00–U+9FFF (CJK ideographs)
    else                       -> en
"""

import re
import sys

# U+3041–U+30FF: hiragana + katakana (Japanese kana). bash range `ぁ-ヿ`.
_KANA = re.compile(r"[ぁ-ヿ]")
# U+4E00–U+9FFF: CJK Unified Ideographs (Han). bash range `一-鿿`.
_CJK = re.compile(r"[一-鿿]")


def detect_language(query: str) -> str:
    """Return 'zh' for Chinese queries, 'en' for everything else."""
    if _KANA.search(query):  # Japanese kana present -> EN
        return "en"
    if _CJK.search(query):  # Han ideographs, no kana -> ZH (Chinese)
        return "zh"
    return "en"  # Latin / Hangul / other -> EN (international default)


def main(argv: list[str]) -> int:
    # The whole query is passed as argv (quote it in the shell). Joining with a
    # space tolerates an unquoted multi-word query without changing the verdict.
    query = " ".join(argv[1:])
    print(detect_language(query))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
