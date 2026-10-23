#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for BatchDescriptor and atomic capsule publishing in LANDING_ZONE."""

import json
import os
import sys
import tempfile
import unittest

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
ORCH_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
for p in (COMMON_DIR, ORCH_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from dataloader_core.capsule import BatchDescriptor, CapsulePathResolver
from lib.sensor import scan_landing_queue


class TestBatchDescriptorCapsule(unittest.TestCase):

    def test_descriptor_serialization_round_trip(self):
        desc = BatchDescriptor(
            batch_id="9001",
            source="ORACLE_FUSION",
            extract_timestamp="2026-10-16 10:00:00",
            extract_timestamp_raw="20261016_100000",
            created_at_utc="2026-10-16T10:00:05Z",
            manifest_filename="MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF",
            manifest_checksum="abc123md5",
            entities={
                "ERP_MSH_USER": {
                    "target_table": "ERP_MSH_USER",
                    "signature": "userpvo",
                    "files": ["file_userpvo-batch9001-.csv"],
                    "file_sizes": {"file_userpvo-batch9001-.csv": 128},
                    "checksums": {"file_userpvo-batch9001-.csv": "def456md5"},
                    "header_columns": ["USER_ID", "USER_NAME"],
                    "sample_file": "file_userpvo-batch9001-.csv",
                }
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "batch_descriptor.json")
            desc.to_json_file(json_path)
            self.assertTrue(os.path.exists(json_path))

            loaded = BatchDescriptor.from_json_file(json_path)
            self.assertEqual(loaded.batch_id, "9001")
            self.assertEqual(loaded.source, "ORACLE_FUSION")
            self.assertEqual(loaded.extract_timestamp, "2026-10-16 10:00:00")
            self.assertIn("ERP_MSH_USER", loaded.entities)
            self.assertEqual(loaded.entities["ERP_MSH_USER"]["header_columns"], ["USER_ID", "USER_NAME"])

    def test_atomic_capsule_staging_and_scan_ignore_staging(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            landing_zone = os.path.join(tmpdir, "LANDING_ZONE", "ORACLE_FUSION")
            os.makedirs(landing_zone, exist_ok=True)

            staging_dir = os.path.join(landing_zone, ".staging_BATCH_20261016_100000_9001")
            os.makedirs(staging_dir, exist_ok=True)
            with open(os.path.join(staging_dir, "file_userpvo-batch9001-.csv"), "w") as f:
                f.write("USER_ID,USER_NAME\nU1,Alice\n")

            # 1. Staging directory (hidden with .) must be ignored by scan_landing_queue
            status, items = scan_landing_queue(landing_zone)
            self.assertEqual(status, "IDLE")
            self.assertEqual(len(items), 0)

            # 2. Stage and publish atomically via CapsulePathResolver
            raw_mf = os.path.join(tmpdir, "MANIFEST-batch9001-.MF")
            with open(raw_mf, "w") as f:
                f.write("filename\nfile_userpvo-batch9001-.csv\n")

            desc = BatchDescriptor(
                batch_id="9001",
                source="ORACLE_FUSION",
                extract_timestamp="2026-10-16 10:00:00",
                extract_timestamp_raw="20261016_100000",
                created_at_utc="2026-10-16T10:00:05Z",
                manifest_filename="MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF",
                manifest_checksum="d41d8cd98f00b204e9800998ecf8427e",
                entities={"ERP_MSH_USER": {"files": ["file_userpvo-batch9001-.csv"]}},
            )

            manifest_content = "filename,checksum\nfile_userpvo-batch9001-.csv,d41d8cd98f00b204e9800998ecf8427e\n"
            receipt_data = {"batch_id": "9001", "source": "ORACLE_FUSION"}

            published_dir = CapsulePathResolver.stage_and_publish_queue_capsule(
                landing_zone=landing_zone,
                source="ORACLE_FUSION",
                batch_id="9001",
                clean_ts="20261016_100000",
                manifest_content=manifest_content,
                batch_descriptor=desc,
                raw_manifest_path=raw_mf,
                receipt_dict=receipt_data,
                payload_files=[(os.path.join(staging_dir, "file_userpvo-batch9001-.csv"), "file_userpvo-batch9001-.csv")],
            )

            self.assertTrue(os.path.isdir(published_dir))
            self.assertFalse(os.path.exists(staging_dir))

            # 3. Now scan_landing_queue should discover exactly 1 published capsule
            status, items = scan_landing_queue(landing_zone)
            self.assertEqual(status, "OK")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].batch_id, "9001")
            self.assertTrue(items[0].is_capsule)


if __name__ == "__main__":
    unittest.main()
