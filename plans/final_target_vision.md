# Final Target Vision: Pattern Discovery Swarm for Credit Agreement Ontology Linking

**Status**: Target architecture. Implement incrementally via phased MVPs.

## Context

We have a 3,538-node leveraged finance ontology (49 families) and 30,000+ credit agreements.
The goal: discover reliable patterns (heading, keyword, DNA phrase, structural position) for each
node that can locate it across thousands of CAs — producing labeled data (node-to-clause mappings)
without per-doc LLM calls.

**Approach**: Agent-driven discovery — one Claude Code agent per concept family, running in tmux,
using a suite of CLI tools to iteratively hypothesize/test/refine patterns against the corpus.

**Pilot**: Indebtedness family — two levels deep (family → children → grandchildren).
Richest expert materials, 13+ structural components.

**New repo**: `/Users/johnchtchekine/Projects/Agent`

### Corpus Location

**S3 Bucket**: `s3://edgar-pipeline-documents-216213517387/` (us-east-1)

```
edgar-pipeline-documents-216213517387/
├── documents/                    # HTML credit agreements
│   ├── cik=0000001750/          # Partitioned by EDGAR CIK (company)
│   │   ├── {accession}_{exhibit}.htm    (500KB–1.8MB each)
│   │   └── ...
│   └── ... (999+ CIK folders)
└── metadata/                    # Per-document metadata JSON
    ├── cik=0000001750/
    │   ├── {accession}.meta.json        (~450 bytes each)
    │   └── ...
    └── ...
```

### Full Architecture

```
Agent/
├── pyproject.toml
├── CLAUDE.md
├── src/agent/
│   ├── textmatch.py            # Port from VP infra/textmatch.py
│   ├── html_utils.py           # VP normalize + TI encoding fallback
│   ├── corpus.py               # DuckDB-backed corpus index
│   ├── section_parser.py       # Hybrid VP+TI section extraction
│   ├── clause_parser.py        # VP clause_tree AST
│   ├── dna.py                  # TF-IDF + log-odds discovery
│   ├── definitions.py          # TI 5-engine definition extractor
│   ├── metadata.py             # TI borrower/agent/facility extraction
│   └── strategy.py             # Strategy dataclass + versioned persistence
├── scripts/                    # CLI tools (16 total)
│   ├── corpus_search.py
│   ├── section_reader.py
│   ├── pattern_tester.py
│   ├── coverage_reporter.py
│   ├── heading_discoverer.py
│   ├── dna_discoverer.py
│   ├── definition_finder.py
│   ├── child_locator.py
│   ├── evidence_collector.py
│   ├── strategy_writer.py
│   ├── llm_judge.py
│   ├── metadata_reader.py
│   ├── template_classifier.py
│   ├── sample_selector.py
│   ├── structural_mapper.py
│   └── setup_workspace.py
├── dashboard/                  # Streamlit review dashboard (5 views)
├── swarm/                      # Tmux orchestration
├── workspaces/                 # Per-family agent workspaces
├── corpus_index/               # DuckDB corpus data
├── tests/
└── data/                       # Ontology + bootstrap strategies
```

### Target Phases (post-MVP)

- **Phase B**: Template classifier + regression gates + deterministic metrics + gold set
- **Phase C**: Swarm orchestration (tmux scripts, 49-agent scale)
- **Phase D**: Streamlit review dashboard (5 views)
- **Phase E**: Full 30K ingestion via Ray cluster

### All Resolved Decisions

1. Corpus: S3 `s3://edgar-pipeline-documents-216213517387/`, CIK-partitioned
2. Ingestion: Staged (500 → 5K → 30K), not all-at-once
3. Template discovery: Statistical clustering (from TI), user labels clusters
4. Pilot scope: Indebtedness, two levels deep
5. Ray compute: AWS Ray cluster (transient, spot instances) for Phase E
6. DuckDB: Immutable per run; one writer produces versioned snapshots; all tools read-only
7. LLM judge: Advisory during iteration, blocking only at release checkpoints
8. Regression: Non-regression on fixed regression set with confidence bounds
9. Schema versioning: Schema version table + migration scripts
10. VP vs TI parsing: HTML: VP; Sections: Hybrid VP+TI; Definitions: TI; Metadata: TI; Clauses: VP
11. Strategy format: Rich multi-tier schema with corpus metrics + template overrides
12. Swarm safety: Constrained working dirs, read-only corpus mount, command logging
13. Gold set: Fixed stratified human-labeled ground truth before tuning
