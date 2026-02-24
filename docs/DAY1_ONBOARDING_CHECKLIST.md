# Day 1 Onboarding Checklist (Copy/Paste Runnable)

Use this as a first-day runbook for a new contributor.

## 0) Preconditions

- Repo path: `/Users/johnchtchekine/Projects/Agent`
- Python 3.12+ available
- Local source corpus available:
  - `/Users/johnchtchekine/Projects/TermIntelligence/data/credit_agreements`
  - `/Users/johnchtchekine/Projects/TermIntelligence/data/sidecar_metadata`

## 1) Move to Repo + Install

```bash
cd /Users/johnchtchekine/Projects/Agent
python3 -m pip install -e ".[dev]"
```

## 2) Quick Health Checks

```bash
python3 -m pytest -q tests/test_tools_30k.py
ruff check src/ scripts/ tests/
```

Expected:
- CLI help smoke tests pass
- no critical lint errors for edited files

## 3) Build a Full Local Corpus DB (from local files)

Create symlinked local corpus staging folder:

```bash
python3 - <<'PY'
from pathlib import Path
import shutil

src_docs = Path('/Users/johnchtchekine/Projects/TermIntelligence/data/credit_agreements')
src_meta = Path('/Users/johnchtchekine/Projects/TermIntelligence/data/sidecar_metadata')
root = Path('/tmp/agent_stage2_full_local')
corpus = root / 'corpus'
doc_dir = corpus / 'documents'
meta_dir = corpus / 'metadata'

if root.exists():
    shutil.rmtree(root)
doc_dir.mkdir(parents=True, exist_ok=True)
meta_dir.mkdir(parents=True, exist_ok=True)

for p in sorted(src_docs.iterdir()):
    if p.is_file() and p.suffix.lower() in {'.htm', '.html'}:
        (doc_dir / p.name).symlink_to(p)
for p in sorted(src_meta.iterdir()):
    if p.is_file() and p.name.endswith('.meta.json'):
        (meta_dir / p.name).symlink_to(p)

print(root)
PY
```

Build DuckDB:

```bash
PYTHONPATH=src python3 scripts/build_corpus_index.py \
  --corpus-dir /tmp/agent_stage2_full_local/corpus \
  --output /tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb \
  --workers 8 \
  --force \
  --verbose
```

Verify DB:

```bash
python3 - <<'PY'
import duckdb
db='/tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb'
con=duckdb.connect(db, read_only=True)
print('docs', con.execute('select count(*) from documents').fetchone()[0])
print('cohort', con.execute('select count(*) from documents where cohort_included=true').fetchone()[0])
print('sections', con.execute('select count(*) from sections').fetchone()[0])
print('clauses', con.execute('select count(*) from clauses').fetchone()[0])
PY
```

## 4) Setup Indebtedness Workspace

```bash
PYTHONPATH=src python3 scripts/setup_workspace.py \
  --family indebtedness \
  --expert-materials /Users/johnchtchekine/Projects/TermIntelligence/analysis/indebtedness \
  --ontology data/ontology/r36a_production_ontology_v2.5.1.json \
  --bootstrap data/bootstrap/bootstrap_all.json \
  --output workspaces/indebtedness
```

## 5) Classify Templates + Sample Gold Docs

```bash
PYTHONPATH=src:/tmp/agent_stage15_deps python3 scripts/template_classifier.py \
  --db /tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb \
  --cluster-method minhash \
  --eps 0.4 \
  --min-samples 2 \
  --lsh-threshold 0.2 \
  --output /tmp/agent_stage2_full_local/corpus_index/templates/classifications_full3411.json
```

```bash
mkdir -p workspaces/indebtedness/results
PYTHONPATH=src python3 scripts/sample_selector.py \
  --db /tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb \
  --n 50 \
  --stratify template_family \
  --seed 42 \
  --output workspaces/indebtedness/results/gold_docs.txt
```

## 6) Run Discovery Baseline

Structural map:

```bash
PYTHONPATH=src python3 scripts/structural_mapper.py \
  --db /tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb \
  --concept indebtedness \
  --heading-patterns "Indebtedness,Limitation on Indebtedness,Debt" \
  --keyword-anchors "incur,incurrence,Permitted Indebtedness,Disqualified Stock" \
  --sample 500 \
  > workspaces/indebtedness/results/structural_mapper_indebtedness_full3411.json
```

Heading discovery:

```bash
PYTHONPATH=src python3 scripts/heading_discoverer.py \
  --db /tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb \
  --seed-headings "Indebtedness,Limitation on Indebtedness,Debt" \
  --article-range 6-8 \
  --sample 500 \
  --with-canonical-summary \
  > workspaces/indebtedness/results/heading_discoverer_indebtedness_full3411.json
```

Create family-level seed strategy:

```bash
python3 - <<'PY'
import json
from pathlib import Path
boot = json.loads(Path('data/bootstrap/bootstrap_all.json').read_text())
rec = boot['debt_capacity.indebtedness.general_basket']
ss = rec['search_strategy']
strategy = {
  'concept_id': 'debt_capacity.indebtedness',
  'concept_name': 'Indebtedness',
  'family': 'indebtedness',
  'heading_patterns': ss.get('heading_patterns', []),
  'keyword_anchors': ss.get('keyword_anchors', []),
  'keyword_anchors_section_only': ss.get('keyword_anchors_in_section_only', []),
  'concept_specific_keywords': ss.get('concept_specific_keywords', []),
  'dna_tier1': [],
  'dna_tier2': [],
  'defined_term_dependencies': ss.get('defined_term_dependencies', []),
  'concept_notes': ss.get('concept_specific_notes', []),
  'fallback_escalation': ss.get('fallback_escalation'),
  'xref_follow': ss.get('xref_follow', []),
  'validation_status': 'bootstrap',
  'version': 1,
  'last_updated': '',
  'update_notes': ['seeded from bootstrap_all general_basket']
}
out = Path('workspaces/indebtedness/results/indebtedness_family_strategy_v0.json')
out.write_text(json.dumps(strategy, indent=2))
print(out)
PY
```

Pattern test + coverage:

```bash
PYTHONPATH=src python3 scripts/pattern_tester.py \
  --db /tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb \
  --strategy workspaces/indebtedness/results/indebtedness_family_strategy_v0.json \
  --sample 500 --verbose \
  > workspaces/indebtedness/results/pattern_tester_indebtedness_sample500_full3411.json

PYTHONPATH=src python3 scripts/coverage_reporter.py \
  --db /tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb \
  --strategy workspaces/indebtedness/results/indebtedness_family_strategy_v0.json \
  --group-by template_family \
  > workspaces/indebtedness/results/coverage_reporter_indebtedness_allcohort_full3411.json
```

## 7) Start Manual Labeling

Generate labeling starter file from sampled docs:

```bash
PYTHONPATH=src python3 scripts/pattern_tester.py \
  --db /tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb \
  --strategy workspaces/indebtedness/results/indebtedness_family_strategy_v0.json \
  --doc-ids workspaces/indebtedness/results/gold_docs.txt \
  --verbose \
  > workspaces/indebtedness/results/pattern_tester_indebtedness_gold50_full3411.json
```

```bash
python3 - <<'PY'
import json
from pathlib import Path
import duckdb

db = '/tmp/agent_stage2_full_local/corpus_index/full_3411.duckdb'
res = Path('workspaces/indebtedness/results')
doc_ids = [line.strip() for line in (res / 'gold_docs.txt').read_text().splitlines() if line.strip()]
pt = json.loads((res / 'pattern_tester_indebtedness_gold50_full3411.json').read_text())
matches = {m['doc_id']: m for m in pt.get('matches', [])}
con = duckdb.connect(db, read_only=True)
q = 'select doc_id, template_family from documents where doc_id in (' + ','.join(['?'] * len(doc_ids)) + ')'
tf = {row[0]: (row[1] if row[1] else 'unknown') for row in con.execute(q, doc_ids).fetchall()}

rows = []
for idx, doc_id in enumerate(doc_ids):
    m = matches.get(doc_id, {})
    rows.append({
        'doc_id': doc_id,
        'ontology_node_id': 'debt_capacity.indebtedness',
        'section_number': m.get('section', ''),
        'clause_path': '',
        'present': bool(m),
        'split': 'eval' if idx < 40 else 'holdout',
        'label_status': 'todo',
        'template_family': tf.get(doc_id, 'unknown'),
        'suggested_heading': m.get('heading', ''),
        'suggested_score': m.get('score', 0.0),
        'suggested_match_method': m.get('match_method', ''),
        'notes': '',
    })

(res / 'gold_set.jsonl').write_text(''.join(json.dumps(r, separators=(',', ':')) + '\\n' for r in rows))
print('wrote', len(rows), 'rows ->', res / 'gold_set.jsonl')
PY
```

## 8) Day 1 Done Criteria

- You can open and query the full local DuckDB.
- You can produce structural/heading/pattern/coverage outputs.
- `gold_set.jsonl` exists with 50 rows and `label_status=todo`.
- You can identify at least one template-level blind spot from coverage output.

## 9) If Something Fails

- DuckDB lock errors:
  - ensure no active writer process is still running.
- Strategy loading errors:
  - verify strategy JSON matches `src/agent/strategy.py` dataclass fields.
- Very low cluster quality:
  - rerun `template_classifier.py` with tuned MinHash params from above.
- High overall hit rate but some 0% clusters:
  - inspect parser health (`section_count`, `clause_count`) for those clusters.
