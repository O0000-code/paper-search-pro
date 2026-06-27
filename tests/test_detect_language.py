"""Tests for detect_language — the UI-language router extracted from SKILL.md STEP 1.

The logic used to be inline bash regex in SKILL.md:
    [[ "$Q" =~ [ぁ-ヿ] ]]  -> en   # kana (U+3041–U+30FF) => Japanese
    [[ "$Q" =~ [一-鿿] ]]  -> zh   # CJK Han (U+4E00–U+9FFF), no kana
    else                  -> en
These tests pin the Python port to that exact behaviour so the extraction stays
byte-for-byte equivalent (R-19: STEP functional semantics must not change).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))

from scripts.detect_language import detect_language  # noqa: E402


@pytest.mark.parametrize(
    "query,expected",
    [
        # Chinese (Han, no kana) -> ZH
        ("工作记忆训练干预", "zh"),
        ("中科院一区 情绪调节", "zh"),
        ("深度学习", "zh"),
        # Kanji-only Japanese is indistinguishable from Chinese at codepoint
        # level -> ZH (matches old bash, which only had kana as the JP signal).
        ("東京大学", "zh"),
        # Japanese with kana -> EN (kana checked first)
        ("東京大学の最新研究", "en"),
        ("ディープラーニング", "en"),
        ("ひらがな", "en"),
        # Korean (Hangul, not matched) -> EN
        ("동기 부여 연구", "en"),
        # English / European -> EN
        ("prospect theory in decision making", "en"),
        ("Müller über Selbstregulation", "en"),
        ("", "en"),
        ("2024 RCT", "en"),
    ],
)
def test_detect_language(query, expected):
    assert detect_language(query) == expected


def test_cli_entrypoint_matches_function():
    """`python3 -m scripts.detect_language <query>` prints the same verdict."""
    env = dict(os.environ, PYTHONPATH=str(SKILL_ROOT))
    for q, expected in [("情绪调节", "zh"), ("emotion regulation", "en"), ("最新の研究", "en")]:
        out = subprocess.run(
            [sys.executable, "-m", "scripts.detect_language", q],
            capture_output=True,
            text=True,
            cwd=str(SKILL_ROOT),
            env=env,
            timeout=30,
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip() == expected


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
