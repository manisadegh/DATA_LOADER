#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for dataloader_core.manifest, checksum, and capsule (CapsulePathResolver)."""

import os
import sys
import tempfile
import unittest

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from dataloader_core.capsule import CapsulePathResolver
from dataloader_core.checksum import compute_file_checksum
from dataloader_core.manifest import (
    extract_batch_id_from_filenames,
    parse_manifest_filename,
    read_manifest_entries,
    write_standardized_manifest,
)


class TestCoreManifestAndCapsule(unittest.TestCase):

    def test_all_4_manifest_filename_patterns(self):
        # Pattern 1: Standard MANIFEST_<SOURCE>_<TS>_<BATCH_ID>.MF
        m1 = parse_manifest_filename("MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF")
        self.assertEqual(m1.source, "ORACLE_FUSION")
        self.assertEqual(m1.extract_timestamp_raw, "20261016_100000")
        self.assertEqual(m1.extract_timestamp_iso, "2026-10-16 10:00:00")
        self.assertEqual(m1.batch_id, "9001")
        self.assertTrue(m1.batch_id_from_manifest)

        # Pattern 2: *MANIFEST-YYYYMMDD_HHMMSS.MF
        m2 = parse_manifest_filename("DT2_MANIFEST-20261013_131116.MF", default_source="ORACLE_FUSION")
        self.assertEqual(m2.source, "ORACLE_FUSION")
        self.assertEqual(m2.extract_timestamp_raw, "20261013_131116")
        self.assertFalse(m2.batch_id_from_manifest)

        # Pattern 3: MANIFEST-batch<ID>-.MF (deleted in F2.6, must raise ValueError)
        with self.assertRaises(ValueError):
            parse_manifest_filename("MANIFEST-batch847376-.MF", default_source="CRM")

        # Pattern 4: MANIFEST_<TOKEN>.MF (deleted in F2.6, must raise ValueError)
        with self.assertRaises(ValueError):
            parse_manifest_filename("MANIFEST_9099.MF", default_source="ORACLE_FUSION")

        # Payload batch ID extraction
        bid = extract_batch_id_from_filenames(["DT2_file_invoiceheaderextractpvo-batch847376139-20261013_131116.zip"])
        self.assertEqual(bid, "847376139")

    def test_read_and_write_manifest_entries_and_checksum(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sample_file = os.path.join(tmpdir, "sample.csv")
            with open(sample_file, "w", encoding="utf-8") as f:
                f.write("ID,NAME\n1,Test\n")

            md5_val = compute_file_checksum(sample_file, "md5")
            sha_val = compute_file_checksum(sample_file, "sha256")
            self.assertEqual(len(md5_val), 32)
            self.assertEqual(len(sha_val), 64)

            # Test delimiter-agnostic parsing (; / \t / ,) and comment/property ignoring
            raw_mf = os.path.join(tmpdir, "raw.MF")
            with open(raw_mf, "w", encoding="utf-8") as f:
                f.write(
                    "# BICC Header Comment\n"
                    "PLV_KEY=ORA_123\n"
                    "filename;checksum\n"
                    f"sample.csv;{md5_val}\n"
                    "file2.csv\tdeadbeef\n"
                )
            entries = read_manifest_entries(raw_mf, require_non_empty=True)
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].filename, "sample.csv")
            self.assertEqual(entries[0].checksum, md5_val)
            self.assertEqual(entries[1].filename, "file2.csv")
            self.assertEqual(entries[1].checksum, "deadbeef")

            # Write standardized manifest
            std_mf = write_standardized_manifest(
                tmpdir, "ORACLE_FUSION", "20261016_100000", "9001", [("sample.csv", md5_val)]
            )
            self.assertTrue(os.path.exists(std_mf))
            std_entries = read_manifest_entries(std_mf, require_non_empty=True)
            self.assertEqual(len(std_entries), 1)
            self.assertEqual(std_entries[0]["filename"], "sample.csv")
            self.assertEqual(std_entries[0]["checksum"], md5_val)

    def test_capsule_path_resolver_substring_edge_case(self):
        # Parent directory contains 'crm' as substring, but terminal segment is 'LOGS'
        base_logs = "/tmp/my_crm_project/LOGS"
        capsule_dir = CapsulePathResolver.get_log_capsule_dir(
            base_logs, "CRM", "9005", "2026-10-16 10:04:00", ensure_exists=False
        )
        expected = os.path.normpath("/tmp/my_crm_project/LOGS/CRM/2026-10/BATCH_9005_20261016_100400")
        self.assertEqual(capsule_dir, expected)

        # Passing an already source-partitioned directory or already resolved capsule directory is idempotent
        capsule_dir_2 = CapsulePathResolver.get_log_capsule_dir(
            "/tmp/my_crm_project/LOGS/CRM", "CRM", "9005", "20261016_100400", ensure_exists=False
        )
        self.assertEqual(capsule_dir_2, expected)

        capsule_dir_3 = CapsulePathResolver.get_log_capsule_dir(
            expected, "CRM", "9005", "20261016_100400", ensure_exists=False
        )
        self.assertEqual(capsule_dir_3, expected)


if __name__ == "__main__":
    unittest.main()
