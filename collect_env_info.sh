#!/bin/bash
# ==============================================================================
# DATA_LOADER Unix Environment Discovery Script
# Safe inspection of environment, paths, TTU, Python, and credentials layout.
# ==============================================================================

echo "=================================================================="
echo "          DATA_LOADER UNIX ENVIRONMENT DISCOVERY REPORT           "
echo "=================================================================="
echo "Report Timestamp : $(date '+%Y-%m-%d %H:%M:%S')"
echo "Hostname         : $(hostname)"
echo "User (whoami)    : $(whoami)"
echo "Current Directory: $(pwd)"
echo ""

echo "--- 1. CORE ENVIRONMENT VARIABLES ---"
for var in TDENV ENV USER_CHAPEAU TDPID SID_ADM_USER TDADEV LANG USER HOME \
           DBT_DIR DBT_PROFILE_TARGET DBT_PROFILE_DIR COMMON_PATH TTU_LINKS TTU_PATH; do
    printf "%-20s : %s\n" "$var" "${!var:-<NOT SET>}"
done
echo ""

echo "--- 2. TERADATA TTU CLIENT BINARIES & VERSIONS ---"
echo "PATH: $PATH"
echo "LD_LIBRARY_PATH: $LD_LIBRARY_PATH"
echo ""
which tbuild 2>/dev/null && tbuild -v 2>&1 | head -n 3 || echo "tbuild : NOT FOUND in PATH"
which bteq 2>/dev/null && bteq -V 2>&1 | head -n 2 || echo "bteq   : NOT FOUND in PATH"
echo ""

echo "--- 3. TERADATA WALLET STATUS ---"
if which tdwallet >/dev/null 2>&1; then
    echo "tdwallet binary: FOUND ($(which tdwallet))"
    WALLET_KEY="${TDENV}${SID_ADM_USER}"
    if [ -n "$WALLET_KEY" ]; then
        if tdwallet list 2>/dev/null | grep -q "$WALLET_KEY"; then
            echo "tdwallet key '${WALLET_KEY}': PRESENT in wallet"
        else
            echo "tdwallet key '${WALLET_KEY}': NOT LISTED in wallet"
        fi
    fi
else
    echo "tdwallet binary: NOT FOUND in PATH"
fi
echo ""

echo "--- 4. PYTHON RUNTIME & LIBRARIES ---"
PYTHON_BIN=$(which python3 2>/dev/null || which python 2>/dev/null)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -n "$PYTHON_BIN" ]; then
    echo "Python Binary   : $PYTHON_BIN"
    echo "Python Version  : $($PYTHON_BIN --version 2>&1)"
    echo "teradatasql     : $($PYTHON_BIN -c 'import teradatasql; print("INSTALLED - version " + teradatasql.__version__)' 2>/dev/null || echo 'NOT INSTALLED')"
    echo "dataloader_core : $($PYTHON_BIN -c "import sys; sys.path.insert(0, '${SCRIPT_DIR}/PROCESSING_TOOLS/COMMON'); import dataloader_core; print('IMPORTABLE - ' + dataloader_core.__file__)" 2>/dev/null || echo 'NOT IMPORTABLE')"
else
    echo "Python Binary : NOT FOUND"
fi
echo ""

echo "--- 5. DBT PROFILE & ENCRYPTED KEY/PASS PROPERTIES ---"
DBT_DIR_RESOLVED="${DBT_PROFILE_DIR:-$HOME/.dbt}"
echo "Checking directory: $DBT_DIR_RESOLVED"
if [ -d "$DBT_DIR_RESOLVED" ]; then
    echo "Existing Key/Pass property files (paths only, no secrets):"
    ls -l "$DBT_DIR_RESOLVED"/*Key.properties "$DBT_DIR_RESOLVED"/*Pass.properties 2>/dev/null || echo "No Key/Pass property files found"
    if [ -f "$DBT_DIR_RESOLVED/profiles.yml" ]; then
        echo "profiles.yml: FOUND (targets defined: $(grep -E '^\s+[a-zA-Z0-9_-]+:' "$DBT_DIR_RESOLVED/profiles.yml" | tr -d ' :' | tr '\n' ' '))"
    fi
else
    echo "Directory $DBT_DIR_RESOLVED does not exist."
fi
echo ""

echo "--- 6. TARGET DATA_LOADER DEPLOYMENT DIRECTORY & WRITE PERMISSIONS ---"
TARGET_DEPLOY="${HOME}/DATA_LOADER"
echo "Expected target path: $TARGET_DEPLOY"
if [ -d "$TARGET_DEPLOY" ]; then
    echo "Directory exists: YES"
    [ -w "$TARGET_DEPLOY" ] && echo "Write permission: GRANTED" || echo "Write permission: DENIED"
else
    echo "Directory exists: NO (Parent writable: $([ -w "$HOME" ] && echo 'YES' || echo 'NO'))"
fi

echo ""
echo "=================================================================="
echo "                        END OF REPORT                             "
echo "=================================================================="
