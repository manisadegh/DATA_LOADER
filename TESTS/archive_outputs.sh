#!/bin/bash
# ==============================================================================
# DATA_LOADER - Test Artifacts & Outputs Archiver
# Captures all logs, generated files, receipts and diagnostic data per scenario
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="${SCRIPT_DIR}"
BASE_DIR="$(cd "${TESTS_DIR}/.." && pwd)"
DATA_DIR="${BASE_DIR}/DATA"
LOGS_DIR="${BASE_DIR}/LOGS"
OUTPUTS_DIR="${TESTS_DIR}/OUTPUTS"

SCENARIO_NAME="${1:-unknown_scenario}"
SCENARIO_STATUS="${2:-UNKNOWN}" # PASS or FAIL
EXIT_CODE="${3:-0}"

SCENARIO_OUT_DIR="${OUTPUTS_DIR}/${SCENARIO_NAME}"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

mkdir -p "${SCENARIO_OUT_DIR}"

echo "=============================================================================="
echo ">>> [ARCHIVING ARTIFACTS] Archiving outputs for : ${SCENARIO_NAME}"
echo "    Status : ${SCENARIO_STATUS} (Exit code: ${EXIT_CODE})"
echo "    Target : ${SCENARIO_OUT_DIR}"
echo "=============================================================================="

# 1. Archive LOGS
mkdir -p "${SCENARIO_OUT_DIR}/LOGS"
if [ -d "${LOGS_DIR}" ]; then
    cp -r "${LOGS_DIR}"/* "${SCENARIO_OUT_DIR}/LOGS/" 2>/dev/null || true
    LOG_COUNT=$(find "${SCENARIO_OUT_DIR}/LOGS" -type f | wc -l)
    echo "  - Archived ${LOG_COUNT} log file(s)."
fi

# 2. Archive ARCHIVE_ZONE deliverables
mkdir -p "${SCENARIO_OUT_DIR}/ARCHIVE_ZONE"
if [ -d "${DATA_DIR}/ARCHIVE_ZONE" ]; then
    cp -r "${DATA_DIR}/ARCHIVE_ZONE"/* "${SCENARIO_OUT_DIR}/ARCHIVE_ZONE/" 2>/dev/null || true
    ARCHIVE_COUNT=$(find "${SCENARIO_OUT_DIR}/ARCHIVE_ZONE" -type f | wc -l)
    echo "  - Archived ${ARCHIVE_COUNT} file(s) from ARCHIVE_ZONE."
fi

# 3. Quick-Access Raw Receipts (Collected directly from batch capsules)
mkdir -p "${SCENARIO_OUT_DIR}/RAW_RECEIPTS"
find "${DATA_DIR}/ARCHIVE_ZONE" -type f -name "RECEIPT_*.json" -exec cp {} "${SCENARIO_OUT_DIR}/RAW_RECEIPTS/" 2>/dev/null \; || true
RECEIPT_COUNT=$(find "${SCENARIO_OUT_DIR}/RAW_RECEIPTS" -type f | wc -l)
echo "  - Archived ${RECEIPT_COUNT} receipt file(s) into RAW_RECEIPTS."

# 4. Capture any remaining transit files (valuable for debugging failures)
mkdir -p "${SCENARIO_OUT_DIR}/REMAINING_IN_TRANSIT"
for ZONE in "DROP_ZONE" "LANDING_ZONE" "LOADING_ZONE"; do
    ZONE_PATH="${DATA_DIR}/${ZONE}"
    if [ -d "${ZONE_PATH}" ]; then
        # Copy everything except the nested ARCHIVE folder in DROP_ZONE
        mkdir -p "${SCENARIO_OUT_DIR}/REMAINING_IN_TRANSIT/${ZONE}"
        find "${ZONE_PATH}" -maxdepth 2 -not -path "*/ARCHIVE*" -not -path "${ZONE_PATH}" -exec cp -r {} "${SCENARIO_OUT_DIR}/REMAINING_IN_TRANSIT/${ZONE}/" 2>/dev/null \; || true
    fi
done

# 5. Generate Execution Summary Report
REPORT_FILE="${SCENARIO_OUT_DIR}/execution_summary.txt"
cat << EOF > "${REPORT_FILE}"
==============================================================================
DATA_LOADER - TEST SCENARIO EXECUTION SUMMARY
==============================================================================
Scenario Name : ${SCENARIO_NAME}
Execution Date: ${TIMESTAMP}
Status        : ${SCENARIO_STATUS}
Exit Code     : ${EXIT_CODE}

--- Environment Context ---
TDENV         : ${TDENV:-Not Set}
ENV           : ${ENV:-Not Set}
TDPID         : ${TDPID:-Not Set}
SID_ADM_USER  : ${SID_ADM_USER:-Not Set}
LANG          : ${LANG:-Not Set}

--- Archived Artifacts Summary ---
Logs Directory        : LOGS/ (${LOG_COUNT:-0} files)
Archive Zone Files    : ARCHIVE_ZONE/ (${ARCHIVE_COUNT:-0} files)
Vault & Receipts      : RAW_RECEIPTS/ (${RECEIPT_COUNT:-0} files)
Remaining In Transit  : REMAINING_IN_TRANSIT/

--- Inventory of Archived Deliverables ---
$(find "${SCENARIO_OUT_DIR}" -type f -exec ls -la {} + 2>/dev/null)

--- Recent Log Extracts ---
EOF

# Append tail of logs if available
for L in $(find "${SCENARIO_OUT_DIR}/LOGS" -type f -name "*.log" 2>/dev/null); do
    if [ -f "$L" ]; then
        echo -e "\n>>> File: $(basename "$L") (Last 40 lines):" >> "${REPORT_FILE}"
        echo "------------------------------------------------------------------------------" >> "${REPORT_FILE}"
        tail -n 40 "$L" >> "${REPORT_FILE}" 2>/dev/null || true
    fi
done

echo ">>> [ARCHIVING COMPLETED] Summary saved to: ${REPORT_FILE}"
echo "=============================================================================="
