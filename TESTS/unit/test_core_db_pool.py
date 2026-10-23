#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for dataloader_core.db (TeradataConnectionManager, credential precedence, thread-safe pool)."""

import os
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
ORCH_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
for p in (COMMON_DIR, ORCH_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from dataloader_core.db import (
    TeradataConnectionManager,
    build_tpt_environment,
    resolve_teradata_credentials,
    validate_sql_identifier,
)
from lib.db_state import TeradataStateDB


class TestCoreDBPool(unittest.TestCase):

    def test_validate_sql_identifier(self):
        self.assertEqual(validate_sql_identifier("DEV0SIDFINSTG"), "DEV0SIDFINSTG")
        self.assertEqual(validate_sql_identifier("ERP_MSH_USER_1"), "ERP_MSH_USER_1")
        for invalid in ("", "DROP TABLE x;", "DB-NAME", "TABLE NAME", "a'b"):
            with self.assertRaises(ValueError):
                validate_sql_identifier(invalid)

    def test_credential_resolution_precedence(self):
        with tempfile.TemporaryDirectory() as tmp_dbt:
            key_p = os.path.join(tmp_dbt, "DEV0SIDFINADM_Key.properties")
            pass_p = os.path.join(tmp_dbt, "DEV0SIDFINADM_Pass.properties")
            with open(key_p, "w", encoding="utf-8") as f:
                f.write("k")
            with open(pass_p, "w", encoding="utf-8") as f:
                f.write("p")

            with patch.dict(os.environ, {"DBT_PROFILE_DIR": tmp_dbt, "TD_PASSWORD": "env_secret"}, clear=False):
                # 1. Explicit key_file & pass_file win over password, dbt files, and TD_PASSWORD
                c1 = resolve_teradata_credentials({
                    "host": "tdadev",
                    "user": "DEV0SIDFINADM",
                    "key_file": "/custom/k.prop",
                    "pass_file": "/custom/p.prop",
                    "password": "plain_password",
                })
                self.assertEqual(c1["password"], "ENCRYPTED_PASSWORD(file:/custom/k.prop,file:/custom/p.prop)")

                # 2. Explicit password wins over dbt files and TD_PASSWORD
                c2 = resolve_teradata_credentials({
                    "host": "tdadev",
                    "user": "DEV0SIDFINADM",
                    "password": "plain_password",
                })
                self.assertEqual(c2["password"], "plain_password")

                # 3. Auto-discovered ~/.dbt/{user}_Key.properties wins over TD_PASSWORD
                c3 = resolve_teradata_credentials({
                    "host": "tdadev",
                    "user": "DEV0SIDFINADM",
                })
                self.assertEqual(c3["password"], f"ENCRYPTED_PASSWORD(file:{key_p},file:{pass_p})")

            # 4. TD_PASSWORD fallback when no dbt files exist
            with tempfile.TemporaryDirectory() as empty_dbt:
                with patch.dict(os.environ, {"DBT_PROFILE_DIR": empty_dbt, "TD_PASSWORD": "env_secret"}, clear=False):
                    c4 = resolve_teradata_credentials({"host": "tdadev", "user": "DEV0SIDFINADM"})
                    self.assertEqual(c4["password"], "env_secret")

    def test_build_tpt_environment(self):
        base = {"TDENV": "DEV0", "SID_ADM_USER": "SIDFINADM", "TD_PASSWORD": "old"}
        env = build_tpt_environment(
            {"host": "tdadev", "password": "ENCRYPTED_PASSWORD(file:a,file:b)"},
            base_env=base,
        )
        self.assertEqual(env["TDPID"], "tdadev")
        self.assertEqual(env["TD_LOGON_USER"], "DEV0SIDFINADM")
        self.assertNotIn("TD_PASSWORD", env)

    def test_multithreaded_connection_pool_reuse(self):
        mock_td_module = MagicMock()

        def make_conn(**kwargs):
            conn = MagicMock()
            cur = MagicMock()
            cur.fetchone.return_value = (1,)
            cur.fetchall.return_value = []
            cur.__enter__.return_value = cur
            conn.cursor.return_value = cur
            return conn

        mock_td_module.connect.side_effect = make_conn

        with patch.dict(sys.modules, {"teradatasql": mock_td_module}):
            mgr = TeradataConnectionManager(
                {"host": "tdadev", "user": "DEV0SIDFINADM", "password": "pw"},
                max_connections=4,
            )
            db = TeradataStateDB(
                {"host": "tdadev", "user": "DEV0SIDFINADM", "password": "pw", "technical_database": "DEV0SIDFINTCH"},
                conn_mgr=mgr,
            )

            def worker_task(idx: int):
                for _ in range(5):
                    db.update_task_start("9001", f"ENT_{idx}", source="ORACLE_FUSION")
                    time.sleep(0.005)
                    db.update_task_end("9001", f"ENT_{idx}", "SUCCESS", source="ORACLE_FUSION")
                return True

            # 8 concurrent threads x 10 DB calls each = 80 total SQL calls
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(worker_task, range(8)))

            self.assertTrue(all(results))
            self.assertLessEqual(mgr.total_connections_created, 4)
            self.assertGreaterEqual(mgr.total_connections_created, 1)

            db.close()

    def test_build_tpt_environment_does_not_touch_USER(self):
        from dataloader_core.db import build_tpt_environment

        fake_env = {"USER": "orig_user", "TDPID": "orig_host"}
        tpt_env = build_tpt_environment({"user": "DEV0X"}, base_env=fake_env)
        self.assertEqual(tpt_env.get("USER"), "orig_user")
        self.assertEqual(tpt_env.get("TD_LOGON_USER"), "DEV0X")


if __name__ == "__main__":
    unittest.main()
