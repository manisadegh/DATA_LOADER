#!/bin/bash
# ==============================================================================
# SCENARIO 06 : TEST DES POST-TASKS SOURCE (INTAKE CONTROLLER) & DE LEUR BYPASS
# Verifies:
# 1. Intake Controller source-specific post-tasks are merged with Orchestrator tasks
#    and successfully executed when --skip-post-tasks is NOT provided.
# 2. Both Intake Controller and Orchestrator post-tasks are cleanly bypassed when
#    --skip-post-tasks IS provided.
# 3. Deliverables, manifests and vaulted receipts are preserved in storage tiers.
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

SCENARIO_NAME="scenario_06_intake_post_tasks"

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
echo ">>> [SCENARIO 06] TEST DES POST-TASKS SOURCE & BYPASS (--skip-post-tasks)"
echo "=============================================================================="

# 1. Nettoyage initial de l'environnement
bash "${TESTS_DIR}/clean_data_and_logs.sh"

# ==============================================================================
# PART A : EXÉCUTION NOMINALE DES POST-TASKS SOURCE (SANS --skip-post-tasks)
# ==============================================================================
echo ""
echo "--- [PART A] VALIDATION DE L'EXÉCUTION DES POST-TASKS CONFIGURÉES DANS L'INTAKE CONTROLLER ---"
echo "[STEP 1.1] Injection du lot 9006 dans DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_POST_TASKS"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

echo "[STEP 1.2] Lancement du Feeder sans option de skip..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}"
RC=$?

if [ ${RC} -ne 0 ]; then
    echo ">>> [FAILURE PART A] Le Feeder a échoué avec le code : ${RC}"
    exit ${RC}
fi

echo "[STEP 1.3] Contrôle de l'exécution des post-tasks dans les logs de l'Orchestrateur..."
# A. Post-task spécifique définie au niveau de l'Intake Controller
if grep -rq "Post-task specific to BICC / ORACLE_FUSION completed for batch 9006" "${LOGS_DIR}"/ 2>/dev/null; then
    echo "  [OK] Post-task spécifique BICC exécutée avec succès pour le lot 9006."
else
    echo ">>> [FAILURE] La post-task spécifique BICC pour le lot 9006 n'a pas été exécutée !"
    exit 1
fi

# B. Post-task globale définie au niveau de l'Orchestrateur
if grep -rq "Ingestion completed for batch 9006 from source ORACLE_FUSION" "${LOGS_DIR}"/ 2>/dev/null; then
    echo "  [OK] Post-task globale de l'Orchestrateur exécutée avec succès pour le lot 9006."
else
    echo ">>> [FAILURE] La post-task globale de l'Orchestrateur pour le lot 9006 n'a pas été exécutée !"
    exit 1
fi

# C. Vérification de l'archivage du lot 9006
MANIFEST_9006=$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "MANIFEST_ORACLE_FUSION_20261016_100500_9006.MF" 2>/dev/null | head -n 1)
FILE_9006=$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "file_userpvo-batch9006-.csv" 2>/dev/null | head -n 1)
if [ -n "${MANIFEST_9006}" ] && [ -f "${MANIFEST_9006}" ] && \
   [ -n "${FILE_9006}" ] && [ -f "${FILE_9006}" ]; then
    echo "  [OK] Lot 9006 correctement archivé dans ARCHIVE_ZONE."
else
    echo ">>> [FAILURE] Lot 9006 manquant dans ARCHIVE_ZONE !"
    exit 1
fi

# ==============================================================================
# PART B : DÉCOUPLAGE HYBRIDE VIA --skip-post-tasks
# ==============================================================================
echo ""
echo "--- [PART B] VALIDATION DU BYPASS INTÉGRAL VIA --skip-post-tasks ---"
echo "[STEP 2.1] Injection du lot 9008 dans DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_POST_TASKS_SKIP"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

echo "[STEP 2.2] Lancement du Feeder avec le flag --skip-post-tasks..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --skip-post-tasks
RC=$?

if [ ${RC} -ne 0 ]; then
    echo ">>> [FAILURE PART B] Le Feeder a échoué avec le code : ${RC}"
    exit ${RC}
fi

echo "[STEP 2.3] Contrôle du contournement effectif des post-tasks dans les logs..."
# A. Présence du message de bypass
if grep -rq "Post-tasks execution skipped via --skip-post-tasks flag" "${LOGS_DIR}"/ 2>/dev/null; then
    echo "  [OK] Trace de contournement (--skip-post-tasks) confirmée dans les logs."
else
    echo ">>> [FAILURE] Aucun message de bypass des post-tasks trouvé pour le lot 9008 !"
    exit 1
fi

# B. Absence d'exécution de la post-task BICC pour le lot 9008
if grep -rq "Post-task specific to BICC / ORACLE_FUSION completed for batch 9008" "${LOGS_DIR}"/ 2>/dev/null; then
    echo ">>> [FAILURE] La post-task spécifique BICC a été exécutée malgré --skip-post-tasks pour le lot 9008 !"
    exit 1
else
    echo "  [OK] Vérification confirmée : Aucune post-task source n'a été exécutée pour le lot 9008."
fi

# C. Absence d'exécution de la post-task globale pour le lot 9008
if grep -rq "Ingestion completed for batch 9008 from source ORACLE_FUSION" "${LOGS_DIR}"/ 2>/dev/null; then
    echo ">>> [FAILURE] La post-task globale a été exécutée malgré --skip-post-tasks pour le lot 9008 !"
    exit 1
else
    echo "  [OK] Vérification confirmée : Aucune post-task globale n'a été exécutée pour le lot 9008."
fi

# D. Vérification de l'archivage du lot 9008
MANIFEST_9008=$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "MANIFEST_ORACLE_FUSION_20261016_100700_9008.MF" 2>/dev/null | head -n 1)
FILE_9008=$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "file_userpvo-batch9008-.csv" 2>/dev/null | head -n 1)
if [ -n "${MANIFEST_9008}" ] && [ -f "${MANIFEST_9008}" ] && \
   [ -n "${FILE_9008}" ] && [ -f "${FILE_9008}" ]; then
    echo "  [OK] Lot 9008 correctement archivé dans ARCHIVE_ZONE malgré le bypass des post-tasks."
else
    echo ">>> [FAILURE] Lot 9008 manquant dans ARCHIVE_ZONE !"
    exit 1
fi

echo ""
echo "=============================================================================="
echo ">>> [SCENARIO 06 REUSSI AVEC SUCCES] Post-tasks source & bypass validés à 100% !"
echo "=============================================================================="
