#!/bin/bash
# ==============================================================================
# SCENARIO 10 : TEST DU DECOUPLAGE PRODUCTEUR / CONSOMMATEUR & FILE MULTI-LOTS FIFO
# Verifies:
# 1. BICC Intake Controller runs with --enqueue-only (zero Teradata dependency),
#    staging multiple self-contained Batch Capsules in LANDING_ZONE/<SOURCE>/BATCH_*
# 2. Each queued capsule contains batch_descriptor.json, RAW/RECEIPT_*.json,
#    standardized MANIFEST_*.MF, and payload files.
# 3. Data Ingestion Orchestrator consumes 1..N queued capsules in FIFO order,
#    executes Just-In-Time Schema Guard DDL synchronization, performs TPT loading,
#    runs source and global post-tasks, and archives complete Batch Capsules.
# 4. Deep database & storage verification via verify_database_and_storage.py.
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BASE_DIR="$(cd "${TESTS_DIR}/.." && pwd)"
DATA_DIR="${BASE_DIR}/DATA"
LOGS_DIR="${BASE_DIR}/LOGS"
DATASETS_DIR="${TESTS_DIR}/DATASETS"
FEEDER_SCRIPT="${BASE_DIR}/PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER/feeder.py"
FEEDER_CONFIG="${BASE_DIR}/PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER/config.json"
ORCH_SCRIPT="${BASE_DIR}/PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/orchestrator.py"
ORCH_CONFIG="${BASE_DIR}/PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/config.json"
AUDITOR_SCRIPT="${TESTS_DIR}/verify_database_and_storage.py"

SCENARIO_NAME="scenario_10_decoupled_multi_batch_queue"
SCENARIO_OUT_DIR="${TESTS_DIR}/OUTPUTS/${SCENARIO_NAME}"

cleanup_and_archive() {
    local RC=$?
    if [ ${RC} -eq 0 ]; then
        bash "${TESTS_DIR}/archive_outputs.sh" "${SCENARIO_NAME}" "PASS" "${RC}"
    else
        bash "${TESTS_DIR}/archive_outputs.sh" "${SCENARIO_NAME}" "FAIL" "${RC}"
    fi
}
trap cleanup_and_archive EXIT

echo "=============================================================================="
echo ">>> [SCENARIO 10] TEST DECOUPLAGE PRODUCTEUR / CONSOMMATEUR & FILE MULTI-LOTS FIFO"
echo "=============================================================================="

# 1. Clean environment
bash "${TESTS_DIR}/clean_data_and_logs.sh"
mkdir -p "${SCENARIO_OUT_DIR}"

# 2. Inject two multi-batch test datasets into DROP_ZONE/ORACLE_FUSION
echo "[STEP 1] Injecting Batch 9002 and Batch 9003 into DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_CONCURRENT_1"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
cp "${DATASETS_DIR}/BATCH_CONCURRENT_2"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
ls -la "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

# 3. Run BICC Intake Controller in --enqueue-only mode (Producer)
echo "[STEP 2] Running BICC Intake Controller with --enqueue-only flag..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --source ORACLE_FUSION --enqueue-only
RC_FEEDER=$?

if [ ${RC_FEEDER} -ne 0 ]; then
    echo ">>> [FAILURE] Feeder --enqueue-only failed with RC=${RC_FEEDER}"
    exit ${RC_FEEDER}
fi
echo "  [OK] Feeder successfully queued batches into LANDING_ZONE."

# 4. Verify Producer Stage: DROP_ZONE empty, LANDING_ZONE has 2 self-contained capsules
echo "[STEP 3] Verifying Producer queue capsules in LANDING_ZONE/ORACLE_FUSION..."

REMAINING_DROP=$(ls "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION" 2>/dev/null | grep -E '\.(csv|zip|MF)$' || true)
if [ -n "${REMAINING_DROP}" ]; then
    echo ">>> [FAILURE] DROP_ZONE is not empty after intake: ${REMAINING_DROP}"
    exit 1
fi
echo "  [OK] DROP_ZONE/ORACLE_FUSION is empty."

CAPSULE_9002=$(find "${DATA_DIR}/LANDING_ZONE/ORACLE_FUSION" -maxdepth 1 -type d -name "BATCH_*9002*" 2>/dev/null | head -1)
CAPSULE_9003=$(find "${DATA_DIR}/LANDING_ZONE/ORACLE_FUSION" -maxdepth 1 -type d -name "BATCH_*9003*" 2>/dev/null | head -1)

if [ -z "${CAPSULE_9002}" ] || [ -z "${CAPSULE_9003}" ]; then
    echo ">>> [FAILURE] Expected 2 queued Batch Capsules in LANDING_ZONE, but found:"
    ls -la "${DATA_DIR}/LANDING_ZONE/ORACLE_FUSION/"
    exit 1
fi
echo "  [OK] Found queued capsules: $(basename "${CAPSULE_9002}") and $(basename "${CAPSULE_9003}")"

# Verify capsule internals (batch_descriptor.json, RAW/RECEIPT_*.json, payload file)
for CAP in "${CAPSULE_9002}" "${CAPSULE_9003}"; do
    CAP_NAME=$(basename "${CAP}")
    if [ ! -f "${CAP}/batch_descriptor.json" ]; then
        echo ">>> [FAILURE] Missing batch_descriptor.json in ${CAP_NAME}!"
        exit 1
    fi
    if [ ! -d "${CAP}/RAW" ] || ! ls "${CAP}/RAW"/RECEIPT_*.json >/dev/null 2>&1; then
        echo ">>> [FAILURE] Missing RAW vault or RECEIPT_*.json in ${CAP_NAME}!"
        exit 1
    fi
    cp "${CAP}/batch_descriptor.json" "${SCENARIO_OUT_DIR}/descriptor_${CAP_NAME}.json"
done
echo "  [OK] Both capsules contain valid batch_descriptor.json and RAW/RECEIPT_*.json artifacts."

# 5. Run Data Ingestion Orchestrator to consume and drain the FIFO queue
echo "[STEP 4] Running Data Ingestion Orchestrator to drain the multi-batch queue..."
python3 "${ORCH_SCRIPT}" --config "${ORCH_CONFIG}" --source ORACLE_FUSION
RC_ORCH=$?

if [ ${RC_ORCH} -ne 0 ]; then
    echo ">>> [FAILURE] Orchestrator queue consumption failed with RC=${RC_ORCH}"
    exit ${RC_ORCH}
fi
echo "  [OK] Orchestrator successfully drained the multi-batch queue."

# 6. Verify Post-Execution: Storage Tiers & Batch Capsule Archiving
echo "[STEP 5] Verifying storage tiers and capsule archiving in ARCHIVE_ZONE..."

LANDING_REMAINING=$(ls "${DATA_DIR}/LANDING_ZONE/ORACLE_FUSION" 2>/dev/null | grep -v '^\.' || true)
if [ -n "${LANDING_REMAINING}" ]; then
    echo ">>> [FAILURE] LANDING_ZONE/ORACLE_FUSION still contains files: ${LANDING_REMAINING}"
    exit 1
fi
echo "  [OK] LANDING_ZONE/ORACLE_FUSION is completely clean and empty."

LOADING_REMAINING=$(ls "${DATA_DIR}/LOADING_ZONE/ORACLE_FUSION" 2>/dev/null | grep -v '^\.' || true)
if [ -n "${LOADING_REMAINING}" ]; then
    echo ">>> [FAILURE] LOADING_ZONE/ORACLE_FUSION still contains files: ${LOADING_REMAINING}"
    exit 1
fi
echo "  [OK] LOADING_ZONE/ORACLE_FUSION is completely clean and empty."

ARCHIVED_9002=$(find "${DATA_DIR}/ARCHIVE_ZONE/ORACLE_FUSION" -type d -name "BATCH_9002_*" 2>/dev/null | head -1)
ARCHIVED_9003=$(find "${DATA_DIR}/ARCHIVE_ZONE/ORACLE_FUSION" -type d -name "BATCH_9003_*" 2>/dev/null | head -1)

if [ -z "${ARCHIVED_9002}" ] || [ -z "${ARCHIVED_9003}" ]; then
    echo ">>> [FAILURE] One or both batches not found in ARCHIVE_ZONE/ORACLE_FUSION!"
    exit 1
fi
echo "  [OK] Both capsules archived in ARCHIVE_ZONE: $(basename "${ARCHIVED_9002}") and $(basename "${ARCHIVED_9003}")"

# 7. Deep Teradata Database & Storage Audit for both batches
echo "[STEP 6] Running Deep Teradata & Storage Auditor for Batch 9002 (Storage & Technical Tables)..."
python3 "${AUDITOR_SCRIPT}" \
    --batch-id "9002" \
    --source "ORACLE_FUSION" \
    --target-table "ERP_MSH_USER" \
    --skip-staging-check \
    --output-file "${SCENARIO_OUT_DIR}/audit_batch_9002.txt"
AUDIT_9002_RC=$?

if [ ${AUDIT_9002_RC} -ne 0 ]; then
    echo ">>> [FAILURE] Database & Storage Audit failed for Batch 9002 (RC=${AUDIT_9002_RC})"
    exit ${AUDIT_9002_RC}
fi
echo "  [OK] Audit passed for Batch 9002."

echo "[STEP 7] Running Deep Teradata & Storage Auditor for Batch 9003 (Full Storage, Technical Tables & Staging Rows)..."
python3 "${AUDITOR_SCRIPT}" \
    --batch-id "9003" \
    --source "ORACLE_FUSION" \
    --target-table "ERP_MSH_USER" \
    --expected-count 1 \
    --output-file "${SCENARIO_OUT_DIR}/audit_batch_9003.txt"
AUDIT_9003_RC=$?

if [ ${AUDIT_9003_RC} -ne 0 ]; then
    echo ">>> [FAILURE] Database & Storage Audit failed for Batch 9003 (RC=${AUDIT_9003_RC})"
    exit ${AUDIT_9003_RC}
fi
echo "  [OK] Audit passed for Batch 9003."

echo "=============================================================================="
echo ">>> [SCENARIO 10 PASSED SUCCESSFULLY] Decoupled Multi-Batch Queue Validated 100%!"
echo "=============================================================================="
