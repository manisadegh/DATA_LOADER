#!/bin/bash
#/***************************************************
# FDJ
#
# Finance domain - Oracle Fusion - Unlock TPT Table
#
# Unlocks a Teradata staging table that was left locked (FastLoad Paused 
# or MultiLoad Paused) after a failed TPT load.
# 
# Usage:
#   unlock_tpt_table.sh -t <table> -m replace|append [-j <job_name>] [-d <database>] [-u <user>] [-w <work_dir>]
#
#   -t  Target table name (mandatory)
#   -m  replace : Resumes failed TPT FastLoad job (requires -j <job_name>)
#       append  : Releases MultiLoad lock (RELEASE MLOAD) via BTEQ
#   -j  Exact TPT job name (mandatory in replace mode)
#   -d  Target database (default: ${TDENV}${DB_STG})
#   -u  Logon user (default: ${TD_LOGON_USER:-${TDENV}${SID_ADM_USER}})
#   -w  Work directory (default: ${TPT_WORK_DIR:-${SCRIPT_DIR}/tmp/tpt_work})
#
#****************************************************/

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"

source "${LIB_DIR}/env_and_helpers.sh"
source "${LIB_DIR}/parse_args.sh" "$@"

[ -z "${TARGET_TABLE}" ] && die 1 "Target table (-t or TargetTable in -v) is required."
[ -z "${TDPID}" ] && die 1 "TDPID environment variable is required."

validate_identifier "${TARGET_DB}" "TARGET_DB"
validate_identifier "${TARGET_TABLE}" "TARGET_TABLE"

FQ_TABLE="${TARGET_DB}.${TARGET_TABLE}"

BTEQ_CMD="bteq"
command -v "${BTEQ_CMD}" >/dev/null || die 1 "bteq not found in PATH."

if [ -n "${TD_PASSWORD}" ]; then
    BTEQ_PWD="${TD_PASSWORD}"
else
    BTEQ_PWD="\$tdwallet(${TD_USER})"
fi

if [ "${LOAD_MODE}" = "append" ]; then
    log INFO "Mode is 'append' (MultiLoad). Sending RELEASE MLOAD to ${FQ_TABLE}..."

    BTEQ_OUT=$(${BTEQ_CMD} <<EOF 2>&1
.logon ${TDPID}/${TD_USER},${BTEQ_PWD}
RELEASE MLOAD ${FQ_TABLE};
.logoff
.quit
EOF
)
    BTEQ_RC=$?
    if [ ${BTEQ_RC} -ne 0 ]; then
        echo "${BTEQ_OUT}"
        die 2 "Failed to unlock table (bteq rc=${BTEQ_RC})."
    fi
    log INFO "Table ${FQ_TABLE} unlocked successfully."

else
    log INFO "Mode is 'replace' (FastLoad). Resuming interrupted TPT LOAD job to unlock ${FQ_TABLE}..."
    
    [ -n "${CLI_JOB_NAME}" ] || die 1 "-j <job_name> is mandatory in replace mode (the exact TPT job name of the failed load)"
    JOB_NAME="${CLI_JOB_NAME}"
    LAST_JOB_DIR="${WORK_DIR}/${JOB_NAME}"
    [ -d "${LAST_JOB_DIR}" ] || die 1 "Job directory not found: ${LAST_JOB_DIR}"
    JOBVARS="${LAST_JOB_DIR}/jobvars.txt"
    JOB_TPT="${LAST_JOB_DIR}/job.tpt"
    [ -f "${JOBVARS}" ] && [ -f "${JOB_TPT}" ] || die 1 "jobvars.txt or job.tpt missing in ${LAST_JOB_DIR}"

    log INFO "Resuming identified job: ${JOB_NAME}. Attempting TPT restart..."
    
    TBUILD_CMD="tbuild"
    command -v "${TBUILD_CMD}" >/dev/null || die 1 "tbuild not found in PATH."

    log INFO "Executing TPT resume: ${TBUILD_CMD} -f ${JOB_TPT} -v ${JOBVARS} -j ${JOB_NAME}"
    ${TBUILD_CMD} -f "${JOB_TPT}" -v "${JOBVARS}" -j "${JOB_NAME}"
    RC=$?
    
    if [ $RC -eq 0 ] || [ $RC -eq 4 ]; then
        log INFO "TPT job resumed and completed successfully. Table ${FQ_TABLE} is now unlocked."
    else
        die 2 "TPT job restart failed (rc=${RC}). Fix the underlying data/table error or recreate the staging table."
    fi
fi

exit 0
