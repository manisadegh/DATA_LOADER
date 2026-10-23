#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for declared row-size guard in schema_guard (F1.7).
Validates that table creation and column addition guard against exceeding max_row_bytes
without altering data contract column widths.
"""

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

from dataloader_core.exceptions import SchemaDriftError
from lib.schema_guard import alter_add_columns, create_staging_table, declared_row_bytes, sync_entity_schema_if_drifted


class TestSchemaGuardRowSize(unittest.TestCase):

    def test_declared_row_bytes_calculation(self):
        # 1 column of VARCHAR(4000) UNICODE = 4000 * 2 + 2 = 8002 bytes
        # Audit columns: TIMESTAMP(0)=10, VARCHAR(100) UNICODE = 100 * 2 + 2 = 202 -> 212 bytes
        # Total for 7 columns = 7 * 8002 + 212 = 56226 bytes
        size_7 = declared_row_bytes(["C" + str(i) for i in range(7)], "VARCHAR(4000)", "UNICODE", has_meta_cols=2)
        self.assertLess(size_7, 64000)

        # Total for 8 columns = 8 * 8002 + 212 = 64228 bytes
        size_8 = declared_row_bytes(["C" + str(i) for i in range(8)], "VARCHAR(4000)", "UNICODE", has_meta_cols=2)
        self.assertGreater(size_8, 64000)

    def test_within_limit_creation(self):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        cols = [f"COL_{i}" for i in range(7)]
        # Should succeed without error
        create_staging_table(mock_conn, "DEV0SIDFINSTG", "TEST_TABLE", cols, default_type="VARCHAR(4000)", character_set="UNICODE", max_row_bytes=64000)
        mock_cursor.execute.assert_called_once()

    def test_exceeds_limit_raises_drift_error(self):
        mock_conn = MagicMock()
        cols = [f"COL_{i}" for i in range(8)]
        with self.assertRaises(SchemaDriftError) as ctx:
            create_staging_table(mock_conn, "DEV0SIDFINSTG", "TEST_TABLE", cols, default_type="VARCHAR(4000)", character_set="UNICODE", max_row_bytes=64000)
        self.assertIn("exceeds max_row_bytes=64000", str(ctx.exception))

    def test_alter_add_exceeds_limit(self):
        mock_conn = MagicMock()
        existing_cols = [f"COL_{i}" for i in range(7)]
        new_cols = ["COL_7"]
        all_cols = existing_cols + new_cols

        with self.assertRaises(SchemaDriftError) as ctx:
            alter_add_columns(mock_conn, "DEV0SIDFINSTG", "TEST_TABLE", all_cols, new_cols, default_type="VARCHAR(4000)", character_set="UNICODE", max_row_bytes=64000)
        self.assertIn("exceeds max_row_bytes=64000", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
