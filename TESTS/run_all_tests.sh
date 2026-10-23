#!/bin/bash
# ==============================================================================
# DATA_LOADER - MASTER TEST RUNNER (UNIX / BASH)
# Orchestrates test scenarios against native DATA_LOADER runtime directories
#
# Execution sequence:
#   1. Phase 1 (Pre-Flight): In-memory unit tests (TESTS/unit/ + test_phase01_units.py)
#      and architectural invariants (< 80 lines).
#   2. Phase 2: Live Teradata end-to-end integration scenarios (09, 08, 01..07, 10, 11).
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIOS_DIR="${SCRIPT_DIR}/scenarios"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUTPUTS_DIR="${SCRIPT_DIR}/OUTPUTS"

COMMON_DIR="${BASE_DIR}/PROCESSING_TOOLS/COMMON"
FEEDER_DIR="${BASE_DIR}/PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER"
ORCH_DIR="${BASE_DIR}/PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR"
TPT_DIR="${BASE_DIR}/PROCESSING_TOOLS/TPT_LOADER"

GREEN="\033[92m"
RED="\033[91m"
CYAN="\033[96m"
YELLOW="\033[93m"
BOLD="\033[1m"
RESET="\033[0m"

print_banner() {
    echo -e "${CYAN}==============================================================================${RESET}"
    echo -e "${BOLD}${CYAN}   DATA_LOADER AUTOMATED TEST SUITE (UNIX RUNTIME)${RESET}"
    echo -e "${CYAN}==============================================================================${RESET}"
}

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --all              Execute unit tests then all scenarios (01 to 11) [Default]"
    echo "  --unit-only, -u    Execute in-memory unit tests and invariants only (fast, no Teradata)"
    echo "  --scenario <1..11> Execute a specific test scenario"
    echo "  --clean            Clean DATA and LOGS directories only"
    echo "  --help, -h         Display this help message"
    echo ""
    echo "Scenarios available:"
    echo "  1: Nominal End-to-End Ingestion Pipeline"
    echo "  2: Hybrid Decoupling (--skip-post-tasks)"
    echo "  3: Concurrency & Active Wait Loop"
    echo "  4: In-Flight Crash Recovery & Stale PID Cleanup"
    echo "  5: Multi-Source Directory Partitioning Isolation"
    echo "  6: Intake Controller Source Post-Tasks & Skip Validation"
    echo "  7: Teradata Vantage Deep DB & Storage Cleanliness Audit"
    echo "  8: Lock Recovery Metadata & Schema Guard Flags"
    echo "  9: Core SDK Unit Tests & Connection Pool Validation"
    echo "  10: Decoupled Multi-Batch Queue & JIT Schema Guard"
    echo "  11: Multi-Source Plugin Framework & Global Utility Slot Governor"
}

run_unit_tests() {
    mkdir -p "${OUTPUTS_DIR}"
    local LOG_FILE="${OUTPUTS_DIR}/scenario_00_unit_tests_console.log"

    echo -e "\n${BOLD}${YELLOW}>>> [PHASE 1] EXECUTING IN-MEMORY UNIT TESTS & ARCHITECTURAL INVARIANTS${RESET}"
    echo -e "${CYAN}    - Discovery Suite: TESTS/unit/test_*.py (Core SDK, Mapping, Schema Guard)${RESET}"
    echo -e "${CYAN}    - Isolated Suite : TESTS/test_phase01_units.py (Phase 01 Parity & Flags)${RESET}"
    echo -e "${CYAN}    - Invariants     : Entrypoint line limits (< 80 lines) & deduplication${RESET}\n"

    local START_TIME=$(date +%s)
    local ALL_OK=0

    export PYTHONPATH="${COMMON_DIR}:${FEEDER_DIR}:${ORCH_DIR}:${TPT_DIR}/lib:${PYTHONPATH}"

    # 1. Discover unit tests in TESTS/unit/
    echo -e "${BOLD}>>> Running Discovery Suite (TESTS/unit/test_*.py)...${RESET}"
    if python3 -m unittest discover -s "${SCRIPT_DIR}/unit" -p "test_*.py" -v 2>&1 | tee "${LOG_FILE}"; then
        echo -e "${GREEN}[PASS] Discovery Suite passed.${RESET}\n"
    else
        echo -e "${RED}[FAIL] Discovery Suite failed.${RESET}"
        ALL_OK=1
    fi

    # 2. Phase 01 Isolated Units
    echo -e "${BOLD}>>> Running Phase 01 Units (TESTS/test_phase01_units.py)...${RESET}"
    if python3 "${SCRIPT_DIR}/test_phase01_units.py" 2>&1 | tee -a "${LOG_FILE}"; then
        echo -e "${GREEN}[PASS] Phase 01 Units passed.${RESET}\n"
    else
        echo -e "${RED}[FAIL] Phase 01 Units failed.${RESET}"
        ALL_OK=1
    fi

    # 3. Architectural Invariants
    echo -e "${BOLD}>>> Verifying Architectural Invariants (< 80 lines)...${RESET}"
    local FEEDER_LINES=$(wc -l < "${FEEDER_DIR}/feeder.py")
    local ORCH_LINES=$(wc -l < "${ORCH_DIR}/orchestrator.py")
    echo "  - feeder.py line count       : ${FEEDER_LINES} (limit: < 80)" | tee -a "${LOG_FILE}"
    echo "  - orchestrator.py line count : ${ORCH_LINES} (limit: < 80)" | tee -a "${LOG_FILE}"

    if [ "${FEEDER_LINES}" -ge 80 ] || [ "${ORCH_LINES}" -ge 80 ]; then
        echo -e "${RED}>>> [FAILURE] Entrypoint line count exceeded 80 lines!${RESET}" | tee -a "${LOG_FILE}"
        ALL_OK=1
    else
        echo -e "${GREEN}[PASS] Architectural invariants verified.${RESET}\n"
    fi

    local DURATION=$(( $(date +%s) - START_TIME ))

    if [ ${ALL_OK} -eq 0 ]; then
        echo -e "${GREEN}${BOLD}>>> [PASS] All unit tests & architectural invariants succeeded in ${DURATION}s.${RESET}"
        return 0
    else
        echo -e "${RED}${BOLD}>>> [FAIL] Unit tests failed! Halting before end-to-end scenarios.${RESET}"
        return 1
    fi
}

run_scenario() {
    local SCENARIO_NUM="$1"
    local SCRIPT_NAME=""
    
    case "${SCENARIO_NUM}" in
        1|01) SCRIPT_NAME="01_test_nominal_pipeline.sh" ;;
        2|02) SCRIPT_NAME="02_test_skip_post_tasks.sh" ;;
        3|03) SCRIPT_NAME="03_test_concurrency_lock.sh" ;;
        4|04) SCRIPT_NAME="04_test_crash_stale_pid.sh" ;;
        5|05) SCRIPT_NAME="05_test_multisource_partition.sh" ;;
        6|06) SCRIPT_NAME="06_test_intake_controller_post_tasks.sh" ;;
        7|07) SCRIPT_NAME="07_test_database_and_storage_audit.sh" ;;
        8|08) SCRIPT_NAME="08_test_lock_recovery_and_schema_flags.sh" ;;
        9|09) SCRIPT_NAME="09_test_unit_and_core_sdk.sh" ;;
        10) SCRIPT_NAME="10_test_decoupled_multi_batch_queue.sh" ;;
        11) SCRIPT_NAME="11_test_multisource_plugin_and_slot_governor.sh" ;;
        *)
            echo -e "${RED}Invalid scenario number: ${SCENARIO_NUM}${RESET}"
            exit 1
            ;;
    esac

    local FULL_PATH="${SCENARIOS_DIR}/${SCRIPT_NAME}"
    if [ ! -f "${FULL_PATH}" ]; then
        echo -e "${RED}Test script not found: ${FULL_PATH}${RESET}"
        exit 1
    fi

    echo -e "\n${BOLD}${YELLOW}>>> LAUNCHING SCENARIO ${SCENARIO_NUM} : ${SCRIPT_NAME}${RESET}"
    local START_TIME=$(date +%s)
    
    if bash "${FULL_PATH}"; then
        local DURATION=$(( $(date +%s) - START_TIME ))
        echo -e "${GREEN}${BOLD}>>> [PASS] Scenario ${SCENARIO_NUM} succeeded in ${DURATION}s.${RESET}"
        return 0
    else
        local DURATION=$(( $(date +%s) - START_TIME ))
        echo -e "${RED}${BOLD}>>> [FAIL] Scenario ${SCENARIO_NUM} failed after ${DURATION}s.${RESET}"
        return 1
    fi
}

# Parse options
MODE="all"
TARGET_SCENARIO=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --all)
            MODE="all"
            shift
            ;;
        --unit-only|-u)
            MODE="unit_only"
            shift
            ;;
        --clean)
            MODE="clean"
            shift
            ;;
        --scenario|-s)
            MODE="scenario"
            TARGET_SCENARIO="$2"
            shift 2
            ;;
        1|2|3|4|5|6|7|8|9|10|11)
            MODE="scenario"
            TARGET_SCENARIO="$1"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${RESET}"
            usage
            exit 1
            ;;
    esac
done

print_banner

if [ "${MODE}" = "clean" ]; then
    bash "${SCRIPT_DIR}/clean_data_and_logs.sh"
    exit 0
fi

if [ "${MODE}" = "unit_only" ]; then
    if run_unit_tests; then
        exit 0
    else
        exit 1
    fi
fi

if [ "${MODE}" = "scenario" ]; then
    if run_scenario "${TARGET_SCENARIO}"; then
        exit 0
    else
        exit 1
    fi
fi

# Default --all mode: Execute Phase 1 (Unit Tests) first, then Phase 2 (Scenarios)
echo -e "${BOLD}Execution Sequence:${RESET}"
echo "  1. Phase 1: In-Memory Unit Tests & Invariants Pre-Flight"
echo "  2. Phase 2: Live End-to-End Scenarios (09, 08, 01..07, 10, 11)"

if ! run_unit_tests; then
    echo -e "\n${RED}${BOLD}Stopping test execution: Unit tests failed before end-to-end scenarios.${RESET}"
    exit 1
fi

echo -e "\n${BOLD}${YELLOW}>>> [PHASE 2] EXECUTING LIVE END-TO-END INTEGRATION SCENARIOS${RESET}"
FAILED_TESTS=0
# Unit-focused and lock scenarios run first, followed by nominal cascade and advanced queues
for S in 9 8 1 2 3 4 5 6 7 10 11; do
    if ! run_scenario "${S}"; then
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo -e "${RED}${BOLD}Pipeline stopped due to scenario failure (FAIL_STOP).${RESET}"
        break
    fi
done

# Bundle all outputs into a tar.gz archive for easy transfer
if [ -d "${SCRIPT_DIR}/OUTPUTS" ]; then
    BUNDLE_NAME="all_test_outputs_$(date +%Y%m%d_%H%M%S).tar.gz"
    LATEST_BUNDLE="all_test_outputs_latest.tar.gz"
    (
        cd "${SCRIPT_DIR}/OUTPUTS" && \
        tar -czf "${BUNDLE_NAME}" $(ls | grep -v '\.tar\.gz$') 2>/dev/null && \
        cp -f "${BUNDLE_NAME}" "${LATEST_BUNDLE}" 2>/dev/null
    ) || true
    echo -e "${CYAN}>>> All scenario outputs archived in : ${SCRIPT_DIR}/OUTPUTS/${RESET}"
    echo -e "${CYAN}    Archive tarball created           : ${SCRIPT_DIR}/OUTPUTS/${LATEST_BUNDLE}${RESET}"
fi

echo -e "\n${CYAN}==============================================================================${RESET}"
if [ ${FAILED_TESTS} -eq 0 ]; then
    echo -e "${GREEN}${BOLD}>>> ALL TEST SCENARIOS COMPLETED SUCCESSFULLY (100% PASS) !${RESET}"
    echo -e "${CYAN}==============================================================================${RESET}"
    exit 0
else
    echo -e "${RED}${BOLD}>>> TEST SUITE FAILED WITH ${FAILED_TESTS} ERROR(S). Review ${SCRIPT_DIR}/OUTPUTS/${RESET}"
    echo -e "${CYAN}==============================================================================${RESET}"
    exit 1
fi
