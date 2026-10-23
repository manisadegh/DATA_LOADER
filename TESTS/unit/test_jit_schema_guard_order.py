#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for Just-In-Time Schema Guard execution ordering in OrchestratorService."""

import json
import logging
import os
import sys
import tempfile
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

from dataloader_core.capsule import BatchDescriptor
from dataloader_core.checksum import compute_file_checksum
from dataloader_core.logging_utils import detach_batch_file_logger
from lib.orchestrator_service import OrchestratorService


class TestJitSchemaGuardOrder(unittest.TestCase):

    def tearDown(self):
        detach_batch_file_logger()

    def test_jit_schema_guard_called_per_batch_in_fifo_order(self):
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
                    "schema_guard": {
                        "enabled": True,
                        "auto_migrate_ddl": True,
                        "target_database": "DEV0SIDFINSTG",
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
                        "verify_checksum": False,
                        "verify_checksum_on_queued_capsule": False,
                        "post_ingestion_tasks": [],
                    },
                }, f)

            svc = OrchestratorService(config_path=cfg_file, source_override="ORACLE_FUSION")

            # Stage Capsule 1 (Batch 9001, 2 columns)
            cap1 = os.path.join(svc.landing_zone, "BATCH_20261016_100100_9001")
            os.makedirs(cap1, exist_ok=True)
            f1_path = os.path.join(cap1, "file_userpvo-batch9001-.csv")
            with open(f1_path, "w", newline="\n") as f:
                f.write("USER_ID,USER_NAME\nU1,Alice\n")
            cs1 = compute_file_checksum(f1_path, "md5")
            mf1_path = os.path.join(cap1, "MANIFEST_ORACLE_FUSION_20261016_100100_9001.MF")
            with open(mf1_path, "w", newline="\n") as f:
                f.write(f"filename,checksum\nfile_userpvo-batch9001-.csv,{cs1}\n")
            mf1_cs = compute_file_checksum(mf1_path, "md5")

            desc1 = BatchDescriptor(
                batch_id="9001",
                source="ORACLE_FUSION",
                extract_timestamp="2026-10-16 10:01:00",
                extract_timestamp_raw="20261016_100100",
                created_at_utc="2026-10-16T10:01:05Z",
                manifest_filename="MANIFEST_ORACLE_FUSION_20261016_100100_9001.MF",
                manifest_checksum=mf1_cs,
                entities={
                    "ERP_MSH_USER": {
                        "files": ["file_userpvo-batch9001-.csv"],
                        "file_sizes": {"file_userpvo-batch9001-.csv": os.path.getsize(f1_path)},
                        "header_columns": ["USER_ID", "USER_NAME"],
                    }
                },
            )
            desc1.to_json_file(os.path.join(cap1, "batch_descriptor.json"))

            # Stage Capsule 2 (Batch 9002, 3 columns)
            cap2 = os.path.join(svc.landing_zone, "BATCH_20261016_100200_9002")
            os.makedirs(cap2, exist_ok=True)
            f2_path = os.path.join(cap2, "file_userpvo-batch9002-.csv")
            with open(f2_path, "w", newline="\n") as f:
                f.write("USER_ID,USER_NAME,EXTRA_COL\nU2,Bob,Extra\n")
            cs2 = compute_file_checksum(f2_path, "md5")
            mf2_path = os.path.join(cap2, "MANIFEST_ORACLE_FUSION_20261016_100200_9002.MF")
            with open(mf2_path, "w", newline="\n") as f:
                f.write(f"filename,checksum\nfile_userpvo-batch9002-.csv,{cs2}\n")
            mf2_cs = compute_file_checksum(mf2_path, "md5")

            desc2 = BatchDescriptor(
                batch_id="9002",
                source="ORACLE_FUSION",
                extract_timestamp="2026-10-16 10:02:00",
                extract_timestamp_raw="20261016_100200",
                created_at_utc="2026-10-16T10:02:05Z",
                manifest_filename="MANIFEST_ORACLE_FUSION_20261016_100200_9002.MF",
                manifest_checksum=mf2_cs,
                entities={
                    "ERP_MSH_USER": {
                        "files": ["file_userpvo-batch9002-.csv"],
                        "file_sizes": {"file_userpvo-batch9002-.csv": os.path.getsize(f2_path)},
                        "header_columns": ["USER_ID", "USER_NAME", "EXTRA_COL"],
                    }
                },
            )
            desc2.to_json_file(os.path.join(cap2, "batch_descriptor.json"))

            mock_db = MagicMock()
            mock_db.get_active_batch_run.return_value = None
            mock_db.get_pending_tasks.side_effect = lambda b_id, source=None: [("ERP_MSH_USER", f"file_userpvo-batch{b_id}-.csv", 0)]
            mock_db.get_batch_summary.return_value = True
            mock_conn = MagicMock()
            mock_db.conn_mgr.acquire_connection.return_value.__enter__.return_value = mock_conn
            mock_db.get_connection.return_value.__enter__.return_value = mock_conn
            svc.db = mock_db

            schema_calls = []

            def fake_sync(*args, **kwargs):
                cols = kwargs.get("csv_cols")
                schema_calls.append(cols)
                meta_val = 0 if len(cols) == 2 else 2
                return True, "IDENTICAL", cols, meta_val

            with patch("lib.orchestrator_service.sync_entity_schema_if_drifted", side_effect=fake_sync), \
                 patch("lib.orchestrator_service.run_tpt_loader", return_value=("ERP_MSH_USER", True)) as mock_loader:
                rc = svc.run()

            logging.shutdown()
            self.assertEqual(rc, 0)
            self.assertEqual(len(schema_calls), 2)
            # Batch 1 processed first with 2 columns and measured has_meta=0
            self.assertEqual(schema_calls[0], ["USER_ID", "USER_NAME"])
            self.assertEqual(mock_loader.call_args_list[0][1]["has_meta"], 0)
            # Batch 2 processed second with 3 columns and measured has_meta=2
            self.assertEqual(schema_calls[1], ["USER_ID", "USER_NAME", "EXTRA_COL"])
            self.assertEqual(mock_loader.call_args_list[1][1]["has_meta"], 2)


if __name__ == "__main__":
    unittest.main()
