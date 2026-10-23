#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for dataloader_core.config (ConfigLoader, expand_env_vars, resolve_zone_path)."""

import json
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

from dataloader_core.config import ConfigLoader, expand_env_vars, load_json_config, resolve_zone_path
from dataloader_core.exceptions import ConfigurationError


class TestCoreConfig(unittest.TestCase):

    def test_expand_env_vars_recursive_and_custom_env(self):
        custom_env = {"TDENV": "DEV0", "SID_ADM_USER": "SIDFINADM", "CURRENT_BATCH_ID": "9001"}
        payload = {
            "target_db": "${TDENV}SIDFINSTG",
            "user": "${TDENV}${SID_ADM_USER}",
            "tasks": ["echo 'Batch $CURRENT_BATCH_ID'", 42],
        }
        expanded = expand_env_vars(payload, env=custom_env)
        self.assertEqual(expanded["target_db"], "DEV0SIDFINSTG")
        self.assertEqual(expanded["user"], "DEV0SIDFINADM")
        self.assertEqual(expanded["tasks"][0], "echo 'Batch 9001'")
        self.assertEqual(expanded["tasks"][1], 42)
        self.assertNotIn("CURRENT_BATCH_ID", os.environ)

    def test_resolve_zone_path_and_substring_safety(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Parent folder contains 'crm' as a substring, but terminal segment is 'DROP_ZONE'
            parent_base = os.path.join(tmpdir, "my_crm_workspace", "PROCESSING_TOOLS")
            os.makedirs(parent_base, exist_ok=True)

            resolved = resolve_zone_path(parent_base, "../DATA/DROP_ZONE", source="CRM", ensure_exists=True)
            self.assertTrue(os.path.isdir(resolved))
            self.assertEqual(os.path.basename(resolved), "CRM")

            # Calling resolve_zone_path again when already ending in 'CRM' must be idempotent
            resolved_again = resolve_zone_path(parent_base, resolved, source="CRM", ensure_exists=True)
            self.assertEqual(resolved, resolved_again)

    def test_load_json_config_valid_and_missing(self):
        with self.assertRaises(ConfigurationError):
            load_json_config("/non/existent/config_999999.json")

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tmp:
            json.dump({"db": "${TEST_CFG_PREFIX}STG"}, tmp)
            tmp_path = tmp.name

        try:
            cfg = ConfigLoader.load_json_config(tmp_path, env={"TEST_CFG_PREFIX": "DEV0"})
            self.assertEqual(cfg["db"], "DEV0STG")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)


if __name__ == "__main__":
    unittest.main()
