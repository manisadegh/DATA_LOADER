#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for batch directory lifecycle and atomic directory transitions (F2.2, F2.3, F2.4).
Verifies:
- Atomic rename dequeue (os.replace) from LANDING to LOADING
- Work area (.work/<ENTITY>/files.lst) creation without payload mutation
- Atomic archive rename to ARCHIVE_ZONE/<SRC>/<YYYY-MM>/BATCH_<ID>_<TS>
- Archive collision move-aside (.previous_<epoch>)
- Chronological in-flight batch discovery
- Stray root files in LOADING_ZONE rejection
- Filesystem device check (st_dev)
"""

import json
import os
import shutil
import sys
import tempfile
import time
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
from dataloader_core.exceptions import ConfigurationError, OrchestratorExecutionError
from dataloader_core.logging_utils import detach_batch_file_logger
from lib.orchestrator_service import (
    BatchContext,
    OrchestratorService,
    prepare_entity_work_area,
)
from lib.sensor import QueuedBatchItem


class TestBatchDirectoryLifecycle(unittest.TestCase):

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
                "verify_checksum": True,
                "verify_checksum_on_queued_capsule": True,
                "allow_orphan_files": False,
            },
        }
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
        return cfg_path

    def test_dequeue_rename_to_loading_zone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")
            svc.db = MagicMock()

            landing_capsule = os.path.join(svc.landing_zone, "BATCH_20261016_100000_9001")
            os.makedirs(landing_capsule, exist_ok=True)
            csv_path = os.path.join(landing_capsule, "file_userpvo-batch9001-.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("USER_ID,NAME\n1,Alice\n")
            cs = compute_file_checksum(csv_path, "md5")

            mf_path = os.path.join(landing_capsule, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF")
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
            desc.save(os.path.join(landing_capsule, "batch_descriptor.json"))

            item = QueuedBatchItem(
                batch_id="9001",
                source="ORACLE_FUSION",
                extract_timestamp="20261016_100000",
                manifest_path=mf_path,
                capsule_dir=landing_capsule,
                data_files=["file_userpvo-batch9001-.csv"],
            )

            ctx = svc.prepare_batch_from_queued_item(item)
            self.assertEqual(ctx.batch_id, "9001")
            # Batch directory must be moved to LOADING_ZONE
            self.assertTrue(ctx.batch_dir.startswith(svc.loading_zone))
            self.assertTrue(os.path.isdir(ctx.batch_dir))
            # Source in LANDING_ZONE must be gone
            self.assertFalse(os.path.exists(landing_capsule))

    def test_prepare_work_area_leaves_payload_untouched(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            batch_dir = os.path.join(tmpdir, "BATCH_20261016_100000_9001")
            os.makedirs(batch_dir, exist_ok=True)
            csv_path = os.path.join(batch_dir, "file_userpvo-batch9001-.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("USER_ID,NAME\n1,Alice\n2,Bob\n")

            hash_before = compute_file_checksum(csv_path, "sha256")
            mtime_before = os.path.getmtime(csv_path)

            file_list_path = prepare_entity_work_area(
                batch_dir=batch_dir,
                entity="ERP_MSH_USER",
                payload_files=["file_userpvo-batch9001-.csv"],
            )

            self.assertTrue(os.path.exists(file_list_path))
            with open(file_list_path, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            self.assertEqual(len(lines), 1)

            # Payload file in batch_dir must be byte-for-byte untouched
            hash_after = compute_file_checksum(csv_path, "sha256")
            self.assertEqual(hash_before, hash_after)
            self.assertEqual(mtime_before, os.path.getmtime(csv_path))

    def test_archive_capsule_and_move_aside_collision(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")
            mock_db = MagicMock()
            mock_db.get_batch_summary.return_value = True
            svc.db = mock_db

            loading_cap = os.path.join(svc.loading_zone, "BATCH_20261016_100000_9001")
            os.makedirs(loading_cap, exist_ok=True)
            with open(os.path.join(loading_cap, "data.csv"), "w", encoding="utf-8") as f:
                f.write("A,B\n1,2\n")
            with open(os.path.join(loading_cap, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF"), "w") as f:
                f.write("filename,checksum\ndata.csv,abc\n")

            # Pre-create conflicting archive capsule
            archive_month = os.path.join(svc.archive_zone, "2026-10")
            os.makedirs(archive_month, exist_ok=True)
            conflict_dir = os.path.join(archive_month, "BATCH_9001_20261016_100000")
            os.makedirs(conflict_dir, exist_ok=True)
            with open(os.path.join(conflict_dir, "old_file.txt"), "w") as f:
                f.write("old data")

            ctx = BatchContext(
                batch_id="9001",
                source="ORACLE_FUSION",
                extract_timestamp="20261016_100000",
                manifest_path=os.path.join(loading_cap, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF"),
                data_files=["data.csv"],
                batch_dir=loading_cap,
            )

            rc = svc.run_completeness_barrier_and_archive(ctx)
            self.assertEqual(rc, 0)

            # Old capsule moved aside to .previous_*
            prev_dirs = [d for d in os.listdir(archive_month) if d.startswith(".previous_") or ".previous_" in d]
            self.assertTrue(len(prev_dirs) >= 1)

            # Loading capsule moved to final archive path
            self.assertFalse(os.path.exists(loading_cap))
            self.assertTrue(os.path.exists(os.path.join(conflict_dir, "data.csv")))

    def test_inflight_batches_sorted_fifo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")
            mock_db = MagicMock()
            mock_db.get_latest_attempt.return_value = None
            svc.db = mock_db

            # Create in-flight batches in non-chronological order: 9003, 9001, 9002
            for b_id, ts in [("9003", "20261016_100300"), ("9001", "20261016_100100"), ("9002", "20261016_100200")]:
                cap = os.path.join(svc.loading_zone, f"BATCH_{ts}_{b_id}")
                os.makedirs(cap, exist_ok=True)
                with open(os.path.join(cap, f"MANIFEST_ORACLE_FUSION_{ts}_{b_id}.MF"), "w") as f:
                    f.write(f"filename,checksum\nfile_{b_id}.csv,abc\n")
                with open(os.path.join(cap, f"file_{b_id}.csv"), "w") as f:
                    f.write("A\n1\n")

            batches = svc.check_inflight_batch()
            self.assertEqual(len(batches), 3)
            self.assertEqual(batches[0].batch_id, "9001")
            self.assertEqual(batches[1].batch_id, "9002")
            self.assertEqual(batches[2].batch_id, "9003")

    def test_stray_regular_files_in_loading_zone_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)
            svc = OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")
            svc.db = MagicMock()

            # Place stray file directly in loading root
            with open(os.path.join(svc.loading_zone, "stray.csv"), "w") as f:
                f.write("illegal")

            with self.assertRaises(OrchestratorExecutionError):
                svc.check_inflight_batch()

    def test_filesystem_dev_check_mismatch_raises_configuration_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = self._create_test_config(tmpdir)

            # Mock os.stat to return differing st_dev values
            orig_stat = os.stat
            def fake_stat(path, *args, **kwargs):
                st = orig_stat(path, *args, **kwargs)
                if "LOADING_ZONE" in path:
                    # Return distinct st_dev
                    mock_st = MagicMock(wraps=st)
                    mock_st.st_dev = 99999
                    return mock_st
                return st

            with patch("os.stat", side_effect=fake_stat):
                with self.assertRaises(ConfigurationError):
                    OrchestratorService(config_path=cfg_path, source_override="ORACLE_FUSION")


if __name__ == "__main__":
    unittest.main()
