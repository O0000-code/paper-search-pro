# Setup: 5-key acquisition + config template

Referenced by `SKILL.md` setup check (before any tier runs). Total time: ~15 min. All keys are FREE.

## Quick status check

Run from **the user's current working directory** (do NOT `cd` into the skill directory — see `output_files.md` for why):

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro python3 -c "from scripts.config import load_config; c = load_config(); \
  print('openalex:', bool(c.openalex_api_key or c.openalex_email)); \
  print('semantic_scholar:', bool(c.semantic_scholar_api_key)); \
  print('ncbi:', bool(c.ncbi_email)); \
  print('crossref:', bool(c.crossref_email))"
```

Expected output (all True for full functionality):

```
openalex: True
semantic_scholar: True
ncbi: True
crossref: True
```

Minimum viable: `openalex` + `ncbi` (the only "required" pair for medical-capable usage). SS / CrossRef / arXiv are optional but recommended.

## Key 1 — OpenAlex (REQUIRED, L1 primary)

| | |
|---|---|
| Apply at | https://openalex.org/keys |
| Cost | Free, $1/day quota for non-premium polite-pool use |
| Time to issue | Instant (email confirmation only) |
| Fills | `openalex_email` (and optionally `openalex_api_key`) |
| Why required | L1 primary source. Without it, the whole pipeline halts. |

**Steps**:
1. Visit https://openalex.org/keys
2. Enter your email (used as polite-pool identifier)
3. Receive confirmation email → click activation link
4. Optionally generate API key for Premium quotas — email-only polite-pool works fine for our usage volume (~200 calls per Standard tier search)

**Verify**:
```bash
curl -s 'https://api.openalex.org/works?search=cancer&mailto=YOUR_EMAIL&per_page=2' | head -c 300
# Should return JSON starting with {"meta":{...
```

## Key 2 — Semantic Scholar (RECOMMENDED, L3)

| | |
|---|---|
| Apply at | https://www.semanticscholar.org/product/api |
| Cost | Free, no paid tier exists |
| Time to issue | ~1 week (manual email review) |
| Fills | `semantic_scholar_api_key` |
| Why recommended | Adds `influentialCitationCount` (unique signal) + abstract fallback |

**Steps**:
1. Visit https://www.semanticscholar.org/product/api
2. Click "Get API Key" → fill in name, email, organization, use case (describe paper-search-pro briefly)
3. Wait for approval email (typically 3-7 business days)
4. Copy the key into config

**Verify**:
```bash
curl -s 'https://api.semanticscholar.org/graph/v1/paper/DOI:10.1162/neco.1997.9.8.1735?fields=influentialCitationCount' \
  -H 'x-api-key: YOUR_KEY' | head -c 200
# Should return {"paperId":"...","influentialCitationCount":10359}
```

## Key 3 — PubMed / NCBI (REQUIRED for medical, L2)

| | |
|---|---|
| Apply at | https://account.ncbi.nlm.nih.gov/settings/ |
| Cost | Free |
| Time to issue | 5 min |
| Fills | `ncbi_email` (mandatory by ToS) + `ncbi_api_key` (boosts 3 → 10 req/s) |
| Why required | Medical queries; PubMed MeSH enrichment for SR workflow |

**Steps**:
1. Visit https://account.ncbi.nlm.nih.gov/settings/ → log in (Google / ORCID / new NCBI account)
2. Scroll to "API Key Management" section
3. Click "Create an API Key"
4. Copy the 36-char hex string into config
5. Add your email separately into `ncbi_email`

**Verify**:
```bash
curl -s 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=metformin&api_key=YOUR_KEY&retmax=2' | head -c 400
# Should return XML <eSearchResult> with <IdList>
```

## Key 4 — CrossRef (RECOMMENDED, L3)

| | |
|---|---|
| Apply at | (none — no key needed) |
| Cost | Free |
| Time to issue | Instant |
| Fills | `crossref_email` only |
| Why recommended | Adds funder/license/clinical-trial-number; polite pool 10/s × 3 conc |

**Steps**: Just put your email into `crossref_email` — CrossRef reads it from the User-Agent header for the polite pool (no API key, no signup). Anonymous access still works at 5/s × 1 conc, but you can easily double throughput by adding your email.

**Verify**:
```bash
curl -s -H 'User-Agent: paper-search-pro/2.0 (mailto:YOUR_EMAIL)' \
  'https://api.crossref.org/works/10.1056/NEJMoa2034577' | head -c 400
# Should return JSON {"status":"ok","message":{...}}
```

## Key 5 — arXiv (NO KEY)

| | |
|---|---|
| Apply at | (none) |
| Cost | Free |
| Required | Nothing |
| Why noted | Just to clarify — no signup needed, but rate limit is strict (1 req per 3 s) |

The arxiv helper enforces this automatically.

## Full config.yaml template

After collecting keys, write to `~/.paper-search-pro/config.yaml` (the helper auto-creates this from defaults on first run; you only need to edit it):

```yaml
# ============================================================================
# paper-search-pro config — fill your keys here
# ============================================================================

# --- OpenAlex (REQUIRED) ---
openalex_email: "you@example.com"
openalex_api_key: ""          # Optional Premium token

# --- Semantic Scholar (RECOMMENDED) ---
semantic_scholar_api_key: "abcdef1234567890..."

# --- PubMed / NCBI (REQUIRED for medical) ---
ncbi_email: "you@example.com"
ncbi_api_key: "0123456789abcdef..."

# --- CrossRef (RECOMMENDED) ---
crossref_email: "you@example.com"

# --- Output ---
output_dir: "./paper-search-results"
default_tier: "standard"      # quick | standard | deep | audit
language: "en"                # en | zh — affects messages, not data

# --- HTML rendering ---
# (No `html_renderer` choice as of 2026-05-23. The Skill always uses the
#  webartifacts Shadcn React bundle; the size-driven jinja2 fallback was
#  removed for UX consistency. No size cap.)

# --- Cache (auto-enabled, safe defaults) ---
cache_enabled: true
cache_ttl_days: 7
cache_max_size_mb: 500

# --- Logging ---
log_level: "INFO"
```

## Verification script

After editing config, run the full check **from the user's current working directory** (the `PYTHONPATH=` prefix lets `scripts.*` import without `cd`):

```bash
PYTHONPATH=~/.claude/skills/paper-search-pro python3 -c "
from scripts.config import load_config
c = load_config()
status = {
    'openalex_email':           bool(c.openalex_email),
    'openalex_api_key':         bool(c.openalex_api_key),
    'semantic_scholar_api_key': bool(c.semantic_scholar_api_key),
    'ncbi_email':               bool(c.ncbi_email),
    'ncbi_api_key':             bool(c.ncbi_api_key),
    'crossref_email':           bool(c.crossref_email),
}
for k, v in status.items():
    print(f'{k:30s} {\"OK\" if v else \"MISSING\"}')
all_ok = status['openalex_email'] or status['openalex_api_key']
all_ok = all_ok and status['ncbi_email']
print('\\nMINIMUM:', 'READY' if all_ok else 'NOT READY — fill openalex + ncbi')
"
```

## Common setup failures

| Failure | Cause | Fix |
|---|---|---|
| `config.yaml not found` | First run never happened | Run any helper once — config.py auto-creates from defaults |
| `yaml.YAMLError: while parsing` | Tabs / quotes in config | Use only spaces. Quote keys with special chars |
| `Permission denied: ~/.paper-search-pro/config.yaml` | Wrong file ownership | `chown $USER ~/.paper-search-pro/config.yaml` |
| `openalex_email empty after editing` | Config loaded but field name typo | Check key names — must be exact (e.g. `openalex_email` not `openalex-email`) |
| `NCBI 403 immediately` | API key not yet propagated | Wait 5 min after creation; NCBI propagation is not instant |
| `SS 429 from minute 1` | Key not associated with paid tier (none exists) | Expected — 1 RPS is hard cap; helper handles via sleep |

## Privacy note

`ncbi_email`, `openalex_email`, and `crossref_email` are sent in HTTP headers — these services log the email per request for rate-limit attribution. Don't use a high-value primary email; use a tagged variant if your provider supports it (e.g. `you+pspro@gmail.com`).

## Security: config file permissions

`~/.paper-search-pro/config.yaml` holds real API keys and **must be mode 0600** (owner read/write only). `config.py` enforces this automatically:

- On first run, the file is created from defaults with 0600.
- On every `load_config()` call, the existing file is re-chmoded to 0600 if it has loosened (e.g. after a `chmod 644` or a backup-tool restore). A stderr warning is printed when this happens so you know the tightening occurred.

You can audit the current mode yourself:

```bash
stat -f %p ~/.paper-search-pro/config.yaml    # macOS — expect 100600
stat -c %a ~/.paper-search-pro/config.yaml    # Linux — expect 600
```

If the file ever shows `0644` (world-readable), other users on the same machine can read your API keys. Re-run any paper-search-pro helper once and the auto-chmod will restore 0600; or run `chmod 600 ~/.paper-search-pro/config.yaml` manually.

**Windows note**: `os.chmod` is a no-op on most Windows filesystems. The auto-chmod silently skips in that case — protect the file via NTFS ACLs or the Windows "Properties → Security" tab instead.
