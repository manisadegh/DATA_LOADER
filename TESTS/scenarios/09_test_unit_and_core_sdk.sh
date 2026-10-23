#!/bin/bash
# ==============================================================================
# SCENARIO 09 : PHASE 02 - CORE SDK UNIT TESTS & CONNECTION POOL VALIDATION
# Validates:
#   1. Full Phase 02 Unit Test Suite (DATA_LOADER/TESTS/unit/test_*.py) via
#      python3 -m unittest discover -s "${TESTS_DIR}/unit" -v
#   2. Architectural Deduplication & Entrypoint Size Invariants (< 80 lines)
#   3. Live End-to-End Ingestion using pooled TeradataConnectionManager,
#      ProcessLock, ManifestHandler, EntityMapper, and CapsulePathResolver
#   4. Deep Teradata & Storage Verification Audit for Batch 9001
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BASE_DIR="$(cd "${TESTS_DIR}/.." && pwd)"
DATA_DIR="${BASE_DIR}/DATA"
LOGS_DIR="${BASE_DIR}/LOGS"
DATASETS_DIR="${TESTS_DIR}/DATASETS"
FEEDER_DIR="${BASE_DIR}/PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER"
FEEDER_SCRIPT="${FEEDER_DIR}/feeder.py"
FEEDER_CONFIG="${FEEDER_DIR}/config.json"
ORCH_DIR="${BASE_DIR}/PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR"
ORCH_SCRIPT="${ORCH_DIR}/orchestrator.py"
COMMON_DIR="${BASE_DIR}/PROCESSING_TOOLS/COMMON"
AUDITOR_SCRIPT="${TESTS_DIR}/verify_database_and_storage.py"

SCENARIO_NAME="scenario_09_unit_and_core_sdk"
OUTPUT_DIR="${TESTS_DIR}/OUTPUTS/${SCENARIO_NAME}"

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
echo ">>> [SCENARIO 09] CORE SDK UNIT TESTS & CONNECTION POOL VALIDATION"
echo "=============================================================================="

# 1. Clean runtime environment
bash "${TESTS_DIR}/clean_data_and_logs.sh"
mkdir -p "${OUTPUT_DIR}"

# 2. Execute Phase 02 Unit Test Suite
echo "[STEP 1] Running Phase 02 Core SDK & Service Unit Test Suite..."
PYTHONPATH="${COMMON_DIR}:${FEEDER_DIR}:${ORCH_DIR}:${PYTHONPATH}" \
    python3 -m unittest discover -s "${TESTS_DIR}/unit" -p "test_*.py" -v 2>&1 | tee "${OUTPUT_DIR}/unit_test_report.txt"
UNIT_RC=${PIPESTATUS[0]}
if [ ${UNIT_RC} -ne 0 ]; then
    echo ">>> [FAILURE] Phase 02 unit test suite failed with RC=${UNIT_RC}"
    exit ${UNIT_RC}
fi
echo "  [OK] All Phase 02 unit tests passed."

# 3. Verify Architectural Invariants (Entrypoint line limits & zero duplication)
echo "[STEP 2] Verifying Phase 02 architectural invariants (CLI line count < 80, zero duplicate helpers)..."
FEEDER_LINES=$(wc -l < "${FEEDER_SCRIPT}")
ORCH_LINES=$(wc -l < "${ORCH_SCRIPT}")
echo "  - feeder.py line count       : ${FEEDER_LINES} (limit: < 80)"
echo "  - orchestrator.py line count : ${ORCH_LINES} (limit: < 80)"
if [ "${FEEDER_LINES}" -ge 80 ] || [ "${ORCH_LINES}" -ge 80 ]; then
    echo ">>> [FAILURE] Entrypoint line count exceeded 80 lines!"
    exit 1
fi

if grep -rnE --include="*.py" "def compute_md5|def get_capsule_subpath|def get_teradata_credentials|fcntl\.flock" "${FEEDER_DIR}" "${ORCH_DIR}" >/dev/null 2>&1; then
    echo ">>> [FAILURE] Found duplicate helper definitions in BICC_INTAKE_CONTROLLER or DATA_INGESTION_ORCHESTRATOR!"
    grep -rnE --include="*.py" "def compute_md5|def get_capsule_subpath|def get_teradata_credentials|fcntl\.flock" "${FEEDER_DIR}" "${ORCH_DIR}"
    exit 1
fi
echo "  [OK] Architectural invariants verified."

# 4. Stage BATCH_NOMINAL (Batch 9001) and run end-to-end ingestion through Core SDK
echo "[STEP 3] Staging BATCH_NOMINAL (Batch 9001) into DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_NOMINAL"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
ls -la "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

echo "[STEP 4] Running BICC Intake Controller with dataloader_core SDK & pooled TeradataConnectionManager..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}"
RC_FEEDER=$?
if [ ${RC_FEEDER} -ne 0 ]; then
    echo ">>> [FAILURE] Feeder failed on BATCH_NOMINAL with RC=${RC_FEEDER}"
    exit ${RC_FEEDER}
fi
echo "  [OK] Batch 9001 ingested end-to-end via dataloader_core SDK."

# 5. Deep Teradata & Storage Verification Audit for Batch 9001
echo "[STEP 5] Running Deep Teradata & Storage Auditor for Batch 9001..."
AUDIT_REPORT="${OUTPUT_DIR}/db_and_storage_audit_report.txt"
python3 "${AUDITOR_SCRIPT}" \
    --batch-id "9001" \
    --source "ORACLE_FUSION" \
    --target-table "ERP_MSH_USER" \
    --expected-count 2 \
    --output-file "${AUDIT_REPORT}"
AUDIT_RC=$?

if [ ${AUDIT_RC} -ne 0 ]; then
    echo ">>> [FAILURE] Database & Storage Audit failed for Batch 9001 (RC=${AUDIT_RC})"
    exit ${AUDIT_RC}
fi

echo "=============================================================================="
echo ">>> [SCENARIO 09 PASSED SUCCESSFULLY]"
echo "=============================================================================="
