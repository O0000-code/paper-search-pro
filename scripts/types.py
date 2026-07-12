"""
paper-search-pro Skill - Shared types across helper scripts.

In v2.0 architecture, this file holds ONLY data types for deterministic helpers.
LLM orchestration (state machine, budget controller, tools) belongs to the main
Claude Code agent driven by SKILL.md, not Python — those types have been removed.

Helper scripts that consume these types:
- openalex_helper.py, ss_helper.py, crossref_helper.py, pubmed_helper.py, arxiv_helper.py
- federated_kg_resolver.py
- discovery_curve.py, rcs_parser.py
- data_materialization.py, html_renderer_webartifacts.py, generate_exports.py, md_report.py
- prisma_s_logger.py, semantic_cache.py
"""

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


# =============================================================================
# Tier
# =============================================================================

Tier = Literal["quick", "standard", "deep", "audit"]


# =============================================================================
# Paper & Authors (unified cross-source representation)
# =============================================================================

@dataclass
class Author:
    """A single author. ORCID and country are best-effort (OpenAlex provides; SS often null)."""
    name: str
    orcid: Optional[str] = None
    affiliation: Optional[str] = None
    country: Optional[str] = None
    is_first: bool = False
    is_corresponding: bool = False


@dataclass
class JournalMetric:
    """Journal influence / quartile for one paper's venue (v2.2 Feature A).

    Additive, opt-in: ``UnifiedPaperEntity.journal_metric`` defaults to None so
    existing serialization / behavior is unchanged. Populated only when the SJR
    lookup and/or OpenAlex source stats are available.

    Naming is deliberate (R-04 / R-09): this is **SJR分区 / 期刊影响力**, never a
    JCR Impact Factor.
    - sjr_quartile               : "Q1".."Q4" or None — SCImago Best Quartile
      (or the chosen category's quartile). Data © SCImago (scimagojr.com),
      non-commercial cited use — SCImago custom terms, NOT a Creative Commons /
      CC BY-NC licence; attribution required.
    - sjr_category_quartiles     : {category: "Qn"} — per-category SJR quartiles.
    - openalex_2yr_mean_citedness: OpenAlex source summary_stats — an OPEN
      journal-impact figure. R-09: this is NOT the official JIF (e.g. JPSP reads
      ~2.7 here vs ~7-8 official); use for relative ranking/filtering only.
    - h_index                    : OpenAlex source h-index (CC0).
    - cwts_snip                  : optional cross-field-normalised SNIP (reserved).
    - sjr_attribution            : the mandatory SJR citation string (R-03) when
      any SJR field is present; None when no SJR data was joined.
    - issn_backfill_needed       : True when the paper has no ISSN to join on
      (SS-primary records frequently lack publicationVenue.issn — R-08). Marks the
      gap so an OpenAlex DOI-lookup backfill can be wired in as an integration
      point.
    """
    sjr_quartile: Optional[str] = None
    sjr_category_quartiles: Dict[str, str] = field(default_factory=dict)
    openalex_2yr_mean_citedness: Optional[float] = None
    h_index: Optional[int] = None
    cwts_snip: Optional[float] = None
    sjr_attribution: Optional[str] = None
    issn_backfill_needed: bool = False


@dataclass
class CASRank:
    """CAS (中科院文献情报中心) journal partition for one venue (v2.2 Feature A).

    Additive / optional — defaults keep serialization byte-compatible. 区 1-4 is a
    PARTITION (大类分区), NOT an Impact Factor (R-04). 勿公开传播 (personal use).
    - tier        : 大类分区 区号 1-4 (1 = top).
    - rank         : within-大类 rank string, e.g. "168/495".
    - top          : CAS Top 期刊 flag.
    - minor        : up to six 小类 (sub-category) partitions
                     [{category, tier, rank}].
    - source_year  : the CAS table year (e.g. 2025).
    """
    tier: Optional[int] = None
    rank: Optional[str] = None
    top: bool = False
    minor: List[Dict] = field(default_factory=list)
    source_year: Optional[int] = None


@dataclass
class JCRRank:
    """JCR (Clarivate) journal record for one venue (v2.2 Feature A).

    Additive / optional. This is the ONLY source of a real **Impact Factor**
    (R-04 / R-09): ``impact_factor`` here is the genuine JCR IF(2024); OpenAlex
    2yr-mean-citedness elsewhere is NOT this.
    - quartile     : "Q1".."Q4" (best across categories).
    - impact_factor: the real JCR IF(2024). © Clarivate.
    - rank         : category rank, e.g. "1/326".
    - category     : raw JCR Category string (may carry multiple, ``;``-joined).
    - source_year  : the JCR table year (e.g. 2024).
    """
    quartile: Optional[str] = None
    impact_factor: Optional[float] = None
    rank: Optional[str] = None
    category: Optional[str] = None
    source_year: Optional[int] = None


@dataclass
class SJRRank:
    """SJR (SCImago) journal record for one venue (v2.2 Feature A).

    Additive / optional. SJR quartile is a PARTITION/quartile, NOT an IF (R-04).
    Data © SCImago (scimagojr.com), non-commercial cited use — NOT CC BY-NC.
    - best_quartile: "Q1".."Q4" (best across categories).
    - sjr           : the SJR indicator value.
    - per_category  : per-category quartiles [{category, quartile}].
    - source_year   : the SJR table year (e.g. 2024).
    """
    best_quartile: Optional[str] = None
    sjr: Optional[float] = None
    per_category: List[Dict] = field(default_factory=list)
    source_year: Optional[int] = None


@dataclass
class JournalRank:
    """Unified multi-platform journal rank for one venue (v2.2 Feature A).

    Additive / optional: ``UnifiedPaperEntity.journal_rank`` defaults to None so
    existing serialization / behavior is byte-compatible. Each platform slot is
    independently optional (a journal found on only one platform still yields a
    valid record). Populated by journal_rank.py when ranking CSVs are cached.

    NOTE this is the v2.2 A-line *multi-platform* schema (CAS + JCR + SJR + an
    OpenAlex open-impact slot). As of the v2.2 single-layer collapse it is the ONE
    journal-rank record on a paper: the older SJR-only ``JournalMetric`` above is no
    longer populated by the search pipeline (kept only for back-compat decoding of
    pre-collapse kg.json).
    - title             : journal title (from whichever platform supplied it).
    - issns             : normalised "XXXX-XXXX" keys (print + electronic).
    - cas / jcr / sjr   : per-platform sub-records (None when not on that platform).
    - openalex          : OPEN journal-impact slot {mean_citedness_2yr, h_index} from
                          OpenAlex summary_stats (CC0). R-04/R-09: this is an OPEN
                          impact figure, NEVER an Impact Factor — only JCR's IF(2024)
                          is a real IF. Filled by the search pipeline, not the CSV
                          parsers; None when no impact was looked up / reachable.
    - matched_issn      : the ISSN a lookup hit on.
    - matched_platforms : which platforms contributed (["cas","jcr","sjr"] subset).
    """
    title: Optional[str] = None
    issns: List[str] = field(default_factory=list)
    cas: Optional["CASRank"] = None
    jcr: Optional["JCRRank"] = None
    sjr: Optional["SJRRank"] = None
    openalex: Optional[Dict] = None  # {mean_citedness_2yr: float|None, h_index: int|None}
    matched_issn: Optional[str] = None
    matched_platforms: List[str] = field(default_factory=list)


@dataclass
class UnifiedPaperEntity:
    """Cross-source unified paper representation. DOI is Primary Key.

    Source merging priority (see federated_kg_resolver.py):
    - title / authors / year: OpenAlex
    - abstract: OpenAlex (reconstructed) -> SS fallback
    - citation_count: OpenAlex
    - influential_citation_count: SS ONLY (unique signal)
    - references: OpenAlex -> CrossRef supplement (skip arXiv DOIs)
    - funder / license / clinical_trial_number: CrossRef
    - mesh_terms / pmcid: PubMed ONLY
    - arxiv_id: arXiv ONLY (also in OpenAlex.locations[])
    """
    # Identifiers
    doi: Optional[str] = None             # lowercase, no URL prefix
    arxiv_id: Optional[str] = None        # without version suffix, e.g. "1706.03762"
    openalex_id: Optional[str] = None     # "W..." prefix
    ss_paper_id: Optional[str] = None     # SS hex paperId
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    # Source-native stable ID for records that carry no DOI / arXiv / PMID /
    # OpenAlex / SS identifier (e.g. NSSD ``nssd:JJYJ2024005009`` or yiigle
    # ``yiigle:...``). Additive / optional (v2.2.1 Phase 0, 0.2): defaults to None
    # so canonical_key / paper_id / serialization stay byte-identical (R-19). The
    # ('native', id) key branch and the paper_id fallback are reached ONLY when
    # this is set — which no OA / SS / CrossRef / PubMed / arXiv record does — so
    # every existing English record behaves exactly as before.
    source_native_id: Optional[str] = None

    # Core metadata
    title: str = ""
    abstract: Optional[str] = None
    authors: List[Author] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    issn: Optional[str] = None             # journal ISSN (e.g. SS publicationVenue.issn / OA source.issn) — used downstream for SJR join
    type: Optional[str] = None             # article / preprint / review / book / dataset

    # Citations
    citation_count: int = 0
    referenced_works_count: Optional[int] = None

    # OpenAlex-specific
    fwci: Optional[float] = None
    cited_by_percentile_year: Optional[float] = None
    topics: List[Dict] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    sdgs: List[Dict] = field(default_factory=list)
    is_oa: Optional[bool] = None

    # Semantic Scholar-specific
    tldr: Optional[str] = None
    influential_citation_count: Optional[int] = None

    # CrossRef-specific
    funders: List[Dict] = field(default_factory=list)        # [{name, doi}]
    license: List[Dict] = field(default_factory=list)        # [{URL, content-version, delay-in-days}]
    clinical_trial_number: Optional[str] = None

    # PubMed-specific
    mesh_terms: List[str] = field(default_factory=list)
    publication_types: List[str] = field(default_factory=list)   # ["Clinical Trial", "Review", ...]

    # arXiv-specific
    arxiv_categories: List[str] = field(default_factory=list)    # ["cs.CL", "cs.AI"]
    arxiv_comment: Optional[str] = None                          # "Accepted at NeurIPS 2024"

    # URLs
    doi_url: Optional[str] = None
    openalex_url: Optional[str] = None
    pdf_url: Optional[str] = None
    pmc_url: Optional[str] = None
    # Additional open-access copy URLs parsed from OpenAlex ``locations[]``
    # (v2.2.1 Phase 0, 0.3 — additive). ``pdf_url`` above still holds the single
    # best OA URL (open_access.oa_url); this is the fuller multi-copy list (e.g.
    # publisher OA + PMC + repository). Empty list for papers with no OA copies,
    # so a non-OA record is byte-identical to pre-0.3 (R-19); the display path
    # (_render_paper) does not emit it, so the deliverable is unchanged.
    oa_locations: List[str] = field(default_factory=list)

    # Journal influence / quartile (v2.2 Feature A, additive — default None so
    # existing serialization is byte-compatible). Populated by sjr_helper +
    # OpenAlex source stats when available; None means "not looked up".
    journal_metric: Optional["JournalMetric"] = None

    # Multi-platform journal rank (v2.2 Feature A-line, additive — default None so
    # existing serialization is byte-compatible). Populated by journal_rank.py
    # (CAS + JCR + SJR) when ranking CSVs are cached; None means "not looked up".
    # Wave A-2 wires this into agent_search; until then it is reserved.
    journal_rank: Optional["JournalRank"] = None

    # Skill-internal (set by main Claude Code agent or scripts)
    rcs: Optional[int] = None                # 0-10, set during classification
    rcs_reasoning: Optional[str] = None
    rcs_flag: Optional[str] = None           # parse_failed_uncertain / off_topic_despite_keywords / abstract_unavailable / no_abstract_uncertain
    sources: List[str] = field(default_factory=list)  # ["openalex", "semantic_scholar", "crossref", "pubmed", "arxiv"]
    discovery_path: Optional[str] = None     # "query: prospect theory" / "ref of W12345" / "cites W12345" / "arxiv:T-0~T-4"

    @property
    def paper_id(self) -> str:
        """Stable identifier across sources. Priority: DOI > arxiv > openalex_id >
        pmid > ss_paper_id > source_native_id > title-hash.

        ``source_native_id`` sits just above the title-hash fallback (0.2): it only
        applies to records lacking every standard ID (e.g. NSSD / yiigle), so any
        record with a DOI / arXiv / OpenAlex / PMID / SS id keeps its prior
        paper_id byte-for-byte (R-19)."""
        return (
            self.doi
            or (f"arxiv:{self.arxiv_id}" if self.arxiv_id else None)
            or self.openalex_id
            or (f"pmid:{self.pmid}" if self.pmid else None)
            or self.ss_paper_id
            or self.source_native_id
            or f"untitled_{hash(self.title)}"
        )


@dataclass
class ParsedRCS:
    """RCS parser output for a single paper. See rcs_parser.py."""
    paper_id: str
    rcs: int
    reasoning: str
    flag: Optional[str] = None


# =============================================================================
# Configuration (loaded from ~/.paper-search-pro/config.yaml)
# =============================================================================

@dataclass
class Config:
    """User config + defaults. Loaded by config.py.

    No state-machine / budget fields — those are managed by the main Claude Code
    agent following SKILL.md, not Python.
    """
    # ---- Data source credentials ----
    openalex_email: str = ""               # Required for OpenAlex polite pool (or use API key)
    openalex_api_key: str = ""             # Optional: OpenAlex Premium / Bearer token
    semantic_scholar_api_key: str = ""     # Optional: SS API key (15x rate limit boost)
    ncbi_email: str = ""                   # Required for PubMed (always)
    ncbi_api_key: str = ""                 # Optional: NCBI key (3 req/s -> 10 req/s)
    crossref_email: str = ""               # Required for CrossRef polite pool

    # ---- Output ----
    output_dir: str = "./paper-search-results"
    default_tier: Tier = "standard"
    language: str = "en"                   # REPORT UI chrome language (en | zh); auto-detected by detect_language.py. ORTHOGONAL to search_language below — this is "what language the report speaks", not "which literature to fish in".

    # ---- Language routing (v2.3, additive — default "auto" preserves v2.2 behavior) ----
    # The search "language space" (axis 2 of the three-axis model): which ocean of
    # literature to search — English, Chinese, or both. Additive / opt-in: a config
    # missing this key defaults to "auto", so every existing (English) run is
    # byte-for-byte unchanged (same additive precedent as primary_source — R-19).
    #   auto (factory) — English query -> en space (byte-identical to v2.2); Chinese
    #                    query -> follow explicit in-query signals, else the human
    #                    path asks once and the agent path passes the query through.
    #   en   — never enter the Chinese space; a Chinese query is planned as an
    #          English search (with a one-line notice, never a silent translation).
    #   zh   — Chinese query runs in the Chinese space (OpenAlex Chinese base +
    #          discipline-routed NSSD/yiigle boosters), search terms kept in Chinese.
    #   both — dual-space federated search (English + Chinese strategy sets).
    # ORTHOGONAL to `language` above (UI chrome) — neither reads nor overrides the
    # other. SSOT for parsing priority / markers: references/source_routing.md
    # §"Language scope".
    search_language: str = "auto"          # auto | en | zh | both

    # ---- Source routing (v2.2, additive — defaults preserve v2.0/2.1 behavior) ----
    # Which source the search entry-point treats as primary. "openalex" = current
    # behavior unchanged. "semantic_scholar" = use SS bulk search as primary.
    # "auto" = start on OpenAlex but let quota_guard (run mode) stickily fall
    # back to SS for the rest of a run when OpenAlex USD budget runs low.
    primary_source: str = "openalex"          # openalex | semantic_scholar | auto
    # When primary_source == "auto", whether the quota-driven fallback is allowed.
    quota_fallback: bool = True
    # USD budget remaining (per OpenAlex X-RateLimit-Remaining-USD) at or below
    # which "auto" mode switches to SS for the remainder of the run.
    quota_fallback_threshold_usd: float = 0.05

    # ---- Journal rank (v2.2 Feature A — additive; default None = built-ins) ----
    # Nested dict from config ``rank:`` (default_platform / cache_dir / sources).
    # None means "use journal_rank.py built-in defaults". Multi-platform partition
    # / quartile (CAS / JCR / SJR); data fetched at runtime, never bundled.
    rank: Optional[Dict] = None

    # ---- HTML rendering ----
    # (No size cap or alternative renderer as of 2026-05-23. The Skill
    # always uses html_renderer_webartifacts; the size-driven jinja2
    # fallback was removed for UX consistency.)

    # ---- Cache ----
    cache_enabled: bool = True
    cache_ttl_days: int = 7
    cache_max_size_mb: int = 500

    # ---- Logging ----
    log_level: str = "INFO"
