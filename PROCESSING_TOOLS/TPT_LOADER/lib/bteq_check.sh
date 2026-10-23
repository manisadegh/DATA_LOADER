#!/bin/bash
# ---------------------------------------------------------------------------
# Check the target table exists, has matching columns, and matching column order
# (accounting for optional INFA_BATCH_ID / INFA_LAST_REPLICATED metadata cols)
# ---------------------------------------------------------------------------

if [ "${SKIP_BTEQ_CHECK}" = "Y" ]; then
    HAS_META="${CLI_HAS_META:-2}"
    log INFO "Skipping BTEQ DBC.ColumnsV pre-check (-C specified; schema pre-validated by Orchestrator, HAS_META=${HAS_META})."
else
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
SELECT 'COLNAME=' || TRIM(ColumnName) (TITLE '')
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

    if [ "${HAS_META}" -eq 2 ]; then
        EXPECTED_COLS=$((HEADER_COLS + 2))
        [ "${TABLE_COLS}" -ne "${EXPECTED_COLS}" ] \
            && die 1 "Column count mismatch: file has ${HEADER_COLS} cols (+ 2 metadata expected = ${EXPECTED_COLS}), but ${FQ_TABLE} has ${TABLE_COLS}"
        log INFO "Target table found with ${TABLE_COLS} columns (including 2 metadata columns) - OK"
    else
        [ "${TABLE_COLS}" -ne "${HEADER_COLS}" ] \
            && die 1 "Column count mismatch: file has ${HEADER_COLS} columns, ${FQ_TABLE} has ${TABLE_COLS}"
        log INFO "Target table found with ${TABLE_COLS} columns - OK"
    fi

    # DAT-01 Fix: Positional and Named Column Alignment Check
    DB_COLS=()
    for c in $(echo "${BTEQ_OUT}" | grep '^COLNAME=' | cut -d= -f2- | tr '[:lower:]' '[:upper:]' | tr -d '\r'); do
        [ -n "$c" ] && DB_COLS+=( "$c" )
    done

    if [ "${SKIP_ROWS}" -gt 0 ]; then
        HEADER_LINE=$(head -1 "${FILES[0]}" | tr -d '\r')
        IFS="${DELIMITER}" read -r -a CSV_COLS_RAW <<< "${HEADER_LINE}"
        CSV_COLS=()
        for col in "${CSV_COLS_RAW[@]}"; do
            cleaned_col=$(clean_column_name "${col}")
            [ -n "${cleaned_col}" ] && CSV_COLS+=( "${cleaned_col}" )
        done

        if [ ${#CSV_COLS[@]} -ne ${#DB_COLS[@]} ]; then
            die 1 "Column count mismatch: CSV has ${#CSV_COLS[@]} columns, target table expects ${#DB_COLS[@]}"
        fi

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
