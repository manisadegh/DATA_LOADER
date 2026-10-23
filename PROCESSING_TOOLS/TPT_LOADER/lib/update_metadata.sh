#!/bin/bash
# ---------------------------------------------------------------------------
# Populate metadata columns (INFA_BATCH_ID, INFA_LAST_REPLICATED) if present
# ---------------------------------------------------------------------------
if [ "${HAS_META}" -eq 2 ]; then
    if [ -z "${BATCH_ID}" ] && [ -z "${META_TS}" ]; then
        log WARN "Metadata columns exist in ${FQ_TABLE} but neither batch ID nor timestamp could be determined"
    else
        SAFE_BATCH_ID="$(escape_sql_literal "${BATCH_ID}")"
        SAFE_META_TS="$(escape_sql_literal "${META_TS}")"
        log INFO "Populating metadata columns in ${FQ_TABLE} (batch='${BATCH_ID:-N/A}', ts='${META_TS}')..."
        META_BTEQ_OUT=$(${BTEQ_CMD} <<EOF 2>&1
.set WIDTH 256
.logon ${TDPID}/${TD_USER},${BTEQ_PWD}
.if ErrorCode <> 0 Then .exit 2
UPDATE ${FQ_TABLE}
SET INFA_BATCH_ID = '${SAFE_BATCH_ID}',
    INFA_LAST_REPLICATED = '${SAFE_META_TS}'
WHERE INFA_BATCH_ID IS NULL;
.if ErrorCode <> 0 Then .exit 1
.logoff
.exit 0
EOF
)
        META_BTEQ_RC=$?
        if [ ${META_BTEQ_RC} -ne 0 ]; then
            echo "${META_BTEQ_OUT}"
            die 3 "Failed to update metadata columns in ${FQ_TABLE} (bteq rc=${META_BTEQ_RC})"
        fi
        log INFO "Metadata columns updated successfully"
    fi
fi
