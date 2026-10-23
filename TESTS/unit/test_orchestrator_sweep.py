#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for multi-source sweep error isolation and --skip-post-tasks drain protection (F2.9, F2.10).
Verifies:
- Multi-source sweep continues when one source fails, recording failure and returning 1 at end
- --skip-post-tasks with replace-mode entities limits consumption to 1 batch unless allow_replace_drain_without_post_tasks=True
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

from dataloader_core.capsule import BatchDescriptor
from dataloader_core.checksum import compute_file_checksum
from dataloader_core.logging_utils import detach_batch_file_logger
from lib.orchestrator_service import OrchestratorService


class TestOrchestratorSweep(unittest.TestCase):

    def tearDown(self):
        detach_batch_file_logger()

    def _create_test_config(self, tmpdir, allow_drain=False):
        cfg_path = os.path.join(tmpdir, "config.json")
        mapping_path = os.path.join(tmpdir, "entity_mapping.csv")
        with open(mapping_path, "w", encoding="utf-8") as f:
            f.write(
                "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION,DELIMITER,LOAD_MODE\n"
                'SRC_A,ERP_TABLE_A,sig_a,".csv,.zip",.csv,",",replace\n'
                'SRC_B,ERP_TABLE_B,sig_b,".csv,.zip",.csv,",",replace\n'
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
                "allow_replace_drain_without_post_tasks": allow_drain,
            },
        }
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return cfg_path

    def test_sweep_continues_on_source_failure_and_exits_one(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(
                config_path=cfg_path,
                sources_list=["SRC_A", "SRC_B"],
            )

            # Mock single-source run() to fail for SRC_A (rc=1) and succeed for SRC_B (rc=0)
            def mock_run():
                if svc.source_override == "SRC_A":
                    return 1
                return 0

            svc.run = MagicMock(side_effect=mock_run)

            rc = svc.run_all_sources()
            # Must return 1 because SRC_A failed
            self.assertEqual(rc, 1)
            # Must have called run for both sources
            self.assertEqual(svc.run.call_count, 2)

    def test_skip_post_tasks_drain_protection_limits_to_one_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir, allow_drain=False)
            svc = OrchestratorService(
                config_path=cfg_path,
                source_override="SRC_A",
                skip_post_tasks=True,
            )
            svc.db = MagicMock()
            svc.wait_or_recover_active_db_batch = MagicMock()
            svc.check_inflight_batch = MagicMock(return_value=[])

            # Stage 2 capsules in LANDING_ZONE/SRC_A
            src_landing = os.path.join(svc.landing_zone)
            os.makedirs(src_landing, exist_ok=True)

            for b_id, ts in [("9001", "20261016_100100"), ("9002", "20261016_100200")]:
                cap = os.path.join(src_landing, f"BATCH_{ts}_{b_id}")
                os.makedirs(cap, exist_ok=True)
                csv_path = os.path.join(cap, f"file_sig_a_{b_id}.csv")
                with open(csv_path, "w") as f:
                    f.write("COL1\nVAL\n")
                cs = compute_file_checksum(csv_path, "md5")
                mf_name = f"MANIFEST_SRC_A_{ts}_{b_id}.MF"
                with open(os.path.join(cap, mf_name), "w") as f:
                    f.write(f"filename,checksum\nfile_sig_a_{b_id}.csv,{cs}\n")
                mf_cs = compute_file_checksum(os.path.join(cap, mf_name), "md5")

                desc = BatchDescriptor.build(
                    batch_id=b_id,
                    source="SRC_A",
                    extract_timestamp=ts,
                    manifest_filename=mf_name,
                    manifest_checksum=mf_cs,
                    files=[{
                        "filename": f"file_sig_a_{b_id}.csv",
                        "target_table": "ERP_TABLE_A",
                        "file_size_bytes": os.path.getsize(csv_path),
                        "checksum": cs,
                        "columns": ["COL1"],
                    }],
                )
                desc.save(os.path.join(cap, "batch_descriptor.json"))

            processed_batches = []
            def fake_prepare(item):
                processed_batches.append(item.batch_id)
                ctx = MagicMock()
                ctx.batch_id = item.batch_id
                ctx.source = "SRC_A"
                return ctx

            svc.prepare_batch_from_queued_item = MagicMock(side_effect=fake_prepare)
            svc.execute_entity_tasks = MagicMock(return_value=True)
            svc.run_completeness_barrier_and_archive = MagicMock(return_value=0)

            rc = svc.run()
            self.assertEqual(rc, 0)
            # Drain protection must have limited processing to ONLY the first batch (9001)
            self.assertEqual(processed_batches, ["9001"])


if __name__ == "__main__":
    unittest.main()
