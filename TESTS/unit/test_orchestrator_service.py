#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for DATA_INGESTION_ORCHESTRATOR/lib/orchestrator_service.py (OrchestratorService) and orchestrator.py."""

import json
import logging
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

from dataloader_core.checksum import compute_file_checksum
from dataloader_core.logging_utils import detach_batch_file_logger
from lib.orchestrator_service import OrchestratorService


class TestOrchestratorService(unittest.TestCase):

    def tearDown(self):
        detach_batch_file_logger()

    def test_orchestrator_entrypoint_line_count_under_80(self):
        orch_py = os.path.join(ORCH_DIR, "orchestrator.py")
        with open(orch_py, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertLess(len(lines), 80, f"orchestrator.py has {len(lines)} lines (expected < 80)")

    def test_orchestrator_service_lifecycle_and_no_environ_mutation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            landing_dir = os.path.join(tmpdir, "LANDING_ZONE")
            loading_dir = os.path.join(tmpdir, "LOADING_ZONE")
            archive_dir = os.path.join(tmpdir, "ARCHIVE_ZONE")
            logs_dir = os.path.join(tmpdir, "LOGS")

            mapping_file = os.path.join(tmpdir, "entity_mapping.csv")
            with open(mapping_file, "w", encoding="utf-8") as f:
                f.write(
                    "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION\n"
                    'ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv,.zip",.csv\n'
                )

            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({
                    "teradata": {
                        "host": "tdadev",
                        "user": "DEV0SIDFINADM",
                        "password": "dummy",
                        "technical_database": "DEV0SIDFINTCH",
                    },
                    "tpt": {
                        "wrapper_script": "/bin/true",
                        "unlock_script": "/bin/true",
                        "target_db": "DEV0SIDFINSTG",
                        "work_db": "DEV0SIDFINWRK",
                    },
                    "orchestration": {
                        "landing_zone": landing_dir,
                        "loading_zone": loading_dir,
                        "archive_zone": archive_dir,
                        "logs_dir": logs_dir,
                        "entity_mapping_file": mapping_file,
                        "verify_checksum": True,
                        "allow_orphan_files": False,
                        "post_ingestion_tasks": [
                            {
                                "type": "shell",
                                "command": "echo 'Batch $CURRENT_BATCH_ID Source $CURRENT_SOURCE'",
                            }
                        ],
                    },
                }, f)

            svc = OrchestratorService(config_path=cfg_file, source_override="ORACLE_FUSION")

            # 1. Stage manifest + data file in LANDING_ZONE/ORACLE_FUSION
            csv_path = os.path.join(svc.landing_zone, "file_userpvo-batch9001-.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("USER_ID,USER_NAME\nU1,Alice\n")
            cs = compute_file_checksum(csv_path, "md5")

            mf_path = os.path.join(svc.landing_zone, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF")
            with open(mf_path, "w", encoding="utf-8") as f:
                f.write(f"filename,checksum\nfile_userpvo-batch9001-.csv,{cs}\n")

            mock_db = MagicMock()
            mock_db.get_active_batch_run.return_value = None
            mock_db.get_pending_tasks.return_value = [("ERP_MSH_USER", "file_userpvo-batch9001-.csv", 0)]
            mock_db.get_batch_summary.return_value = True
            svc.db = mock_db

            with patch("lib.orchestrator_service.sync_entity_schema_if_drifted", return_value=(True, "IDENTICAL", ["USER_ID", "USER_NAME"], 2)), \
                 patch("lib.orchestrator_service.run_tpt_loader", return_value=("ERP_MSH_USER", True)):
                rc = svc.run()

            logging.shutdown()
            self.assertEqual(rc, 0)
            # Ensure global os.environ was NOT polluted
            self.assertNotIn("CURRENT_BATCH_ID", os.environ)
            self.assertNotIn("CURRENT_SOURCE", os.environ)
            self.assertNotIn("CURRENT_MANIFEST", os.environ)

            # Ensure files were archived into ARCHIVE_ZONE/ORACLE_FUSION/2026-10/BATCH_9001_20261016_100000
            expected_capsule = os.path.join(archive_dir, "ORACLE_FUSION", "2026-10", "BATCH_9001_20261016_100000")
            self.assertTrue(os.path.exists(os.path.join(expected_capsule, "file_userpvo-batch9001-.csv")))
            self.assertTrue(
                os.path.exists(os.path.join(expected_capsule, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF"))
            )


if __name__ == "__main__":
    unittest.main()
