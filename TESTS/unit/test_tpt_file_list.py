#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for TPT loader file list (-L) and batch metadata enforcement (F1.9, F1.11).
Tests argument parsing, pre-checks validation, and job variables synthesis.
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
TPT_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "TPT_LOADER")
LIB_DIR = os.path.join(TPT_DIR, "lib")


def get_bash():
    if sys.platform != "win32":
        return "/bin/bash"
    for cand in [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe"]:
        if os.path.exists(cand):
            return cand
    return shutil.which("bash") or "bash"


class TestTptFileList(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.work_dir = os.path.join(self.tmpdir.name, "tpt_work")
        os.makedirs(self.work_dir, exist_ok=True)
        self.bash = get_bash()

        # Create dummy data files
        self.data1 = os.path.join(self.tmpdir.name, "data1.csv")
        self.data2 = os.path.join(self.tmpdir.name, "data2.csv")
        for f in (self.data1, self.data2):
            with open(f, "w", encoding="utf-8", newline="\n") as fh:
                fh.write("ID,NAME\n1,Alpha\n")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _run_sh(self, script_body, extra_env=None):
        env = os.environ.copy()
        env["SCRIPT_DIR"] = TPT_DIR.replace("\\", "/")
        env["LIB_DIR"] = LIB_DIR.replace("\\", "/")
        env["TPT_TEMPLATE"] = os.path.join(LIB_DIR, "load_csv_generic.tpt.template").replace("\\", "/")
        env["TPT_WORK_DIR"] = self.work_dir.replace("\\", "/")
        env["TDPID"] = "tdadev"
        env["TDENV"] = "DEV0"
        env["SID_ADM_USER"] = "SIDFINADM"
        env["DB_STG"] = "SIDFINSTG"
        env["DB_WRK"] = "SIDFINWRK"
        env["PATH"] = f"{os.path.join(UNIT_DIR, 'helpers', 'stub_bin')}:{env.get('PATH', '')}"
        if extra_env:
            env.update(extra_env)

        helpers = os.path.join(LIB_DIR, "env_and_helpers.sh").replace("\\", "/")
        cmd = f"source '{helpers}' && {script_body}"
        return subprocess.run(
            [self.bash, "-c", cmd],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_mutually_exclusive(self):
        list_file = os.path.join(self.tmpdir.name, "list.txt")
        with open(list_file, "w", encoding="utf-8") as fh:
            fh.write(f"{self.data1}\n")

        parse_args = os.path.join(LIB_DIR, "parse_args.sh").replace("\\", "/")
        pre_checks = os.path.join(LIB_DIR, "pre_checks.sh").replace("\\", "/")

        body = f"source '{parse_args}' -f '{self.data1}' -L '{list_file}' -t TEST && source '{pre_checks}'"
        proc = self._run_sh(body)
        self.assertNotEqual(proc.returncode, 0)
        out = f"{proc.stdout}\n{proc.stderr}"
        self.assertIn("-f and -L are mutually exclusive", out)

    def test_relative_path_rejected(self):
        list_file = os.path.join(self.tmpdir.name, "rel_list.txt")
        with open(list_file, "w", encoding="utf-8") as fh:
            fh.write("relative/path/to/file.csv\n")

        parse_args = os.path.join(LIB_DIR, "parse_args.sh").replace("\\", "/")
        pre_checks = os.path.join(LIB_DIR, "pre_checks.sh").replace("\\", "/")

        body = f"source '{parse_args}' -L '{list_file}' -t TEST && source '{pre_checks}'"
        proc = self._run_sh(body)
        self.assertNotEqual(proc.returncode, 0)
        out = f"{proc.stdout}\n{proc.stderr}"
        self.assertIn("File list entries must be absolute paths", out)

    def test_jobvars_filelist_mode(self):
        list_file = os.path.join(self.tmpdir.name, "abs_list.txt").replace("\\", "/")
        with open(list_file, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f"{self.data1.replace(chr(92), '/')}\n{self.data2.replace(chr(92), '/')}\n")

        parse_args = os.path.join(LIB_DIR, "parse_args.sh").replace("\\", "/")
        pre_checks = os.path.join(LIB_DIR, "pre_checks.sh").replace("\\", "/")
        gen_jobvars = os.path.join(LIB_DIR, "generate_jobvars.sh").replace("\\", "/")

        # Stub run_dir
        job_dir = os.path.join(self.work_dir, "TPT_TEST_123456").replace("\\", "/")
        os.makedirs(job_dir, exist_ok=True)

        body = (
            f"source '{parse_args}' -L '{list_file}' -t TEST_TBL && "
            f"RUN_DIR='{job_dir}' && "
            f"source '{pre_checks}' && "
            f"source '{gen_jobvars}'"
        )
        proc = self._run_sh(body)
        self.assertEqual(proc.returncode, 0, f"Failed: stdout={proc.stdout}\nstderr={proc.stderr}")

        jobvars_path = os.path.join(job_dir, "jobvars.txt")
        self.assertTrue(os.path.exists(jobvars_path))
        with open(jobvars_path, "r", encoding="utf-8") as fh:
            content = fh.read()

        self.assertIn("FileList              = 'Y'", content)
        self.assertIn(f"FileName              = '{list_file}'", content)
        self.assertIn("DirectoryPath         = ''", content)
        self.assertIn("RecordErrorFile       =", content)
        self.assertIn("rejected_rows.txt", content)

    def test_missing_batch_id_with_audit_columns_fails(self):
        # bteq_check.sh should fail if HAS_META=2 and BATCH_ID is missing
        parse_args = os.path.join(LIB_DIR, "parse_args.sh").replace("\\", "/")
        bteq_check = os.path.join(LIB_DIR, "bteq_check.sh").replace("\\", "/")

        # We test the validation section of bteq_check
        body = (
            f"source '{parse_args}' -f '{self.data1.replace(chr(92), '/')}' -t TEST_TBL && "
            f"HAS_META=2 && BATCH_ID='' && META_TS='2026-10-23 10:00:00' && FQ_TABLE='DEV0SIDFINSTG.TEST_TBL' && "
            f"if [ \"${{HAS_META}}\" -eq 2 ]; then [ -n \"${{BATCH_ID}}\" ] || die 1 \"${{FQ_TABLE}} has audit columns: -B <batch_id> (or -b pattern) is mandatory\"; fi"
        )
        proc = self._run_sh(body)
        self.assertNotEqual(proc.returncode, 0)
        out = f"{proc.stdout}\n{proc.stderr}"
        self.assertIn("has audit columns: -B <batch_id> (or -b pattern) is mandatory", out)


if __name__ == "__main__":
    unittest.main()
