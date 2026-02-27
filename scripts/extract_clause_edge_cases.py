#!/usr/bin/env python3
import duckdb
import json
from pathlib import Path

def main():
    db_path = Path("corpus_index/corpus.duckdb")
    out_path = Path("data/quality/clause_edge_cases_batch_1.jsonl")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Connecting to {db_path}...")
    conn = duckdb.connect(str(db_path), read_only=True)

    query_edge_sections = r"""
    SELECT DISTINCT doc_id, section_number
    FROM clauses
    WHERE 
        (clause_id LIKE '%\_dup%' ESCAPE '\')
        OR (clause_id LIKE '%.x' OR clause_id LIKE '%.y' OR clause_id LIKE '%.z' OR clause_id IN ('x', 'y', 'z'))
        OR (parse_confidence < 0.6 AND parse_confidence > 0.0)
    LIMIT 100
    """
    
    edge_sections = conn.execute(query_edge_sections).fetchall()
    print(f"Found {len(edge_sections)} edge case sections. Extracting full trees...")

    results = []
    for doc_id, sec_num in edge_sections:
        text_row = conn.execute(
            "SELECT text FROM section_text WHERE doc_id = ? AND section_number = ?", 
            [doc_id, sec_num]
        ).fetchone()
        raw_text = text_row[0] if text_row else ""
        
        clauses = conn.execute(
            """
            SELECT clause_id, label, parent_id, depth, is_structural, parse_confidence, span_start, span_end
            FROM clauses 
            WHERE doc_id = ? AND section_number = ?
            ORDER BY span_start
            """, 
            [doc_id, sec_num]
        ).fetchall()
        
        tree = []
        for c in clauses:
            c_id, lbl, p_id, depth, is_struct, conf, start, end = c
            snippet = raw_text[start:end] if raw_text and start is not None and end is not None else ""
            tree.append({
                "path": c_id,
                "label": lbl,
                "parent_id": p_id,
                "depth": depth,
                "is_structural": is_struct,
                "parse_confidence": conf,
                "text_snippet": snippet[:100] + "..." if len(snippet) > 100 else snippet
            })
            
        results.append({
            "doc_id": doc_id,
            "section_number": sec_num,
            "raw_text": raw_text,
            "current_tree": tree
        })

    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r) + "\n")

    print(f"Successfully extracted {len(results)} edge cases to {out_path}")

if __name__ == "__main__":
    main()
