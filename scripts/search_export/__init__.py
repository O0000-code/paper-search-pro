"""Search-strategy-export mechanical layer (v2.4 STEP 11.5).

Modules:
- proximity.py     canonical max_gap -> per-host proximity n + operator-shell render
                   (reads proximity_table.json; degrades honestly on no-proximity hosts)
- linter.py        deterministic search-string checks L1-L11 (reads syntax cards +
                   proximity table as data; flags only mechanically decidable defects)
- deeplink.py      A-tier clickable deep-link constructor (+ optional live verify)
- vocab_verify.py  controlled-vocabulary existence verification (MeSH/ERIC free API;
                   Emtree/CINAHL/APA -> pending manual; CMeSH -> optional soft cross-check)
- generate.py      STEP 11.5 generator (layer 2/3 orchestrator): platform-independent
                   concept_model -> per-host search_strategies.md + search_strategies.json
                   (card-driven render + vocab verify + deep link + linter gate)
"""
