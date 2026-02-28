import json
import sys
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", required=True, help="Path to JSON file containing the record to append")
    parser.add_argument("--source", default="data/quality/clause_edge_cases_batch_1.jsonl")
    parser.add_argument("--dest", default="data/fixtures/gold/v1/fixtures.jsonl")
    args = parser.parse_args()

    with open(args.record, "r") as f:
        record = json.load(f)

    doc_id = record["source"]["doc_id"]
    section_number = record["source"]["section_number"]

    # Find raw text in source
    raw_text = None
    with open(args.source, "r") as f:
        for line in f:
            data = json.loads(line)
            if data["doc_id"] == doc_id and data["section_number"] == section_number:
                raw_text = data["raw_text"]
                break
    
    if raw_text is None:
        print(f"Error: Could not find doc_id={doc_id}, section={section_number} in {args.source}")
        sys.exit(1)
        
    record["text"]["raw_text"] = raw_text

    with open(args.dest, "a") as f:
        f.write(json.dumps(record) + "\n")
        
    print(f"Appended fixture for {doc_id} {section_number} to {args.dest}")

if __name__ == "__main__":
    main()
