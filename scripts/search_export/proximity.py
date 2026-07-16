"""Proximity-operator conversion + shell rendering (Design Spec §5.1).

Where this sits in the pipeline
-------------------------------
STEP 11.5 (Search Strategy Export) three-sandwich **layer 2** (mechanical
templating). The LLM (layer 1) decides the *canonical* proximity intent as a
single number ``k = max_gap`` — the maximum number of words allowed *between*
the two terms — and never touches per-host arithmetic (risk A-3: "禁止 LLM 逐次
口算"). This module is the deterministic table that turns that one canonical ``k``
into each host's native operator:

    render(host, ["sleep", "therapy"], k=3)   # PubMed -> "sleep therapy"[tiab:~3]
    render("ovid", ["heart", "attack"], k=1)  # Ovid   -> heart adj2 attack
    render("ebsco", ["heart", "attack"], k=1) # EBSCO  -> heart N1 attack

The two families differ by exactly one (Design Spec §5.1, verified A1 §2):

    gap          hosts (ebsco/proquest/scopus/wos)          ->  n = k
    gap_plus_one hosts (cochrane/ovid/embase_com)           ->  n = k + 1

so **Ovid adj2 ≡ EBSCO N1** (both = "at most one intervening word", k=1) — the
canonical equivalence the build unit-test pins.

Design invariants
-----------------
- **Pure data + arithmetic; network-free.** All facts come from
  ``references/search_export/proximity_table.json`` (in git, D-19). No hardcoded
  per-host semantics — this module reads the table, it does not embed it.
- **No-proximity hosts return a degradation signal, never a fabricated operator.**
  ACM / ClinicalTrials.gov / 万方 / ERIC(free site) / SciFinder / SinoMed carry
  ``unordered: null`` in the table; ``render`` returns ``supported=False`` with the
  table's declared ``fallback`` (AND / phrase) so the caller degrades honestly
  rather than emitting a NEAR that the host silently drops.
- **Standalone hosts carry their own ``n_semantics``** (pubmed/cnki/ieee/cabi are
  not in the two families); the resolver reads it off the operator shell.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

# ``references/search_export/proximity_table.json`` relative to the repo root
# (scripts/search_export/proximity.py -> parents[2] == repo root).
_DEFAULT_TABLE = (
    Path(__file__).resolve().parents[2]
    / "references"
    / "search_export"
    / "proximity_table.json"
)

# Alias map: caller-facing host names / card filenames -> proximity_table
# operator_shells key. Keeps the table's key space (e.g. "cochrane", "embase_com",
# "ovid") the single source while accepting the friendlier names the rest of the
# pipeline uses (card filenames, platform labels, CJK names).
_HOST_ALIASES = {
    "acm_dl": "acm",
    "acm dl": "acm",
    "cochrane_central": "cochrane",
    "cochrane central": "cochrane",
    "central": "cochrane",
    "cochranelibrary": "cochrane",
    "embase.com": "embase_com",
    "embase (embase.com)": "embase_com",
    "embase-com": "embase_com",
    "embase_ovid": "ovid",
    "embase-on-ovid": "ovid",
    "psycinfo_ovid": "ovid",
    "medline_ovid": "ovid",
    "cinahl_ebsco": "ebsco",
    "cinahl": "ebsco",
    "econlit_ebsco": "ebsco",
    "econlit": "ebsco",
    "psycinfo_ebsco": "ebsco",
    "ebscohost": "ebsco",
    "ieee_xplore": "ieee",
    "ieee xplore": "ieee",
    "cab_cabi": "cabi",
    "cab": "cabi",
    "web of science": "wos",
    "webofscience": "wos",
    "wos_core": "wos",
    "clinicaltrials.gov": "clinicaltrials_gov",
    "ct.gov": "clinicaltrials_gov",
    "ctgov": "clinicaltrials_gov",
    "知网": "cnki",
    "万方": "wanfang",
    "cbm": "sinomed",
}

# Hosts the table explicitly marks as having no proximity operator (unordered=null).
# Kept only for a friendly error message / introspection; the truth is the table.
NO_PROXIMITY_HOSTS = frozenset(
    {"acm", "clinicaltrials_gov", "wanfang", "eric", "scifinder", "sinomed"}
)


class UnknownHostError(KeyError):
    """Raised when a host is not present in the proximity table."""


@dataclass
class ProximityRender:
    """Result of converting a canonical ``k`` into one host's proximity operator.

    - ``supported`` False  -> host has no proximity operator; ``expression`` is None
      and ``fallback`` carries the table's degrade strategy ("AND_or_phrase", ...).
    - ``semantics``        -> "gap" | "gap_plus_one" (None only when unsupported).
    - ``n``                -> the host-native operand for the operator (None when
      unsupported).
    - ``operator``         -> the bare infix token ("NEAR/3", "adj2", "N1"); None for
      phrase-shell hosts (PubMed/CABI) where the operator is fused into a quoted
      phrase, and None when unsupported.
    - ``expression``       -> the fully rendered proximity clause for ``terms``.
    """

    host: str
    k: int
    n: Optional[int]
    semantics: Optional[str]
    in_family: bool
    supported: bool
    expression: Optional[str] = None
    operator: Optional[str] = None
    fallback: Optional[str] = None
    note: str = ""
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Table loading + host normalisation
# ---------------------------------------------------------------------------


@lru_cache(maxsize=8)
def _load_cached(path_str: str) -> Dict:
    with open(path_str, "r", encoding="utf-8") as fh:
        return json.load(fh)


def load_table(path: Optional[Path] = None) -> Dict:
    """Load ``proximity_table.json`` (cached per path). Returns the parsed dict."""
    p = Path(path) if path is not None else _DEFAULT_TABLE
    return _load_cached(str(p))


def normalize_host(host: str) -> str:
    """Map a caller-facing host name/card filename onto an operator_shells key."""
    key = (host or "").strip().lower()
    return _HOST_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Family / semantics resolution (the lookup_algorithm from the table _meta)
# ---------------------------------------------------------------------------


def _shell(host: str, table: Dict) -> Dict:
    shells = table.get("operator_shells", {})
    if host not in shells:
        raise UnknownHostError(
            f"host {host!r} not in proximity_table.operator_shells"
        )
    return shells[host]


def semantics_for(host: str, table: Optional[Dict] = None):
    """Return ("gap"|"gap_plus_one" | None, in_family) for a host.

    Implements the table's ``_meta.lookup_algorithm``:
      1. host in a family's ``hosts`` -> that family (name == the semantics);
      2. else read the operator shell's ``n_semantics`` (standalone hosts);
      3. shell ``unordered`` is null -> None (no proximity -> degrade).
    """
    host = normalize_host(host)
    table = table if table is not None else load_table()
    for fam_name, fam in table.get("families", {}).items():
        if host in fam.get("hosts", []):
            return fam_name, True
    shell = _shell(host, table)
    if shell.get("unordered") is None:
        return None, False
    return shell.get("n_semantics"), False


def _n_from_semantics(semantics: str, k: int) -> int:
    # gap_plus_one adds one; gap is identity. (Design Spec §5.1 n_formula.)
    return k + 1 if semantics == "gap_plus_one" else k


def host_n(host: str, k: int, table: Optional[Dict] = None) -> Optional[int]:
    """Host-native ``n`` for a canonical ``k`` (None when host has no proximity)."""
    semantics, _ = semantics_for(host, table)
    if semantics is None:
        return None
    return _n_from_semantics(semantics, k)


def canonical_k(host: str, n: int, table: Optional[Dict] = None) -> Optional[int]:
    """Inverse of :func:`host_n`: recover canonical ``k`` from a host-native ``n``.

    Lets two hosts' operators be compared for equivalence: ``adj2`` (ovid, gap+1)
    and ``N1`` (ebsco, gap) both map back to ``k == 1``.
    """
    semantics, _ = semantics_for(host, table)
    if semantics is None:
        return None
    return n - 1 if semantics == "gap_plus_one" else n


def equivalent(
    host_a: str, n_a: int, host_b: str, n_b: int, table: Optional[Dict] = None
) -> bool:
    """True when two hosts' proximity operands denote the same canonical gap.

    ``equivalent("ovid", 2, "ebsco", 1)`` is True (the Ovid adj2 ≡ EBSCO N1 pin).
    """
    ka = canonical_k(host_a, n_a, table)
    kb = canonical_k(host_b, n_b, table)
    return ka is not None and ka == kb


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

# Ordered-variant shell keys, tried in order when ``ordered=True``.
_ORDERED_KEYS = ("ordered", "ordered_prev", "ordered_aft", "ordered_adjacent")


def render(
    host: str,
    terms: List[str],
    k: int,
    *,
    field_code: Optional[str] = None,
    ordered: bool = False,
    table: Optional[Dict] = None,
) -> ProximityRender:
    """Render the canonical proximity intent ``k`` into ``host``'s native clause.

    ``terms``      the two (or more) operands, e.g. ["sleep", "therapy"].
    ``k``          canonical max_gap (words allowed *between* the terms).
    ``field_code`` field for phrase-shell hosts that embed one (PubMed ``tiab``);
                   defaults to the shell's first declared field.
    ``ordered``    prefer the ordered operator (PRE/NEXT/ONEAR/adj) when the shell
                   offers one; falls back to the unordered operator otherwise.

    For a no-proximity host returns ``supported=False`` + the table ``fallback``
    (never a fabricated operator).
    """
    if k < 0:
        raise ValueError(f"k (max_gap) must be >= 0, got {k}")
    norm = normalize_host(host)
    table = table if table is not None else load_table()
    semantics, in_family = semantics_for(norm, table)
    shell = _shell(norm, table)

    if semantics is None:
        fallback = shell.get("fallback")
        return ProximityRender(
            host=norm,
            k=k,
            n=None,
            semantics=None,
            in_family=False,
            supported=False,
            expression=None,
            operator=None,
            fallback=fallback,
            note=(
                f"{norm} has no proximity operator -> degrade to "
                f"{fallback or 'AND/phrase'}"
            ),
        )

    n = _n_from_semantics(semantics, k)

    template = None
    if ordered:
        for key in _ORDERED_KEYS:
            if shell.get(key):
                template = shell[key]
                break
    if template is None:
        template = shell["unordered"]

    rendered_op = template.replace("{n}", str(n))
    warnings: List[str] = []

    if "{terms}" in template:
        # Phrase-shell hosts (PubMed, CABI): operator is fused into a quoted phrase.
        joined = " ".join(terms)
        expression = rendered_op.replace("{terms}", joined)
        if "{field}" in expression:
            fld = field_code
            if fld is None:
                fields = shell.get("field") or []
                fld = fields[0] if fields else ""
            expression = expression.replace("{field}", fld)
        operator_token = None
    else:
        # Infix operator hosts: term1 <OP> term2.
        operator_token = rendered_op
        if len(terms) >= 2:
            expression = f"{terms[0]} {rendered_op} {terms[1]}"
            if len(terms) > 2:
                warnings.append(
                    "proximity operators are binary; only the first two terms "
                    "were joined"
                )
        elif len(terms) == 1:
            expression = f"{terms[0]} {rendered_op}"
        else:
            expression = rendered_op

    return ProximityRender(
        host=norm,
        k=k,
        n=n,
        semantics=semantics,
        in_family=in_family,
        supported=True,
        expression=expression,
        operator=operator_token,
        fallback=None,
        note="",
        warnings=warnings,
    )


__all__ = [
    "ProximityRender",
    "UnknownHostError",
    "NO_PROXIMITY_HOSTS",
    "load_table",
    "normalize_host",
    "semantics_for",
    "host_n",
    "canonical_k",
    "equivalent",
    "render",
]
