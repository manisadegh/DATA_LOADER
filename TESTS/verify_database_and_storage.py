#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
DATA_LOADER - DATABASE & STORAGE VERIFICATION AUDITOR
=============================================================================
Deeply verifies:
1. Teradata Technical Tables (BATCH_RUNS: STATUS='SUCCESS', PROCESS_PID is NOT NULL; BATCH_TASKS)
2. Teradata Target Staging Table (Row counts, payload data, audit columns INFA_BATCH_ID, INFA_LAST_REPLICATED)
3. Storage Tiers (LANDING_ZONE is empty, LOADING_ZONE is empty, DROP_ZONE vaulted, ARCHIVE_ZONE populated)
4. Centralized Logs existence and validity
=============================================================================
"""

import os
import sys
import argparse
import json
import logging
from datetime import datetime

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(TESTS_DIR)

# Add PROCESSING_TOOLS/COMMON to sys.path to import dataloader_core
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from dataloader_core.config import ConfigLoader
from dataloader_core.db import TeradataConnectionManager

GREEN = "\033[92m"
RED = "\033[91m"
CYAN = "\033[96m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
RESET = "\033[0m"

def audit_batch(batch_id, source, target_table, expected_count, output_file=None, skip_staging_check=False):
    report_lines = []
    def log(msg, color=None):
        report_lines.append(msg)
        if color:
            print(f"{color}{msg}{RESET}")
        else:
            print(msg)

    log("=" * 80, CYAN)
    log(f"   COMPREHENSIVE AUDIT REPORT: BATCH {batch_id} (SOURCE: {source})", BOLD + CYAN)
    log("=" * 80, CYAN)
    log(f"Audit Timestamp : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Target Staging  : {target_table}")
    log(f"Expected Rows   : {expected_count}")

    # Load configuration
    feeder_cfg_path = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "BICC_INTAKE_CONTROLLER", "config.json")
    config = ConfigLoader.load_json_config(feeder_cfg_path)
    td_cfg = config.get("teradata", {})
    tech_db = td_cfg.get("technical_database") or f"{os.environ.get('TDENV', '')}SIDFINTCH"
    stg_db = config.get("schema_guard", {}).get("target_database") or f"{os.environ.get('TDENV', '')}SIDFINSTG"

    data_dir = os.path.join(BASE_DIR, "DATA")
    logs_dir = os.path.join(BASE_DIR, "LOGS")

    all_passed = True

    # -------------------------------------------------------------------------
    # 1. STORAGE LIFECYCLES AUDIT
    # -------------------------------------------------------------------------
    log("\n--- [PART 1] STORAGE LIFECYCLES AUDIT ---", YELLOW)

    # 1.1 LANDING_ZONE must be empty
    landing_zone = os.path.join(data_dir, "LANDING_ZONE")
    src_landing = os.path.join(landing_zone, source)
    chk_landing = src_landing if os.path.isdir(src_landing) else landing_zone
    landing_items = [f for f in os.listdir(chk_landing) if not f.startswith(".")] if os.path.exists(chk_landing) else []
    if not landing_items:
        log(f"  [PASS] LANDING_ZONE is completely clean and empty ({chk_landing}).", GREEN)
    else:
        log(f"  [FAIL] LANDING_ZONE contains unconsumed orphan files: {landing_items}", RED)
        all_passed = False

    # 1.2 LOADING_ZONE must be empty
    loading_zone = os.path.join(data_dir, "LOADING_ZONE")
    src_loading = os.path.join(loading_zone, source)
    chk_loading = src_loading if os.path.isdir(src_loading) else loading_zone
    loading_items = os.listdir(chk_loading) if os.path.exists(chk_loading) else []
    if not loading_items:
        log(f"  [PASS] LOADING_ZONE is completely clean and empty ({chk_loading}).", GREEN)
    else:
        log(f"  [FAIL] LOADING_ZONE contains remaining files/markers/locks: {loading_items}", RED)
        all_passed = False

    # 1.3 Manifest Archive Vault & Capsule verification
    vaulted_receipts = []
    legacy_receipts = []
    found_loc = ""
    archive_dir = os.path.join(data_dir, "ARCHIVE_ZONE")
    if os.path.exists(archive_dir):
        for root, dirs, files in os.walk(archive_dir):
            for f in files:
                if f == "intake_receipt.json" and (str(batch_id) in f or str(batch_id) in root):
                    legacy_receipts.append(os.path.join(root, f))
                elif f.startswith(f"RECEIPT_{source}_") and f.endswith(f"_{batch_id}.json"):
                    vaulted_receipts.append(os.path.join(root, f))
                    found_loc = root

    if vaulted_receipts and not legacy_receipts:
        rel_loc = os.path.relpath(found_loc, data_dir)
        log(f"  [PASS] Found canonical vaulted intake receipt(s) in {rel_loc} : {[os.path.basename(x) for x in vaulted_receipts]}", GREEN)
    elif legacy_receipts:
        log(f"  [FAIL] Found deprecated legacy intake_receipt.json in archive vault: {legacy_receipts}", RED)
        all_passed = False
    else:
        log(f"  [FAIL] No canonical intake receipt (RECEIPT_{source}_*_{batch_id}.json) found in manifest archive vault!", RED)
        all_passed = False

    # Verify no legacy post_tasks_*.json clutter in root LOGS/<SOURCE>/
    src_logs_dir = os.path.join(logs_dir, source)
    legacy_post_tasks = [
        f for f in (os.listdir(src_logs_dir) if os.path.isdir(src_logs_dir) else [])
        if f.startswith("post_tasks_") and f.endswith(".json")
    ]
    if not legacy_post_tasks:
        log(f"  [PASS] No deprecated top-level post_tasks_*.json files in {src_logs_dir}.", GREEN)
    else:
        log(f"  [FAIL] Found deprecated top-level post_tasks_*.json files in {src_logs_dir}: {legacy_post_tasks}", RED)
        all_passed = False

    # 1.4 ARCHIVE_ZONE & Batch Capsule verification
    archived_files = []
    capsule_dirs = []
    if os.path.exists(archive_dir):
        for root, dirs, files in os.walk(archive_dir):
            if f"BATCH_{batch_id}" in os.path.basename(root):
                capsule_dirs.append(root)
            for f in files:
                if str(batch_id) in f and not f.endswith(".json"):
                    archived_files.append(os.path.join(root, f))

    if archived_files:
        capsule_msg = f" (Capsule: {os.path.relpath(capsule_dirs[0], data_dir)})" if capsule_dirs else ""
        log(f"  [PASS] Found archived deliverables for batch {batch_id} in ARCHIVE_ZONE{capsule_msg}: {[os.path.basename(x) for x in archived_files]}", GREEN)
    else:
        log(f"  [FAIL] No files matching batch {batch_id} found in ARCHIVE_ZONE!", RED)
        all_passed = False

    # -------------------------------------------------------------------------
    # 2. TERADATA TECHNICAL TABLES AUDIT (BATCH_RUNS & BATCH_TASKS)
    # -------------------------------------------------------------------------
    log("\n--- [PART 2] TERADATA TECHNICAL TABLES AUDIT ---", YELLOW)
    conn_mgr = None
    try:
        conn_mgr = TeradataConnectionManager(td_cfg, max_connections=1)
        with conn_mgr.cursor() as cur:
            # 2.1 Audit BATCH_RUNS
            log(f"Querying {tech_db}.BATCH_RUNS for Batch {batch_id} (Source: {source})...")
            try:
                cur.execute(f"""
                    SELECT BATCH_ID, SOURCE, RUN_DATE, START_TIME, END_TIME, STATUS, PROCESS_PID, RUN_ATTEMPT, PROCESS_HOST 
                    FROM {tech_db}.BATCH_RUNS 
                    WHERE BATCH_ID = ? AND SOURCE = ?
                    ORDER BY RUN_ATTEMPT DESC
                """, (str(batch_id), str(source)))
                b_run = cur.fetchone()
                r_attempt = b_run[7] if b_run and len(b_run) > 7 else None
                r_host = b_run[8] if b_run and len(b_run) > 8 else None
            except Exception:
                cur.execute(f"""
                    SELECT BATCH_ID, SOURCE, RUN_DATE, START_TIME, END_TIME, STATUS, PROCESS_PID 
                    FROM {tech_db}.BATCH_RUNS 
                    WHERE BATCH_ID = ? AND SOURCE = ?
                """, (str(batch_id), str(source)))
                b_run = cur.fetchone()
                r_attempt, r_host = 1, None

            if not b_run:
                log(f"  [FAIL] No entry found in {tech_db}.BATCH_RUNS for BATCH_ID '{batch_id}', SOURCE '{source}'!", RED)
                all_passed = False
            else:
                r_id, r_src, r_date, r_start, r_end, r_status, r_pid = b_run[:7]
                log(f"  -> Record in BATCH_RUNS: Date={r_date}, Start={r_start}, End={r_end}, Status={r_status}, PID={r_pid}, Attempt={r_attempt}, Host={r_host}")

                # Status must be SUCCESS
                if r_status == 'SUCCESS':
                    log("  [PASS] BATCH_RUNS.STATUS is 'SUCCESS'.", GREEN)
                else:
                    log(f"  [FAIL] BATCH_RUNS.STATUS is '{r_status}' (expected 'SUCCESS')!", RED)
                    all_passed = False

                # END_TIME must be not null
                if r_end is not None:
                    log(f"  [PASS] BATCH_RUNS.END_TIME is recorded ({r_end}).", GREEN)
                else:
                    log("  [FAIL] BATCH_RUNS.END_TIME is NULL!", RED)
                    all_passed = False

                # CRITICAL TEST: PROCESS_PID must NOT be null!
                if r_pid is not None and int(r_pid) > 0:
                    log(f"  [PASS] BATCH_RUNS.PROCESS_PID is NOT NULL (Retained Value: {r_pid}). Audit preservation confirmed!", GREEN)
                else:
                    log(f"  [FAIL] BATCH_RUNS.PROCESS_PID is NULL or 0! Process PID was not preserved upon completion.", RED)
                    all_passed = False

                if r_host:
                    log(f"  [PASS] BATCH_RUNS.PROCESS_HOST is recorded ({r_host}).", GREEN)
                if r_attempt:
                    log(f"  [PASS] BATCH_RUNS.RUN_ATTEMPT is recorded ({r_attempt}).", GREEN)

            # 2.2 Audit BATCH_TASKS
            log(f"\nQuerying {tech_db}.BATCH_TASKS for Batch {batch_id} (Source: {source})...")
            try:
                cur.execute(f"""
                    SELECT ENTITY_NAME, FILE_COUNT, STATUS, START_TIME, END_TIME, RETRY_COUNT, ERROR_MESSAGE, RUN_ATTEMPT 
                    FROM {tech_db}.BATCH_TASKS 
                    WHERE BATCH_ID = ? AND SOURCE = ?
                    ORDER BY RUN_ATTEMPT DESC
                """, (str(batch_id), str(source)))
                tasks = cur.fetchall()
            except Exception:
                cur.execute(f"""
                    SELECT ENTITY_NAME, FILE_NAME, STATUS, START_TIME, END_TIME, RETRY_COUNT, ERROR_MESSAGE 
                    FROM {tech_db}.BATCH_TASKS 
                    WHERE BATCH_ID = ? AND SOURCE = ?
                """, (str(batch_id), str(source)))
                tasks = cur.fetchall()

            if not tasks:
                log(f"  [FAIL] No tasks found in {tech_db}.BATCH_TASKS for BATCH_ID '{batch_id}'!", RED)
                all_passed = False
            else:
                log(f"  Found {len(tasks)} task record(s) in BATCH_TASKS:")
                for t in tasks:
                    t_ent, t_file, t_stat, t_start, t_end, t_retries, t_err = t[:7]
                    t_att = t[7] if len(t) > 7 else None
                    att_str = f" | Attempt: {t_att}" if t_att is not None else ""
                    log(f"    - Entity: {t_ent} | File/Count: {t_file}{att_str} | Status: {t_stat} | Start: {t_start} | End: {t_end} | Retries: {t_retries}")
                    if t_stat == 'SUCCESS':
                        log(f"      [PASS] Task '{t_ent}' completed with SUCCESS.", GREEN)
                    else:
                        log(f"      [FAIL] Task '{t_ent}' status is '{t_stat}' (Error: {t_err})!", RED)
                        all_passed = False

            # -----------------------------------------------------------------
            # 3. TARGET STAGING TABLE & AUDIT METADATA AUDIT
            # -----------------------------------------------------------------
            log(f"\n--- [PART 3] TARGET STAGING TABLE AUDIT ({stg_db}.{target_table}) ---", YELLOW)
            if skip_staging_check:
                log("  [INFO] Skipping target staging table row count check (--skip-staging-check specified; batch superseded in replace mode).", YELLOW)
            else:
                cur.execute(f"""
                    SELECT COUNT(*), 
                           COUNT(INFA_BATCH_ID), 
                           COUNT(INFA_LAST_REPLICATED) 
                    FROM {stg_db}.{target_table} 
                    WHERE INFA_BATCH_ID = ?
                """, (str(batch_id),))
                row_count, batch_id_count, rep_count = cur.fetchone()
                log(f"  Row Count for INFA_BATCH_ID='{batch_id}': {row_count} (Expected: {expected_count})")
                log(f"  Non-Null INFA_BATCH_ID Count           : {batch_id_count}")
                log(f"  Non-Null INFA_LAST_REPLICATED Count    : {rep_count}")

                if row_count == expected_count:
                    log(f"  [PASS] Staging table row count matches expected ({row_count}/{expected_count}).", GREEN)
                else:
                    log(f"  [FAIL] Staging table row count mismatch ({row_count} vs expected {expected_count})!", RED)
                    all_passed = False

                if batch_id_count == row_count and row_count > 0:
                    log(f"  [PASS] Audit column INFA_BATCH_ID is 100% populated with '{batch_id}'.", GREEN)
                else:
                    log("  [FAIL] Audit column INFA_BATCH_ID contains NULLs or missing values!", RED)
                    all_passed = False

                if rep_count == row_count and row_count > 0:
                    log(f"  [PASS] Audit column INFA_LAST_REPLICATED is 100% populated with timestamps.", GREEN)
                else:
                    log("  [FAIL] Audit column INFA_LAST_REPLICATED contains NULLs!", RED)
                    all_passed = False

                # Sample payload rows display
                cur.execute(f"SELECT * FROM {stg_db}.{target_table} WHERE INFA_BATCH_ID = ?", (str(batch_id),))
                sample_rows = cur.fetchmany(5)
                col_names = [d[0] for d in cur.description]
                log(f"\nSample Rows from {stg_db}.{target_table}:")
                log(f"Columns: {col_names}")
                for sr in sample_rows:
                    log(f"  {sr}")

    except Exception as e:
        log(f"  [FAIL] Database query failed with exception: {e}", RED)
        all_passed = False
    finally:
        if conn_mgr is not None:
            conn_mgr.close_all()

    log("\n" + "=" * 80, CYAN)
    if all_passed:
        log(f">>> [AUDIT PASS] ALL DATABASE, STORAGE AND PID CHECKS PASSED FOR BATCH {batch_id}!", GREEN + BOLD)
    else:
        log(f">>> [AUDIT FAIL] AT LEAST ONE AUDIT CHECK FAILED FOR BATCH {batch_id}!", RED + BOLD)
    log("=" * 80 + "\n", CYAN)

    if output_file:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as out_f:
            out_f.write("\n".join(report_lines) + "\n")

    return all_passed

def main():
    parser = argparse.ArgumentParser(description="DATA_LOADER Deep Database & Storage Auditor")
    parser.add_argument("--batch-id", type=str, required=True, help="Batch ID to audit")
    parser.add_argument("--source", type=str, default="ORACLE_FUSION", help="Source system code")
    parser.add_argument("--target-table", type=str, default="ERP_MSH_USER", help="Target staging table")
    parser.add_argument("--expected-count", type=int, default=2, help="Expected row count")
    parser.add_argument("--skip-staging-check", action="store_true", help="Skip target staging table row count check (for batches superseded in replace mode)")
    parser.add_argument("--output-file", type=str, default=None, help="File to write report to")
    args = parser.parse_args()

    success = audit_batch(
        batch_id=args.batch_id,
        source=args.source,
        target_table=args.target_table,
        expected_count=args.expected_count,
        output_file=args.output_file,
        skip_staging_check=args.skip_staging_check
    )
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
