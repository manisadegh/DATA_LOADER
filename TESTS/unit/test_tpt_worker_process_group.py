#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for process-group termination and precise lock detection regex in tpt_worker (F1.10).
"""

import os
import sys
import tempfile
import time
import unittest

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
ORCH_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
for p in (COMMON_DIR, ORCH_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from lib.tpt_worker import _is_table_locked, _run


class TestTptWorkerProcessGroup(unittest.TestCase):

    def test_lock_regex_positive_negative(self):
        # Negative cases (should NOT trigger lock detection)
        self.assertFalse(_is_table_locked("Total rows processed: 2652"))
        self.assertFalse(_is_table_locked("Order ID 2652 created successfully"))
        self.assertFalse(_is_table_locked("Timestamp: 2026-10-23 12:26:52"))

        # Positive cases (MUST trigger lock detection)
        self.assertTrue(_is_table_locked("RDBMS error 2652: The specified table is being Loaded."))
        self.assertTrue(_is_table_locked("TPT02652: Error 2652 encountered during acquisition"))
        self.assertTrue(_is_table_locked("Table DEV0SIDFINSTG.ERP_MSH_USER is being Loaded"))
        self.assertTrue(_is_table_locked("Table DEV0SIDFINSTG.ERP_MSH_USER is being MLoaded"))

    @unittest.skipIf(sys.platform == "win32", "Process-group SIGKILL termination test requires POSIX runtime")
    def test_timeout_kills_group(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_file = os.path.join(tmpdir, "timeout.out")
            start = time.time()
            res = _run(
                ["/bin/bash", "-c", "sleep 60 & wait"],
                env=os.environ.copy(),
                timeout=1,
                output_path=out_file,
                grace_seconds=1,
            )
            elapsed = time.time() - start
            self.assertLess(elapsed, 10, f"Process group termination took too long ({elapsed}s)")
            self.assertNotEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
