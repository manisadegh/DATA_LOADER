#!/bin/bash
# ==============================================================================
# SCENARIO 07 : TEST D'AUDIT COMPLET BASE DE DONNÉES, STORAGE TIERS ET PROCESS_PID
# Verifies:
# 1. End-to-end ingestion of batch 9007 (3 payload records).
# 2. Teradata Technical Tables:
#    - BATCH_RUNS: STATUS = 'SUCCESS', START_TIME, END_TIME, and PROCESS_PID IS NOT NULL.
#    - BATCH_TASKS: STATUS = 'SUCCESS' for all entities.
# 3. Teradata Staging Table (DEV0SIDFINSTG.ERP_MSH_USER):
#    - Row count equals 3.
#    - INFA_BATCH_ID equals '9007'.
#    - INFA_LAST_REPLICATED IS NOT NULL.
# 4. Storage Tiers Cleanliness & Vaulting:
#    - LANDING_ZONE is clean.
#    - LOADING_ZONE is clean.
#    - ARCHIVE_ZONE contains Batch Capsule with RAW/ vaulted manifest and RECEIPT_*.json.
#    - ARCHIVE_ZONE contains final deliverables.
# 5. Generates detailed audit report in OUTPUTS.
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
AUDIT_SCRIPT="${TESTS_DIR}/verify_database_and_storage.py"

SCENARIO_NAME="scenario_07_database_and_storage_audit"
OUTPUT_DIR="${TESTS_DIR}/OUTPUTS/${SCENARIO_NAME}"
mkdir -p "${OUTPUT_DIR}"

# Trap d'archivage automatique en sortie (succès ou échec)
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
echo ">>> [SCENARIO 07] AUDIT COMPLET BASE DE DONNÉES, STORAGE TIERS & PROCESS_PID"
echo "=============================================================================="

# 1. Nettoyage initial de l'environnement
bash "${TESTS_DIR}/clean_data_and_logs.sh"

# 2. Injection du lot pour audit en base (Batch 9007)
echo "[STEP 1] Injection du lot 9007 (3 enregistrements) dans DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_DB_AUDIT"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

# 3. Exécution du Feeder
echo "[STEP 2] Lancement de l'ingestion via le BICC Intake Controller..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}"
RC=$?

if [ ${RC} -ne 0 ]; then
    echo ">>> [FAILURE] Le Feeder a échoué avec le code : ${RC}"
    exit ${RC}
fi

# 4. Audit approfondi Teradata & Système de Fichiers
echo "[STEP 3] Lancement de l'auditeur Python (Teradata Vantage & Storage Tiers)..."
AUDIT_REPORT="${OUTPUT_DIR}/db_and_storage_audit_report.txt"

python3 "${AUDIT_SCRIPT}" \
    --batch-id "9007" \
    --source "ORACLE_FUSION" \
    --target-table "ERP_MSH_USER" \
    --expected-count 3 \
    --output-file "${AUDIT_REPORT}"
AUDIT_RC=$?

if [ ${AUDIT_RC} -ne 0 ]; then
    echo ">>> [FAILURE] L'audit de base de données ou de stockage a détecté une anomalie !"
    if [ -f "${AUDIT_REPORT}" ]; then
        cat "${AUDIT_REPORT}"
    fi
    exit ${AUDIT_RC}
fi

echo ""
echo "  [OK] Rapport d'audit généré avec succès dans : ${AUDIT_REPORT}"
echo "=============================================================================="
echo ">>> [SCENARIO 07 REUSSI AVEC SUCCES] Données cibles, tables techniques et stockage validés !"
echo "=============================================================================="
