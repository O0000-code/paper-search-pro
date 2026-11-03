"""SKILL.md frontmatter: the description fits the spec and keeps its routing anchors.

The description is what an agent reads when it decides whether to load this Skill.
The Agent Skills spec caps it at 1,024 characters. Codex truncates a longer one in
its skill list: from v2.3 to v2.5 that cut off every Chinese trigger and the whole
"Do NOT use" part, and validators reject it outright.

Three separate edits that shortened the description also dropped trigger phrases
without anyone noticing, so the phrases that carry a routing decision are pinned
below. Removing one should be a decision, not a side effect of trimming.
"""

import re
from pathlib import Path

import yaml

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
MAX_DESCRIPTION_CHARS = 1024  # agentskills.io specification, `description` field

# Boundaries: requests that must route elsewhere, each with its example.
BOUNDARY_ANCHORS = [
    "Do NOT use",
    "'what is X'",
    "'影响因子怎么算'",
    "'帮我写'",
    "'help me write a paragraph'",
    "interpreting one paper",
    "PDF download",
    "paper-downloader-portable",
    "existing literature set",
    "literature-set-review",
]
# One anchor per capability, in the language users ask in.
CAPABILITY_ANCHORS = [
    "Find academic papers",
    "literature search",
    "systematic review",
    "'help me write a lit review'",
    "找文献",
    "文献综述",
    "中文原生",
    "CSSCI",
    "中科院分区",
    "JCR/SJR quartile",
    "检索式",
    "boolean search strategies",
    "知网专业检索",
    "PRISMA-S",
]


def _frontmatter():
    text = SKILL_MD.read_text(encoding="utf-8")
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, "SKILL.md must start with a YAML frontmatter block"
    return yaml.safe_load(match.group(1))


def _description():
    # Loaders collapse runs of whitespace before showing the description (Codex
    # does), so count and match the text the way an agent will see it.
    description = _frontmatter()["description"]
    assert isinstance(description, str)
    return " ".join(description.split())


def test_name_follows_spec():
    name = _frontmatter()["name"]
    assert name == "paper-search-pro"
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) and len(name) <= 64


def test_description_within_spec_limit():
    description = _description()
    assert description
    assert len(description) <= MAX_DESCRIPTION_CHARS, (
        f"description is {len(description)} characters; the limit is "
        f"{MAX_DESCRIPTION_CHARS} and Codex cuts off everything past it"
    )
    assert "<" not in description and ">" not in description


def test_description_keeps_routing_anchors():
    description = _description()
    missing = [a for a in BOUNDARY_ANCHORS + CAPABILITY_ANCHORS if a not in description]
    assert not missing, f"description no longer contains: {missing}"
