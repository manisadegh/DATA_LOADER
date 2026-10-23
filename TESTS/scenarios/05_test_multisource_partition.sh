#!/bin/bash
# ==============================================================================
# SCENARIO 05 : TEST DU CLOISONNEMENT DU STOCKAGE MULTI-SOURCES
# Verifies sub-directory partitioning isolation between sources (ORACLE_FUSION & CRM)
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

SCENARIO_NAME="scenario_05_multisource_partition"

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
echo ">>> [SCENARIO 05] TEST DU CLOISONNEMENT MULTI-SOURCES (ORACLE_FUSION & CRM)"
echo "=============================================================================="

# 1. Nettoyage de l'environnement
bash "${TESTS_DIR}/clean_data_and_logs.sh"

# 2. Création des arborescences de sas partitionnées
echo "[STEP 1] Création des sous-répertoires partitionnés par source..."
for SRC in "ORACLE_FUSION" "CRM"; do
    mkdir -p "${DATA_DIR}/DROP_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/LANDING_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/LOADING_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/ARCHIVE_ZONE/${SRC}"
done

# 3. Dépôt des jeux de données dans chaque sas source respectif
echo "[STEP 2] Injection des lots dans les sas cloisonnés..."
cp "${DATASETS_DIR}/BATCH_NOMINAL"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
cp "${DATASETS_DIR}/BATCH_CRM"/* "${DATA_DIR}/DROP_ZONE/CRM/"

echo "Contenu DROP_ZONE/ORACLE_FUSION :"
ls -la "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
echo "Contenu DROP_ZONE/CRM :"
ls -la "${DATA_DIR}/DROP_ZONE/CRM/"

# 4. Exécution ciblée uniquement pour la source CRM
echo "[STEP 3] Traitement ciblé pour la source CRM (--source CRM)..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --source CRM
RC_CRM=$?

if [ ${RC_CRM} -ne 0 ]; then
    echo ">>> [FAILURE] Le traitement CRM a échoué avec le code : ${RC_CRM}"
    exit ${RC_CRM}
fi

# 5. Contrôle d'étanchéité : le sas ORACLE_FUSION ne doit absolument pas avoir bougé
echo "[STEP 4] Vérification de l'étanchéité stricte entre sources..."
if [ -f "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/file_userpvo-batch9001-.csv" ]; then
    echo "  [OK] Le sas ORACLE_FUSION est resté totalement intact pendant le run CRM."
else
    echo ">>> [FAILURE] Le sas ORACLE_FUSION a été altéré par le run CRM !"
    exit 1
fi

# Vérification présence lot CRM dans ARCHIVE_ZONE/CRM
FILE_CRM=$(find "${DATA_DIR}/ARCHIVE_ZONE/CRM" -name "file_customerpvo-batch9005-.csv" 2>/dev/null | head -n 1)
if [ -n "${FILE_CRM}" ] && [ -f "${FILE_CRM}" ]; then
    echo "  [OK] Le lot CRM 9005 est bien archivé dans ARCHIVE_ZONE/CRM."
else
    echo ">>> [FAILURE] Le lot CRM n'a pas été archivé dans ARCHIVE_ZONE/CRM !"
    exit 1
fi

# 6. Exécution ciblée pour ORACLE_FUSION
echo "[STEP 5] Traitement ciblé pour la source ORACLE_FUSION (--source ORACLE_FUSION)..."
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --source ORACLE_FUSION
RC_ORA=$?

if [ ${RC_ORA} -ne 0 ]; then
    echo ">>> [FAILURE] Le traitement ORACLE_FUSION a échoué avec le code : ${RC_ORA}"
    exit ${RC_ORA}
fi

# Vérification finale archivage ORACLE_FUSION
FILE_ORA=$(find "${DATA_DIR}/ARCHIVE_ZONE/ORACLE_FUSION" -name "file_userpvo-batch9001-.csv" 2>/dev/null | head -n 1)
if [ -n "${FILE_ORA}" ] && [ -f "${FILE_ORA}" ]; then
    echo "  [OK] Le lot ORACLE_FUSION 9001 est bien archivé dans ARCHIVE_ZONE/ORACLE_FUSION."
else
    echo ">>> [FAILURE] Le lot ORACLE_FUSION n'a pas été archivé !"
    exit 1
fi

# Vérification du cloisonnement des logs par source (LOGS/CRM et LOGS/ORACLE_FUSION)
echo "[STEP 6] Vérification du partitionnement des logs par source..."
if [ -d "${LOGS_DIR}/CRM" ] && [ -d "${LOGS_DIR}/ORACLE_FUSION" ]; then
    echo "  [OK] Les logs sont partitionnés par source dans LOGS/CRM et LOGS/ORACLE_FUSION."
else
    echo ">>> [FAILURE] Répertoires de logs partitionnés introuvables !"
    exit 1
fi

# 7. Exécution parallèle multi-sources (vérification de l'absence de blocage inter-sources sur BATCH_RUNS)
echo "[STEP 7] Test d'exécution simultanée CRM & ORACLE_FUSION (non-blocage inter-sources)..."
bash "${TESTS_DIR}/clean_data_and_logs.sh"
for SRC in "ORACLE_FUSION" "CRM"; do
    mkdir -p "${DATA_DIR}/DROP_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/LANDING_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/LOADING_ZONE/${SRC}"
    mkdir -p "${DATA_DIR}/ARCHIVE_ZONE/${SRC}"
done
cp "${DATASETS_DIR}/BATCH_NOMINAL"/* "${DATA_DIR}/DROP_ZONE/ORACLE_FUSION/"
cp "${DATASETS_DIR}/BATCH_CRM"/* "${DATA_DIR}/DROP_ZONE/CRM/"

python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --source CRM &
PID_CRM=$!
python3 "${FEEDER_SCRIPT}" --config "${FEEDER_CONFIG}" --source ORACLE_FUSION &
PID_ORA=$!

wait ${PID_CRM}
RC_CRM_PAR=$?
wait ${PID_ORA}
RC_ORA_PAR=$?

if [ ${RC_CRM_PAR} -ne 0 ] || [ ${RC_ORA_PAR} -ne 0 ]; then
    echo ">>> [FAILURE] Exécution parallèle multi-sources échouée (RC_CRM=${RC_CRM_PAR}, RC_ORA=${RC_ORA_PAR}) !"
    exit 1
fi
echo "  [OK] Exécution parallèle CRM et ORACLE_FUSION terminée avec succès sans blocage mutuel."

echo "=============================================================================="
echo ">>> [SCENARIO 05 REUSSI AVEC SUCCES]"
echo "=============================================================================="
