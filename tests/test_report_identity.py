"""Regression tests for report identity and scholarly title separation."""

from __future__ import annotations

import json

import pytest

from scripts.data_materialization import materialize
from scripts.html_renderer_webartifacts import _build_report_data
from scripts.md_report import render_md
from scripts.report_identity import (
    build_report_identity,
    normalize_one_line,
    resolve_display_title,
)
from scripts.types import UnifiedPaperEntity


RAW_ZH = (
    "请帮我用 Paper Search Pro 找 2026 年英文、中科院 1/2 区的发展心理学 AI 文献，"
    "并导出 RIS。"
)
TOPIC = "developmental psychology; AI/agents as research methods or developmental contexts"
TITLE_ZH = "人工智能与智能体在发展心理学中的双重角色：研究工具与发展情境"


def _kg():
    paper = UnifiedPaperEntity(
        doi="10.1/example",
        title="Example paper",
        abstract="Example abstract for report identity tests.",
        year=2026,
        venue="Example Journal",
        rcs=7,
        sources=["openalex"],
    )
    return {paper.paper_id: paper}


def test_build_report_identity_keeps_four_roles_separate():
    raw = RAW_ZH + "\n第二行审计文本"
    identity = build_report_identity(
        original_user_query=raw,
        search_topic=TOPIC,
        display_title=f"#  {TITLE_ZH}\n",
        language="zh",
    )

    assert identity["query"] == raw  # legacy audit alias remains verbatim
    assert identity["original_user_query"] == raw
    assert identity["search_topic"] == TOPIC
    assert identity["display_title"] == TITLE_ZH
    assert identity["language"] == "zh"


@pytest.mark.parametrize(
    ("query", "language", "expected"),
    [
        (RAW_ZH, None, "文献检索报告"),
        ("Please find papers about attachment.", None, "Literature Search Report"),
        ("東京大学の最新研究", None, "Literature Search Report"),
        (RAW_ZH, "en", "Literature Search Report"),
    ],
)
def test_missing_title_uses_localized_generic_never_raw_query(query, language, expected):
    assert resolve_display_title(
        "   ", language=language, original_user_query=query
    ) == expected
    assert expected != query


def test_normalize_one_line_preserves_meaning_without_markdown_heading():
    assert normalize_one_line("##  Child development\n  and social robots ") == (
        "Child development and social robots"
    )


def test_materialization_emits_explicit_report_identity(tmp_path):
    artifacts = materialize(
        _kg(),
        tmp_path,
        user_query=RAW_ZH,
        search_topic=TOPIC,
        display_title=TITLE_ZH,
        language="zh",
        tier="standard",
        search_id="sid",
        summary="Summary",
    )
    metadata = json.loads(artifacts["metadata"].read_text(encoding="utf-8"))

    assert metadata["query"] == RAW_ZH
    assert metadata["original_user_query"] == RAW_ZH
    assert metadata["search_topic"] == TOPIC
    assert metadata["display_title"] == TITLE_ZH
    assert metadata["language"] == "zh"


def test_materialization_without_authored_title_does_not_promote_request(tmp_path):
    artifacts = materialize(
        _kg(), tmp_path, user_query=RAW_ZH, language="zh", summary="Summary"
    )
    metadata = json.loads(artifacts["metadata"].read_text(encoding="utf-8"))

    assert metadata["original_user_query"] == RAW_ZH
    assert metadata["display_title"] == "文献检索报告"
    assert metadata["display_title"] != metadata["query"]


def test_legacy_html_payload_gets_safe_title_without_losing_query():
    payload = _build_report_data(
        metadata={"query": RAW_ZH},
        paper_list=[],
        chart_data={},
        prisma_log_raw={},
        language="zh",
    )
    metadata = payload["metadata"]

    assert metadata["original_user_query"] == RAW_ZH
    assert metadata["query"] == RAW_ZH
    assert metadata["display_title"] == "文献检索报告"


def test_explicit_html_title_overrides_materialized_title():
    payload = _build_report_data(
        metadata={
            "query": "find papers",
            "display_title": "Old title",
            "language": "en",
        },
        paper_list=[],
        chart_data={},
        prisma_log_raw={},
        display_title="Evidence-bounded new title",
        language="en",
    )
    assert payload["metadata"]["display_title"] == "Evidence-bounded new title"


def test_markdown_h1_uses_display_title_not_original_request(tmp_path):
    materialize(
        _kg(),
        tmp_path,
        user_query=RAW_ZH,
        search_topic=TOPIC,
        display_title=TITLE_ZH,
        language="zh",
        summary="Summary",
    )
    output = tmp_path / "report.md"
    render_md(tmp_path, output, summary="Summary", user_query=RAW_ZH)
    first_line = output.read_text(encoding="utf-8").splitlines()[0]

    assert first_line == f"# {TITLE_ZH}"
    assert RAW_ZH not in first_line


def test_legacy_markdown_metadata_falls_back_to_generic_h1(tmp_path):
    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "query": RAW_ZH,
                "language": "zh",
                "coverage_estimate": None,
                "wall_clock_total_s": 0,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (tmp_path / "paper_list.json").write_text("[]", encoding="utf-8")
    (tmp_path / "chart_data.json").write_text(
        json.dumps({"theme_treemap": {"themes": []}}), encoding="utf-8"
    )
    output = tmp_path / "legacy.md"

    render_md(tmp_path, output, summary="Summary")
    first_line = output.read_text(encoding="utf-8").splitlines()[0]

    assert first_line == "# 文献检索报告"
    assert RAW_ZH not in first_line
