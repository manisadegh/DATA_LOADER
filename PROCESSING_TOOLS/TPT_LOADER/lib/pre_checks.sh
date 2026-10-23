#!/bin/bash
# ---------------------------------------------------------------------------
# Pre-checks
# ---------------------------------------------------------------------------
[ -z "${FILE_SPEC}" ]            && { usage; die 1 "-f <file|pattern> is mandatory"; }
[ -z "${TARGET_TABLE}" ]         && { usage; die 1 "-t <table> is mandatory"; }
[ -z "${TDPID}" ]                && die 1 "TDPID is not set"
[ -z "${TDENV+x}" ]              && log WARN "TDENV is not set - using no environment prefix"
[ -f "${TPT_SCRIPT}" ]           || die 1 "TPT script not found: ${TPT_SCRIPT}"

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

# Expand the file spec (exact file or wildcard pattern)
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

# Decompress ZIP / GZ archives if passed directly
IS_ARCHIVE="N"
for f in "${FILES[@]}"; do
    if [[ "${f,,}" == *.zip || "${f,,}" == *.gz ]]; then
        IS_ARCHIVE="Y"
        break
    fi
done

if [ "${IS_ARCHIVE}" = "Y" ]; then
    UNZIP_DIR="${WORK_DIR}/unzipped_$(date +%s)_$$"
    mkdir -p "${UNZIP_DIR}" || die 1 "Cannot create decompression directory: ${UNZIP_DIR}"
    log INFO "Archive detected. Decompressing ${#FILES[@]} file(s) into temporary workspace ${UNZIP_DIR}..."
    for f in "${FILES[@]}"; do
        if [[ "${f,,}" == *.zip ]]; then
            if command -v unzip >/dev/null 2>&1; then
                unzip -q -o "${f}" -d "${UNZIP_DIR}" || die 1 "Failed to decompress ${f}"
            else
                die 1 "unzip utility not available for decompressing ${f}"
            fi
        elif [[ "${f,,}" == *.gz ]]; then
            base_f="$(basename "${f}")"
            out_base="${base_f%.gz}"
            [[ "${out_base}" != *.* ]] && out_base="${out_base}.csv"
            if command -v gzip >/dev/null 2>&1; then
                gzip -dc "${f}" > "${UNZIP_DIR}/${out_base}" || die 1 "Failed to decompress ${f}"
            else
                die 1 "gzip utility not available for decompressing ${f}"
            fi
        fi
    done
    EXTRACTED_FILES=()
    for item in "${UNZIP_DIR}"/*; do
        [ -f "${item}" ] && EXTRACTED_FILES+=( "${item}" )
    done
    [ ${#EXTRACTED_FILES[@]} -eq 0 ] && die 1 "No payload files extracted from archive(s)"
    FILES=( "${EXTRACTED_FILES[@]}" )
    DIRECTORY_PATH="${UNZIP_DIR}"
    if [ ${#EXTRACTED_FILES[@]} -eq 1 ]; then
        FILE_NAME="$(basename "${EXTRACTED_FILES[0]}")"
    else
        EXT="$(echo "${EXTRACTED_FILES[0]}" | sed -n 's/.*\.\([A-Za-z0-9_]*\)$/\1/p')"
        if [ -n "${EXT}" ]; then
            FILE_NAME="*.${EXT}"
        else
            FILE_NAME="*"
        fi
    fi
    trap 'rm -rf "${UNZIP_DIR}"' EXIT INT TERM
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

# MultipleReaders (several instances on ONE file) is incompatible with a
# wildcard scan, where parallelism comes from distributing files to instances.
MULTIPLE_READERS="N"
case "${FILE_SPEC}" in
    *\**|*\?*) [ ${READER_INSTANCES} -gt ${#FILES[@]} ] && READER_INSTANCES=${#FILES[@]} ;;
    *)         [ ${READER_INSTANCES} -gt 1 ] && MULTIPLE_READERS="Y" ;;
esac

# Extract metadata from filename using the patterns
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

# If no batch ID or timestamp was provided/extracted, fallback to the current time.
# Use unix epoch for the batch ID (fits in a standard INTEGER) and ISO for the timestamp.
if [ -z "${BATCH_ID}" ] || [ -z "${META_TS}" ]; then
    CURRENT_EPOCH="$(date '+%s')"
    CURRENT_ISO="$(date '+%Y-%m-%d %H:%M:%S')"
    [ -z "${BATCH_ID}" ] && BATCH_ID="${CURRENT_EPOCH}"
    [ -z "${META_TS}" ]  && META_TS="${CURRENT_ISO}"
fi

# Column count in the file header
HEADER_COLS=$(head -1 "${FILES[0]}" | tr -d '\r' | awk -F"${DELIMITER}" '{print NF}')

log INFO "System      : ${TDPID}  user=${TD_USER}  (env prefix '${TDENV}')"
log INFO "Utility DB  : ${WRK_DB}"
log INFO "Target      : ${FQ_TABLE}  mode=${LOAD_MODE}"
log INFO "Files       : ${#FILES[@]} file(s) in ${DIRECTORY_PATH}  pattern='${FILE_NAME}'"
log INFO "Header      : ${HEADER_COLS} column(s), delimiter '${DELIMITER}'"
[ -n "${BATCH_ID}" ] && log INFO "Batch ID    : ${BATCH_ID}"
[ -n "${META_TS}" ]  && log INFO "Timestamp   : ${META_TS}"
