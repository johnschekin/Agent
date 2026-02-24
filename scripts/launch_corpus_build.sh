#!/usr/bin/env bash
# launch_corpus_build.sh — Provision a c7i.metal-48xl, run the Parquet-sharded
# corpus build pipeline with early-exit classification, upload results to S3,
# and tear down.
#
# Usage:
#   ./scripts/launch_corpus_build.sh            # Full build (34K docs)
#   ./scripts/launch_corpus_build.sh --limit 100  # Test with 100 docs
#   ./scripts/launch_corpus_build.sh --dry-run  # Print commands, don't execute
#
# Prerequisites:
#   - AWS CLI configured with credentials (us-east-1)
#   - SSH key at ~/.ssh/ray-corpus.pem
#   - Security group sg-0aab12f9d2be6bc59 (ray-autoscaler-corpus-build)
#   - IAM instance profile ray-corpus-head
#
# Total cost: ~$0.50 for a full 34K doc build (~6 min on c7i.24xlarge at $4.03/hr)
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
INSTANCE_TYPE="c7i.24xlarge"  # 96 vCPU, 192 GB RAM — $4.03/hr (128 vCPU account limit)
AMI_ID="ami-0071174ad8cbb9e17"  # Ubuntu 24.04 (Python 3.12), 2026-02-18
KEY_NAME="ray-corpus"
SSH_KEY="$HOME/.ssh/ray-corpus.pem"
SECURITY_GROUP="sg-0aab12f9d2be6bc59"
SUBNET="subnet-0f12bfebe707cdb13"
IAM_PROFILE="ray-corpus-head"
REGION="us-east-1"

BUCKET="edgar-pipeline-documents-216213517387"
S3_UPLOAD="s3://${BUCKET}/corpus_index/corpus.duckdb"
REMOTE_OUTPUT="/home/ubuntu/corpus_index/corpus.duckdb"

# Parse arguments
DOC_LIMIT=""
DRY_RUN=false
for arg in "$@"; do
    case "$arg" in
        --limit)  shift; DOC_LIMIT="--limit $1"; shift ;;
        --limit=*) DOC_LIMIT="--limit ${arg#*=}" ;;
        --dry-run) DRY_RUN=true ;;
    esac
done

# ---------------------------------------------------------------------------
# User-data script (runs on the instance at boot)
# ---------------------------------------------------------------------------
read -r -d '' USERDATA_SCRIPT << 'USERDATA_EOF' || true
#!/bin/bash
set -euxo pipefail
exec > /var/log/corpus-build.log 2>&1

echo "=== Corpus build starting at $(date -u) ==="

# System setup
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3.12 python3.12-venv python3-pip git awscli

# Create workspace
mkdir -p /home/ubuntu/corpus_index
cd /home/ubuntu

# Clone the project (we'll sync files via SCP instead for speed)
# The launch script will SCP the project after SSH is available

echo "=== System setup complete at $(date -u) ==="
USERDATA_EOF

# ---------------------------------------------------------------------------
# Build setup script that runs AFTER project files are synced
# ---------------------------------------------------------------------------
read -r -d '' SETUP_SCRIPT << 'SETUP_EOF' || true
#!/bin/bash
set -euxo pipefail
exec > /home/ubuntu/corpus-build-run.log 2>&1

echo "=== Waiting for cloud-init to finish at $(date -u) ==="
cloud-init status --wait || true

echo "=== Installing system packages at $(date -u) ==="
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq python3-pip python3-venv python3-dev

cd /home/ubuntu/agent-project

echo "=== Creating venv + installing Python dependencies at $(date -u) ==="
python3 -m venv /home/ubuntu/venv
source /home/ubuntu/venv/bin/activate
pip install --upgrade pip --quiet
pip install -e ".[ray]" --quiet
pip install pyarrow tqdm --quiet

echo "=== Dependencies installed at $(date -u) ==="
python3 -c "import ray; import duckdb; import pyarrow; print('All imports OK')"

echo "=== Starting corpus build at $(date -u) ==="
python3 scripts/build_corpus_ray_v2.py \
    --bucket BUCKET_PLACEHOLDER \
    --output /home/ubuntu/corpus_index/corpus.duckdb \
    --s3-upload S3_UPLOAD_PLACEHOLDER \
    --local --force -v \
    LIMIT_PLACEHOLDER

echo "=== Corpus build finished at $(date -u) ==="

# Signal completion
touch /home/ubuntu/BUILD_COMPLETE
SETUP_EOF

# Substitute placeholders
SETUP_SCRIPT="${SETUP_SCRIPT//BUCKET_PLACEHOLDER/$BUCKET}"
SETUP_SCRIPT="${SETUP_SCRIPT//S3_UPLOAD_PLACEHOLDER/$S3_UPLOAD}"
SETUP_SCRIPT="${SETUP_SCRIPT//LIMIT_PLACEHOLDER/$DOC_LIMIT}"

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
log() { echo "[$(date '+%H:%M:%S')] $*"; }

ssh_cmd() {
    ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
        -i "$SSH_KEY" "ubuntu@$1" "$2"
}

wait_for_ssh() {
    local ip="$1"
    local max_wait=300
    local waited=0
    log "Waiting for SSH on $ip ..."
    while ! ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 \
                -i "$SSH_KEY" "ubuntu@$ip" "echo ok" &>/dev/null; do
        sleep 10
        waited=$((waited + 10))
        if [ "$waited" -ge "$max_wait" ]; then
            log "ERROR: SSH not available after ${max_wait}s"
            return 1
        fi
        log "  ... waiting ($waited/${max_wait}s)"
    done
    log "SSH available on $ip"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
log "=== Corpus Build Launcher (c7i.24xlarge) ==="
log "Instance type: $INSTANCE_TYPE"
log "Doc limit: ${DOC_LIMIT:-none (full build)}"

if $DRY_RUN; then
    log "[DRY RUN] Would launch $INSTANCE_TYPE with AMI $AMI_ID"
    log "[DRY RUN] Would sync project and run build_corpus_ray_v2.py"
    exit 0
fi

# Step 1: Launch EC2 instance
log "Launching $INSTANCE_TYPE instance ..."
INSTANCE_ID=$(aws ec2 run-instances \
    --image-id "$AMI_ID" \
    --instance-type "$INSTANCE_TYPE" \
    --key-name "$KEY_NAME" \
    --security-group-ids "$SECURITY_GROUP" \
    --subnet-id "$SUBNET" \
    --iam-instance-profile Name="$IAM_PROFILE" \
    --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":200,"VolumeType":"gp3","Iops":10000,"Throughput":700}}]' \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=corpus-build-v3-c7i}]" \
    --user-data "$USERDATA_SCRIPT" \
    --region "$REGION" \
    --query 'Instances[0].InstanceId' \
    --output text)

log "Instance launched: $INSTANCE_ID"

# Step 2: Wait for running + get public IP
log "Waiting for instance to be running ..."
aws ec2 wait instance-running --instance-ids "$INSTANCE_ID" --region "$REGION"

PUBLIC_IP=$(aws ec2 describe-instances \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' \
    --output text)

log "Instance running at $PUBLIC_IP"

# Cleanup trap: terminate on script exit/error
cleanup() {
    if [ -n "${INSTANCE_ID:-}" ]; then
        log "Terminating instance $INSTANCE_ID ..."
        aws ec2 terminate-instances --instance-ids "$INSTANCE_ID" --region "$REGION" &>/dev/null || true
        log "Terminate request sent."
    fi
}
trap cleanup EXIT

# Step 3: Wait for SSH
wait_for_ssh "$PUBLIC_IP"

# Step 4: Sync project files
log "Syncing project files to instance ..."
rsync -az --progress \
    -e "ssh -o StrictHostKeyChecking=no -i $SSH_KEY" \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'corpus_index/' \
    --exclude '.mypy_cache' \
    --exclude '.ruff_cache' \
    --exclude 'node_modules/' \
    --exclude 'dashboard/' \
    --exclude '.next/' \
    "$(cd /Users/johnchtchekine/Projects/Agent && pwd)/" \
    "ubuntu@${PUBLIC_IP}:/home/ubuntu/agent-project/"

log "Project synced."

# Step 5: Upload and run the build script
log "Starting corpus build on instance ..."
echo "$SETUP_SCRIPT" | ssh -o StrictHostKeyChecking=no -i "$SSH_KEY" \
    "ubuntu@${PUBLIC_IP}" "cat > /home/ubuntu/run_build.sh && chmod +x /home/ubuntu/run_build.sh"

# Run in background with nohup so it survives SSH disconnect
ssh_cmd "$PUBLIC_IP" "nohup bash /home/ubuntu/run_build.sh </dev/null >/dev/null 2>&1 &"
sleep 3  # Let the process start before polling

# Step 6: Monitor progress
log "Build running. Monitoring progress ..."
log "  SSH: ssh -i $SSH_KEY ubuntu@$PUBLIC_IP"
log "  Logs: ssh -i $SSH_KEY ubuntu@$PUBLIC_IP tail -f /home/ubuntu/corpus-build-run.log"
log ""

# Poll until BUILD_COMPLETE exists or failure
POLL_INTERVAL=30
MAX_WAIT=1800  # 30 minutes max (build should finish in ~5 min)
WAITED=0
while true; do
    sleep "$POLL_INTERVAL"
    WAITED=$((WAITED + POLL_INTERVAL))

    # Check if build completed
    if ssh_cmd "$PUBLIC_IP" "test -f /home/ubuntu/BUILD_COMPLETE" 2>/dev/null; then
        log "Build completed successfully!"
        break
    fi

    # Check if still running (run_build.sh or build_corpus_ray)
    if ! ssh_cmd "$PUBLIC_IP" "pgrep -f 'run_build.sh|build_corpus_ray|pip|apt-get|cloud-init'" &>/dev/null; then
        # Process exited — check if it completed or failed
        if ssh_cmd "$PUBLIC_IP" "test -f /home/ubuntu/BUILD_COMPLETE" 2>/dev/null; then
            log "Build completed successfully!"
            break
        else
            log "ERROR: Build process exited without completion marker."
            log "Fetching last 50 lines of log:"
            ssh_cmd "$PUBLIC_IP" "tail -50 /home/ubuntu/corpus-build-run.log" || true
            exit 1
        fi
    fi

    # Progress update
    LAST_LOG=$(ssh_cmd "$PUBLIC_IP" "tail -1 /home/ubuntu/corpus-build-run.log 2>/dev/null" || echo "...")
    log "[$((WAITED/60))m elapsed] $LAST_LOG"

    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        log "ERROR: Build exceeded ${MAX_WAIT}s timeout"
        exit 1
    fi
done

# Step 7: Download results
log "Downloading corpus.duckdb from S3 ..."
LOCAL_OUTPUT="/Users/johnchtchekine/Projects/Agent/corpus_index/corpus.duckdb"
mkdir -p "$(dirname "$LOCAL_OUTPUT")"
aws s3 cp "$S3_UPLOAD" "$LOCAL_OUTPUT" --region "$REGION"

DB_SIZE=$(ls -lh "$LOCAL_OUTPUT" | awk '{print $5}')
log "Downloaded: $LOCAL_OUTPUT ($DB_SIZE)"

# Step 8: Verify
log "Verifying corpus ..."
python3 -c "
import duckdb
conn = duckdb.connect('$LOCAL_OUTPUT', read_only=True)
for table in ['documents', 'sections', 'clauses', 'definitions', 'section_text']:
    count = conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]
    print(f'  {table}: {count:,} rows')
conn.close()
"

# Cleanup happens via trap (terminates instance)
log ""
log "=== Corpus build complete! ==="
log "Output: $LOCAL_OUTPUT"
log "S3 backup: $S3_UPLOAD"
log "Instance $INSTANCE_ID will be terminated."
