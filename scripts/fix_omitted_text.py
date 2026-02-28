import json

source_file = "data/quality/clause_edge_cases_batch_1.jsonl"
fixture_file = "data/fixtures/gold/v1/fixtures.jsonl"

source_texts = {}
with open(source_file, "r") as f:
    for line in f:
        data = json.loads(line)
        key = (data["doc_id"], data["section_number"])
        source_texts[key] = data["raw_text"]

fixed_records = []
with open(fixture_file, "r") as f:
    for line in f:
        record = json.loads(line)
        key = (record["source"]["doc_id"], record["source"]["section_number"])
        if key in source_texts:
            record["text"]["raw_text"] = source_texts[key]
        fixed_records.append(record)

with open(fixture_file, "w") as f:
    for record in fixed_records:
        f.write(json.dumps(record) + "\n")
print(f"Fixed {len(fixed_records)} records in {fixture_file}")
