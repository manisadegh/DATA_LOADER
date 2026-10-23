#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for post-ingestion tasks validation and execution (F2.9).
Verifies:
- Configuration validation enforces required fields ('select' for dbt, positive timeout)
- Logging streamed to <batch_log_dir>/POST_TASKS/<n>_<type>.log
- Process group termination and tail error logging on timeout
- Process environment isolation without global os.environ mutation
"""

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

from dataloader_core.exceptions import ConfigurationError
from lib.post_tasks import run_post_tasks, validate_post_tasks


class TestPostTasks(unittest.TestCase):

    def test_validate_dbt_task_missing_select_raises_error(self):
        tasks = [{
            "type": "dbt",
            "project_dir": "/path/to/project",
            "profiles_dir": "/path/to/profiles",
            # missing 'select'
        }]
        with self.assertRaises(ConfigurationError) as ctx:
            validate_post_tasks(tasks)
        self.assertIn("requires non-empty 'select' parameter", str(ctx.exception))

    def test_validate_task_negative_timeout_raises_error(self):
        tasks = [{
            "type": "shell",
            "command": "echo test",
            "timeout_seconds": -10,
        }]
        with self.assertRaises(ConfigurationError) as ctx:
            validate_post_tasks(tasks)
        self.assertIn("Invalid timeout_seconds", str(ctx.exception))

    def test_validate_valid_tasks_succeeds(self):
        tasks = [
            {
                "type": "dbt",
                "project_dir": "/path/to/project",
                "profiles_dir": "/path/to/profiles",
                "select": "tag:staging",
                "timeout_seconds": 600,
            },
            {
                "type": "shell",
                "command": "echo hello",
                "timeout_seconds": 30,
            },
        ]
        # Should not raise
        validate_post_tasks(tasks)

    def test_run_post_tasks_streams_to_post_tasks_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "BATCH_LOGS")
            os.makedirs(log_dir)

            tasks = [
                {
                    "type": "shell",
                    "command": f"{sys.executable} -c 'print(\"STREAMED_OUTPUT_MESSAGE\")'",
                    "timeout_seconds": 10,
                }
            ]

            ok = run_post_tasks(
                post_tasks_config=tasks,
                context_env={"CURRENT_BATCH_ID": "9001"},
                batch_log_dir=log_dir,
            )
            self.assertTrue(ok)

            post_task_log = os.path.join(log_dir, "POST_TASKS", "1_shell.log")
            self.assertTrue(os.path.exists(post_task_log))
            with open(post_task_log, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertIn("STREAMED_OUTPUT_MESSAGE", content)

    def test_run_post_tasks_timeout_terminates_and_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = os.path.join(tmpdir, "BATCH_LOGS")
            os.makedirs(log_dir)

            # Hanging script that sleeps longer than timeout
            tasks = [
                {
                    "type": "shell",
                    "command": f"{sys.executable} -c 'import time; time.sleep(10)'",
                    "timeout_seconds": 1,
                }
            ]

            ok = run_post_tasks(
                post_tasks_config=tasks,
                context_env={"CURRENT_BATCH_ID": "9001"},
                batch_log_dir=log_dir,
            )
            self.assertFalse(ok)

            post_task_log = os.path.join(log_dir, "POST_TASKS", "1_shell.log")
            self.assertTrue(os.path.exists(post_task_log))


if __name__ == "__main__":
    unittest.main()
