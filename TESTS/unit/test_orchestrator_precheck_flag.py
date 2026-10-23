#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests verifying the conditional passing of the precheck flag (-C)
to TPT loader: only when Schema Guard actually ran in the current process (F1.5).
"""

import json
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

from lib.orchestrator_service import BatchContext, OrchestratorService


class TestOrchestratorPrecheckFlag(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.landing = os.path.join(self.tmpdir.name, "LANDING")
        self.loading = os.path.join(self.tmpdir.name, "LOADING")
        self.archive = os.path.join(self.tmpdir.name, "ARCHIVE")
        self.logs = os.path.join(self.tmpdir.name, "LOGS")
        for d in (self.landing, self.loading, self.archive, self.logs):
            os.makedirs(d, exist_ok=True)

        self.mapping_file = os.path.join(self.tmpdir.name, "entity_mapping.csv")
        with open(self.mapping_file, "w", encoding="utf-8") as f:
            f.write(
                "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION\n"
                'ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv",.csv\n'
            )

    def tearDown(self):
        self.tmpdir.cleanup()

    def _make_config(self, guard_enabled=True):
        return {
            "teradata": {
                "host": "tdadev",
                "user": "DEV0SIDFINADM",
                "technical_database": "DEV0SIDFINTCH",
            },
            "schema_guard": {
                "enabled": guard_enabled,
                "auto_migrate_ddl": False,
                "target_database": "DEV0SIDFINSTG",
            },
            "tpt": {
                "wrapper_script": "/bin/true",
                "unlock_script": "/bin/true",
                "target_db": "DEV0SIDFINSTG",
                "work_db": "DEV0SIDFINWRK",
            },
            "orchestration": {
                "landing_zone": self.landing,
                "loading_zone": self.loading,
                "archive_zone": self.archive,
                "logs_dir": self.logs,
                "entity_mapping_file": self.mapping_file,
                "max_concurrent_jobs": 1,
            },
        }

    @patch("lib.orchestrator_service.process_entity_task")
    def test_no_skip_when_guard_disabled(self, mock_process_task):
        mock_process_task.return_value = True
        cfg = self._make_config(guard_enabled=False)
        cfg_file = os.path.join(self.tmpdir.name, "config_disabled.json")
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        service = OrchestratorService(cfg_file)
        mock_db = MagicMock()
        mock_db.get_pending_tasks.return_value = [("ERP_MSH_USER", "file_userpvo-batch1-.csv", 0)]
        service._db = mock_db

        ctx = BatchContext(
            batch_id="101",
            source="ORACLE_FUSION",
            extract_ts="20261016_100000",
            manifest_file="MANIFEST_ORACLE_FUSION_20261016_100000_101.MF",
            manifest_entries={},
            capsule_dir=os.path.join(self.landing, "BATCH_20261016_100000_101"),
            validated_files=["file_userpvo-batch1-.csv"],
            entities_workload={
                "ERP_MSH_USER": {
                    "files": ["file_userpvo-batch1-.csv"],
                    "signature": "userpvo",
                    "target_table": "ERP_MSH_USER",
                }
            },
        )

        ok = service.execute_entity_tasks(ctx)
        self.assertTrue(ok)
        mock_process_task.assert_called_once()
        _, kwargs = mock_process_task.call_args
        self.assertFalse(kwargs.get("skip_precheck"), "Expected skip_precheck=False when schema guard is disabled")

    @patch("lib.orchestrator_service.process_entity_task")
    @patch("lib.orchestrator_service.sync_entity_schema_if_drifted")
    def test_skip_when_guard_identical(self, mock_sync_schema, mock_process_task):
        mock_process_task.return_value = True
        mock_sync_schema.return_value = (True, "IDENTICAL", ["C1", "C2"], 2)

        cfg = self._make_config(guard_enabled=True)
        cfg_file = os.path.join(self.tmpdir.name, "config_enabled.json")
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump(cfg, f)

        service = OrchestratorService(cfg_file)
        mock_db = MagicMock()
        mock_db.conn_mgr = MagicMock()
        mock_db.get_connection.return_value.__enter__.return_value = MagicMock()
        mock_db.get_pending_tasks.return_value = [("ERP_MSH_USER", "file_userpvo-batch1-.csv", 0)]
        service._db = mock_db

        ctx = BatchContext(
            batch_id="102",
            source="ORACLE_FUSION",
            extract_ts="20261016_100000",
            manifest_file="MANIFEST_ORACLE_FUSION_20261016_100000_102.MF",
            manifest_entries={},
            capsule_dir=os.path.join(self.landing, "BATCH_20261016_100000_102"),
            validated_files=["file_userpvo-batch1-.csv"],
            entities_workload={
                "ERP_MSH_USER": {
                    "files": ["file_userpvo-batch1-.csv"],
                    "signature": "userpvo",
                    "target_table": "ERP_MSH_USER",
                }
            },
        )

        ok = service.execute_entity_tasks(ctx)
        self.assertTrue(ok)
        mock_process_task.assert_called_once()
        _, kwargs = mock_process_task.call_args
        self.assertTrue(kwargs.get("skip_precheck"), "Expected skip_precheck=True when schema guard ran and was identical")
        self.assertEqual(kwargs.get("has_meta"), 2)


if __name__ == "__main__":
    unittest.main()
