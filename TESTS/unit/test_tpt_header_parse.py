#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for TPT header parsing utility (TPT_LOADER/lib/parse_header.py).
Validates quoted delimiters, special character sanitization, and unicode BOM (F1.5).
"""

import os
import sys
import tempfile
import unittest

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
TPT_LIB = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "TPT_LOADER", "lib")
if TPT_LIB not in sys.path:
    sys.path.insert(0, TPT_LIB)

from parse_header import extract_header_columns


class TestTptHeaderParse(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_quoted_delimiter_in_header(self):
        file_path = os.path.join(self.tmpdir.name, "sample.csv")
        with open(file_path, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write('"USER - ID","USER_NAME, EXTRA","EMAIL"\n1,"Smith, John",jsmith@example.com\n')

        cols = extract_header_columns(file_path, delimiter=",")
        self.assertEqual(len(cols), 3)
        self.assertEqual(cols, ["USER_ID", "USER_NAME_EXTRA", "EMAIL"])

    def test_semicolon_delimited_and_accents(self):
        file_path = os.path.join(self.tmpdir.name, "sample_semi.csv")
        with open(file_path, "w", encoding="utf-8-sig", newline="\n") as f:
            f.write('"CODE CLIENT";"NUMÉRO IDENTIFIANT";"MONTANT"\n101;202;300\n')

        cols = extract_header_columns(file_path, delimiter=";")
        self.assertEqual(len(cols), 3)
        self.assertEqual(cols[0], "CODE_CLIENT")
        self.assertEqual(cols[2], "MONTANT")


if __name__ == "__main__":
    unittest.main()
