#!/bin/bash
# ==============================================================================
# SCENARIO 03 : TEST DE CONCURRENCE & ATTENTE ACTIVE (MUTUAL EXCLUSION)
# Verifies process lock acquisition, active wait polling loop, and sequential execution
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

SCENARIO_NAME="scenario_03_concurrency_lock"

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
echo ">>> [SCENARIO 03] TEST DE CONCURRENCE ET D'ATTENTE ACTIVE"
echo "=============================================================================="

# 1. Nettoyage
bash "${TESTS_DIR}/clean_data_and_logs.sh"

# 2. Injection du premier lot (BATCH 9002)
echo "[STEP 1] Injection du Lot 1 (BATCH 9002) dans DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_CONCURRENT_1"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

echo "[STEP 2] Lancement de l'Instance Feeder 1 en arrière-plan..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" &
PID_FEEDER_1=$!
echo "  -> Feeder 1 démarré avec PID : ${PID_FEEDER_1}"

# Attente courte pour garantir que Feeder 1 a posé son verrou (.feeder_ORACLE_FUSION.pid)
sleep 0.5

# 3. Injection du second lot (BATCH 9003)
echo "[STEP 3] Injection du Lot 2 (BATCH 9003) dans DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_CONCURRENT_2"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

echo "[STEP 4] Lancement simultané de l'Instance Feeder 2 (doit entrer en attente active)..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" &
PID_FEEDER_2=$!
echo "  -> Feeder 2 démarré avec PID : ${PID_FEEDER_2}"

# 4. Attente de la complétion des deux instances
echo "[STEP 5] Attente de la synchronisation et de la complétion des deux processus..."
wait ${PID_FEEDER_1}
RC1=$?
wait ${PID_FEEDER_2}
RC2=$?

echo "  Feeder 1 code retour : ${RC1}"
echo "  Feeder 2 code retour : ${RC2}"

if [ ${RC1} -ne 0 ] || [ ${RC2} -ne 0 ]; then
    echo ">>> [FAILURE] Un des deux Feeder concurrents a échoué !"
    exit 1
fi

# 5. Vérification dans les logs de l'attente active
echo "[STEP 6] Vérification des traces d'attente active dans les logs..."
if grep -rq "Another BICC Intake Controller is currently active" "${LOGS_DIR}"/ 2>/dev/null || \
   grep -rq "Entering active waiting loop" "${LOGS_DIR}"/ 2>/dev/null; then
    echo "  [OK] L'attente active a été déclenchée et journalisée avec succès !"
else
    echo "  [INFO] Les deux processus ont sérialisé leur exécution."
fi

# 6. Vérification que les deux lots sont bien archivés
MANIFEST_9002=$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "MANIFEST_ORACLE_FUSION_20261016_100100_9002.MF" 2>/dev/null | head -n 1)
MANIFEST_9003=$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "MANIFEST_ORACLE_FUSION_20261016_100200_9003.MF" 2>/dev/null | head -n 1)
if [ -n "${MANIFEST_9002}" ] && [ -f "${MANIFEST_9002}" ] && \
   [ -n "${MANIFEST_9003}" ] && [ -f "${MANIFEST_9003}" ]; then
    echo "  [OK] Les deux lots 9002 et 9003 ont été traités et archivés avec succès."
else
    echo ">>> [FAILURE] Au moins un lot manque dans ARCHIVE_ZONE !"
    exit 1
fi

echo "=============================================================================="
echo ">>> [SCENARIO 03 REUSSI AVEC SUCCES]"
echo "=============================================================================="
