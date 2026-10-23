#!/bin/bash
#/***************************************************
# FDJ
#
# Finance domain - Oracle Fusion - Generic delimited file loader (TPT)
#
# Loads a BICC CSV extract (one file, all parts via wildcard, or via listfile)
# into an existing Teradata staging table, using dynamic payload schema generation
# and template lib/load_csv_generic.tpt.template.
#
# Usage:
#   load_csv_generic.sh (-f <file|pattern> | -L <listfile>) -t <table> [-d <database>] [-k <utility_db>]
#                       [-u <user>] [-m replace|append] [-s <delimiter>] [-e <error_limit>]
#                       [-r <reader_instances>] [-l <load_instances>]
#                       [-x <max_sessions>] [-a <archive_dir>] [-w <work_dir>]
#                       [-b <batch_pattern>] [-c <timestamp_pattern>]
#                       [-v <jobvariables_file>] [-j <job_name>] [-C] [-M <has_meta>]
#
#   -f  Data file, or a quoted wildcard pattern for multi-part extracts, e.g.
#       '/data/in/file_..._invoiceheaderextractpvo-batch1736238000-*.csv'
#   -L  List file containing absolute paths of data files to load (mutually exclusive with -f)
#   -t  Target table name (mandatory - never derived from the file name)
#   -d  Target database (default: ${TDENV}${DB_STG})
#   -k  Database for the TPT log / error / work tables (default: ${TDENV}${DB_WRK})
#   -u  Logon user (default: ${TD_LOGON_USER:-${TDENV}${SID_ADM_USER}})
#   -m  replace : DELETE ALL then Load operator (FastLoad)          [default]
#       append  : keep existing rows, Update operator (MultiLoad)
#   -s  Field delimiter (default: ',')
#   -S  Number of header rows to skip (default: 1)
#   -Y  Skip header rows on every file when loading multi-file wildcards: Y|N (default: 'N')
#   -e  ErrorLimit: number of rejected rows that aborts the job (default: 1)
#   -r  DataConnector reader instances (default: 1; >1 useful for multi-part files)
#   -l  Load/Update operator instances (default: 1)
#   -x  Max database sessions for the consumer operator (default: 8)
#   -B  Batch ID for INFA_BATCH_ID (mandatory when target table has audit columns)
#   -T  Timestamp for INFA_LAST_REPLICATED (mandatory when target table has audit columns)
#   -b  Batch ID extraction pattern (e.g. s/.*-batch\([0-9][0-9]*\)-.*/\1/p)
#   -c  Timestamp extraction pattern (e.g. s/.*-\([0-9]\{4\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)_\([0-9]\{2\}\)\([0-9]\{2\}\)\([0-9]\{2\}\)\..*/\1-\2-\3 \4:\5:\6/p)
#   -a  Archive directory: loaded files are moved there on success (default: none)
#   -w  Work directory for job variables / logs / rejected rows
#       (default: ${TPT_WORK_DIR:-${SCRIPT_DIR}/tmp/tpt_work})
#   -v  Job variables configuration file (TPT format: Key='Value').
#       Values in this file serve as defaults, overridden by explicit CLI args.
#   -j  Exact TPT job name (default: TPT_<TARGET_TABLE>_<RUN_TS>)
#   -C  Skip BTEQ header column name comparison only (table check & field count check still run)
#   -M  Count of audit columns present (0, 1, or 2)
#
# Environment (same conventions as the BTEQ DDL scripts):
#   TDPID   Teradata system name                  (mandatory)
#   TDENV   Environment prefix for users/databases, e.g. "D_" (may be empty)
#   Password resolved through Teradata Wallet: $tdwallet(<user>)
#   TD_PASSWORD  if set, used as a plain password INSTEAD of the wallet
#                (dev / sandpit environments without tdwallet only)
#
# Exit codes:
#   0  success (TPT exit 0 or 4)
#   1  usage / pre-check error (file missing, column count mismatch ...)
#   2  connection error or target table not found
#   3  TPT job failed (TPT exit 8 or 12)
#
# History
#
# Date          Auteur          Description
# 07/10/2026    Mani Sadegh     Creation
# 08/10/2026    Mani Sadegh     Refactoring to modular architecture (lib/)
# 23/10/2026    Mani Sadegh     Phase 1 improvements (dynamic payload schema, audit literals in INSERT, -L listfile)
#
#****************************************************/

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/lib"
TPT_TEMPLATE="${LIB_DIR}/load_csv_generic.tpt.template"

# Source modular components
source "${LIB_DIR}/env_and_helpers.sh"
source "${LIB_DIR}/parse_args.sh" "$@"
source "${LIB_DIR}/pre_checks.sh"
source "${LIB_DIR}/bteq_check.sh"
source "${LIB_DIR}/generate_jobvars.sh"
source "${LIB_DIR}/generate_tpt_job.sh"
source "${LIB_DIR}/run_tpt.sh"
source "${LIB_DIR}/archive_files.sh"

exit 0
