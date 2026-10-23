#!/bin/bash
# ==============================================================================
# SCENARIO 01 : TEST END-TO-END NOMINAL PIPELINE
# Verifies complete cascade: Feeder -> Schema Guard -> Orchestrator -> TPT -> Archive
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

SCENARIO_NAME="scenario_01_nominal_pipeline"

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
echo ">>> [SCENARIO 01] END-TO-END NOMINAL PIPELINE INGESTION"
echo "=============================================================================="

# 1. Nettoyage de l'environnement
bash "${TESTS_DIR}/clean_data_and_logs.sh"

# 2. Injection du jeu de test nominal
echo "[STEP 1] Injection du lot nominal BATCH 9001 dans DROP_ZONE/ORACLE_FUSION..."
cp "${DATASETS_DIR}/BATCH_NOMINAL"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
ls -la "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"

# 3. Exécution du Feeder
echo "[STEP 2] Lancement du BICC Intake Controller..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}"
RC=$?

if [ ${RC} -ne 0 ]; then
    echo ">>> [FAILURE] BICC Intake Controller s'est terminé avec le code d'erreur : ${RC}"
    exit ${RC}
fi

# 4. Contrôles post-exécution
echo "[STEP 3] Contrôle des livrables et de l'archivage..."

# Vérification présence dans ARCHIVE_ZONE (recherche récursive dans la capsule de lot)
ARCHIVED_PAYLOAD=$(find "${DATA_DIR}/ARCHIVE_ZONE" -type f -name "*9001*.csv" 2>/dev/null | head -1)
ARCHIVED_MF=$(find "${DATA_DIR}/ARCHIVE_ZONE" -type f -name "MANIFEST_*9001*.MF" 2>/dev/null | head -1)
if [ -n "${ARCHIVED_PAYLOAD}" ] && [ -n "${ARCHIVED_MF}" ]; then
    echo "  [OK] Le lot 9001 est correctement archivé dans sa Capsule ARCHIVE_ZONE."
else
    echo ">>> [FAILURE] Fichiers manquants dans ARCHIVE_ZONE !"
    exit 1
fi

# Vérification du coffre-fort de manifests bruts
ARCHIVE_VAULT=$(find "${DATA_DIR}/ARCHIVE_ZONE" -type d -name "RAW" 2>/dev/null | head -1)
if [ -n "${ARCHIVE_VAULT}" ] && ls "${ARCHIVE_VAULT}"/RECEIPT_*.json >/dev/null 2>&1 && [ ! -f "${ARCHIVE_VAULT}/intake_receipt.json" ]; then
    echo "  [OK] Le manifest brut et son reçu d'intake canonique (RECEIPT_*.json sans intake_receipt.json obsolète) ont été archivés dans : ${ARCHIVE_VAULT}"
else
    echo ">>> [FAILURE] Reçu d'intake canonique introuvable ou fichier intake_receipt.json obsolète présent dans ARCHIVE_ZONE !"
    exit 1
fi

# Vérification des logs (supporte racine LOGS/ ou sous-dossier partitionné LOGS/<SOURCE>/.../BATCH_<ID>/)
if grep -rq "SUCCESS" "${LOGS_DIR}" 2>/dev/null; then
    echo "  [OK] Succès confirmé dans les logs de l'Orchestrateur."
else
    echo ">>> [WARNING] Vérifiez les logs dans ${LOGS_DIR}"
fi

echo "=============================================================================="
echo ">>> [SCENARIO 01 REUSSI AVEC SUCCES]"
echo "=============================================================================="
