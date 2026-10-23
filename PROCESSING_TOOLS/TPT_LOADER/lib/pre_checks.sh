#!/bin/bash
# ---------------------------------------------------------------------------
# Pre-checks
# ---------------------------------------------------------------------------
[ -z "${TARGET_TABLE}" ]         && { usage; die 1 "-t <table> is mandatory"; }
[ -z "${TDPID}" ]                && die 1 "TDPID is not set"
[ -z "${TDENV+x}" ]              && log WARN "TDENV is not set - using no environment prefix"
[ -f "${TPT_TEMPLATE}" ]         || die 1 "TPT template not found: ${TPT_TEMPLATE}"

validate_identifier "${TARGET_DB}" "TARGET_DB"
validate_identifier "${TARGET_TABLE}" "TARGET_TABLE"
validate_identifier "${WRK_DB}" "WRK_DB"

# Verify tbuild and bteq (POSIX / Unix)
command -v tbuild >/dev/null 2>&1 || die 1 "tbuild not found in PATH"
command -v bteq   >/dev/null 2>&1 || die 1 "bteq not found in PATH"
TBUILD_CMD="tbuild"
BTEQ_CMD="bteq"

case "${LOAD_MODE}" in
    replace|append) ;;
    *) die 1 "-m must be 'replace' or 'append' (got '${LOAD_MODE}')" ;;
esac

# Validate file inputs (-f or -L)
if [ -n "${FILE_LIST}" ] && [ -n "${FILE_SPEC}" ]; then
    die 1 "-f and -L are mutually exclusive"
fi

if [ -n "${FILE_LIST}" ]; then
    [ -s "${FILE_LIST}" ] || die 1 "File list not found or empty: ${FILE_LIST}"
    mapfile -t FILES < <(tr -d '\r' < "${FILE_LIST}")
    [ ${#FILES[@]} -eq 0 ] && die 1 "File list contains no entries: ${FILE_LIST}"
    for f in "${FILES[@]}"; do
        [[ "${f}" = /* ]] || die 1 "File list entries must be absolute paths: ${f}"
        [ -s "${f}" ] || die 1 "File is empty or unreadable: ${f}"
    done
    USE_FILE_LIST="Y"
else
    [ -n "${FILE_SPEC}" ] || { usage; die 1 "-f <file|pattern> or -L <listfile> is mandatory"; }
    shopt -s nullglob
    FILES=( ${FILE_SPEC} )
    shopt -u nullglob
    [ ${#FILES[@]} -eq 0 ] && die 1 "No file matches: ${FILE_SPEC}"

    DIRECTORY_PATH="$(cd "$(dirname "${FILES[0]}")" && pwd)"
    FILE_NAME="$(basename "${FILE_SPEC}")"
    for f in "${FILES[@]}"; do
        [ "$(cd "$(dirname "${f}")" && pwd)" = "${DIRECTORY_PATH}" ] \
            || die 1 "All files must be in the same directory (pattern: ${FILE_SPEC})"
        [ -s "${f}" ] || die 1 "File is empty or unreadable: ${f}"
    done
    USE_FILE_LIST="N"
fi

FQ_TABLE="${TARGET_DB}.${TARGET_TABLE}"

# Password: Teradata Wallet by default; TD_PASSWORD overrides it (dev/sandpit only)
if [ -n "${TD_PASSWORD}" ]; then
    BTEQ_PWD="${TD_PASSWORD}"
    TPT_PWD="${TD_PASSWORD//\'/\'\'}"              # TPT: escape single quotes
    log WARN "TD_PASSWORD is set - using a plain password instead of Teradata Wallet"
else
    BTEQ_PWD="\$tdwallet(${TD_USER})"
    TPT_PWD="\"\$tdwallet(${TD_USER})\""
fi

# Deterministic first-file skipping (F1.9 step 3)
if [ "${SKIP_ROWS_EVERY_FILE}" = "N" ] && [ "${SKIP_ROWS}" -gt 0 ] && [ ${#FILES[@]} -gt 1 ]; then
    if [ "${READER_INSTANCES}" -gt 1 ]; then
        log INFO "Forcing ReaderInstances=1 for multi-file load with SkipRowsEveryFile=N to ensure deterministic first-file skipping"
        READER_INSTANCES=1
    fi
fi

# MultipleReaders (several instances on ONE file) is incompatible with a multi-file scan
MULTIPLE_READERS="N"
if [ "${USE_FILE_LIST}" = "Y" ]; then
    [ ${#FILES[@]} -eq 1 ] && [ ${READER_INSTANCES} -gt 1 ] && MULTIPLE_READERS="Y"
else
    case "${FILE_SPEC}" in
        *\**|*\?*) [ ${READER_INSTANCES} -gt ${#FILES[@]} ] && READER_INSTANCES=${#FILES[@]} ;;
        *)         [ ${READER_INSTANCES} -gt 1 ] && MULTIPLE_READERS="Y" ;;
    esac
fi

# Extract metadata from filename using patterns (F1.11: no date fallback)
FIRST_BASENAME="$(basename "${FILES[0]}")"
AUTO_BATCH_ID=""
[ -n "${BATCH_ID_PATTERN}" ] && AUTO_BATCH_ID=$(echo "${FIRST_BASENAME}" | sed -n "${BATCH_ID_PATTERN}")
BATCH_ID="${CLI_BATCH_ID:-${AUTO_BATCH_ID}}"

AUTO_TS=""
[ -n "${TIMESTAMP_PATTERN}" ] && AUTO_TS=$(echo "${FIRST_BASENAME}" | sed -n "${TIMESTAMP_PATTERN}")
META_TS="${CLI_TIMESTAMP:-${AUTO_TS}}"

# Normalize timestamp format YYYYMMDD_HHMMSS -> YYYY-MM-DD HH:MM:SS (avoids Teradata error 5404)
if [[ "${META_TS}" =~ ^([0-9]{4})([0-9]{2})([0-9]{2})_([0-9]{2})([0-9]{2})([0-9]{2})$ ]]; then
    META_TS="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}-${BASH_REMATCH[3]} ${BASH_REMATCH[4]}:${BASH_REMATCH[5]}:${BASH_REMATCH[6]}"
fi

log INFO "System      : ${TDPID}  user=${TD_USER}  (env prefix '${TDENV}')"
log INFO "Utility DB  : ${WRK_DB}"
log INFO "Target      : ${FQ_TABLE}  mode=${LOAD_MODE}"
