#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for dataloader_core.mapping (EntityMapper, inspect_file_inner_extension, 2-pass matching)."""

import os
import sys
import tempfile
import unittest
import zipfile

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
if COMMON_DIR not in sys.path:
    sys.path.insert(0, COMMON_DIR)

from dataloader_core.mapping import EntityMapper, inspect_file_inner_extension


class TestCoreMapping(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.mapping_csv = os.path.join(self.tmpdir.name, "entity_mapping.csv")
        with open(self.mapping_csv, "w", encoding="utf-8") as f:
            f.write(
                "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION\n"
                'ORACLE_FUSION,ERP_MSH_INVOICE_HEADER,invoiceheaderextractpvo,".csv,.zip,.gz,.csv.gz",.csv\n'
                'ORACLE_FUSION,ERP_MSH_INVOICE_HEADER_AK,invoiceheaderextractpvo,".pecsv,.zip,.gz,.pecsv.gz",.pecsv\n'
                'ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv,.zip,.gz,.csv.gz",.csv\n'
                'CRM,CRM_MSH_CUSTOMER,customerpvo,".csv,.zip,.gz,.csv.gz",.csv\n'
                '*,GLOBAL_SHARED_LOOKUP,sharedlookup,".csv,.zip",.csv\n'
            )
        self.mapper = EntityMapper(mapping_file=self.mapping_csv)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_csv_and_pecsv_and_gz_matching(self):
        r_csv = self.mapper.match_file(
            "file_invoiceheaderextractpvo-batch101-.csv",
            file_dir=self.tmpdir.name,
            source="ORACLE_FUSION",
        )
        self.assertIsNotNone(r_csv)
        self.assertEqual(r_csv.target_table, "ERP_MSH_INVOICE_HEADER")

        r_pecsv = self.mapper.match_file(
            "file_invoiceheaderextractpvo-batch101-.pecsv",
            file_dir=self.tmpdir.name,
            source="ORACLE_FUSION",
        )
        self.assertIsNotNone(r_pecsv)
        self.assertEqual(r_pecsv.target_table, "ERP_MSH_INVOICE_HEADER_AK")

        r_gz = self.mapper.match_file(
            "file_invoiceheaderextractpvo-batch101-.pecsv.gz",
            file_dir=self.tmpdir.name,
            source="ORACLE_FUSION",
        )
        self.assertIsNotNone(r_gz)
        self.assertEqual(r_gz.target_table, "ERP_MSH_INVOICE_HEADER_AK")

    def test_zip_inner_extension_inspection_and_2pass(self):
        zip_csv = os.path.join(self.tmpdir.name, "DT2_invoiceheaderextractpvo-batch101-.zip")
        with zipfile.ZipFile(zip_csv, "w") as z:
            z.writestr("invoiceheaderextractpvo.csv", "ID,NUM\n1,A\n")

        zip_pecsv = os.path.join(self.tmpdir.name, "DT2_invoiceheaderextractpvo_keys-batch101-.zip")
        with zipfile.ZipFile(zip_pecsv, "w") as z:
            z.writestr("invoiceheaderextractpvo.pecsv", "ID\n1\n")

        self.assertEqual(inspect_file_inner_extension(zip_csv), ".csv")
        self.assertEqual(inspect_file_inner_extension(zip_pecsv), ".pecsv")

        m_csv = self.mapper.match_file(os.path.basename(zip_csv), file_dir=self.tmpdir.name, source="ORACLE_FUSION")
        self.assertEqual(m_csv.target_table, "ERP_MSH_INVOICE_HEADER")

        m_pecsv = self.mapper.match_file(os.path.basename(zip_pecsv), file_dir=self.tmpdir.name, source="ORACLE_FUSION")
        self.assertEqual(m_pecsv.target_table, "ERP_MSH_INVOICE_HEADER_AK")

    def test_source_isolation_and_wildcard(self):
        # CRM file should not match when querying for ORACLE_FUSION
        self.assertIsNone(
            self.mapper.match_file("file_customerpvo-batch9005-.csv", file_dir=self.tmpdir.name, source="ORACLE_FUSION")
        )
        # CRM file matches for CRM
        m_crm = self.mapper.match_file("file_customerpvo-batch9005-.csv", file_dir=self.tmpdir.name, source="CRM")
        self.assertIsNotNone(m_crm)
        self.assertEqual(m_crm.target_table, "CRM_MSH_CUSTOMER")

        # Wildcard '*' matches any source
        m_glob = self.mapper.match_file("file_sharedlookup-batch1-.csv", file_dir=self.tmpdir.name, source="CRM")
        self.assertIsNotNone(m_glob)
        self.assertEqual(m_glob.target_table, "GLOBAL_SHARED_LOOKUP")


if __name__ == "__main__":
    unittest.main()
