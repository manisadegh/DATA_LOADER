#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for multi-batch queue scanning and FIFO ordering in sensor.py."""

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

from dataloader_core.logging_utils import detach_batch_file_logger
from lib.sensor import scan_landing_queue


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
                mf_name = f"MANIFEST_ORACLE_FUSION_{ts}_{b_id}.MF"
                with open(os.path.join(cap_dir, mf_name), "w") as f:
                    f.write(f"filename,checksum\nfile-batch{b_id}.csv,dummy\n")
                with open(os.path.join(cap_dir, f"file-batch{b_id}.csv"), "w") as f:
                    f.write("COL1,COL2\nval1,val2\n")

            status, items = scan_landing_queue(lz)
            self.assertEqual(status, "OK")
            self.assertEqual(len(items), 3)

            # Assert strict FIFO chronological ordering: 9001 -> 9002 -> 9003
            self.assertEqual(items[0].batch_id, "9001")
            self.assertEqual(items[1].batch_id, "9002")
            self.assertEqual(items[2].batch_id, "9003")

    def test_scan_legacy_flat_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lz = os.path.join(tmpdir, "LANDING_ZONE", "ORACLE_FUSION")
            os.makedirs(lz, exist_ok=True)

            mf_name = "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF"
            with open(os.path.join(lz, mf_name), "w") as f:
                f.write("filename,checksum\nfile-batch9001.csv,dummy\n")
            with open(os.path.join(lz, "file-batch9001.csv"), "w") as f:
                f.write("COL1,COL2\nval1,val2\n")

            status, items = scan_landing_queue(lz)
            self.assertEqual(status, "OK")
            self.assertEqual(len(items), 1)
            self.assertEqual(items[0].batch_id, "9001")
            self.assertFalse(items[0].is_capsule)

    def test_scan_unmanifested_orphan_data_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lz = os.path.join(tmpdir, "LANDING_ZONE", "ORACLE_FUSION")
            os.makedirs(lz, exist_ok=True)

            with open(os.path.join(lz, "orphan_file.csv"), "w") as f:
                f.write("COL1,COL2\nval1,val2\n")

            status, items = scan_landing_queue(lz)
            self.assertEqual(status, "ERROR_MISSING_MANIFEST")
            self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
