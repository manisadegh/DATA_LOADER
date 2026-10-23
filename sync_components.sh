#!/bin/bash
# ==============================================================================
# DATA_LOADER Component Synchronization Utility (sync_components.sh)
# Synchronizes code, templates, and documentation from the standalone root Git
# component repositories into DATA_LOADER/PROCESSING_TOOLS/ and DATA_LOADER/DOCS/
# while preserving Unix-configured config.json files.
# ==============================================================================
set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
TOOLS_DIR="${SCRIPT_DIR}/PROCESSING_TOOLS"
DOCS_DIR="${SCRIPT_DIR}/DOCS"

echo "======================================================================"
echo " Synchronizing Root Component Repositories -> DATA_LOADER"
echo "======================================================================"

# 0. COMMON (dataloader_core Shared SDK)
echo "[1/4] Syncing COMMON (dataloader_core)..."
mkdir -p "${TOOLS_DIR}/COMMON/dataloader_core" "${TOOLS_DIR}/COMMON/dataloader_core/intake" "${TOOLS_DIR}/COMMON/docs" "${DOCS_DIR}/00_COMMON_CORE_SDK"
cp "${ROOT_DIR}/COMMON/README.md" "${TOOLS_DIR}/COMMON/"
cp "${ROOT_DIR}/COMMON/dataloader_core/"*.py "${TOOLS_DIR}/COMMON/dataloader_core/"
cp "${ROOT_DIR}/COMMON/dataloader_core/intake/"*.py "${TOOLS_DIR}/COMMON/dataloader_core/intake/"
cp "${ROOT_DIR}/COMMON/docs/"*.md "${TOOLS_DIR}/COMMON/docs/"
cp "${ROOT_DIR}/COMMON/docs/"*.md "${DOCS_DIR}/00_COMMON_CORE_SDK/"

# 1. BICC_INTAKE_CONTROLLER
echo "[2/4] Syncing BICC_INTAKE_CONTROLLER..."
rm -f "${TOOLS_DIR}/BICC_INTAKE_CONTROLLER/lib/schema_guard.py"
cp "${ROOT_DIR}/BICC_INTAKE_CONTROLLER/feeder.py" "${TOOLS_DIR}/BICC_INTAKE_CONTROLLER/"
cp "${ROOT_DIR}/BICC_INTAKE_CONTROLLER/config_template.json" "${TOOLS_DIR}/BICC_INTAKE_CONTROLLER/"
cp "${ROOT_DIR}/BICC_INTAKE_CONTROLLER/entity_mapping.csv" "${TOOLS_DIR}/BICC_INTAKE_CONTROLLER/"
cp "${ROOT_DIR}/BICC_INTAKE_CONTROLLER/lib/"*.py "${TOOLS_DIR}/BICC_INTAKE_CONTROLLER/lib/"
cp "${ROOT_DIR}/BICC_INTAKE_CONTROLLER/docs/"*.md "${TOOLS_DIR}/BICC_INTAKE_CONTROLLER/docs/"
cp "${ROOT_DIR}/BICC_INTAKE_CONTROLLER/docs/"*.md "${DOCS_DIR}/01_BICC_INTAKE_CONTROLLER/"

# 2. DATA_INGESTION_ORCHESTRATOR
echo "[3/4] Syncing DATA_INGESTION_ORCHESTRATOR..."
cp "${ROOT_DIR}/DATA_INGESTION_ORCHESTRATOR/orchestrator.py" "${TOOLS_DIR}/DATA_INGESTION_ORCHESTRATOR/"
cp "${ROOT_DIR}/DATA_INGESTION_ORCHESTRATOR/config_template.json" "${TOOLS_DIR}/DATA_INGESTION_ORCHESTRATOR/"
cp "${ROOT_DIR}/DATA_INGESTION_ORCHESTRATOR/entity_mapping.csv" "${TOOLS_DIR}/DATA_INGESTION_ORCHESTRATOR/"
cp "${ROOT_DIR}/DATA_INGESTION_ORCHESTRATOR/ddl_technical_tables.sql" "${TOOLS_DIR}/DATA_INGESTION_ORCHESTRATOR/"
cp "${ROOT_DIR}/DATA_INGESTION_ORCHESTRATOR/lib/"*.py "${TOOLS_DIR}/DATA_INGESTION_ORCHESTRATOR/lib/"
cp "${ROOT_DIR}/DATA_INGESTION_ORCHESTRATOR/docs/"*.md "${TOOLS_DIR}/DATA_INGESTION_ORCHESTRATOR/docs/"
cp "${ROOT_DIR}/DATA_INGESTION_ORCHESTRATOR/docs/"*.md "${DOCS_DIR}/02_DATA_INGESTION_ORCHESTRATOR/"

# 3. TPT_LOADER
echo "[4/4] Syncing TPT_LOADER..."
cp "${ROOT_DIR}/TPT_LOADER/load_csv_generic.sh" "${TOOLS_DIR}/TPT_LOADER/"
cp "${ROOT_DIR}/TPT_LOADER/unlock_tpt_table.sh" "${TOOLS_DIR}/TPT_LOADER/"
cp "${ROOT_DIR}/TPT_LOADER/jobvariables_template.txt" "${TOOLS_DIR}/TPT_LOADER/"
cp "${ROOT_DIR}/TPT_LOADER/config/"* "${TOOLS_DIR}/TPT_LOADER/config/"
cp "${ROOT_DIR}/TPT_LOADER/lib/"* "${TOOLS_DIR}/TPT_LOADER/lib/"
cp "${ROOT_DIR}/TPT_LOADER/docs/"*.md "${TOOLS_DIR}/TPT_LOADER/docs/"
cp "${ROOT_DIR}/TPT_LOADER/docs/"*.md "${DOCS_DIR}/03_TPT_LOADER/"

chmod +x "${TOOLS_DIR}/TPT_LOADER/"*.sh "${TOOLS_DIR}/TPT_LOADER/lib/"*.sh 2>/dev/null || true

echo "======================================================================"
echo " [OK] All 4 components and documentation suites synchronized."
echo "======================================================================"
