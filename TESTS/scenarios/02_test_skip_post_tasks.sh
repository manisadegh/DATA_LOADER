#!/bin/bash
# ==============================================================================
# SCENARIO 02 : TEST DU DÉCOUPLAGE HYBRIDE (--skip-post-tasks)
# Verifies that --skip-post-tasks propagates from Feeder to Orchestrator and skips hooks
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

SCENARIO_NAME="scenario_02_skip_post_tasks"

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
echo ">>> [SCENARIO 02] TEST DU DÉCOUPLAGE HYBRIDE (--skip-post-tasks)"
echo "=============================================================================="

# 1. Nettoyage de l'environnement
bash "${TESTS_DIR}/clean_data_and_logs.sh"

# 2. Injection du jeu de données nominal
echo "[STEP 1] Injection du lot dans DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_NOMINAL"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

# 3. Exécution avec le flag --skip-post-tasks
echo "[STEP 2] Lancement du Feeder avec --skip-post-tasks..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --skip-post-tasks
RC=$?

if [ ${RC} -ne 0 ]; then
    echo ">>> [FAILURE] Le Feeder a échoué avec le code : ${RC}"
    exit ${RC}
fi

# 4. Vérification de la prise en compte du flag dans les logs
echo "[STEP 3] Contrôle des logs de l'Orchestrateur pour la trace du bypass..."
if grep -rq "Post-tasks execution skipped via --skip-post-tasks flag" "${LOGS_DIR}" 2>/dev/null; then
    echo "  [OK] Découplage validé : Le message de bypass des post-traitements est consigné."
else
    echo ">>> [FAILURE] Le message de bypass n'a pas été trouvé dans les logs !"
    exit 1
fi

# 5. Vérification du statut final d'archivage (dans la capsule)
if [ -n "$(find "${DATA_DIR}/ARCHIVE_ZONE" -name "MANIFEST_ORACLE_FUSION_*9001*.MF" 2>/dev/null | head -1)" ]; then
    echo "  [OK] Le lot est archivé avec succès dans sa capsule malgré le bypass des post-tasks."
else
    echo ">>> [FAILURE] Le lot n'a pas été archivé !"
    exit 1
fi

echo "=============================================================================="
echo ">>> [SCENARIO 02 REUSSI AVEC SUCCES]"
echo "=============================================================================="
