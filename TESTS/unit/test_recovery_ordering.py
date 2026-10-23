#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for crash recovery sequencing and orphaned staging cleanup (F2.1, F2.8).
Verifies:
- In-flight batches in LOADING_ZONE are processed before newly queued batches in LANDING_ZONE
- Orphaned .staging_BATCH_* directories from interrupted feeder runs are moved to QUARANTINE
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
FEEDER_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "BICC_INTAKE_CONTROLLER")
for p in (COMMON_DIR, ORCH_DIR, FEEDER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from dataloader_core.capsule import BatchDescriptor
from dataloader_core.checksum import compute_file_checksum
from dataloader_core.logging_utils import detach_batch_file_logger
from lib.intake_service import IntakeControllerService
from lib.orchestrator_service import OrchestratorService


class TestRecoveryOrdering(unittest.TestCase):

    def tearDown(self):
        detach_batch_file_logger()

    def test_inflight_batches_processed_before_queued_landing_batches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "config.json")
            mapping_path = os.path.join(tmpdir, "entity_mapping.csv")
            with open(mapping_path, "w", encoding="utf-8") as f:
                f.write(
                    "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION\n"
                    'ORACLE_FUSION,ERP_TABLE,sig,".csv,.zip",.csv\n'
                )

            landing_zone = os.path.join(tmpdir, "LANDING_ZONE")
            loading_zone = os.path.join(tmpdir, "LOADING_ZONE")
            archive_zone = os.path.join(tmpdir, "ARCHIVE_ZONE")
            logs_dir = os.path.join(tmpdir, "LOGS")

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
                    "landing_zone": landing_zone,
                    "loading_zone": loading_zone,
                    "archive_zone": archive_zone,
                    "logs_dir": logs_dir,
                    "entity_mapping_file": mapping_path,
                },
            }
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f)

            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")
            svc.db = MagicMock()
            svc.wait_or_recover_active_db_batch = MagicMock()

            # 1. Stage in-flight batch (8001) in LOADING_ZONE
            in_cap = os.path.join(svc.loading_zone, "BATCH_20261016_090000_8001")
            os.makedirs(in_cap, exist_ok=True)
            f1_path = os.path.join(in_cap, "file_sig_8001.csv")
            with open(f1_path, "w") as f:
                f.write("A\n1\n")
            cs1 = compute_file_checksum(f1_path, "md5")
            mf1_path = os.path.join(in_cap, "MANIFEST_ORACLE_FUSION_20261016_090000_8001.MF")
            with open(mf1_path, "w") as f:
                f.write(f"filename,checksum\nfile_sig_8001.csv,{cs1}\n")
            mf1_cs = compute_file_checksum(mf1_path, "md5")
            desc1 = BatchDescriptor.build(
                batch_id="8001",
                source="ORACLE_FUSION",
                extract_timestamp="20261016_090000",
                manifest_filename=os.path.basename(mf1_path),
                manifest_checksum=mf1_cs,
                files=[{
                    "filename": "file_sig_8001.csv",
                    "target_table": "ERP_TABLE",
                    "file_size_bytes": os.path.getsize(f1_path),
                    "checksum": cs1,
                    "columns": ["A"],
                }],
            )
            desc1.save(os.path.join(in_cap, "batch_descriptor.json"))

            # 2. Stage queued batch (9001) in LANDING_ZONE
            q_cap = os.path.join(svc.landing_zone, "BATCH_20261016_100000_9001")
            os.makedirs(q_cap, exist_ok=True)
            f2_path = os.path.join(q_cap, "file_sig_9001.csv")
            with open(f2_path, "w") as f:
                f.write("A\n2\n")
            cs2 = compute_file_checksum(f2_path, "md5")
            mf2_path = os.path.join(q_cap, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF")
            with open(mf2_path, "w") as f:
                f.write(f"filename,checksum\nfile_sig_9001.csv,{cs2}\n")
            mf2_cs = compute_file_checksum(mf2_path, "md5")
            desc2 = BatchDescriptor.build(
                batch_id="9001",
                source="ORACLE_FUSION",
                extract_timestamp="20261016_100000",
                manifest_filename=os.path.basename(mf2_path),
                manifest_checksum=mf2_cs,
                files=[{
                    "filename": "file_sig_9001.csv",
                    "target_table": "ERP_TABLE",
                    "file_size_bytes": os.path.getsize(f2_path),
                    "checksum": cs2,
                    "columns": ["A"],
                }],
            )
            desc2.save(os.path.join(q_cap, "batch_descriptor.json"))

            order_of_execution = []
            def fake_execute(ctx):
                order_of_execution.append(ctx.batch_id)
                return True

            svc.execute_entity_tasks = MagicMock(side_effect=fake_execute)
            svc.run_completeness_barrier_and_archive = MagicMock(return_value=0)

            rc = svc.run()
            self.assertEqual(rc, 0)
            # In-flight 8001 MUST be executed BEFORE queued 9001
            self.assertEqual(order_of_execution, ["8001", "9001"])

    def test_orphaned_staging_directory_quarantined_at_feeder_startup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            drop_zone = os.path.join(tmpdir, "DATA", "DROP_ZONE")
            landing_zone = os.path.join(tmpdir, "DATA", "LANDING_ZONE")
            archive_zone = os.path.join(tmpdir, "DATA", "ARCHIVE_ZONE")
            logs_dir = os.path.join(tmpdir, "LOGS")

            os.makedirs(os.path.join(drop_zone, "ORACLE_FUSION"), exist_ok=True)
            src_landing = os.path.join(landing_zone, "ORACLE_FUSION")
            os.makedirs(src_landing, exist_ok=True)

            # Leftover orphaned .staging_BATCH_* from interrupted process
            leftover_staging = os.path.join(src_landing, ".staging_BATCH_20261016_080000_7001")
            os.makedirs(leftover_staging, exist_ok=True)
            with open(os.path.join(leftover_staging, "partial.csv"), "w") as f:
                f.write("partial data")

            feeder_cfg = os.path.join(tmpdir, "feeder_config.json")
            with open(feeder_cfg, "w", encoding="utf-8") as f:
                json.dump({
                    "feeder": {
                        "drop_zone": drop_zone,
                        "logs_dir": logs_dir,
                        "source_system_code": "ORACLE_FUSION",
                        "intake_plugin": "bicc",
                    },
                    "orchestrator": {
                        "orchestrator_dir": tmpdir,
                        "config_file": "config.json",
                        "landing_zone": landing_zone,
                        "archive_zone": archive_zone,
                        "trigger_orchestrator": False,
                    },
                }, f)

            service = IntakeControllerService(
                config_path=feeder_cfg,
                source_override="ORACLE_FUSION",
                enqueue_only=True,
            )

            rc = service.run()
            self.assertEqual(rc, 0)

            # Orphaned directory must NOT remain in landing zone root
            self.assertFalse(os.path.exists(leftover_staging))

            # Must have been moved to QUARANTINE
            quarantine_dir = os.path.join(src_landing, "QUARANTINE")
            self.assertTrue(os.path.isdir(quarantine_dir))
            quarantined_items = os.listdir(quarantine_dir)
            self.assertTrue(len(quarantined_items) >= 1)
            self.assertTrue(any(".staging_BATCH_20261016_080000_7001" in item for item in quarantined_items))


if __name__ == "__main__":
    unittest.main()
