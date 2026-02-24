#!/usr/bin/env python3
"""Read a specific section with optional definition unrolling and clause tree.

Lists sections for a document, or reads a specific section with full text,
clause tree structure, and auto-unrolled definitions.

Usage:
    # List all sections for a document
    python3 scripts/section_reader.py --db corpus_index/corpus.duckdb --doc-id abc123

    # Read a specific section with auto-unrolled definitions
    python3 scripts/section_reader.py --db corpus_index/corpus.duckdb \
      --doc-id abc123 --section "7.01" --auto-unroll

    # Show all sections in article 7
    python3 scripts/section_reader.py --db corpus_index/corpus.duckdb \
      --doc-id abc123 --article 7
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import orjson

    def dump_json(obj: object) -> None:
        sys.stdout.buffer.write(orjson.dumps(obj, option=orjson.OPT_INDENT_2))
        sys.stdout.buffer.write(b"\n")
except ImportError:

    def dump_json(obj: object) -> None:
        json.dump(obj, sys.stdout, indent=2, default=str)
        print()


from agent.corpus import ClauseRecord, CorpusIndex


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read a specific section with optional definition unrolling."
    )
    parser.add_argument(
        "--db", required=True, type=Path, help="Path to corpus.duckdb"
    )
    parser.add_argument("--doc-id", required=True, help="Document ID")
    parser.add_argument(
        "--section",
        default=None,
        help="Section number (e.g., '7.01'). If omitted, list all sections.",
    )
    parser.add_argument(
        "--article",
        type=int,
        default=None,
        help="Article number. If given without --section, show all sections in that article.",
    )
    parser.add_argument(
        "--auto-unroll",
        action="store_true",
        help="Find capitalized terms matching known definitions and append their texts.",
    )
    parser.add_argument(
        "--clauses",
        action="store_true",
        help="Include clause tree structure in output.",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-cohort documents (default is cohort-only).",
    )
    return parser


# Pattern for capitalized multi-word terms (e.g., "Permitted Indebtedness",
# "Administrative Agent"). Matches sequences of 1+ capitalized words.
_CAPITALIZED_TERM_RE = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b")


def _build_clause_tree(clauses: list[ClauseRecord]) -> list[dict[str, object]]:
    """Build a tree structure from flat clause records.

    Returns a list of clause dicts with nested 'children' lists containing
    child clause IDs.
    """
    # Index clauses by ID
    clause_map: dict[str, ClauseRecord] = {c.clause_id: c for c in clauses}
    children_map: dict[str, list[str]] = {}

    for c in clauses:
        if c.parent_id and c.parent_id in clause_map:
            children_map.setdefault(c.parent_id, []).append(c.clause_id)

    tree: list[dict[str, object]] = []
    for c in clauses:
        node: dict[str, object] = {
            "id": c.clause_id,
            "label": c.label,
            "depth": c.depth,
            "header_text": c.header_text,
            "children": children_map.get(c.clause_id, []),
        }
        tree.append(node)

    return tree


def _find_capitalized_terms(text: str) -> set[str]:
    """Extract candidate defined terms from section text.

    Finds capitalized multi-word terms that are likely references to
    defined terms in the agreement.
    """
    matches = _CAPITALIZED_TERM_RE.findall(text)
    # Filter out very short or common words that are unlikely defined terms
    skip = {
        "The", "This", "That", "Each", "Any", "All", "Such", "No", "Not",
        "For", "From", "With", "Without", "Under", "Upon", "Into", "After",
        "Before", "Between", "During", "Except", "Until", "Unless", "Whether",
        "Article", "Section", "Subsection", "Paragraph", "Clause",
    }
    return {m for m in matches if m not in skip and len(m) > 2}


def main() -> None:
    args = build_parser().parse_args()

    if not args.db.exists():
        print(f"Error: database not found: {args.db}", file=sys.stderr)
        sys.exit(1)

    with CorpusIndex(args.db) as corpus:
        # Verify document exists
        doc = corpus.get_doc(args.doc_id)
        if doc is None:
            print(f"Error: document not found: {args.doc_id}", file=sys.stderr)
            sys.exit(1)
        if not args.include_all and not doc.cohort_included:
            print(
                f"Error: document {args.doc_id} is excluded from cohort; use --include-all to inspect",
                file=sys.stderr,
            )
            sys.exit(1)

        if args.section is None:
            # List mode: show all sections (optionally filtered by article)
            sections = corpus.search_sections(
                doc_id=args.doc_id,
                article_num=args.article,
                cohort_only=not args.include_all,
                limit=1000,
            )

            result = [
                {
                    "section_number": s.section_number,
                    "heading": s.heading,
                    "article_num": s.article_num,
                    "word_count": s.word_count,
                }
                for s in sections
            ]

            print(
                f"Found {len(result)} sections for doc {args.doc_id}"
                + (f" (article {args.article})" if args.article else ""),
                file=sys.stderr,
            )
            dump_json(result)
        else:
            # Section detail mode
            # Find the section record
            sections = corpus.search_sections(
                doc_id=args.doc_id,
                cohort_only=not args.include_all,
                limit=1000,
            )
            section_rec = None
            for s in sections:
                if s.section_number == args.section:
                    section_rec = s
                    break

            if section_rec is None:
                print(
                    f"Error: section {args.section} not found in doc {args.doc_id}",
                    file=sys.stderr,
                )
                sys.exit(1)

            # Get section text
            text = corpus.get_section_text(args.doc_id, args.section)
            if text is None:
                print(
                    f"Error: text not found for section {args.section} in doc {args.doc_id}",
                    file=sys.stderr,
                )
                sys.exit(1)

            result_dict: dict[str, object] = {
                "doc_id": args.doc_id,
                "section_number": section_rec.section_number,
                "heading": section_rec.heading,
                "article_num": section_rec.article_num,
                "char_start": section_rec.char_start,
                "char_end": section_rec.char_end,
                "word_count": section_rec.word_count,
                "text": text,
            }

            # Clause tree
            if args.clauses:
                clause_records = corpus.get_clauses(args.doc_id, args.section)
                result_dict["clause_tree"] = _build_clause_tree(clause_records)
                print(
                    f"Included {len(clause_records)} clauses",
                    file=sys.stderr,
                )
            else:
                result_dict["clause_tree"] = None

            # Auto-unroll definitions
            if args.auto_unroll:
                candidate_terms = _find_capitalized_terms(text)
                definitions = corpus.get_definitions(args.doc_id)

                # Build a lookup by term (case-insensitive)
                def_by_term: dict[str, dict[str, str]] = {}
                for d in definitions:
                    def_by_term[d.term.lower()] = {
                        "term": d.term,
                        "text": d.definition_text,
                    }

                unrolled: list[dict[str, str]] = []
                seen: set[str] = set()
                for term in sorted(candidate_terms):
                    key = term.lower()
                    if key in def_by_term and key not in seen:
                        seen.add(key)
                        entry = def_by_term[key]
                        # Find which section the definition comes from
                        unrolled.append({
                            "term": entry["term"],
                            "text": entry["text"],
                        })

                result_dict["unrolled_definitions"] = unrolled
                print(
                    f"Unrolled {len(unrolled)} definitions from "
                    f"{len(candidate_terms)} candidate terms",
                    file=sys.stderr,
                )
            else:
                result_dict["unrolled_definitions"] = None

            print(
                f"Section {args.section} ({section_rec.heading}): "
                f"{section_rec.word_count} words",
                file=sys.stderr,
            )
            dump_json(result_dict)


if __name__ == "__main__":
    main()
