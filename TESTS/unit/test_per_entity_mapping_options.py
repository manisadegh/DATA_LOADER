#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for extended EntityMapper attributes and per-entity header mode handling."""

import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
ORCH_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "DATA_INGESTION_ORCHESTRATOR")
for p in (COMMON_DIR, ORCH_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from dataloader_core.mapping import EntityMapper, EntityRule
from lib.orchestrator_service import process_entity_task


class TestPerEntityMappingOptions(unittest.TestCase):

    def test_legacy_5_column_backward_compatibility(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(
                "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION\n"
                'ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv,.zip",.csv\n'
            )
            mapping_path = f.name

        try:
            mapper = EntityMapper(mapping_path, default_source="ORACLE_FUSION")
            rules = mapper.load_rules()
            self.assertEqual(len(rules), 1)
            rule = rules[0]
            self.assertEqual(rule.delimiter, ",")
            self.assertEqual(rule.load_mode, "replace")
            self.assertEqual(rule.skip_rows, 1)
            self.assertEqual(rule.header_mode, "first_chunk_only")
        finally:
            if os.path.exists(mapping_path):
                os.remove(mapping_path)

    def test_extended_9_column_parsing(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write(
                "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION,DELIMITER,LOAD_MODE,SKIP_ROWS,HEADER_MODE\n"
                'ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv",.csv,",",replace,1,first_chunk_only\n'
                'CRM,CRM_EVENTS,events,".csv",.csv,;,append,2,every_file\n'
                'SAP,SAP_RAW_FEED,feed,".csv",.csv,"|",append,0,none\n'
            )
            mapping_path = f.name

        try:
            mapper = EntityMapper(mapping_path)
            rules = mapper.load_rules()
            self.assertEqual(len(rules), 3)

            crm_rule = mapper.match_file("file_events-batch1001-part1.csv", source="CRM")
            self.assertIsNotNone(crm_rule)
            self.assertEqual(crm_rule.delimiter, ";")
            self.assertEqual(crm_rule.load_mode, "append")
            self.assertEqual(crm_rule.skip_rows, 2)
            self.assertEqual(crm_rule.header_mode, "every_file")

            sap_rule = mapper.match_file("feed-batch2001-part1.csv", source="SAP")
            self.assertIsNotNone(sap_rule)
            self.assertEqual(sap_rule.delimiter, "|")
            self.assertEqual(sap_rule.load_mode, "append")
            self.assertEqual(sap_rule.skip_rows, 0)
            self.assertEqual(sap_rule.header_mode, "none")
        finally:
            if os.path.exists(mapping_path):
                os.remove(mapping_path)

    @patch("lib.orchestrator_service.run_tpt_loader")
    def test_process_entity_task_header_modes(self, mock_run_tpt):
        mock_run_tpt.return_value = (None, True)
        mock_db = MagicMock()
        mock_db.get_pending_tasks.return_value = []

        with tempfile.TemporaryDirectory() as tmpdir:
            loading_zone = tmpdir

            # 1. Test every_file header mode on multi-chunk (does NOT strip chunk 1)
            chunk1 = os.path.join(loading_zone, "events_chunk1.csv")
            chunk2 = os.path.join(loading_zone, "events_chunk2.csv")
            with open(chunk1, "w") as f:
                f.write("HDR1;HDR2\nA;1\n")
            with open(chunk2, "w") as f:
                f.write("HDR1;HDR2\nB;2\n")

            entity_info = {
                "files": ["events_chunk1.csv", "events_chunk2.csv"],
                "signature": "events",
                "delimiter": ";",
                "load_mode": "append",
                "skip_rows": 1,
                "header_mode": "every_file",
            }
            orch_config = {"loading_zone": loading_zone}
            tpt_config = {}

            res = process_entity_task(
                entity="CRM_EVENTS",
                entity_info=entity_info,
                batch_id="5001",
                source="CRM",
                extract_timestamp="20261021_100000",
                tpt_config=tpt_config,
                orch_config=orch_config,
                db=mock_db,
            )
            self.assertTrue(res)

            # Assert run_tpt_loader was called with skip_rows=1, skip_rows_every_file='Y', delimiter=';'
            mock_run_tpt.assert_called_once()
            call_kwargs = mock_run_tpt.call_args[1]
            self.assertEqual(call_kwargs["skip_rows"], 1)
            self.assertEqual(call_kwargs["skip_rows_every_file"], "Y")
            self.assertEqual(call_kwargs["load_mode"], "append")
            self.assertEqual(call_kwargs["delimiter"], ";")

            # Assert chunk1 header was NOT stripped in-place
            with open(chunk1, "r") as f:
                first_line = f.readline().strip()
            self.assertEqual(first_line, "HDR1;HDR2")


if __name__ == "__main__":
    unittest.main()
