#!/bin/bash
# ---------------------------------------------------------------------------
# Arguments Parsing
# ---------------------------------------------------------------------------
FILE_SPEC=""
FILE_LIST=""
CLI_JOB_NAME=""
TARGET_TABLE=""
TARGET_DB="${TDENV}${DB_STG}"
WRK_DB="${TDENV}${DB_WRK}"
TD_USER="${TD_LOGON_USER:-${TDENV}${SID_ADM_USER}}"
LOAD_MODE="replace"
DELIMITER=","
ERROR_LIMIT=1
READER_INSTANCES=1
LOAD_INSTANCES=1
MAX_SESSIONS=8
SKIP_ROWS=1
SKIP_ROWS_EVERY_FILE="N"
ARCHIVE_DIR=""
WORK_DIR="${TPT_WORK_DIR:-${SCRIPT_DIR}/tmp/tpt_work}"
CLI_BATCH_ID=""
CLI_TIMESTAMP=""
SKIP_BTEQ_CHECK="N"
CLI_HAS_META=""

BATCH_ID_PATTERN=""
TIMESTAMP_PATTERN=""

# First pass: look for a job variables config file (-v)
OPTIND=1
JOB_VARS_FILE=""
while getopts ":f:t:d:k:u:m:s:e:r:l:x:S:Y:a:w:B:T:b:c:v:CM:L:j:h" opt; do
    case "${opt}" in
        v) JOB_VARS_FILE="${OPTARG}" ;;
        C) SKIP_BTEQ_CHECK="Y" ;;
        M) CLI_HAS_META="${OPTARG}" ;;
        L) FILE_LIST="${OPTARG}" ;;
        j) CLI_JOB_NAME="${OPTARG}" ;;
    esac
done

if [ -n "${JOB_VARS_FILE}" ]; then
    [ -f "${JOB_VARS_FILE}" ] || die 1 "Job variables file not found: ${JOB_VARS_FILE}"
    
    get_var() {
        local var_name="$1"
        grep -i "^[[:space:]]*${var_name}[[:space:]]*=" "${JOB_VARS_FILE}" | tail -1 | sed -E "s/^[^=]+=[[:space:]]*//; s/[[:space:]]*$//; s/^['\"]//; s/['\"]$//" | tr -d '\r'
    }
    
    DIR_PATH=""
    FILE_NAME_VAR=""
    VAL="$(get_var DirectoryPath)";    [ -n "$VAL" ] && DIR_PATH="$VAL"
    VAL="$(get_var FileName)";         [ -n "$VAL" ] && FILE_NAME_VAR="$VAL"
    if [ -n "$DIR_PATH" ] && [ -n "$FILE_NAME_VAR" ]; then
        FILE_SPEC="${DIR_PATH}/${FILE_NAME_VAR}"
    elif [ -n "$FILE_NAME_VAR" ]; then
        FILE_SPEC="${FILE_NAME_VAR}"
    fi
    
    VAL="$(get_var FileList)";         [ -n "$VAL" ] && FILE_LIST="$VAL"
    VAL="$(get_var JobName)";          [ -n "$VAL" ] && CLI_JOB_NAME="$VAL"
    VAL="$(get_var TargetTable)";      [ -n "$VAL" ] && TARGET_TABLE="$VAL"
    VAL="$(get_var TargetDatabase)";   [ -n "$VAL" ] && TARGET_DB="$VAL"
    VAL="$(get_var UtilityDatabase)";  [ -n "$VAL" ] && WRK_DB="$VAL"
    VAL="$(get_var UserName)";         [ -n "$VAL" ] && TD_USER="$VAL"
    
    VAL="$(get_var ConsumerOperator)"
    if [ "$VAL" = "LOAD_OPERATOR" ]; then
        LOAD_MODE="replace"
    elif [ "$VAL" = "UPDATE_OPERATOR" ]; then
        LOAD_MODE="append"
    fi
    
    VAL="$(get_var TextDelimiter)";    [ -n "$VAL" ] && DELIMITER="$VAL"
    VAL="$(get_var ErrorLimit)";       [ -n "$VAL" ] && ERROR_LIMIT="$VAL"
    VAL="$(get_var ReaderInstances)";  [ -n "$VAL" ] && READER_INSTANCES="$VAL"
    VAL="$(get_var LoadInstances)";    [ -n "$VAL" ] && LOAD_INSTANCES="$VAL"
    VAL="$(get_var MaxSessions)";      [ -n "$VAL" ] && MAX_SESSIONS="$VAL"
    VAL="$(get_var SkipRows)";         [ -n "$VAL" ] && SKIP_ROWS="$VAL"
    VAL="$(get_var SkipRowsEveryFile)"; [ -n "$VAL" ] && SKIP_ROWS_EVERY_FILE="$VAL"
    VAL="$(get_var ArchiveDirectory)"; [ -n "$VAL" ] && ARCHIVE_DIR="$VAL"
    VAL="$(get_var WorkDirectory)";    [ -n "$VAL" ] && WORK_DIR="$VAL"
    VAL="$(get_var BatchId)";          [ -n "$VAL" ] && CLI_BATCH_ID="$VAL"
    VAL="$(get_var Timestamp)";        [ -n "$VAL" ] && CLI_TIMESTAMP="$VAL"
    VAL="$(get_var BatchIdPattern)";   [ -n "$VAL" ] && BATCH_ID_PATTERN="$VAL"
    VAL="$(get_var TimestampPattern)"; [ -n "$VAL" ] && TIMESTAMP_PATTERN="$VAL"
fi

# Second pass: apply CLI arguments (overrides config file)
OPTIND=1
while getopts ":f:t:d:k:u:m:s:e:r:l:x:S:Y:a:w:B:T:b:c:v:CM:L:j:h" opt; do
    case "${opt}" in
        f) FILE_SPEC="${OPTARG}" ;;
        L) FILE_LIST="${OPTARG}" ;;
        j) CLI_JOB_NAME="${OPTARG}" ;;
        t) TARGET_TABLE="${OPTARG}" ;;
        d) TARGET_DB="${OPTARG}" ;;
        k) WRK_DB="${OPTARG}" ;;
        u) TD_USER="${OPTARG}" ;;
        m) LOAD_MODE="${OPTARG}" ;;
        s) DELIMITER="${OPTARG}" ;;
        e) ERROR_LIMIT="${OPTARG}" ;;
        r) READER_INSTANCES="${OPTARG}" ;;
        l) LOAD_INSTANCES="${OPTARG}" ;;
        x) MAX_SESSIONS="${OPTARG}" ;;
        S) SKIP_ROWS="${OPTARG}" ;;
        Y) SKIP_ROWS_EVERY_FILE="${OPTARG}" ;;
        a) ARCHIVE_DIR="${OPTARG}" ;;
        w) WORK_DIR="${OPTARG}" ;;
        B) CLI_BATCH_ID="${OPTARG}" ;;
        T) CLI_TIMESTAMP="${OPTARG}" ;;
        b) BATCH_ID_PATTERN="${OPTARG}" ;;
        c) TIMESTAMP_PATTERN="${OPTARG}" ;;
        C) SKIP_BTEQ_CHECK="Y" ;;
        M) CLI_HAS_META="${OPTARG}" ;;
        v) ;; # Already handled in first pass
        h) usage; exit 0 ;;
        :) usage; die 1 "Option -${OPTARG} requires a value" ;;
        *) usage; die 1 "Unknown option -${OPTARG}" ;;
    esac
done

# Strip surrounding single or double quotes from FILE_SPEC and FILE_LIST
FILE_SPEC="${FILE_SPEC%\"}"
FILE_SPEC="${FILE_SPEC#\"}"
FILE_SPEC="${FILE_SPEC%\'}"
FILE_SPEC="${FILE_SPEC#\'}"

FILE_LIST="${FILE_LIST%\"}"
FILE_LIST="${FILE_LIST#\"}"
FILE_LIST="${FILE_LIST%\'}"
FILE_LIST="${FILE_LIST#\'}"
