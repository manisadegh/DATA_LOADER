#!/bin/bash
# ==============================================================================
# SCENARIO 04 : TEST DE REPRISE SUR CRASH & PID MORT (STALE LOCK RECOVERY)
# Verifies dead PID detection, stale lock cleanup, and in-flight batch resumption
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

SCENARIO_NAME="scenario_04_crash_recovery"

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
echo ">>> [SCENARIO 04] TEST DE REPRISE SUR CRASH ET NETTOYAGE DE VERROU MORT"
echo "=============================================================================="

# 1. Nettoyage
bash "${TESTS_DIR}/clean_data_and_logs.sh"

# 2. Simulation d'un crash en plein vol dans LOADING_ZONE/ORACLE_FUSION
echo "[STEP 1] Injection du lot crashé BATCH 9004 directement dans LOADING_ZONE/ORACLE_FUSION..."
CRASH_CAPSULE_DIR="${DATA_DIR}/LOADING_ZONE/ORACLE_FUSION/BATCH_20261016_100300_9004"
mkdir -p "${CRASH_CAPSULE_DIR}"
cp -r "${DATASETS_DIR}/BATCH_CRASH"/* "${CRASH_CAPSULE_DIR}/"

DEAD_PID="999999"
echo "[STEP 2] Création d'un verrou orphelin avec PID mort (${DEAD_PID})..."
echo "${DEAD_PID}" > "${DATA_DIR}/LOADING_ZONE/ORACLE_FUSION/.orchestrator.pid"

ls -la "${DATA_DIR}/LOADING_ZONE/ORACLE_FUSION/"
ls -la "${CRASH_CAPSULE_DIR}/"

# 3. Lancement du Feeder : il doit constater le PID inactif et reprendre le lot en cours
echo "[STEP 3] Lancement du Feeder pour reprise automatique du lot interrompu..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}"
RC=$?

if [ ${RC} -ne 0 ]; then
    echo ">>> [FAILURE] La reprise sur crash a échoué avec le code : ${RC}"
    exit ${RC}
fi

# 4. Contrôles post-reprise
echo "[STEP 4] Vérification de la reprise et de l'archivage..."

# Le verrou doit être supprimé
if [ -f "${DATA_DIR}/LOADING_ZONE/ORACLE_FUSION/.orchestrator.pid" ] || [ -f "${DATA_DIR}/LOADING_ZONE/.orchestrator.pid" ]; then
    echo ">>> [FAILURE] Le verrou orphelin n'a pas été supprimé !"
    exit 1
else
    echo "  [OK] Verrou orphelin nettoyé avec succès."
fi

# Le batch crashé doit être désormais dans ARCHIVE_ZONE
MANIFEST_9004=$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "MANIFEST_ORACLE_FUSION_20261016_100300_9004.MF" 2>/dev/null | head -n 1)
FILE_9004=$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "file_userpvo-batch9004-.csv" 2>/dev/null | head -n 1)
if [ -n "${MANIFEST_9004}" ] && [ -f "${MANIFEST_9004}" ] && \
   [ -n "${FILE_9004}" ] && [ -f "${FILE_9004}" ]; then
    echo "  [OK] Le lot crashé 9004 a été complété, validé et archivé avec succès !"
else
    echo ">>> [FAILURE] Le lot crashé n'a pas été archivé après la reprise !"
    exit 1
fi

echo "=============================================================================="
echo ">>> [SCENARIO 04 REUSSI AVEC SUCCES]"
echo "=============================================================================="
