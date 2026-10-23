#!/bin/bash
# ---------------------------------------------------------------------------
# Helpers and Environment setup (POSIX / Unix)
# ---------------------------------------------------------------------------

# Load global domain configuration if present
if [ -f "${SCRIPT_DIR}/config/global.env" ]; then
    source "${SCRIPT_DIR}/config/global.env"
fi

log()   { echo "$(date '+%Y-%m-%d %H:%M:%S') [$1] ${*:2}"; }
die()   { log ERROR "$2"; exit "$1"; }

usage() {
    sed -n '/^# Usage:/,/^# Exit codes:/p' "${SCRIPT_DIR}/load_csv_generic.sh" \
        | sed 's/^# \{0,1\}//' \
        | sed '$d'
}

validate_identifier() {
    local id_val="$1"
    local id_label="${2:-Identifier}"
    if [[ ! "${id_val}" =~ ^[A-Za-z0-9_]+$ ]]; then
        die 1 "Invalid SQL identifier for ${id_label}: '${id_val}'"
    fi
}

escape_sql_literal() {
    local val="$1"
    echo "${val//\'/\'\'}"
}

clean_column_name() {
    echo "$1" | sed -E "s/^[[:space:]\"']+//; s/[[:space:]\"']+$//; s/[^A-Za-z0-9_]/_/g; s/_+/_/g; s/^_+//; s/_+$//" | tr '[:lower:]' '[:upper:]'
}
