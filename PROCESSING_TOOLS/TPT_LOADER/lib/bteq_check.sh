#!/bin/bash
# ---------------------------------------------------------------------------
# Check the target table exists, retrieve columns metadata into columns.txt,
# and validate field counts and positional alignment
# ---------------------------------------------------------------------------

# Setup run timestamp, job name and private run directory (F1.1 & F1.4)
RUN_TS="$(date '+%Y%m%d_%H%M%S')"
if [ -n "${CLI_JOB_NAME}" ]; then
    [[ "${CLI_JOB_NAME}" =~ ^[A-Za-z0-9_]{1,120}$ ]] || die 1 "-j job name may contain only letters, digits and underscore"
    JOB_NAME="${CLI_JOB_NAME}"
else
    JOB_NAME="TPT_${TARGET_TABLE}_${RUN_TS}"
fi
RUN_DIR="${WORK_DIR}/${JOB_NAME}"
mkdir -p "${RUN_DIR}" && chmod 700 "${RUN_DIR}" || die 1 "Cannot create work dir ${RUN_DIR}"

# Unconditional BTEQ query for table existence, audit columns, and column definitions
BTEQ_OUT=$(${BTEQ_CMD} <<EOF 2>&1
.set WIDTH 256
.set TITLEDASHES OFF
.logon ${TDPID}/${TD_USER},${BTEQ_PWD}
.if ErrorCode <> 0 Then .Goto ERR_CONNEXION
SELECT 'NBCOL=' || TRIM(COUNT(*)) (TITLE '')
FROM DBC.ColumnsV
WHERE DatabaseName = '${TARGET_DB}' AND TableName = '${TARGET_TABLE}';
SELECT 'HAS_META=' || TRIM(COUNT(*)) (TITLE '')
FROM DBC.ColumnsV
WHERE DatabaseName = '${TARGET_DB}' AND TableName = '${TARGET_TABLE}'
  AND ColumnName IN ('INFA_BATCH_ID', 'INFA_LAST_REPLICATED');
SELECT 'COLDEF=' || TRIM(ColumnName) || '|' || TRIM(ColumnType) || '|'
       || TRIM(COALESCE(ColumnLength, 0)) || '|' || TRIM(COALESCE(CharType, 0)) || '|'
       || TRIM(COALESCE(DecimalTotalDigits, 0)) || '|' || TRIM(COALESCE(DecimalFractionalDigits, 0)) (TITLE '')
FROM DBC.ColumnsV
WHERE DatabaseName = '${TARGET_DB}' AND TableName = '${TARGET_TABLE}'
  AND ColumnName NOT IN ('INFA_BATCH_ID', 'INFA_LAST_REPLICATED')
ORDER BY ColumnId;
.if ErrorCode <> 0 Then .Goto ERR_EXEC
.logoff
.exit 0
.LABEL ERR_EXEC
.exit 1
.LABEL ERR_CONNEXION
.exit 2
EOF
)
BTEQ_RC=$?
if [ ${BTEQ_RC} -ne 0 ]; then
    echo "${BTEQ_OUT}"
    die 2 "BTEQ pre-check failed (rc=${BTEQ_RC}) - connection or metadata query error"
fi

TABLE_COLS=$(echo "${BTEQ_OUT}" | grep -o 'NBCOL=[0-9][0-9]*' | head -1 | cut -d= -f2)
HAS_META=$(echo "${BTEQ_OUT}" | grep -o 'HAS_META=[0-9][0-9]*' | head -1 | cut -d= -f2)
[ -z "${HAS_META}" ] && HAS_META=0

[ -z "${TABLE_COLS}" ] || [ "${TABLE_COLS}" -eq 0 ] \
    && die 2 "Target table ${FQ_TABLE} does not exist"

if [ "${HAS_META}" -eq 1 ]; then
    die 1 "${FQ_TABLE} has exactly one of INFA_BATCH_ID / INFA_LAST_REPLICATED; it must have both or neither"
fi

echo "${BTEQ_OUT}" | grep '^COLDEF=' | sed 's/^COLDEF=//' | tr -d '\r' > "${RUN_DIR}/columns.txt"
PAYLOAD_COL_COUNT=$(wc -l < "${RUN_DIR}/columns.txt" | tr -d ' ')

# Header field extraction
if [ "${SKIP_ROWS}" -gt 0 ]; then
    mapfile -t CSV_COLS < <(python3 "${LIB_DIR}/parse_header.py" "${FILES[0]}" "${DELIMITER}")
    HEADER_COLS=${#CSV_COLS[@]}
else
    HEADER_COLS=$(head -1 "${FILES[0]}" | tr -d '\r' | awk -F"${DELIMITER}" '{print NF}')
fi

# Field-count pre-check runs unconditionally, even with -C (F1.1 step 6 & F1.5)
if [ "${PAYLOAD_COL_COUNT}" -ne "${HEADER_COLS}" ]; then
    die 1 "Column count mismatch: file has ${HEADER_COLS} fields, ${FQ_TABLE} has ${PAYLOAD_COL_COUNT} payload columns"
fi

# Named column alignment check (skipped when -C is given)
if [ "${SKIP_BTEQ_CHECK}" = "Y" ]; then
    log INFO "Skipping header column name validation (-C specified; schema pre-validated by Orchestrator, HAS_META=${HAS_META})"
elif [ "${SKIP_ROWS}" -gt 0 ]; then
    mapfile -t DB_COLS < <(cut -d'|' -f1 "${RUN_DIR}/columns.txt" | tr '[:lower:]' '[:upper:]')
    for ((i=0; i<${#CSV_COLS[@]}; i++)); do
        csv_col="${CSV_COLS[$i]}"
        db_col="${DB_COLS[$i]}"
        if [ "${csv_col}" != "${db_col}" ]; then
            die 1 "Column order/name mismatch at position $((i+1)): CSV has '${csv_col}', but ${FQ_TABLE} expects '${db_col}'"
        fi
    done
    log INFO "Column names and physical order validated successfully (${#CSV_COLS[@]} columns match) - OK"
else
    log INFO "SkipRows is 0 (headless CSV / normalized chunks) - skipping header column name validation"
fi

# Validate batch metadata presence (F1.11)
if [ "${HAS_META}" -eq 2 ]; then
    [ -n "${BATCH_ID}" ] || die 1 "${FQ_TABLE} has audit columns: -B <batch_id> (or -b pattern) is mandatory"
    [ -n "${META_TS}"  ] || die 1 "${FQ_TABLE} has audit columns: -T <timestamp> (or -c pattern) is mandatory"
else
    if [ -n "${BATCH_ID}" ] || [ -n "${META_TS}" ]; then
        log INFO "Target table ${FQ_TABLE} has no audit columns (HAS_META=0); ignoring batch metadata."
    fi
fi

# DAT-02 Fix: Metadata integrity check in append mode (protect against historical NULL overwrite)
if [ "${LOAD_MODE}" = "append" ] && [ "${HAS_META}" -eq 2 ]; then
    log INFO "Checking for orphan NULL metadata in ${FQ_TABLE} before append..."
    NULL_CNT_OUT=$(${BTEQ_CMD} <<EOF 2>&1
.set WIDTH 256
.set TITLEDASHES OFF
.logon ${TDPID}/${TD_USER},${BTEQ_PWD}
.if ErrorCode <> 0 Then .exit 2
SELECT 'NULL_CNT=' || TRIM(COUNT(*)) (TITLE '')
FROM ${FQ_TABLE}
WHERE INFA_BATCH_ID IS NULL;
.if ErrorCode <> 0 Then .exit 1
.logoff
.exit 0
EOF
)
    NULL_CNT_RC=$?
    if [ ${NULL_CNT_RC} -ne 0 ]; then
        echo "${NULL_CNT_OUT}"
        die 2 "BTEQ check failed: unable to query metadata integrity in ${FQ_TABLE} (rc=${NULL_CNT_RC})"
    fi
    NULL_COUNT=$(echo "${NULL_CNT_OUT}" | grep -o 'NULL_CNT=[0-9][0-9]*' | head -1 | cut -d= -f2)
    if [ -n "${NULL_COUNT}" ] && [ "${NULL_COUNT}" -gt 0 ]; then
        die 1 "Integrity violation: Target table ${FQ_TABLE} contains ${NULL_COUNT} row(s) with NULL INFA_BATCH_ID in append mode. Operation aborted to protect historical metadata."
    fi
    log INFO "Append metadata check passed: no orphan NULL INFA_BATCH_ID found in ${FQ_TABLE} - OK"
fi
