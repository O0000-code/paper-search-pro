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

    # Core metadata
    title: str = ""
    abstract: Optional[str] = None
    authors: List[Author] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
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

    # Skill-internal (set by main Claude Code agent or scripts)
    rcs: Optional[int] = None                # 0-10, set during classification
    rcs_reasoning: Optional[str] = None
    rcs_flag: Optional[str] = None           # parse_failed_uncertain / off_topic_despite_keywords / abstract_unavailable / no_abstract_uncertain
    sources: List[str] = field(default_factory=list)  # ["openalex", "semantic_scholar", "crossref", "pubmed", "arxiv"]
    discovery_path: Optional[str] = None     # "query: prospect theory" / "ref of W12345" / "cites W12345" / "arxiv:T-0~T-4"

    @property
    def paper_id(self) -> str:
        """Stable identifier across sources. Priority: DOI > arxiv > openalex_id > pmid > ss_paper_id > title-hash."""
        return (
            self.doi
            or (f"arxiv:{self.arxiv_id}" if self.arxiv_id else None)
            or self.openalex_id
            or (f"pmid:{self.pmid}" if self.pmid else None)
            or self.ss_paper_id
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
    language: str = "en"

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
