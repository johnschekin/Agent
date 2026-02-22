# CLAUDE.md — Agent (Pattern Discovery Swarm)

## Overview

Pattern discovery platform for credit agreement ontology linking. Agents iteratively
discover patterns (heading, keyword, DNA phrase, structural position) that locate
ontology concepts in leveraged finance credit agreements.

## Commands

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
ruff check src/ tests/ scripts/
pyright src/
```

## Conventions

- Python >=3.12, type hints everywhere
- Use `python3` not `python`
- `orjson` for JSON (not stdlib json)
- All contracts: `@dataclass(frozen=True, slots=True)`
- pyright strict mode, zero errors
- DuckDB corpus index is immutable per run (read-only in CLI tools)
- All char offsets reference normalized text (global, never section-relative)
- Strategy versions are monotonically numbered per concept

## Architecture

- `src/agent/` — Core library (textmatch, html, parsing, corpus, strategy)
- `scripts/` — CLI tools (agent-callable, structured JSON output to stdout)
- `data/` — Ontology + bootstrap strategies (checked in)
- `corpus/` — S3-synced documents (gitignored)
- `corpus_index/` — DuckDB databases (gitignored)
- `workspaces/` — Per-family agent working directories (gitignored)

## Rules

1. NEVER fabricate domain content from training knowledge. All patterns must trace to corpus evidence.
2. All char offsets are GLOBAL (in normalized text), never section-relative.
3. DuckDB files are opened read-only by CLI tools. Only build_corpus_index.py writes.
4. CLI tools output structured JSON to stdout. Human-readable messages go to stderr.
5. Strategy versions are immutable once written. New versions create new files.
6. Evidence must include (doc_id, char_start, char_end) as canonical coordinates.

## Plans

- Final target vision: `plans/final_target_vision.md`
- Current MVP: `plans/mvp_phase_a.md`
