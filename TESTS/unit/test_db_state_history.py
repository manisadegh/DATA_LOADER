#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for Teradata State Machine attempt history tracking and zero deletions (F2.11).
Verifies:
- Zero 'DELETE FROM' statements in db_state.py (immutable history)
- First attempt initialization (RUN_ATTEMPT = 1, PROCESS_HOST recorded)
- Subsequent attempt increments (RUN_ATTEMPT = MAX + 1)
- Carry-over of previously SUCCESS entity tasks on re-attempt
- Scoped completion updates by (BATCH_ID, SOURCE, RUN_ATTEMPT)
- Attempt-scoped completeness barrier validation
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, call, patch

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
ORCH_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
for p in (COMMON_DIR, ORCH_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from lib.db_state import TeradataStateDB


class TestDbStateHistory(unittest.TestCase):

    def test_zero_delete_from_in_db_state_source(self):
        db_state_path = os.path.join(ORCH_DIR, "lib", "db_state.py")
        with open(db_state_path, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertNotIn("DELETE FROM", code.upper(), "db_state.py must never delete state rows (F2.11).")

    def test_start_batch_run_first_attempt(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__.return_value = mock_conn
        mock_cur.__enter__.return_value = mock_cur

        # No prior attempt (max attempt None, no active run)
        mock_cur.fetchone.side_effect = [
            None,          # SELECT MAX(RUN_ATTEMPT) -> None
            None,          # SELECT STATUS, PROCESS_PID from prev attempt -> None
        ]

        db = TeradataStateDB(mock_conn, tech_db="TEST_TCH", default_source="ORACLE_FUSION")
        attempt = db.start_batch_run(
            batch_id="9001",
            source="ORACLE_FUSION",
            extract_timestamp="20261016_100000",
            entities_files={"ERP_USER": ["f1.csv"]},
        )

        self.assertEqual(attempt, 1)
        # Verify attempt 1 was inserted
        sql_calls = [c[0][0] for c in mock_cur.execute.call_args_list]
        self.assertTrue(any("INSERT INTO TEST_TCH.BATCH_RUNS" in sql for sql in sql_calls))
        self.assertTrue(any("INSERT INTO TEST_TCH.BATCH_TASKS" in sql for sql in sql_calls))

    def test_start_batch_run_increments_attempt_and_carries_over_success_tasks(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__.return_value = mock_conn
        mock_cur.__enter__.return_value = mock_cur

        # Attempt 1 existed with status FAILED, entity E1 was SUCCESS, entity E2 was FAILED
        mock_cur.fetchone.side_effect = [
            (1,),                     # SELECT MAX(RUN_ATTEMPT) -> 1
            ("FAILED", 99999, "other_host"), # Prev attempt status, pid, host
        ]
        mock_cur.fetchall.side_effect = [
            [("E1", 1, 0, "TPT_E1", "2026-10-16 10:00:00", "2026-10-16 10:05:00")],  # SELECT ... STATUS='SUCCESS'
        ]

        db = TeradataStateDB(mock_conn, tech_db="TEST_TCH", default_source="ORACLE_FUSION")
        attempt = db.start_batch_run(
            batch_id="9001",
            source="ORACLE_FUSION",
            extract_timestamp="20261016_100000",
            entities_files={"E1": ["f1.csv"], "E2": ["f2.csv"]},
        )

        # New attempt must be 2
        self.assertEqual(attempt, 2)

        # Verify E1 was inserted as SUCCESS (carried over) and E2 was inserted as PENDING
        executed_params = [c[0][1] for c in mock_cur.execute.call_args_list if len(c[0]) > 1]
        
        # Check that E1 insert had STATUS 'SUCCESS'
        task_inserts = [
            c[0] for c in mock_cur.execute.call_args_list 
            if "INSERT INTO TEST_TCH.BATCH_TASKS" in c[0][0]
        ]
        self.assertEqual(len(task_inserts), 2)
        # E1 carried over
        self.assertIn("'SUCCESS'", task_inserts[0][0])
        # E2 pending
        self.assertIn("'PENDING'", task_inserts[1][0])

    def test_finish_batch_updates_attempt_scoped(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__.return_value = mock_conn
        mock_cur.__enter__.return_value = mock_cur

        db = TeradataStateDB(mock_conn, tech_db="TEST_TCH", default_source="ORACLE_FUSION")
        db.finish_batch(batch_id="9001", final_status="SUCCESS", source="ORACLE_FUSION", run_attempt=2)

        update_call = [c for c in mock_cur.execute.call_args_list if "UPDATE TEST_TCH.BATCH_RUNS" in c[0][0]][0]
        sql, params = update_call[0]
        self.assertIn("RUN_ATTEMPT = ?", sql)
        self.assertEqual(params[0], "SUCCESS")
        self.assertEqual(params[2], "9001")
        self.assertEqual(params[3], "ORACLE_FUSION")
        self.assertEqual(params[4], 2)

    def test_get_batch_summary_checks_run_attempt(self):
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_conn.__enter__.return_value = mock_conn
        mock_cur.__enter__.return_value = mock_cur
        mock_cur.fetchone.return_value = (3,)

        db = TeradataStateDB(mock_conn, tech_db="TEST_TCH", default_source="ORACLE_FUSION")
        ok = db.get_batch_summary(batch_id="9001", expected_entity_count=3, source="ORACLE_FUSION", run_attempt=2)
        self.assertTrue(ok)

        summary_call = [c for c in mock_cur.execute.call_args_list if "SELECT COUNT(*)" in c[0][0]][0]
        sql, params = summary_call[0]
        self.assertIn("RUN_ATTEMPT = ?", sql)
        self.assertEqual(params, ("9001", "ORACLE_FUSION", 2))


if __name__ == "__main__":
    unittest.main()
