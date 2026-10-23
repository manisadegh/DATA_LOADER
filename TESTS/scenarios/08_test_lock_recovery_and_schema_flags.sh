#!/bin/bash
# ==============================================================================
# SCENARIO 08 : PHASE 01 - LOCK RECOVERY METADATA & SCHEMA GUARD FLAGS
# Validates:
#   - Part A: Phase 01 Unit Test Suite (test_phase01_units.py) & CSV Column
#             Sanitization Parity (BATCH_SPECIAL_COLS with spaces/hyphens/slashes)
#   - Part B: Schema Guard auto_migrate_ddl=false & append-mode drift protection
#   - Part C: unlock_tpt_table.sh replace-mode recovery via exact job name
#             verified end-to-end via verify_database_and_storage.py
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
TPT_DIR="${BASE_DIR}/PROCESSING_TOOLS/TPT_LOADER"
UNLOCK_SCRIPT="${TPT_DIR}/unlock_tpt_table.sh"
AUDITOR_SCRIPT="${TESTS_DIR}/verify_database_and_storage.py"
UNIT_TEST_SCRIPT="${TESTS_DIR}/test_phase01_units.py"

SCENARIO_NAME="scenario_08_lock_recovery_and_schema_flags"
SCENARIO_OUT_DIR="${TESTS_DIR}/OUTPUTS/${SCENARIO_NAME}"

cleanup_and_archive() {
    local RC=$?
    rm -f "${FEEDER_DIR}/config_no_ddl_tmp.json" 2>/dev/null || true
    if [ ${RC} -eq 0 ]; then
        bash "${TESTS_DIR}/archive_outputs.sh" "${SCENARIO_NAME}" "PASS" "${RC}"
    else
        bash "${TESTS_DIR}/archive_outputs.sh" "${SCENARIO_NAME}" "FAIL" "${RC}"
    fi
}
trap cleanup_and_archive EXIT

echo "=============================================================================="
echo ">>> [SCENARIO 08] LOCK RECOVERY METADATA & SCHEMA GUARD FLAGS"
echo "=============================================================================="

# 1. Clean runtime environment
bash "${TESTS_DIR}/clean_data_and_logs.sh"
mkdir -p "${SCENARIO_OUT_DIR}"

# 2. Part A.1: Execute Phase 01 Unit Test Suite
echo "[STEP 1] Running Phase 01 Unit Test Suite (test_phase01_units.py)..."
python3 "${UNIT_TEST_SCRIPT}" 2>&1 | tee "${SCENARIO_OUT_DIR}/unit_test_report.txt"
UNIT_RC=${PIPESTATUS[0]}
if [ ${UNIT_RC} -ne 0 ]; then
    echo ">>> [FAILURE] Phase 01 unit tests failed with RC=${UNIT_RC}"
    exit ${UNIT_RC}
fi
echo "  [OK] Phase 01 unit tests passed."

# 3. Part A.2: Ingest BATCH_SPECIAL_COLS (Batch 9009 with special chars in CSV header)
echo "[STEP 2] Injecting BATCH_SPECIAL_COLS (Batch 9009) into DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_SPECIAL_COLS"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
ls -la "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

echo "[STEP 3] Running BICC Intake Controller on BATCH 9009 (testing column sanitization parity)..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --source ORACLE_FUSION
RC_FEEDER=$?
if [ ${RC_FEEDER} -ne 0 ]; then
    echo ">>> [FAILURE] Feeder failed on BATCH_SPECIAL_COLS with RC=${RC_FEEDER}"
    exit ${RC_FEEDER}
fi
echo "  [OK] Batch 9009 ingested with special header characters sanitized identically in Python and Bash."

# 4. Part B: Verify auto_migrate_ddl: false blocks destructive DDL on schema drift
echo "[STEP 4] Verifying Schema Guard blocks DDL when auto_migrate_ddl=false on drifted CSV..."
python3 -c '
import json, sys
cfg_path, out_path = sys.argv[1], sys.argv[2]
with open(cfg_path, "r", encoding="utf-8") as f:
    cfg = json.load(f)
cfg.setdefault("schema_guard", {})["auto_migrate_ddl"] = False
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)
' "${FEEDER_CONFIG}" "${FEEDER_DIR}/config_no_ddl_tmp.json"

cat << 'EOF' > "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/file_userpvo-batch9099-.csv"
USER_ID,USER_NAME,EMAIL_ADDRESS,EXTRA_DRIFT_COLUMN
U999,DriftUser,drift@example.com,DriftVal
EOF
cat << 'EOF' > "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/MANIFEST_ORACLE_FUSION_20261016_100900_9099.MF"
filename,checksum
file_userpvo-batch9099-.csv,00000000000000000000000000000000
EOF

set +e
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_DIR}/config_no_ddl_tmp.json" --source ORACLE_FUSION
DRIFT_RC=$?
set -e

# Clean up temporary drift test files from DROP_ZONE, LANDING_ZONE, LOADING_ZONE and temp config
rm -rf "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION"/*9099* \
       "${DATA_DIR}/LANDING_ZONE/ORACLE_FUSION"/*9099* \
       "${DATA_DIR}/LOADING_ZONE/ORACLE_FUSION"/* \
       "${FEEDER_DIR}/config_no_ddl_tmp.json"

if [ ${DRIFT_RC} -eq 0 ]; then
    echo ">>> [FAILURE] Feeder should have aborted with non-zero RC when auto_migrate_ddl=false on drifted schema!"
    exit 1
fi
echo "  [OK] Feeder correctly blocked destructive DDL when auto_migrate_ddl=false (RC=${DRIFT_RC})."

# 5. Part C: Verify unlock_tpt_table.sh in replace mode resumes FastLoad
echo "[STEP 5] Testing unlock_tpt_table.sh replace-mode recovery..."
TPT_CAPSULE_DIR=$(find "${LOGS_DIR}/ORACLE_FUSION" -type d -path "*BATCH_9009*/TPT" 2>/dev/null | head -1)
if [ -z "${TPT_CAPSULE_DIR}" ]; then
    echo ">>> [FAILURE] Could not locate TPT work directory for Batch 9009 in ${LOGS_DIR}/ORACLE_FUSION"
    exit 1
fi

TPT_JOB_DIR=$(find "${TPT_CAPSULE_DIR}" -mindepth 1 -maxdepth 1 -type d -name "TPT_ERP_MSH_USER_*" 2>/dev/null | head -1)
if [ -z "${TPT_JOB_DIR}" ]; then
    echo ">>> [FAILURE] Could not locate TPT job directory for ERP_MSH_USER in ${TPT_CAPSULE_DIR}"
    exit 1
fi
TPT_JOB_NAME=$(basename "${TPT_JOB_DIR}")

# Stage payload file back into LOADING_ZONE/ORACLE_FUSION to simulate interrupted FastLoad recovery
cp "${DATASETS_DIR}/BATCH_SPECIAL_COLS/file_userpvo-batch9009-.csv" "${DATA_DIR}/LOADING_ZONE/ORACLE_FUSION/"

bash "${UNLOCK_SCRIPT}" \
    -t ERP_MSH_USER \
    -m replace \
    -j "${TPT_JOB_NAME}" \
    -w "${TPT_CAPSULE_DIR}"
UNLOCK_RC=$?

# Remove staged recovery file from LOADING_ZONE after unlock completes
rm -f "${DATA_DIR}/LOADING_ZONE/ORACLE_FUSION/file_userpvo-batch9009-.csv"

if [ ${UNLOCK_RC} -ne 0 ]; then
    echo ">>> [FAILURE] unlock_tpt_table.sh failed with RC=${UNLOCK_RC}"
    exit ${UNLOCK_RC}
fi
echo "  [OK] unlock_tpt_table.sh completed replace-mode resume."

# 6. Deep Teradata & Storage Verification Audit for Batch 9009
echo "[STEP 6] Running Deep Teradata & Storage Auditor for Batch 9009..."
AUDIT_REPORT="${SCENARIO_OUT_DIR}/db_and_storage_audit_report.txt"
python3 "${AUDITOR_SCRIPT}" \
    --batch-id "9009" \
    --source "ORACLE_FUSION" \
    --target-table "ERP_MSH_USER" \
    --expected-count 2 \
    --output-file "${AUDIT_REPORT}"
AUDIT_RC=$?

if [ ${AUDIT_RC} -ne 0 ]; then
    echo ">>> [FAILURE] Database & Storage Audit failed for Batch 9009 (RC=${AUDIT_RC})"
    exit ${AUDIT_RC}
fi

echo "=============================================================================="
echo ">>> [SCENARIO 08 PASSED SUCCESSFULLY]"
echo "=============================================================================="
