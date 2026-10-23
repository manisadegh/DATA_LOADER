#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for F1.3: Dynamic measurement of has_meta from DBC.ColumnsV in Schema Guard."""

import os
import sys
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

from dataloader_core.exceptions import SchemaSyncError
from lib.schema_guard import get_teradata_table_columns, sync_entity_schema_if_drifted


class TestSchemaGuardHasMeta(unittest.TestCase):

    def test_has_meta_two(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("COL_A",),
            ("COL_B",),
            ("INFA_BATCH_ID",),
            ("INFA_LAST_REPLICATED",),
        ]

        cols, has_meta = get_teradata_table_columns(mock_conn, "TEST_DB", "TEST_TABLE")
        self.assertEqual(cols, ["COL_A", "COL_B"])
        self.assertEqual(has_meta, 2)

    def test_has_meta_zero(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("COL_A",),
            ("COL_B",),
        ]

        cols, has_meta = get_teradata_table_columns(mock_conn, "TEST_DB", "TEST_TABLE")
        self.assertEqual(cols, ["COL_A", "COL_B"])
        self.assertEqual(has_meta, 0)

    def test_has_meta_one_raises(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchall.return_value = [
            ("COL_A",),
            ("COL_B",),
            ("INFA_BATCH_ID",),
        ]

        cols, has_meta = get_teradata_table_columns(mock_conn, "TEST_DB", "TEST_TABLE")
        self.assertEqual(cols, ["COL_A", "COL_B"])
        self.assertEqual(has_meta, 1)

        with self.assertRaises(SchemaSyncError) as cm:
            sync_entity_schema_if_drifted(
                conn=mock_conn,
                td_db="TEST_DB",
                td_table="TEST_TABLE",
                csv_cols=["COL_A", "COL_B"],
            )
        self.assertIn("exactly one audit column", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
