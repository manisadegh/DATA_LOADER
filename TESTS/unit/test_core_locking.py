#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for dataloader_core.locking (ProcessLock, is_pid_alive, concurrent polling, stale PID)."""

import logging
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from dataloader_core.exceptions import LockTimeoutError
from dataloader_core.locking import ProcessLock, is_pid_alive, read_pid_file


class TestCoreLocking(unittest.TestCase):

    def test_is_pid_alive(self):
        self.assertTrue(is_pid_alive(os.getpid()))
        self.assertFalse(is_pid_alive(-1))
        self.assertFalse(is_pid_alive(0))
        self.assertFalse(is_pid_alive(999999))

    def test_read_pid_file_formats(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            p_legacy = os.path.join(tmpdir, "legacy.pid")
            with open(p_legacy, "w", encoding="utf-8") as f:
                f.write("12345\n")
            h, pid = read_pid_file(p_legacy)
            self.assertIsNone(h)
            self.assertEqual(pid, 12345)

            p_new = os.path.join(tmpdir, "new.pid")
            with open(p_new, "w", encoding="utf-8") as f:
                f.write("mycluster.node1:67890\n")
            h, pid = read_pid_file(p_new)
            self.assertEqual(h, "mycluster.node1")
            self.assertEqual(pid, 67890)

            p_inv = os.path.join(tmpdir, "invalid.pid")
            with open(p_inv, "w", encoding="utf-8") as f:
                f.write("gibberish\n")
            h, pid = read_pid_file(p_inv)
            self.assertIsNone(h)
            self.assertEqual(pid, 0)

    def test_process_lock_acquire_and_release(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, ".test.pid")
            with ProcessLock(lock_path, poll_interval_sec=0.1, timeout_sec=5):
                self.assertTrue(os.path.exists(lock_path))
                h, pid = read_pid_file(lock_path)
                self.assertEqual(pid, os.getpid())
                self.assertEqual(h, socket.gethostname())
            self.assertFalse(os.path.exists(lock_path))

    def test_process_lock_stale_dead_pid_recovery(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, ".stale.pid")
            with open(lock_path, "w", encoding="utf-8") as f:
                f.write("999999\n")

            with ProcessLock(lock_path, poll_interval_sec=0.1, timeout_sec=5):
                h, pid = read_pid_file(lock_path)
                self.assertEqual(pid, os.getpid())
            self.assertFalse(os.path.exists(lock_path))

            # Test new host:pid format with local host and dead PID
            with open(lock_path, "w", encoding="utf-8") as f:
                f.write(f"{socket.gethostname()}:999999\n")

            with ProcessLock(lock_path, poll_interval_sec=0.1, timeout_sec=5):
                h, pid = read_pid_file(lock_path)
                self.assertEqual(pid, os.getpid())
            self.assertFalse(os.path.exists(lock_path))

    def test_process_lock_foreign_host_does_not_kill(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, ".foreign.pid")
            with open(lock_path, "w", encoding="utf-8") as f:
                f.write("foreign_cluster_node_99:999999\n")

            # Must timeout rather than assuming dead PID because host is foreign
            with self.assertRaises(LockTimeoutError):
                with ProcessLock(lock_path, poll_interval_sec=0.1, timeout_sec=0.3):
                    pass

    def test_process_lock_concurrent_active_wait_and_timeout(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            lock_path = os.path.join(tmpdir, ".concurrent.pid")
            helper_code = (
                f"import sys, time; sys.path.insert(0, {COMMON_DIR!r}); "
                f"from dataloader_core.locking import ProcessLock; "
                f"lock = ProcessLock({lock_path!r}, poll_interval_sec=0.1, timeout_sec=10); "
                f"lock.acquire(); print('LOCKED', flush=True); time.sleep(1.2); lock.release()"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", helper_code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                line = proc.stdout.readline().strip()
                self.assertEqual(line, "LOCKED")

                # 1. Timeout test when timeout_sec < remaining sleep
                with self.assertRaises(LockTimeoutError):
                    with ProcessLock(lock_path, poll_interval_sec=0.1, timeout_sec=0.2):
                        pass

                # 2. Active waiting succeeds once subprocess releases lock
                logger = logging.getLogger("test_lock_logger")
                with ProcessLock(lock_path, poll_interval_sec=0.1, timeout_sec=5.0, logger=logger):
                    h, pid = read_pid_file(lock_path)
                    self.assertEqual(pid, os.getpid())
            finally:
                proc.wait(timeout=10)
                if proc.stdout:
                    proc.stdout.close()
                if proc.stderr:
                    proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
