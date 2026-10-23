#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for OrchestratorService pre-flight state validation (F2.8, F2.11).
Verifies:
- Database connectivity failure at startup is fatal (raises DataLoaderError)
- Foreign host RUNNING batch halts execution safely (raises DataLoaderError)
- Local crashed batch with dead PID is marked FAILED in technical database
- Reconciled in-flight batch already marked SUCCESS skips TPT execution
"""

import json
import os
import socket
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

from dataloader_core.capsule import BatchDescriptor
from dataloader_core.checksum import compute_file_checksum
from dataloader_core.exceptions import DataLoaderError
from dataloader_core.logging_utils import detach_batch_file_logger
from lib.orchestrator_service import BatchContext, OrchestratorService


class TestOrchestratorPreflight(unittest.TestCase):

    def tearDown(self):
        detach_batch_file_logger()

    def _create_test_config(self, tmpdir):
        cfg_path = os.path.join(tmpdir, "config.json")
        mapping_path = os.path.join(tmpdir, "entity_mapping.csv")
        with open(mapping_path, "w", encoding="utf-8") as f:
            f.write(
                "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION\n"
                'ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv,.zip",.csv\n'
            )
        cfg = {
            "teradata": {
                "host": "localhost",
                "user": "TEST_USER",
                "technical_database": "TEST_TCH",
            },
            "tpt": {
                "wrapper_script": "/bin/true",
                "unlock_script": "/bin/true",
                "target_db": "TEST_STG",
                "work_db": "TEST_WRK",
            },
            "orchestration": {
                "landing_zone": os.path.join(tmpdir, "LANDING_ZONE"),
                "loading_zone": os.path.join(tmpdir, "LOADING_ZONE"),
                "archive_zone": os.path.join(tmpdir, "ARCHIVE_ZONE"),
                "logs_dir": os.path.join(tmpdir, "LOGS"),
                "entity_mapping_file": mapping_path,
            },
        }
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return cfg_path

    def test_preflight_db_error_is_fatal(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")
            mock_db = MagicMock()
            mock_db.get_active_batch_run.side_effect = Exception("Teradata 10054 Connection reset")
            svc.db = mock_db

            with self.assertRaises(DataLoaderError) as ctx:
                svc.wait_or_recover_active_db_batch()
            self.assertIn("Pre-flight state check failed", str(ctx.exception))

    def test_preflight_foreign_host_running_batch_halts_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")
            mock_db = MagicMock()
            mock_db.get_active_batch_run.return_value = {
                "batch_id": "9001",
                "source": "ORACLE_FUSION",
                "process_pid": 12345,
                "process_host": "foreign_server_node_02.corp",
            }
            svc.db = mock_db

            with self.assertRaises(DataLoaderError) as ctx:
                svc.wait_or_recover_active_db_batch()
            self.assertIn("RUNNING on foreign host", str(ctx.exception))

    def test_preflight_local_dead_pid_marks_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")
            mock_db = MagicMock()
            mock_db.get_active_batch_run.return_value = {
                "batch_id": "9001",
                "source": "ORACLE_FUSION",
                "process_pid": 999999,
                "process_host": socket.gethostname(),
            }
            svc.db = mock_db

            svc.wait_or_recover_active_db_batch()
            mock_db.mark_batch_failed.assert_called_once_with("9001", source="ORACLE_FUSION")

    def test_inflight_batch_reconciled_as_success_skips_tpt(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")

            loading_cap = os.path.join(svc.loading_zone, "BATCH_20261016_100000_9001")
            os.makedirs(loading_cap, exist_ok=True)
            csv_path = os.path.join(loading_cap, "file_userpvo-batch9001-.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("USER_ID,NAME\n1,Alice\n")
            cs = compute_file_checksum(csv_path, "md5")

            mf_path = os.path.join(loading_cap, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF")
            with open(mf_path, "w", encoding="utf-8") as f:
                f.write(f"filename,checksum\nfile_userpvo-batch9001-.csv,{cs}\n")
            mf_cs = compute_file_checksum(mf_path, "md5")

            desc = BatchDescriptor.build(
                batch_id="9001",
                source="ORACLE_FUSION",
                extract_timestamp="20261016_100000",
                manifest_filename=os.path.basename(mf_path),
                manifest_checksum=mf_cs,
                files=[{
                    "filename": "file_userpvo-batch9001-.csv",
                    "target_table": "ERP_MSH_USER",
                    "file_size_bytes": os.path.getsize(csv_path),
                    "checksum": cs,
                    "columns": ["USER_ID", "NAME"],
                }],
            )
            desc.save(os.path.join(loading_cap, "batch_descriptor.json"))

            mock_db = MagicMock()
            mock_db.get_latest_attempt.return_value = {
                "run_attempt": 1,
                "status": "SUCCESS",
            }
            svc.db = mock_db

            batches = svc.check_inflight_batch()
            self.assertEqual(len(batches), 1)
            ctx = batches[0]
            self.assertTrue(ctx.already_loaded)

            # execute_entity_tasks must return True immediately without invoking run_tpt_loader
            with patch("lib.orchestrator_service.run_tpt_loader") as mock_tpt:
                res = svc.execute_entity_tasks(ctx)
                self.assertTrue(res)
                mock_tpt.assert_not_called()


if __name__ == "__main__":
    unittest.main()
