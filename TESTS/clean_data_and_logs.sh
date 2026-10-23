#!/bin/bash
# ==============================================================================
# DATA_LOADER - Clean DATA & LOGS Environments
# Resets all storage tiers and logs for test repeatability
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
DATA_DIR="${BASE_DIR}/DATA"
LOGS_DIR="${BASE_DIR}/LOGS"

echo "=============================================================================="
echo ">>> [CLEANUP] Resetting DATA_LOADER Runtime Storage & Logs..."
echo "=============================================================================="
echo "Base Directory : ${BASE_DIR}"
echo "Data Directory : ${DATA_DIR}"
echo "Logs Directory : ${LOGS_DIR}"

# 1. Clean and recreate standard zones
for ZONE in "DROP_ZONE" "LANDING_ZONE" "LOADING_ZONE" "ARCHIVE_ZONE"; do
    ZONE_PATH="${DATA_DIR}/${ZONE}"
    if [ -d "${ZONE_PATH}" ]; then
        echo "  - Purging ${ZONE}..."
        rm -rf "${ZONE_PATH:?}"/* "${ZONE_PATH}"/.[!.]* 2>/dev/null || true
    fi
    mkdir -p "${ZONE_PATH}"
    for SRC in "ORACLE_FUSION" "CRM"; do
        mkdir -p "${ZONE_PATH}/${SRC}"
    done
done

# 2. Clean and recreate logs
if [ -d "${LOGS_DIR}" ]; then
    echo "  - Purging LOGS..."
    rm -rf "${LOGS_DIR:?}"/* 2>/dev/null || true
fi
mkdir -p "${LOGS_DIR}"
for SRC in "ORACLE_FUSION" "CRM"; do
    mkdir -p "${LOGS_DIR}/${SRC}"
done

# 3. Purge test batch records (9001..9099) from Teradata BATCH_TASKS & BATCH_RUNS
ORCH_CFG="${BASE_DIR}/PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/config.json"
COMMON_DIR="${BASE_DIR}/PROCESSING_TOOLS/COMMON"
if [ -f "${ORCH_CFG}" ] && [ -d "${COMMON_DIR}" ]; then
    echo "  - Purging test batch state (9001..9099) from Teradata BATCH_RUNS & BATCH_TASKS and resetting test staging tables..."
    PYTHONPATH="${COMMON_DIR}:${PYTHONPATH}" python3 -c '
import os, sys
from dataloader_core.config import load_json_config
from dataloader_core.db import TeradataConnectionManager, validate_sql_identifier
try:
    cfg = load_json_config(sys.argv[1])
    td_cfg = cfg.get("teradata", {})
    default_db = os.environ.get("TDENV", "") + os.environ.get("DB_TCH", "SIDFINTCH")
    tech_db = validate_sql_identifier(td_cfg.get("technical_database") or os.environ.get("TD_TECH_DB", default_db))
    tpt_cfg = cfg.get("tpt", {})
    env_pfx = os.environ.get("TDENV", "")
    target_db = validate_sql_identifier(tpt_cfg.get("target_db") or f"{env_pfx}SIDFINSTG")
    work_db = validate_sql_identifier(tpt_cfg.get("work_db") or f"{env_pfx}SIDFINWRK")
    mgr = TeradataConnectionManager(td_cfg, max_connections=1)
    with mgr.acquire_connection() as conn:
        with conn.cursor() as cur:
            # Ensure Version 3.0 technical table columns exist in Teradata (F2.11)
            for alter_sql in [
                f"ALTER TABLE {tech_db}.BATCH_RUNS ADD RUN_ATTEMPT INTEGER DEFAULT 1 NOT NULL",
                f"ALTER TABLE {tech_db}.BATCH_RUNS ADD PROCESS_HOST VARCHAR(255) CHARACTER SET UNICODE NOT CASESPECIFIC",
                f"ALTER TABLE {tech_db}.BATCH_TASKS ADD EXTRACT_TIMESTAMP VARCHAR(50) CHARACTER SET UNICODE NOT CASESPECIFIC",
                f"ALTER TABLE {tech_db}.BATCH_TASKS ADD RUN_ATTEMPT INTEGER DEFAULT 1 NOT NULL",
                f"ALTER TABLE {tech_db}.BATCH_TASKS ADD FILE_COUNT INTEGER DEFAULT 1",
                f"ALTER TABLE {tech_db}.BATCH_TASKS ADD TPT_JOB_NAME VARCHAR(128) CHARACTER SET UNICODE NOT CASESPECIFIC",
                f"ALTER TABLE {tech_db}.BATCH_TASKS DROP FILE_NAME",
            ]:
                try:
                    cur.execute(alter_sql)
                except Exception:
                    pass
            cur.execute(f"DELETE FROM {tech_db}.BATCH_TASKS WHERE BATCH_ID IN (\x279001\x27,\x279002\x27,\x279003\x27,\x279004\x27,\x279005\x27,\x279006\x27,\x279007\x27,\x279008\x27,\x279009\x27,\x279099\x27)")
            cur.execute(f"DELETE FROM {tech_db}.BATCH_RUNS WHERE BATCH_ID IN (\x279001\x27,\x279002\x27,\x279003\x27,\x279004\x27,\x279005\x27,\x279006\x27,\x279007\x27,\x279008\x27,\x279009\x27,\x279099\x27)")
            for tbl in ["ERP_MSH_USER", "CRM_MSH_CUSTOMER"]:
                try:
                    cur.execute(f"DROP TABLE {target_db}.{tbl}")
                except Exception:
                    pass
                for pfx in ["ET_", "UV_", "WT_", "LG_"]:
                    try:
                        cur.execute(f"DROP TABLE {work_db}.{pfx}{tbl}")
                    except Exception:
                        pass
            try:
                cur.execute(f"""
                    CREATE MULTISET TABLE {target_db}.ERP_MSH_USER ,NO FALLBACK ,
                         NO BEFORE JOURNAL,
                         NO AFTER JOURNAL,
                         CHECKSUM = DEFAULT,
                         DEFAULT MERGEBLOCKRATIO
                         (
                            USER_ID VARCHAR(4000) CHARACTER SET UNICODE NOT CASESPECIFIC,
                            USER_NAME VARCHAR(4000) CHARACTER SET UNICODE NOT CASESPECIFIC,
                            EMAIL_ADDRESS VARCHAR(4000) CHARACTER SET UNICODE NOT CASESPECIFIC,
                            INFA_LAST_REPLICATED TIMESTAMP(0),
                            INFA_BATCH_ID VARCHAR(100) CHARACTER SET UNICODE NOT CASESPECIFIC
                         )
                    NO PRIMARY INDEX
                """)
            except Exception as exc:
                print(f"    [WARN] Recreating ERP_MSH_USER staging table warning: {exc}")
            try:
                cur.execute(f"""
                    CREATE MULTISET TABLE {target_db}.CRM_MSH_CUSTOMER ,NO FALLBACK ,
                         NO BEFORE JOURNAL,
                         NO AFTER JOURNAL,
                         CHECKSUM = DEFAULT,
                         DEFAULT MERGEBLOCKRATIO
                         (
                            CUSTOMER_ID VARCHAR(4000) CHARACTER SET UNICODE NOT CASESPECIFIC,
                            CUSTOMER_NAME VARCHAR(4000) CHARACTER SET UNICODE NOT CASESPECIFIC,
                            REGION VARCHAR(4000) CHARACTER SET UNICODE NOT CASESPECIFIC,
                            INFA_LAST_REPLICATED TIMESTAMP(0),
                            INFA_BATCH_ID VARCHAR(100) CHARACTER SET UNICODE NOT CASESPECIFIC
                         )
                    NO PRIMARY INDEX
                """)
            except Exception as exc:
                print(f"    [WARN] Recreating CRM_MSH_CUSTOMER staging table warning: {exc}")
            try:
                cur.execute(f"ALTER TABLE {tech_db}.BATCH_TASKS ADD TPT_JOB_NAME VARCHAR(128) CHARACTER SET UNICODE NOT CASESPECIFIC")
            except Exception:
                pass
    mgr.close_all()
except Exception as exc:
    print(f"    [WARN] Non-blocking Teradata state purge warning: {exc}")
' "${ORCH_CFG}" || true
fi

echo ">>> [CLEANUP COMPLETED] Runtime storage and logs are clean and ready."
echo "=============================================================================="
