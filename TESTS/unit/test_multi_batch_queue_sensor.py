#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for multi-batch queue scanning and FIFO ordering in sensor.py."""

import hashlib
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

from dataloader_core.capsule import BatchDescriptor
from dataloader_core.checksum import compute_file_checksum
from dataloader_core.logging_utils import detach_batch_file_logger
from dataloader_core.mapping import EntityMapper
from lib.sensor import scan_landing_queue, verify_descriptor_batch


class TestMultiBatchQueueSensor(unittest.TestCase):

    def tearDown(self):
        detach_batch_file_logger()

    def test_scan_empty_landing_zone_returns_idle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lz = os.path.join(tmpdir, "LANDING_ZONE")
            status, items = scan_landing_queue(lz)
            self.assertEqual(status, "IDLE")
            self.assertEqual(items, [])

    def test_scan_out_of_order_capsules_sorted_fifo(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lz = os.path.join(tmpdir, "LANDING_ZONE", "ORACLE_FUSION")
            os.makedirs(lz, exist_ok=True)

            # Create capsules in non-chronological order: 9003, 9001, 9002
            batches = [
                ("9003", "20261016_100300"),
                ("9001", "20261016_100100"),
                ("9002", "20261016_100200"),
            ]

            for b_id, ts in batches:
                cap_dir = os.path.join(lz, f"BATCH_{ts}_{b_id}")
                os.makedirs(cap_dir, exist_ok=True)
                csv_path = os.path.join(cap_dir, f"file-batch{b_id}.csv")
                with open(csv_path, "w", encoding="utf-8") as f:
                    f.write("COL1,COL2\nval1,val2\n")
                cs = compute_file_checksum(csv_path, "md5")
                mf_name = f"MANIFEST_ORACLE_FUSION_{ts}_{b_id}.MF"
                with open(os.path.join(cap_dir, mf_name), "w", encoding="utf-8") as f:
                    f.write(f"filename,checksum\nfile-batch{b_id}.csv,{cs}\n")

            status, items = scan_landing_queue(lz)
            self.assertEqual(status, "OK")
            self.assertEqual(len(items), 3)

            # Assert strict FIFO chronological ordering: 9001 -> 9002 -> 9003
            self.assertEqual(items[0].batch_id, "9001")
            self.assertTrue(items[0].is_capsule)
            self.assertEqual(items[1].batch_id, "9002")
            self.assertTrue(items[1].is_capsule)
            self.assertEqual(items[2].batch_id, "9003")
            self.assertTrue(items[2].is_capsule)

    def test_scan_stray_flat_files_returns_error_unexpected_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lz = os.path.join(tmpdir, "LANDING_ZONE", "ORACLE_FUSION")
            os.makedirs(lz, exist_ok=True)

            with open(os.path.join(lz, "stray_file.csv"), "w", encoding="utf-8") as f:
                f.write("COL1,COL2\nval1,val2\n")

            status, items = scan_landing_queue(lz)
            self.assertEqual(status, "ERROR_UNEXPECTED_FILES")
            self.assertEqual(items, [])

    def test_verify_descriptor_batch_orphan_rejected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cap_dir = os.path.join(tmpdir, "BATCH_20261016_100000_9001")
            os.makedirs(cap_dir, exist_ok=True)

            csv_name = "file_userpvo-batch9001-.csv"
            csv_path = os.path.join(cap_dir, csv_name)
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("USER_ID,NAME\n1,Alice\n")
            cs = compute_file_checksum(csv_path, "md5")

            mf_name = "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF"
            with open(os.path.join(cap_dir, mf_name), "w", encoding="utf-8") as f:
                f.write(f"filename,checksum\n{csv_name},{cs}\n")

            desc = BatchDescriptor.build(
                batch_id="9001",
                source="ORACLE_FUSION",
                extract_timestamp="20261016_100000",
                manifest_filename=mf_name,
                manifest_checksum=compute_file_checksum(os.path.join(cap_dir, mf_name), "md5"),
                files=[{
                    "filename": csv_name,
                    "target_table": "ERP_USER",
                    "file_size_bytes": os.path.getsize(csv_path),
                    "checksum": cs,
                    "columns": ["USER_ID", "NAME"],
                }],
            )
            desc.save(os.path.join(cap_dir, "batch_descriptor.json"))

            # Inject undeclared orphan file in capsule
            with open(os.path.join(cap_dir, "undeclared_intruder.csv"), "w", encoding="utf-8") as f:
                f.write("X,Y\n1,2\n")

            mapper = EntityMapper()
            with self.assertRaises(ValueError) as ctx:
                verify_descriptor_batch(cap_dir, mapper, allow_orphan_files=False)
            self.assertIn("Boundary violation (OPS-01)", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
