#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for TPT worker unlock and lock recovery logic (F1.4).
Validates that:
1. Unlock success is never treated as load success; only the subsequent retry determines outcome.
2. Exact -j job name is passed to loader, unlocker, and recorded in BATCH_TASKS.
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
ORCH_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
for p in (COMMON_DIR, ORCH_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from lib.tpt_worker import RunResult, run_tpt_loader


class TestTptWorkerUnlock(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.work_dir = self.tmpdir.name

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("lib.tpt_worker._run")
    def test_unlock_success_does_not_mark_entity_success(self, mock_run):
        # 1st call (load): fail with 2652
        out_file = os.path.join(self.work_dir, "run1.out")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write("RDBMS error 2652: The specified table is being Loaded.\n")
        res_fail = RunResult(returncode=12, output_path=out_file)

        # 2nd call (unlock): success 0
        res_unlock = RunResult(returncode=0, output_path=out_file)

        # 3rd call (retry load): still fails with 12
        res_retry = RunResult(returncode=12, output_path=out_file)

        mock_run.side_effect = [res_fail, res_unlock, res_retry]

        mock_db = MagicMock()
        tpt_cfg = {
            "wrapper_script": "/bin/true",
            "unlock_script": "/bin/true",
            "work_dir": self.work_dir,
        }

        entity, success = run_tpt_loader(
            entity="ERP_MSH_USER",
            file_path_or_pattern="user.csv",
            retry_count=0,
            batch_id="9001",
            tpt_config=tpt_cfg,
            db_state=mock_db,
            source="ORACLE_FUSION",
        )

        self.assertFalse(success)
        self.assertEqual(entity, "ERP_MSH_USER")
        self.assertEqual(mock_run.call_count, 3)
        mock_db.update_task_end.assert_called_with("9001", "ERP_MSH_USER", "FAILED", 0, error_msg=unittest.mock.ANY, source="ORACLE_FUSION")

    @patch("lib.tpt_worker._run")
    def test_unlock_then_retry_success(self, mock_run):
        out_file = os.path.join(self.work_dir, "run2.out")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write("Error 2652: Table is being Loaded\n")
        res_fail = RunResult(returncode=12, output_path=out_file)
        res_unlock = RunResult(returncode=0, output_path=out_file)
        res_retry = RunResult(returncode=0, output_path=out_file)

        mock_run.side_effect = [res_fail, res_unlock, res_retry]

        mock_db = MagicMock()
        tpt_cfg = {
            "wrapper_script": "/bin/true",
            "unlock_script": "/bin/true",
            "work_dir": self.work_dir,
        }

        entity, success = run_tpt_loader(
            entity="ERP_MSH_USER",
            file_path_or_pattern="user.csv",
            retry_count=0,
            batch_id="9002",
            tpt_config=tpt_cfg,
            db_state=mock_db,
            source="ORACLE_FUSION",
        )

        self.assertTrue(success)
        self.assertEqual(mock_run.call_count, 3)
        mock_db.update_task_end.assert_called_with("9002", "ERP_MSH_USER", "SUCCESS", source="ORACLE_FUSION")

    @patch("lib.tpt_worker._run")
    def test_job_name_passed_and_stored(self, mock_run):
        out_file = os.path.join(self.work_dir, "run3.out")
        with open(out_file, "w", encoding="utf-8") as f:
            f.write("OK\n")
        mock_run.return_value = RunResult(returncode=0, output_path=out_file)

        mock_db = MagicMock()
        tpt_cfg = {
            "wrapper_script": "/bin/true",
            "unlock_script": "/bin/true",
            "work_dir": self.work_dir,
        }

        run_tpt_loader(
            entity="ERP_MSH_USER",
            file_path_or_pattern="user.csv",
            retry_count=0,
            batch_id="9003",
            tpt_config=tpt_cfg,
            db_state=mock_db,
            source="ORACLE_FUSION",
        )

        # Check that update_task_start was called with tpt_job_name starting with TPT_ERP_MSH_USER_
        mock_db.update_task_start.assert_called_once()
        _, start_kwargs = mock_db.update_task_start.call_args
        job_name = start_kwargs.get("tpt_job_name")
        self.assertIsNotNone(job_name)
        self.assertTrue(job_name.startswith("TPT_ERP_MSH_USER_"))

        # Check that -j was passed to cmd
        cmd_called = mock_run.call_args[0][0]
        self.assertIn("-j", cmd_called)
        j_index = cmd_called.index("-j")
        self.assertEqual(cmd_called[j_index + 1], job_name)


if __name__ == "__main__":
    unittest.main()
