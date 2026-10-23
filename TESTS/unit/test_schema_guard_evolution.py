#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for non-destructive schema evolution via ALTER TABLE ADD in schema_guard (F1.6).
Validates that:
- Pure column appends with auto_migrate_ddl=True execute ALTER TABLE ADD.
- Missing columns, reordered columns, or column drops raise SchemaDriftError.
- Missing tables with auto_migrate_ddl=False raise SchemaDriftError.
- No DROP TABLE statements are ever issued.
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
from lib.schema_guard import sync_entity_schema_if_drifted


class TestSchemaGuardEvolution(unittest.TestCase):

    def setUp(self):
        self.mock_conn = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_conn.cursor.return_value = self.mock_cursor
        self.executed_sql = []

        def record_execute(sql, *args, **kwargs):
            self.executed_sql.append(sql)

        self.mock_cursor.execute.side_effect = record_execute

    @patch("lib.schema_guard.get_teradata_table_columns")
    def test_pure_append_executes_alter_table_add(self, mock_get_cols):
        # Existing table has A, B and 2 audit columns
        mock_get_cols.return_value = (["A", "B"], 2)
        
        identical, action, cols, has_meta = sync_entity_schema_if_drifted(
            connection=self.mock_conn,
            target_db="DEV0SIDFINSTG",
            target_table="TEST_TABLE",
            csv_cols=["A", "B", "C"],
            auto_migrate_ddl=True,
            default_type="VARCHAR(100)",
            character_set="UNICODE",
        )

        self.assertFalse(identical)
        self.assertEqual(action, "ALTERED")
        self.assertEqual(has_meta, 2)
        self.assertEqual(len(self.executed_sql), 1)
        self.assertIn("ALTER TABLE DEV0SIDFINSTG.TEST_TABLE ADD C VARCHAR(100) CHARACTER SET UNICODE NOT CASESPECIFIC", self.executed_sql[0])

    @patch("lib.schema_guard.get_teradata_table_columns")
    def test_missing_column_raises_drift_error(self, mock_get_cols):
        # Table has A, B; File has A, C (B missing)
        mock_get_cols.return_value = (["A", "B"], 2)

        with self.assertRaises(SchemaDriftError) as ctx:
            sync_entity_schema_if_drifted(
                connection=self.mock_conn,
                target_db="DEV0SIDFINSTG",
                target_table="TEST_TABLE",
                csv_cols=["A", "C"],
                auto_migrate_ddl=True,
            )
        self.assertIn("only appended new columns can be migrated automatically", str(ctx.exception))
        self.assertEqual(len(self.executed_sql), 0)

    @patch("lib.schema_guard.get_teradata_table_columns")
    def test_reordered_columns_raises_drift_error(self, mock_get_cols):
        # Table has A, B; File has B, A
        mock_get_cols.return_value = (["A", "B"], 2)

        with self.assertRaises(SchemaDriftError) as ctx:
            sync_entity_schema_if_drifted(
                connection=self.mock_conn,
                target_db="DEV0SIDFINSTG",
                target_table="TEST_TABLE",
                csv_cols=["B", "A"],
                auto_migrate_ddl=True,
            )
        self.assertIn("only appended new columns can be migrated automatically", str(ctx.exception))
        self.assertEqual(len(self.executed_sql), 0)

    @patch("lib.schema_guard.get_teradata_table_columns")
    def test_fewer_columns_raises_drift_error(self, mock_get_cols):
        # Table has A, B, C; File has A, B
        mock_get_cols.return_value = (["A", "B", "C"], 2)

        with self.assertRaises(SchemaDriftError) as ctx:
            sync_entity_schema_if_drifted(
                connection=self.mock_conn,
                target_db="DEV0SIDFINSTG",
                target_table="TEST_TABLE",
                csv_cols=["A", "B"],
                auto_migrate_ddl=True,
            )
        self.assertIn("only appended new columns can be migrated automatically", str(ctx.exception))
        self.assertEqual(len(self.executed_sql), 0)

    @patch("lib.schema_guard.get_teradata_table_columns")
    def test_missing_table_with_auto_migrate_false_raises_drift_error(self, mock_get_cols):
        # Table does not exist
        mock_get_cols.return_value = (None, 0)

        with self.assertRaises(SchemaDriftError) as ctx:
            sync_entity_schema_if_drifted(
                connection=self.mock_conn,
                target_db="DEV0SIDFINSTG",
                target_table="TEST_TABLE",
                csv_cols=["A", "B"],
                auto_migrate_ddl=False,
            )
        self.assertIn("does not exist and auto_migrate_ddl is disabled", str(ctx.exception))
        self.assertEqual(len(self.executed_sql), 0)


if __name__ == "__main__":
    unittest.main()
