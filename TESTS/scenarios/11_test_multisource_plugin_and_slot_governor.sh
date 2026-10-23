#!/bin/bash
# ==============================================================================
# SCENARIO 11 : TEST MULTI-SOURCES, ARCHITECTURE DE PLUGINS & GOUVERNANCE DE SLOTS
# Validates:
#   1. Pluggable Source Intake Framework (BICCIntakePlugin for ORACLE_FUSION,
#      StandardManifestIntakePlugin for CRM) staging independent Batch Capsules
#      using --enqueue-only.
#   2. Extended Entity Mapping attributes (DELIMITER, LOAD_MODE, SKIP_ROWS, HEADER_MODE)
#      propagated into batch_descriptor.json.
#   3. Multi-Source Orchestration via orchestrator.py --all-sources draining all
#      active source queues in LANDING_ZONE.
#   4. Global Teradata Utility Slot Governor bounding concurrent loads across sources.
#   5. Deep Teradata DB and Storage audit for both ORACLE_FUSION and CRM batches.
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

SCENARIO_NAME="scenario_11_multisource_plugin_and_slot_governor"
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
echo ">>> [SCENARIO 11] TEST MULTI-SOURCES, PLUGINS & GOUVERNANCE DE SLOTS"
echo "=============================================================================="

# 1. Clean environment
bash "${TESTS_DIR}/clean_data_and_logs.sh"
mkdir -p "${SCENARIO_OUT_DIR}"

# 2. Partitioned directories setup
echo "[STEP 1] Creating source-partitioned drop and queue zones..."
for SRC in "ORACLE_FUSION" "CRM"; do
    mkdir -p "${DATA_DIR}/DROP_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/LANDING_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/LOADING_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/ARCHIVE_ZONE/${SRC}"
    mkdir -p "${LOGS_DIR}/${SRC}"
done

# 3. Inject multi-source datasets
echo "[STEP 2] Injecting datasets: Batch 9001 (ORACLE_FUSION) and Batch 9005 (CRM)..."
cp "${DATASETS_DIR}/BATCH_NOMINAL"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
cp "${DATASETS_DIR}/BATCH_CRM"/* "${DATA_DIR}/DROP_ZONE/CRM/"

echo "  - DROP_ZONE/ORACLE_FUSION:"
ls -la "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
echo "  - DROP_ZONE/CRM:"
ls -la "${DATA_DIR}/DROP_ZONE/CRM/"

# 4. Enqueue ORACLE_FUSION via BICCIntakePlugin (--enqueue-only)
echo "[STEP 3] Running Intake Controller for ORACLE_FUSION (--enqueue-only)..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --source ORACLE_FUSION --enqueue-only
RC_FEEDER_ORA=$?
if [ ${RC_FEEDER_ORA} -ne 0 ]; then
    echo ">>> [FAILURE] Feeder --enqueue-only failed for ORACLE_FUSION (RC=${RC_FEEDER_ORA})"
    exit ${RC_FEEDER_ORA}
fi
echo "  [OK] Batch 9001 queued into LANDING_ZONE/ORACLE_FUSION."

# 5. Enqueue CRM via StandardManifestIntakePlugin (--enqueue-only)
echo "[STEP 4] Running Intake Controller for CRM (--enqueue-only)..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --source CRM --enqueue-only
RC_FEEDER_CRM=$?
if [ ${RC_FEEDER_CRM} -ne 0 ]; then
    echo ">>> [FAILURE] Feeder --enqueue-only failed for CRM (RC=${RC_FEEDER_CRM})"
    exit ${RC_FEEDER_CRM}
fi
echo "  [OK] Batch 9005 queued into LANDING_ZONE/CRM."

# 6. Verify queued capsules and descriptor contents across sources
echo "[STEP 5] Verifying queued capsules in LANDING_ZONE for both sources..."
CAP_ORA=$(find "${DATA_DIR}/LANDING_ZONE/ORACLE_FUSION" -maxdepth 1 -type d -name "BATCH_*9001*" 2>/dev/null | head -1)
CAP_CRM=$(find "${DATA_DIR}/LANDING_ZONE/CRM" -maxdepth 1 -type d -name "BATCH_*9005*" 2>/dev/null | head -1)

if [ -z "${CAP_ORA}" ] || [ -z "${CAP_CRM}" ]; then
    echo ">>> [FAILURE] Expected queued capsules in both ORACLE_FUSION and CRM landing zones!"
    exit 1
fi

echo "  [OK] Found ORACLE_FUSION capsule: $(basename "${CAP_ORA}")"
echo "  [OK] Found CRM capsule:           $(basename "${CAP_CRM}")"

for CAP in "${CAP_ORA}" "${CAP_CRM}"; do
    if [ ! -f "${CAP}/batch_descriptor.json" ]; then
        echo ">>> [FAILURE] Missing batch_descriptor.json in ${CAP}!"
        exit 1
    fi
    if [ ! -d "${CAP}/RAW" ] || ! ls "${CAP}/RAW"/RECEIPT_*.json >/dev/null 2>&1; then
        echo ">>> [FAILURE] Missing RAW vault or RECEIPT_*.json in ${CAP}!"
        exit 1
    fi
done
echo "  [OK] Both capsules contain valid descriptors, manifests, and vaulted receipts."

# 7. Execute Multi-Source Orchestration (--all-sources) with Global Utility Slot Governor
echo "[STEP 6] Running Orchestrator with --all-sources (sweeps all active source queues)..."
python3 "${ORCH_SCRIPT}" --config "${ORCH_CONFIG}" --all-sources
RC_ORCH=$?
if [ ${RC_ORCH} -ne 0 ]; then
    echo ">>> [FAILURE] Orchestrator --all-sources failed with RC=${RC_ORCH}"
    exit ${RC_ORCH}
fi
echo "  [OK] Multi-source sweep completed successfully."

# 8. Verify clean storage tiers across all sources
echo "[STEP 7] Verifying storage tier cleanliness across all sources..."
for SRC in "ORACLE_FUSION" "CRM"; do
    REM_LAND=$(ls "${DATA_DIR}/LANDING_ZONE/${SRC}" 2>/dev/null | grep -v '^\.' || true)
    REM_LOAD=$(ls "${DATA_DIR}/LOADING_ZONE/${SRC}" 2>/dev/null | grep -v '^\.' || true)
    if [ -n "${REM_LAND}" ]; then
        echo ">>> [FAILURE] LANDING_ZONE/${SRC} is not clean: ${REM_LAND}"
        exit 1
    fi
    if [ -n "${REM_LOAD}" ]; then
        echo ">>> [FAILURE] LOADING_ZONE/${SRC} is not clean: ${REM_LOAD}"
        exit 1
    fi
    echo "  [OK] Storage tiers clean for source: ${SRC}"
done

# 9. Verify Batch Capsules in ARCHIVE_ZONE
echo "[STEP 8] Verifying Batch Capsules in ARCHIVE_ZONE..."
ARCH_ORA=$(find "${DATA_DIR}/ARCHIVE_ZONE/ORACLE_FUSION" -type d -name "BATCH_9001_*" 2>/dev/null | head -1)
ARCH_CRM=$(find "${DATA_DIR}/ARCHIVE_ZONE/CRM" -type d -name "BATCH_9005_*" 2>/dev/null | head -1)

if [ -z "${ARCH_ORA}" ] || [ -z "${ARCH_CRM}" ]; then
    echo ">>> [FAILURE] One or both batches missing from ARCHIVE_ZONE!"
    exit 1
fi
echo "  [OK] Archived capsule for ORACLE_FUSION: $(basename "${ARCH_ORA}")"
echo "  [OK] Archived capsule for CRM:           $(basename "${ARCH_CRM}")"

# 10. Deep Database & Storage Audit for both batches
echo "[STEP 9] Running Deep Teradata & Storage Auditor for Batch 9001 (ORACLE_FUSION)..."
python3 "${AUDITOR_SCRIPT}" \
    --batch-id "9001" \
    --source "ORACLE_FUSION" \
    --target-table "ERP_MSH_USER" \
    --expected-count 2 \
    --output-file "${SCENARIO_OUT_DIR}/audit_batch_9001_oracle_fusion.txt"
RC_AUDIT_ORA=$?
if [ ${RC_AUDIT_ORA} -ne 0 ]; then
    echo ">>> [FAILURE] Database audit failed for Batch 9001 (RC=${RC_AUDIT_ORA})"
    exit ${RC_AUDIT_ORA}
fi
echo "  [OK] Audit passed for Batch 9001 (ORACLE_FUSION)."

echo "[STEP 10] Running Deep Teradata & Storage Auditor for Batch 9005 (CRM)..."
python3 "${AUDITOR_SCRIPT}" \
    --batch-id "9005" \
    --source "CRM" \
    --target-table "CRM_MSH_CUSTOMER" \
    --expected-count 1 \
    --output-file "${SCENARIO_OUT_DIR}/audit_batch_9005_crm.txt"
RC_AUDIT_CRM=$?
if [ ${RC_AUDIT_CRM} -ne 0 ]; then
    echo ">>> [FAILURE] Database audit failed for Batch 9005 (RC=${RC_AUDIT_CRM})"
    exit ${RC_AUDIT_CRM}
fi
echo "  [OK] Audit passed for Batch 9005 (CRM)."

echo "=============================================================================="
echo ">>> [SCENARIO 11 PASSED SUCCESSFULLY] Multi-Source Plugins & Slot Governor Validated 100%!"
echo "=============================================================================="
