#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for TPT job script generation (lib/generate_tpt_job.sh).
Validates schema width rules, strict row rejection, audit column literals,
and type validation (F1.1, F1.2).
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
LIB_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "TPT_LOADER", "lib")


def get_bash():
    if sys.platform != "win32":
        return "/bin/bash"
    for cand in [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"]:
        if os.path.exists(cand):
            return cand
    return shutil.which("bash") or "bash"


class TestTptJobGeneration(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.run_dir = os.path.join(self.tmpdir.name, "run_dir")
        os.makedirs(self.run_dir, exist_ok=True)
        self.bash = get_bash()

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run_generator(self, columns_content, has_meta="2", batch_id="9001", meta_ts="2026-10-16 10:00:00", extra_env=None):
        cols_file = os.path.join(self.run_dir, "columns.txt")
        with open(cols_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(columns_content)

        env = os.environ.copy()
        env["RUN_DIR"] = self.run_dir.replace("\\", "/")
        env["LIB_DIR"] = LIB_DIR.replace("\\", "/")
        env["FQ_TABLE"] = "DEV0SIDFINSTG.TEST_TABLE"
        env["HAS_META"] = str(has_meta)
        env["BATCH_ID"] = str(batch_id)
        env["META_TS"] = str(meta_ts)
        if extra_env:
            env.update(extra_env)

        gen_script = os.path.join(LIB_DIR, "generate_tpt_job.sh").replace("\\", "/")
        helpers_script = os.path.join(LIB_DIR, "env_and_helpers.sh").replace("\\", "/")

        bash_cmd = f"source '{helpers_script}' && source '{gen_script}'"
        proc = subprocess.run(
            [self.bash, "-c", bash_cmd],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return proc

    def test_schema_width_rules(self):
        # CV(UNICODE, len 20 -> chars 10 -> width 30), DA(10), TS(32), SZ(40), AT(20), I(21), D(18+3=21), F(40)
        cols_data = (
            "COL_CV|CV|20|2|0|0\n"
            "COL_DA|DA|4|0|0|0\n"
            "COL_TS|TS|10|0|0|0\n"
            "COL_SZ|SZ|10|0|0|0\n"
            "COL_AT|AT|6|0|0|0\n"
            "COL_I|I|4|0|0|0\n"
            "COL_D|D|8|0|18|4\n"
            "COL_F|F|8|0|0|0\n"
        )
        proc = self._run_generator(cols_data, has_meta="2")
        self.assertEqual(proc.returncode, 0, f"Generator failed: {proc.stderr}")

        job_tpt_path = os.path.join(self.run_dir, "job.tpt")
        self.assertTrue(os.path.exists(job_tpt_path))
        with open(job_tpt_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('"COL_CV" VARCHAR(30),', content)
        self.assertIn('"COL_DA" VARCHAR(10),', content)
        self.assertIn('"COL_TS" VARCHAR(32),', content)
        self.assertIn('"COL_SZ" VARCHAR(40),', content)
        self.assertIn('"COL_AT" VARCHAR(20),', content)
        self.assertIn('"COL_I" VARCHAR(21),', content)
        self.assertIn('"COL_D" VARCHAR(21),', content)
        self.assertIn('"COL_F" VARCHAR(40)', content)
        self.assertIn("AcceptMissingColumns = 'N'", content)

    def test_unsupported_type_fails(self):
        cols_data = "COL_BAD|BV|16|0|0|0\n"
        proc = self._run_generator(cols_data)
        self.assertNotEqual(proc.returncode, 0)
        out = f"{proc.stdout}\n{proc.stderr}"
        self.assertIn("Unsupported column type 'BV'", out)

    def test_insert_with_audit_columns(self):
        cols_data = "C1|CV|20|1|0|0\nC2|I|4|0|0|0\n"
        proc = self._run_generator(cols_data, has_meta="2", batch_id="9001", meta_ts="2026-10-16 10:00:00")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        with open(os.path.join(self.run_dir, "job.tpt"), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("INFA_BATCH_ID, INFA_LAST_REPLICATED", content)
        self.assertIn("''9001'', ''2026-10-16 10:00:00''", content)

    def test_insert_without_audit_columns(self):
        cols_data = "C1|CV|20|1|0|0\n"
        proc = self._run_generator(cols_data, has_meta="0")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        with open(os.path.join(self.run_dir, "job.tpt"), "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("INFA_BATCH_ID", content)
        self.assertNotIn("INFA_LAST_REPLICATED", content)

    def test_invalid_batch_id_rejected(self):
        cols_data = "C1|CV|20|1|0|0\n"
        proc = self._run_generator(cols_data, has_meta="2", batch_id="90'01;--")
        self.assertNotEqual(proc.returncode, 0)
        out = f"{proc.stdout}\n{proc.stderr}"
        self.assertIn("characters not allowed in INFA_BATCH_ID", out)


if __name__ == "__main__":
    unittest.main()
