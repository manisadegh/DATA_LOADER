#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for UtilitySlotGovernor in dataloader_core.locking."""

import os
import sys
import tempfile
import threading
import time
import unittest

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from dataloader_core.exceptions import LockTimeoutError
from dataloader_core.locking import UtilitySlotGovernor


class TestUtilitySlotGovernor(unittest.TestCase):

    def test_concurrent_slot_bounding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            slot_dir = os.path.join(tmpdir, ".utility_slots")
            governor = UtilitySlotGovernor(slot_dir=slot_dir, max_slots=2)

            max_observed_concurrent = 0
            current_active = 0
            active_lock = threading.Lock()
            errors = []

            def worker_task(worker_id: int):
                nonlocal max_observed_concurrent, current_active
                try:
                    with governor.acquire_slot(entity=f"ENTITY_{worker_id}", source="TEST_SRC", poll_interval_sec=0.05, timeout_sec=5.0):
                        with active_lock:
                            current_active += 1
                            if current_active > max_observed_concurrent:
                                max_observed_concurrent = current_active
                        time.sleep(0.1)
                        with active_lock:
                            current_active -= 1
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker_task, args=(i,)) for i in range(6)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(errors), 0, f"Encountered unexpected errors in worker threads: {errors}")
            self.assertLessEqual(max_observed_concurrent, 2, f"Observed {max_observed_concurrent} concurrent slots (max allowed: 2)")

    def test_slot_timeout_when_exhausted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            slot_dir = os.path.join(tmpdir, ".utility_slots")
            governor = UtilitySlotGovernor(slot_dir=slot_dir, max_slots=1)

            # Hold slot 1 in a context
            with governor.acquire_slot(entity="BLOCKING_JOB", source="TEST", poll_interval_sec=0.05, timeout_sec=1.0):
                # Second request with short timeout should raise LockTimeoutError
                with self.assertRaises(LockTimeoutError):
                    with governor.acquire_slot(entity="BLOCKED_JOB", source="TEST", poll_interval_sec=0.05, timeout_sec=0.2):
                        pass


if __name__ == "__main__":
    unittest.main()
