#!/usr/bin/env bash
set -euo pipefail

OPENAI_API_KEY="${OPENAI_API_KEY:-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}"

if [[ -z "$OPENAI_API_KEY" ]]; then
  echo "OPENAI_API_KEY is not set"
  exit 1
fi

OUT_DIR="${1:-/Users/johnchtchekine/Projects/Agent/artifacts/openai_batches/trainstart_b1_120_qsafe_32k_rerun1}"
WINDOW="${2:-24h}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required but not found"
  exit 1
fi

shopt -s nullglob
request_files=("$OUT_DIR"/openai_batch_requests_*.jsonl)
if [[ ${#request_files[@]} -eq 0 ]]; then
  echo "No openai_batch_requests_*.jsonl files found under $OUT_DIR"
  exit 1
fi

for request_file in "${request_files[@]}"; do
  base="$(basename "$request_file" .jsonl)"
  upload_json="$OUT_DIR/${base}.file.json"
  batch_json="$OUT_DIR/${base}.batch.json"

  echo "Uploading: $request_file"
  curl -sS https://api.openai.com/v1/files \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -F purpose="batch" \
    -F file="@${request_file}" > "$upload_json"

  file_id="$(jq -r '.id // empty' "$upload_json")"
  if [[ -z "$file_id" ]]; then
    echo "Failed to obtain file_id from $upload_json"
    cat "$upload_json"
    exit 1
  fi

  payload="$(jq -n \
    --arg input_file_id "$file_id" \
    --arg completion_window "$WINDOW" \
    --arg request_file "$(basename "$request_file")" \
    '{input_file_id:$input_file_id, endpoint:"/v1/chat/completions", completion_window:$completion_window, metadata:{job:"gold-fixture-adjudication", request_file:$request_file}}')"

  curl -sS https://api.openai.com/v1/batches \
    -H "Authorization: Bearer $OPENAI_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$payload" > "$batch_json"

  batch_id="$(jq -r '.id // empty' "$batch_json")"
  if [[ -z "$batch_id" ]]; then
    echo "Failed to obtain batch_id from $batch_json"
    cat "$batch_json"
    exit 1
  fi
  echo "Created batch: $batch_id for $(basename "$request_file")"
done
