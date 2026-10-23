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
#   unlock_tpt_table.sh -t <table> [-d <database>] [-u <user>] [-m replace|append] [-v <jobvariables_file>]
#
#   -t  Target table name (mandatory unless specified in -v)
#   -d  Target database (default: ${TDENV}${DB_STG})
#   -u  Logon user (default: ${TDENV}${SID_ADM_USER})
#   -m  replace : Tries to restart the last failed TPT job to resolve the lock
#       append  : Releases MultiLoad lock (RELEASE MLOAD) via BTEQ
#   -v  Job variables configuration file. Values in this file serve as defaults.
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
    
    # Locate the latest job directory generated for this target table
    LAST_JOB_DIR=$(ls -1td "${WORK_DIR}/LOAD_${TARGET_TABLE}_"* "${WORK_DIR}/TPT_${TARGET_TABLE}_"* "${WORK_DIR}/"*${TARGET_TABLE}* 2>/dev/null | head -1)
    
    if [ -z "${LAST_JOB_DIR}" ]; then
        die 1 "Unable to locate previous job history in ${WORK_DIR} for table ${TARGET_TABLE}. To unlock the table manually without resuming the job, drop and recreate the table."
    fi
    
    JOB_NAME=$(basename "${LAST_JOB_DIR}")
    log INFO "Latest job identified: ${JOB_NAME}. Attempting TPT restart..."
    
    TBUILD_CMD="tbuild"
    command -v "${TBUILD_CMD}" >/dev/null || die 1 "tbuild not found in PATH."

    JOBVARS="${LAST_JOB_DIR}/jobvars.txt"
    TPT_SCRIPT="${LIB_DIR}/load_csv_generic.tpt"
    
    log INFO "Executing TPT resume: ${TBUILD_CMD} -f ${TPT_SCRIPT} -v ${JOBVARS} -j ${JOB_NAME}"
    ${TBUILD_CMD} -f "${TPT_SCRIPT}" -v "${JOBVARS}" -j "${JOB_NAME}"
    RC=$?
    
    if [ $RC -eq 0 ] || [ $RC -eq 4 ]; then
        log INFO "TPT job resumed and completed successfully. Table ${FQ_TABLE} is now unlocked."
        
        # Resolve BATCH_ID and META_TS from CLI (-B / -T) or fallback to jobvars.txt
        BATCH_ID="${CLI_BATCH_ID}"
        META_TS="${CLI_TIMESTAMP}"
        if [ -f "${JOBVARS}" ]; then
            if [ -z "${BATCH_ID}" ]; then
                BATCH_ID=$(grep -i "^[[:space:]]*BatchId[[:space:]]*=" "${JOBVARS}" | tail -1 | sed -E "s/^[^=]+=[[:space:]]*//; s/[[:space:]]*$//; s/^['\"]//; s/['\"]$//" | tr -d '\r')
            fi
            if [ -z "${META_TS}" ]; then
                META_TS=$(grep -i "^[[:space:]]*Timestamp[[:space:]]*=" "${JOBVARS}" | tail -1 | sed -E "s/^[^=]+=[[:space:]]*//; s/[[:space:]]*$//; s/^['\"]//; s/['\"]$//" | tr -d '\r')
            fi
        fi

        # Normalize timestamp format YYYYMMDD_HHMMSS -> YYYY-MM-DD HH:MM:SS
        if [[ "${META_TS}" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
            META_TS="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}"
        fi

        if [ -z "${BATCH_ID}" ] || [ -z "${META_TS}" ]; then
            CURRENT_EPOCH="$(date '+%s')"
            CURRENT_ISO="$(date '+%Y-%m-%d %H:%M:%S')"
            [ -z "${BATCH_ID}" ] && BATCH_ID="${CURRENT_EPOCH}"
            [ -z "${META_TS}" ]  && META_TS="${CURRENT_ISO}"
        fi

        # Query HAS_META on the target table and backfill INFA_BATCH_ID / INFA_LAST_REPLICATED
        META_CHK_OUT=$(${BTEQ_CMD} <<EOF 2>&1
.set WIDTH 256
.set TITLEDASHES OFF
.logon ${TDPID}/${TD_USER},${BTEQ_PWD}
.if ErrorCode <> 0 Then .exit 2
SELECT 'HAS_META=' || TRIM(COUNT(*)) (TITLE '')
FROM DBC.ColumnsV
WHERE DatabaseName = '${TARGET_DB}' AND TableName = '${TARGET_TABLE}'
  AND ColumnName IN ('INFA_BATCH_ID', 'INFA_LAST_REPLICATED');
.logoff
.exit 0
EOF
)
        HAS_META=$(echo "${META_CHK_OUT}" | grep -o 'HAS_META=[0-9][0-9]*' | head -1 | cut -d= -f2)
        [ -z "${HAS_META}" ] && HAS_META=0

        source "${LIB_DIR}/update_metadata.sh"
    else
        die 2 "TPT job restart failed (rc=${RC}). Fix the underlying data/table error or recreate the staging table."
    fi
fi

exit 0
