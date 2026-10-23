#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for dataloader_core.intake (Plugin Framework & BaseIntakeController)."""

import json
import os
import sys
import tempfile
import unittest
from typing import List

UNIT_DIR = os.path.dirname(os.path.abspath(__file__))
TESTS_DIR = os.path.dirname(UNIT_DIR)
BASE_DIR = os.path.dirname(TESTS_DIR)
COMMON_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "COMMON")
FEEDER_DIR = os.path.join(BASE_DIR, "PROCESSING_TOOLS", "BICC_INTAKE_CONTROLLER")
for p in (COMMON_DIR, FEEDER_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from dataloader_core.intake import (
    BaseIntakeController,
    BICCIntakePlugin,
    ManifestlessDropIntakePlugin,
    PluginRegistry,
    RawBatchCandidate,
    SourceIntakePlugin,
    StandardManifestIntakePlugin,
)


class CustomSourcePlugin(SourceIntakePlugin):
    """Mock custom plugin implemented in <25 lines demonstrating extensibility."""

    source_code = "SAP_ERP"

    def discover_raw_batches(self, drop_zone: str) -> List[RawBatchCandidate]:
        candidates = []
        for f in os.listdir(drop_zone):
            if f.endswith(".ctl") and not f.startswith("."):
                f_path = os.path.join(drop_zone, f)
                with open(f_path, "r") as ctl_f:
                    lines = [ln.strip() for ln in ctl_f if ln.strip()]
                candidates.append(
                    RawBatchCandidate(
                        batch_id="7001",
                        source="SAP_ERP",
                        extract_timestamp_raw="20261021_120000",
                        sort_key=(1000.0, "7001"),
                        manifest_path=f_path,
                        declared_files=lines,
                    )
                )
        return candidates


class TestIntakePluginFramework(unittest.TestCase):

    def test_plugin_registry_resolution(self):
        PluginRegistry.register("CUSTOM_SAP", CustomSourcePlugin)
        plugin = PluginRegistry.get_plugin("CUSTOM_SAP", default_source="SAP_ERP")
        self.assertIsInstance(plugin, CustomSourcePlugin)
        self.assertEqual(plugin.source_code, "SAP_ERP")

        bicc_plugin = PluginRegistry.get_plugin("bicc", default_source="ORACLE_FUSION")
        self.assertIsInstance(bicc_plugin, BICCIntakePlugin)

        crm_plugin = PluginRegistry.get_plugin("standard_manifest", default_source="CRM")
        self.assertIsInstance(crm_plugin, StandardManifestIntakePlugin)

        drop_plugin = PluginRegistry.get_plugin("manifestless", default_source="DROPS")
        self.assertIsInstance(drop_plugin, ManifestlessDropIntakePlugin)

    def test_custom_plugin_intake_lifecycle_to_capsule(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            drop_dir = os.path.join(tmpdir, "DROP_ZONE", "SAP_ERP")
            landing_dir = os.path.join(tmpdir, "LANDING_ZONE")
            logs_dir = os.path.join(tmpdir, "LOGS")
            orch_dir = os.path.join(tmpdir, "ORCH")
            os.makedirs(drop_dir, exist_ok=True)
            os.makedirs(orch_dir, exist_ok=True)

            mapping_file = os.path.join(tmpdir, "entity_mapping.csv")
            with open(mapping_file, "w", encoding="utf-8") as f:
                f.write(
                    "SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION,DELIMITER,LOAD_MODE,SKIP_ROWS,HEADER_MODE\n"
                    'SAP_ERP,SAP_GL_ENTRY,gl_entry,".csv",.csv,;,replace,1,first_chunk_only\n'
                )

            # Create data payload and .ctl control file
            payload_file = os.path.join(drop_dir, "sap_gl_entry_20261021.csv")
            with open(payload_file, "w", encoding="utf-8") as f:
                f.write("ENTRY_ID;ACCOUNT_CODE;AMOUNT\n101;AC4000;1250.50\n")

            ctl_file = os.path.join(drop_dir, "SAP_GL_7001.ctl")
            with open(ctl_file, "w", encoding="utf-8") as f:
                f.write("sap_gl_entry_20261021.csv\n")

            cfg_file = os.path.join(tmpdir, "config.json")
            with open(cfg_file, "w", encoding="utf-8") as f:
                json.dump({
                    "feeder": {
                        "drop_zone": drop_dir,
                        "logs_dir": logs_dir,
                        "file_stability_window_seconds": 0,
                        "source_system_code": "SAP_ERP",
                        "entity_mapping_file": mapping_file,
                        "intake_plugin": "CUSTOM_SAP",
                    },
                    "orchestrator": {
                        "orchestrator_dir": orch_dir,
                        "config_file": "config.json",
                        "landing_zone": landing_dir,
                        "trigger_orchestrator": False,
                    },
                }, f)

            controller = BaseIntakeController(
                config_path=cfg_file,
                source_override="SAP_ERP",
                enqueue_only=True,
                plugin=CustomSourcePlugin(source_code="SAP_ERP"),
            )

            rc = controller.run()
            self.assertEqual(rc, 0)

            # Verify staged capsule in LANDING_ZONE/SAP_ERP/BATCH_20261021_120000_7001
            capsule_dir = os.path.join(landing_dir, "SAP_ERP", "BATCH_20261021_120000_7001")
            self.assertTrue(os.path.isdir(capsule_dir))
            self.assertTrue(os.path.isfile(os.path.join(capsule_dir, "batch_descriptor.json")))
            self.assertTrue(os.path.isdir(os.path.join(capsule_dir, "RAW")))

            with open(os.path.join(capsule_dir, "batch_descriptor.json"), "r") as df:
                desc = json.load(df)
            self.assertEqual(desc["batch_id"], "7001")
            self.assertEqual(desc["source"], "SAP_ERP")
            self.assertIn("SAP_GL_ENTRY", desc["entities"])
            entity_data = desc["entities"]["SAP_GL_ENTRY"]
            self.assertEqual(entity_data["delimiter"], ";")
            self.assertEqual(entity_data["header_columns"], ["ENTRY_ID", "ACCOUNT_CODE", "AMOUNT"])


if __name__ == "__main__":
    unittest.main()
