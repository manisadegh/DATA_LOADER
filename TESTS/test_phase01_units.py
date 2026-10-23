#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
DATA_LOADER - PHASE 01 UNIT TEST SUITE
=============================================================================
Validates Phase 01 bug fixes and guardrails in isolation (without requiring
live Teradata mutations):
1. test_schema_guard_flags:
   - auto_migrate_ddl=False raises RuntimeError on missing table or drift
   - load_mode='append' raises RuntimeError on schema drift without DROP TABLE
   - generate_staging_ddl honors character_set ('UNICODE' vs 'LATIN')
2. test_db_state_source_scoping:
   - Mandatory source parameter on all TeradataStateDB methods
   - Every SQL query against BATCH_RUNS and BATCH_TASKS includes SOURCE = ?
3. test_column_sanitization_parity:
   - Python clean_column_name() in schema_guard.py matches Bash
     clean_column_name() in TPT_LOADER/lib/env_and_helpers.sh 100%
4. test_tpt_worker_args:
   - run_tpt_loader forwards -Y <SkipRowsEveryFile> to load_csv_generic.sh
   - run_tpt_loader forwards -m <load_mode> -B <batch_id> -T <extract_ts>
     to unlock_tpt_table.sh on retry / Error 2652
=============================================================================
"""

import os
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(TESTS_DIR)

COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
FEEDER_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "BICC_INTAKE_CONTROLLER")
ORCH_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
TPT_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "TPT_LOADER")

sys.path.insert(0, COMMON_DIR)
sys.path.insert(0, FEEDER_DIR)
sys.path.insert(0, ORCH_DIR)

# Ensure teradatasql is importable even in mock mode if needed
if "teradatasql" not in sys.modules:
    try:
        import teradatasql  # noqa: F401
    except ImportError:
        sys.modules["teradatasql"] = MagicMock()

from lib.schema_guard import (
    clean_column_name,
    generate_staging_ddl,
    sync_entity_schema_if_drifted,
)
from lib.db_state import TeradataStateDB
from lib.tpt_worker import run_tpt_loader


class TestPhase01Units(unittest.TestCase):

    def test_schema_guard_flags(self):
        """Verify auto_migrate_ddl, load_mode='append' protection, and character_set."""
        # 1. character_set in generate_staging_ddl
        ddl_unicode = generate_staging_ddl(
            "DEV0SIDFINSTG", "ERP_MSH_USER", ["USER_ID", "USER_NAME"],
            default_type="VARCHAR(4000)", character_set="UNICODE"
        )
        self.assertIn("CHARACTER SET UNICODE NOT CASESPECIFIC", ddl_unicode)

        ddl_latin = generate_staging_ddl(
            "DEV0SIDFINSTG", "ERP_MSH_USER", ["USER_ID", "USER_NAME"],
            default_type="VARCHAR(4000)", character_set="LATIN"
        )
        self.assertIn("CHARACTER SET LATIN NOT CASESPECIFIC", ddl_latin)

        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as tmp:
            tmp.write("USER_ID,USER_NAME,NEW_DRIFT_COL\n1,Alice,Extra\n")
            tmp_csv = tmp.name

        try:
            # 2. auto_migrate_ddl=False on missing table -> raises RuntimeError without CREATE TABLE
            mock_conn = MagicMock()
            with patch("lib.schema_guard.get_teradata_table_columns", return_value=None), \
                 patch("lib.schema_guard.recreate_staging_table") as mock_recreate:
                with self.assertRaises(RuntimeError) as ctx:
                    sync_entity_schema_if_drifted(
                        mock_conn, "DEV0SIDFINSTG", "ERP_MSH_USER", tmp_csv,
                        auto_migrate_ddl=False, load_mode="replace"
                    )
                self.assertIn("auto_migrate_ddl is disabled", str(ctx.exception))
                mock_recreate.assert_not_called()

            # 3. auto_migrate_ddl=False on drifted table -> raises RuntimeError without DROP TABLE
            with patch("lib.schema_guard.get_teradata_table_columns", return_value=["USER_ID", "USER_NAME"]), \
                 patch("lib.schema_guard.recreate_staging_table") as mock_recreate:
                with self.assertRaises(RuntimeError) as ctx:
                    sync_entity_schema_if_drifted(
                        mock_conn, "DEV0SIDFINSTG", "ERP_MSH_USER", tmp_csv,
                        auto_migrate_ddl=False, load_mode="replace"
                    )
                self.assertIn("auto_migrate_ddl is disabled", str(ctx.exception))
                mock_recreate.assert_not_called()

            # 4. load_mode='append' on drifted table -> raises RuntimeError without DROP TABLE
            with patch("lib.schema_guard.get_teradata_table_columns", return_value=["USER_ID", "USER_NAME"]), \
                 patch("lib.schema_guard.recreate_staging_table") as mock_recreate:
                with self.assertRaises(RuntimeError) as ctx:
                    sync_entity_schema_if_drifted(
                        mock_conn, "DEV0SIDFINSTG", "ERP_MSH_USER", tmp_csv,
                        auto_migrate_ddl=True, load_mode="append"
                    )
                self.assertIn("append", str(ctx.exception))
                mock_recreate.assert_not_called()
        finally:
            if os.path.exists(tmp_csv):
                os.remove(tmp_csv)

    def test_db_state_source_scoping(self):
        """Verify mandatory source parameter and SOURCE = ? in all TeradataStateDB SQL queries."""
        db = TeradataStateDB({
            "host": "tdadev",
            "user": "DEV0SIDFINADM",
            "password": "dummy",
            "technical_database": "DEV0SIDFINTCH",
        })

        # Calling methods without source must raise ValueError
        with self.assertRaises(ValueError):
            db.get_pending_tasks("9001", source="")
        with self.assertRaises(ValueError):
            db.update_task_start("9001", "ERP_MSH_USER", source=None)
        with self.assertRaises(ValueError):
            db.update_task_end("9001", "ERP_MSH_USER", "SUCCESS", file_name="f.csv", error_msg="", source=None)
        with self.assertRaises(ValueError):
            db.get_batch_summary("9001", 1, source="")
        with self.assertRaises(ValueError):
            db.finish_batch("9001", "SUCCESS", source=None)
        with self.assertRaises(ValueError):
            db.mark_batch_failed("9001", source="")

        # Verify SQL statements always filter by BATCH_ID = ? AND SOURCE = ?
        executed_sql = []
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_cursor.fetchone.return_value = (1,)

        def capture_execute(sql, params=None):
            executed_sql.append((sql, params))

        mock_cursor.execute.side_effect = capture_execute
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_conn.__enter__.return_value = mock_conn

        with patch.object(db, "get_connection", return_value=mock_conn):
            db.get_pending_tasks("9001", source="ORACLE_FUSION")
            db.update_task_start("9001", "ERP_MSH_USER", file_name="f.csv", source="ORACLE_FUSION")
            db.update_task_end("9001", "ERP_MSH_USER", "SUCCESS", file_name="f.csv", error_msg="", source="ORACLE_FUSION")
            db.get_batch_summary("9001", 1, source="ORACLE_FUSION")
            db.finish_batch("9001", "SUCCESS", source="ORACLE_FUSION")
            db.mark_batch_failed("9001", source="ORACLE_FUSION")

        self.assertEqual(len(executed_sql), 6)
        for sql, params in executed_sql:
            self.assertIn("SOURCE = ?", sql, f"Missing SOURCE = ? in SQL: {sql}")
            self.assertIn("ORACLE_FUSION", params, f"Missing source param in {params}")

    def test_column_sanitization_parity(self):
        """Verify 100% parity between Python clean_column_name and Bash clean_column_name."""
        env_helpers = os.path.join(TPT_DIR, "lib", "env_and_helpers.sh")
        test_headers = [
            '"USER - ID"',
            '"EMAIL / ADDRESS"',
            '"Invoice - Number / ID"',
            '"  USER__NAME  "',
            "'Special (Col) #1'",
            "SIMPLE_COL_123",
        ]
        for raw in test_headers:
            py_cleaned = clean_column_name(raw)
            if os.name != "nt":
                res = subprocess.run(
                    ["bash", "-c", f'source "{env_helpers}" && clean_column_name { subprocess.list2cmdline([raw]) }'],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                bash_cleaned = res.stdout.strip()
                self.assertEqual(
                    py_cleaned,
                    bash_cleaned,
                    f"Parity mismatch for {raw!r}: Python={py_cleaned!r} vs Bash={bash_cleaned!r}",
                )

    def test_tpt_worker_args(self):
        """Verify run_tpt_loader passes -Y to load_csv_generic.sh and -m/-B/-T to unlock_tpt_table.sh."""
        mock_db = MagicMock()
        with tempfile.TemporaryDirectory() as tmp_work_dir:
            tpt_cfg = {
                "wrapper_script": "/path/to/load_csv_generic.sh",
                "unlock_script": "/path/to/unlock_tpt_table.sh",
                "default_load_mode": "append",
                "target_db": "DEV0SIDFINSTG",
                "work_db": "DEV0SIDFINWRK",
                "work_dir": tmp_work_dir,
                "timeout_seconds": 60,
                "delimiter": ",",
            }
            orch_cfg = {"loading_zone": "/tmp/loading"}

            mock_proc_ok = MagicMock()
            mock_proc_ok.returncode = 0
            mock_proc_ok.stdout = "Load OK"
            mock_proc_ok.stderr = ""

            with patch("lib.tpt_worker.subprocess.run", return_value=mock_proc_ok) as mock_run:
                ent, success = run_tpt_loader(
                    entity="ERP_MSH_USER",
                    file_path_or_pattern="file_userpvo.csv",
                    retry_count=1,
                    batch_id="9009",
                    tpt_config=tpt_cfg,
                    orch_config=orch_cfg,
                    db_state=mock_db,
                    load_mode="append",
                    skip_rows=1,
                    skip_rows_every_file="Y",
                    extract_timestamp="20261016_100800",
                    source="ORACLE_FUSION",
                )
                self.assertEqual(ent, "ERP_MSH_USER")
                self.assertTrue(success)
                self.assertEqual(mock_run.call_count, 2)

                unlock_call_args = mock_run.call_args_list[0][0][0]
                load_call_args = mock_run.call_args_list[1][0][0]

                # Verify unlock_cmd includes -m append -B 9009 -T 20261016_100800
                self.assertIn("-m", unlock_call_args)
                m_idx = unlock_call_args.index("-m")
                self.assertEqual(unlock_call_args[m_idx + 1], "append")
                self.assertIn("-B", unlock_call_args)
                b_idx = unlock_call_args.index("-B")
                self.assertEqual(unlock_call_args[b_idx + 1], "9009")
                self.assertIn("-T", unlock_call_args)
                t_idx = unlock_call_args.index("-T")
                self.assertEqual(unlock_call_args[t_idx + 1], "20261016_100800")

                # Verify load_cmd includes -Y Y
                self.assertIn("-Y", load_call_args)
                y_idx = load_call_args.index("-Y")
                self.assertEqual(load_call_args[y_idx + 1], "Y")


if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestPhase01Units)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
