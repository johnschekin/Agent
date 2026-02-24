# Architecture Diagram (One Page)

This is a visual-first view of how the system works.

## 1) End-to-End Pipeline

```text
┌───────────────────────────────────────────────────────────────────────────┐
│                           Source Data Layer                              │
│  S3/local corpus                                                         │
│  - documents/*.htm                                                       │
│  - metadata/*.meta.json                                                  │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
                                v
┌───────────────────────────────────────────────────────────────────────────┐
│                        Ingestion + Parsing Layer                          │
│  scripts/build_corpus_index.py / scripts/build_corpus_ray.py             │
│  - normalize HTML                                                        │
│  - parse sections                                                        │
│  - parse clause tree                                                     │
│  - extract definitions                                                   │
│  - extract metadata                                                      │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
                                v
┌───────────────────────────────────────────────────────────────────────────┐
│                            Corpus Index Layer                             │
│  DuckDB (single source of truth for discovery tools)                     │
│  - documents                                                             │
│  - sections                                                              │
│  - clauses                                                               │
│  - definitions                                                           │
│  - section_text                                                          │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
                                v
┌───────────────────────────────────────────────────────────────────────────┐
│                        Discovery + Evaluation Layer                       │
│  Tools (scripts/*.py)                                                    │
│  - heading_discoverer, structural_mapper, dna_discoverer                 │
│  - pattern_tester, coverage_reporter                                     │
│  - child_locator, definition_finder                                      │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
                                v
┌───────────────────────────────────────────────────────────────────────────┐
│                     Strategy + Evidence Workspace Layer                   │
│  workspaces/{family}/                                                    │
│  - strategies/*.json                                                     │
│  - evidence/*.jsonl                                                      │
│  - results/*.json                                                        │
│  - gold_set.jsonl                                                        │
└───────────────────────────────┬───────────────────────────────────────────┘
                                │
                                v
┌───────────────────────────────────────────────────────────────────────────┐
│                           Ontology Link Layer                             │
│  data/ontology/r36a_production_ontology_v2.5.1.json                      │
│  - 6 domains -> 49 families -> 3,538 nodes                               │
│  Final output: ontology_node_id -> clause (+ provenance)                 │
└───────────────────────────────────────────────────────────────────────────┘
```

## 2) Ontology Discovery Loop

```text
Pick Family -> Bootstrap Strategy -> Discover Signals -> Test Coverage
     ^                                                    |
     |                                                    v
Persist Strategy <---- Analyze Misses <---- Template/Cluster Gaps
```

Signals used:
- headings
- keyword anchors
- DNA phrases
- structural priors (article/section)

## 3) Runtime Modes

```text
Local mode:
  build_corpus_index.py
  Good for: fast iteration, parser debugging, pilot loops

Distributed mode (Ray):
  build_corpus_ray.py
  Good for: full-corpus scale, checkpoint/resume, S3-native execution
```

## 4) Data Contracts

Core IDs:
- `doc_id`: content-addressed document ID
- `ontology_node_id`: canonical ontology key
- `section_number`: section identity within document
- `clause_id` / `clause_path`: clause identity in tree

Quality expectations:
- global hit rate is not enough
- coverage must be checked by `template_family`
- strategy/evidence rows must always use valid ontology IDs

## 5) Where Beginners Start

1. Read `docs/BEGINNER_GUIDE.md`.
2. Run `docs/DAY1_ONBOARDING_CHECKLIST.md`.
3. Use `plans/pilot_protocol.md` for full pilot sequencing.
4. Use `docs/ARCHITECTURE.md` for deeper technical context.
