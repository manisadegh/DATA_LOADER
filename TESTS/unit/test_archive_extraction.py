#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for archive extraction safety and validation in extract_archive_members (F2.4).
Verifies:
- Valid zip archive extraction
- Truncated / corrupted zip archive rejection and cleanup
- Valid gzip archive extraction
- Duplicate member across archives rejection
- Temporary extraction directory cleanup on failure
"""

import gzip
import os
import shutil
import sys
import tempfile
import unittest
import zipfile

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
ORCH_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
for p in (COMMON_DIR, ORCH_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from dataloader_core.exceptions import BatchValidationError
from lib.orchestrator_service import extract_archive_members


class TestArchiveExtraction(unittest.TestCase):

    def test_extract_valid_zip_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = os.path.join(tmpdir, "work")
            os.makedirs(work_dir)
            zip_path = os.path.join(tmpdir, "valid.zip")

            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("chunk_01.csv", "COL1,COL2\nval1,val2\n")
                zf.writestr("chunk_02.csv", "COL1,COL2\nval3,val4\n")

            extracted = extract_archive_members(zip_path, work_dir)
            self.assertEqual(len(extracted), 2)
            self.assertTrue(all(os.path.exists(p) for p in extracted))
            self.assertTrue(all(os.path.getsize(p) > 0 for p in extracted))

            # Temporary extraction directory should be cleaned up
            self.assertFalse(os.path.exists(os.path.join(work_dir, ".extract_tmp")))

    def test_extract_truncated_corrupt_zip_fails_and_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = os.path.join(tmpdir, "work")
            os.makedirs(work_dir)
            bad_zip = os.path.join(tmpdir, "corrupt.zip")

            with open(bad_zip, "wb") as f:
                f.write(b"PK\x03\x04truncated_corrupted_payload")

            with self.assertRaises(BatchValidationError):
                extract_archive_members(bad_zip, work_dir)

            # Assert .extract_tmp was cleaned up
            self.assertFalse(os.path.exists(os.path.join(work_dir, ".extract_tmp")))

    def test_extract_valid_gzip_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = os.path.join(tmpdir, "work")
            os.makedirs(work_dir)
            gz_path = os.path.join(tmpdir, "payload.csv.gz")

            with gzip.open(gz_path, "wb") as f:
                f.write(b"COL1,COL2\nval1,val2\n")

            extracted = extract_archive_members(gz_path, work_dir)
            self.assertEqual(len(extracted), 1)
            self.assertTrue(os.path.exists(extracted[0]))
            self.assertTrue(os.path.basename(extracted[0]).endswith(".csv"))

            with open(extracted[0], "rb") as f:
                content = f.read()
            self.assertEqual(content, b"COL1,COL2\nval1,val2\n")

    def test_extract_empty_gzip_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = os.path.join(tmpdir, "work")
            os.makedirs(work_dir)
            gz_path = os.path.join(tmpdir, "empty.csv.gz")

            with gzip.open(gz_path, "wb") as f:
                pass  # 0 bytes

            with self.assertRaises(BatchValidationError) as ctx:
                extract_archive_members(gz_path, work_dir)
            self.assertIn("Empty gzip payload", str(ctx.exception))

    def test_duplicate_member_name_collision_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            work_dir = os.path.join(tmpdir, "work")
            os.makedirs(work_dir)

            # Pre-existing member file in work_dir
            existing_file = os.path.join(work_dir, "chunk_01.csv")
            with open(existing_file, "w") as f:
                f.write("existing")

            zip_path = os.path.join(tmpdir, "second.zip")
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr("chunk_01.csv", "collision_data")

            with self.assertRaises(BatchValidationError) as ctx:
                extract_archive_members(zip_path, work_dir)
            self.assertIn("Duplicate member name", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
