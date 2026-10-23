#!/bin/bash
# -*- coding: utf-8 -*-
"""Unit tests for BICC_INTAKE_CONTROLLER/lib/intake_service.py (IntakeControllerService) and feeder.py."""

import json
import logging
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
FEEDER_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "BICC_INTAKE_CONTROLLER")
for p in (COMMON_DIR, FEEDER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from dataloader_core.capsule import BatchDescriptor
from dataloader_core.mapping import EntityMapper
from lib.intake_service import IntakeControllerService


class TestIntakeService(unittest.TestCase):

    def tearDown(self):
        feeder_logger = logging.getLogger("BICC_INTAKE_CONTROLLER")
        for h in list(feeder_logger.handlers):
            try:
                h.close()
            except Exception:
                pass
            feeder_logger.removeHandler(h)

    def test_feeder_entrypoint_line_count_under_80(self):
        feeder_py = os.path.join(FEEDER_DIR, "feeder.py")
        with open(feeder_py, "r", encoding="utf-8") as f:
            lines = f.readlines()
        self.assertLess(len(lines), 80, f"feeder.py has {len(lines)} lines (expected < 80)")

    def test_intake_service_empty_and_single_batch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            drop_dir = os.path.join(tmpdir, "DROP_ZONE")
            landing_dir = os.path.join(tmpdir, "LANDING_ZONE")
            logs_dir = os.path.join(tmpdir, "LOGS")
            orch_dir = os.path.join(tmpdir, "ORCH")
            os.makedirs(orch_dir, exist_ok=True)

            mapping_file = os.path.join(tmpdir, "entity_mapping.csv")
            with open(mapping_file, "w", encoding="utf-8") as f:
                f.write(
                    "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION\n"
                    'ORACLE_FUSION,ERP_MSH_USER,userpvo,".csv,.zip",.csv\n'
                )

            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({
                    "feeder": {
                        "drop_zone": drop_dir,
                        "logs_dir": logs_dir,
                        "file_stability_window_seconds": 0,
                        "source_system_code": "ORACLE_FUSION",
                        "entity_mapping_file": mapping_file,
                    },
                    "orchestrator": {
                        "orchestrator_dir": orch_dir,
                        "config_file": "config.json",
                        "landing_zone": landing_dir,
                        "trigger_orchestrator": True,
                    },
                }, f)

            svc = IntakeControllerService(config_path=cfg_file, source_override="ORACLE_FUSION")

            # 1. Empty drop zone -> discover_and_sort_batches returns []
            self.assertEqual(svc.discover_and_sort_batches(), [])

            # 2. Populate a batch in DROP_ZONE/ORACLE_FUSION
            csv_file = os.path.join(svc.drop_zone, "file_userpvo-batch9001-.csv")
            with open(csv_file, "w", encoding="utf-8") as f:
                f.write("USER_ID,USER_NAME\nU1,Alice\n")
            mf_file = os.path.join(svc.drop_zone, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF")
            with open(mf_file, "w", encoding="utf-8") as f:
                f.write("filename\nfile_userpvo-batch9001-.csv\n")

            batches = svc.discover_and_sort_batches()
            self.assertEqual(len(batches), 1)
            self.assertEqual(batches[0]["batch_id"], "9001")

            mapper = EntityMapper(mapping_file=mapping_file, default_source="ORACLE_FUSION")

            capsule_path = svc.process_single_batch(batches[0], mapper)
            self.assertTrue(os.path.isdir(capsule_path))

            # Verify capsule layout in LANDING_ZONE/ORACLE_FUSION/BATCH_20261016_100000_9001
            expected_capsule = os.path.join(landing_dir, "ORACLE_FUSION", "BATCH_20261016_100000_9001")
            self.assertEqual(os.path.normpath(capsule_path), os.path.normpath(expected_capsule))
            self.assertTrue(os.path.exists(os.path.join(expected_capsule, "file_userpvo-batch9001-.csv")))
            self.assertTrue(
                os.path.exists(os.path.join(expected_capsule, "MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF"))
            )
            self.assertTrue(os.path.exists(os.path.join(expected_capsule, "batch_descriptor.json")))

            desc = BatchDescriptor.from_json_file(os.path.join(expected_capsule, "batch_descriptor.json"))
            self.assertEqual(desc.batch_id, "9001")
            self.assertIn("ERP_MSH_USER", desc.entities)
            self.assertEqual(desc.entities["ERP_MSH_USER"]["header_columns"], ["USER_ID", "USER_NAME"])

            # Verify RAW vault inside capsule
            raw_dir = os.path.join(expected_capsule, "RAW")
            self.assertTrue(os.path.isdir(raw_dir))
            receipts = [f for f in os.listdir(raw_dir) if f.startswith("RECEIPT_") and f.endswith(".json")]
            self.assertEqual(len(receipts), 1)

            # Test run() triggers orchestrator once
            with patch("lib.intake_service.invoke_orchestrator", return_value=0) as mock_orch:
                rc = svc.run()
                self.assertEqual(rc, 0)
                mock_orch.assert_called_once()
            logging.shutdown()


if __name__ == "__main__":
    unittest.main()
