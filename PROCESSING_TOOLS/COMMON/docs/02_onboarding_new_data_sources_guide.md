# Onboarding New Data Sources Developer Guide

This guide provides a comprehensive, step-by-step tutorial for onboarding a new data source into the **DATA_LOADER** ecosystem. With the Phase 04 pluggable intake architecture and extended mapping capabilities, integrating a new source requires minimal boilerplate while benefiting from the entire framework (FIFO ordering, file stability sentries, in-memory schema extraction, JIT Schema Guard, atomic Batch Capsules, and global Teradata workload governance).

---

## 1. Architecture Overview

Every data source in `DATA_LOADER` operates through the 3-Tier processing cascade:

```
┌────────────────────────────────────────────────────────────────────────┐
│ TIER 1: INTAKE PRODUCER (BaseIntakeController + SourceIntakePlugin)    │
│  - Discovers incoming batches in DROP_ZONE/<SOURCE>/                  │
│  - Extracts metadata & inspects CSV/ZIP column headers in memory       │
│  - Computes MD5 checksums & creates batch_descriptor.json              │
│  - Atomically stages Batch Capsule in LANDING_ZONE/<SOURCE>/           │
│  - Zero Teradata dependency                                            │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ Queues Batch Capsule
┌──────────────────────────────────▼─────────────────────────────────────┐
│ TIER 2: ORCHESTRATOR CONSUMER (OrchestratorService)                    │
│  - Discovers queued capsules in LANDING_ZONE in FIFO order             │
│  - O(1) file verification via batch_descriptor.json                    │
│  - JIT Schema Guard & Auto-DDL on Teradata                             │
│  - Governs concurrency via global UtilitySlotGovernor                  │
│  - Parallel entity execution -> Post-tasks -> ARCHIVE_ZONE             │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │ Invokes TPT Loader (-s, -S, -Y, -C)
┌──────────────────────────────────▼─────────────────────────────────────┐
│ TIER 3: TPT LOADER (load_csv_generic.sh)                               │
│  - FastLoad (replace) or MultiLoad (append)                            │
│  - Respects per-entity delimiter, header mode, and skip rows           │
│  - Teradata Vantage Staging & In-Database Audit Metadata Backfill      │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Step 1: Choose Your Intake Strategy

DATA_LOADER provides 3 built-in plugins in `dataloader_core.intake.plugin`:

| Built-in Plugin Name | Class | Description & Drop Zone Format |
|:---|:---|:---|
| `"bicc"` | `BICCIntakePlugin` | Oracle Fusion BICC exports with raw manifests (`MANIFEST-batch<id>-.MF` or timestamped manifests). |
| `"standard_manifest"` | `StandardManifestIntakePlugin` | Generic feeds accompanied by a standardized manifest: `MANIFEST_<SOURCE>_<TIMESTAMP>_<BATCH_ID>.MF`. |
| `"manifestless"` | `ManifestlessDropIntakePlugin` | Data feeds delivered without any manifest files. Batches are discovered by timestamp grouping or directory arrival. |

If your data source matches one of these conventions, you can use the built-in plugin directly by specifying `"intake_plugin": "standard_manifest"` (or `"manifestless"`) in your `config.json`.

---

## 3. Step 2: Implement a Custom Intake Plugin (If Needed)

If your source uses custom file naming conventions or an upstream metadata format (e.g., XML/JSON manifests, specific control files), implement a custom plugin by inheriting from `SourceIntakePlugin` and registering it with `@PluginRegistry.register`:

```python
# custom_intake_plugin.py
from typing import List
import os
import re
from dataloader_core.intake import SourceIntakePlugin, RawBatchCandidate, PluginRegistry

@PluginRegistry.register("crm_salesforce")
class SalesforceIntakePlugin(SourceIntakePlugin):
    """Custom intake plugin for Salesforce daily bulk exports."""

    @property
    def source_name(self) -> str:
        return "CRM_SFDC"

    def discover_batches(self, drop_dir: str) -> List[RawBatchCandidate]:
        """Scans drop_dir for ready export packages."""
        candidates = []
        if not os.path.exists(drop_dir):
            return candidates

        # Example pattern: SFDC_EXPORT_YYYYMMDD_HHMMSS_<BATCH_ID>.ready
        pattern = re.compile(r"^SFDC_EXPORT_(\d{8}_\d{6})_([A-Za-z0-9]+)\.ready$")
        for fname in os.listdir(drop_dir):
            match = pattern.match(fname)
            if match:
                extract_ts = match.group(1)
                batch_id = match.group(2)
                
                # Find all payload CSVs belonging to this batch
                payload_prefix = f"SFDC_{batch_id}_"
                payloads = [
                    f for f in os.listdir(drop_dir)
                    if f.startswith(payload_prefix) and f.endswith(".csv")
                ]
                
                candidate = RawBatchCandidate(
                    batch_id=batch_id,
                    extract_timestamp=extract_ts,
                    manifest_file=os.path.join(drop_dir, fname),
                    payload_files=payloads,
                    metadata={"source_system": "Salesforce_EU"}
                )
                candidates.append(candidate)
        return candidates

    def extract_batch_metadata(self, drop_dir: str, candidate: RawBatchCandidate) -> RawBatchCandidate:
        """Parse control file or enrich metadata if necessary."""
        return candidate

    def verify_payload_files(self, drop_dir: str, candidate: RawBatchCandidate) -> bool:
        """Verify that all expected payload files exist and have non-zero size."""
        if not candidate.payload_files:
            return False
        for pfile in candidate.payload_files:
            path = os.path.join(drop_dir, pfile)
            if not os.path.isfile(path) or os.path.getsize(path) == 0:
                return False
        return True
```

To run this plugin:
1. Inherit from `BaseIntakeController`:
   ```python
   # feeder_sfdc.py
   from dataloader_core.intake import BaseIntakeController
   from dataloader_core.config import ConfigLoader
   import custom_intake_plugin  # Registers @PluginRegistry.register("crm_salesforce")

   if __name__ == "__main__":
       config = ConfigLoader.load_json_config("config_sfdc.json")
       service = BaseIntakeController(config=config, source_override="CRM_SFDC")
       service.run()
   ```

---

## 4. Step 3: Configure `entity_mapping.csv`

The routing and loading behavior for each incoming file signature is configured in `CONFIG/entity_mapping.csv`. DATA_LOADER supports extended 9-column specifications while preserving 100% backward compatibility with legacy 5-column configurations.

### 9-Column Specification

```csv
SOURCE,TARGET_TABLE,FILE_SIGNATURE,EXTENSION,INNER_EXTENSION,DELIMITER,LOAD_MODE,SKIP_ROWS,HEADER_MODE
CRM_SFDC,SFDC_ACCOUNT_STG,account_extract,".csv,.zip",.csv,;,replace,1,every_file
CRM_SFDC,SFDC_OPPORTUNITY_STG,opportunity_extract,".csv,.zip",.csv,;,append,0,none
ORACLE_FUSION,ERP_AP_INVOICES,invoiceheaderextractpvo,".csv,.zip",.csv,",",replace,1,first_chunk_only
```

### Column Definitions

| Column | Type | Default | Description & Allowed Values |
|:---|:---|:---|:---|
| `SOURCE` | `str` | *(Requis)* | Name of the source partition (e.g. `CRM_SFDC`, `ORACLE_FUSION`). |
| `TARGET_TABLE` | `str` | *(Requis)* | Target Teradata staging table name (without database prefix). |
| `FILE_SIGNATURE` | `str` | *(Requis)* | Substring pattern in filename identifying the entity. |
| `EXTENSION` | `str` | `".csv,.zip"` | Supported file extensions. |
| `INNER_EXTENSION` | `str` | `""` | Optional extension of payload inside `.zip` archives (`.csv` vs `.pecsv`). |
| `DELIMITER` | `str` | `","` | Character separator (e.g., `,`, `;`, `\t`, `\|`). Passed to TPT via `-s`. |
| `LOAD_MODE` | `str` | `"replace"` | Ingestion engine: `replace` (FastLoad `DELETE ALL`) or `append` (MultiLoad). |
| `SKIP_ROWS` | `int` | `1` | Header rows to skip in data files. |
| `HEADER_MODE` | `str` | `"first_chunk_only"` | Header treatment: <br>• `first_chunk_only`: Oracle BICC Solution A (header stripped on chunk 1, TPT `-S 0 -Y N`).<br>• `every_file`: Standard CSVs where every file retains header (TPT `-S <SKIP_ROWS> -Y Y`).<br>• `none`: Headless data files (TPT `-S 0 -Y N`). |

---

## 5. Step 4: Configure `config.json`

Create or update the configuration file for your source (e.g., `CONFIG/config_crm.json`):

```json
{
  "source": "CRM_SFDC",
  "intake_plugin": "crm_salesforce",
  "paths": {
    "drop_zone": "../../DATA/DROP_ZONE",
    "landing_zone": "../../DATA/LANDING_ZONE",
    "loading_zone": "../../DATA/LOADING_ZONE",
    "archive_zone": "../../DATA/ARCHIVE_ZONE",
    "logs_dir": "../../LOGS"
  },
  "file_stability_window_seconds": 5,
  "max_global_utility_slots": 8,
  "auto_migrate_ddl": true,
  "max_parallel_workers": 4,
  "post_ingestion_tasks": {
    "CRM_SFDC": [
      {
        "name": "Notify Downstream SFDC Pipeline",
        "command": "/bin/bash scripts/notify_crm_loaded.sh ${BATCH_ID} ${EXTRACT_TIMESTAMP}"
      }
    ]
  }
}
```

---

## 6. Step 5: Execution

### 6.1 Running Tier 1 (Intake Producer)
You can run the intake producer either coupled (triggering the orchestrator immediately) or decoupled (`--enqueue-only`):

```bash
# Coupled mode (Producer enqueues capsule and triggers Orchestrator):
python3 feeder.py --config config_crm.json --source CRM_SFDC

# Decoupled mode (Pure producer, only stages Batch Capsules in LANDING_ZONE):
python3 feeder.py --config config_crm.json --source CRM_SFDC --enqueue-only
```

### 6.2 Running Tier 2 (Orchestrator Consumer)
Consume queued capsules for a single source or across all sources:

```bash
# Process single source:
python3 orchestrator.py --config config.json --source CRM_SFDC

# Process multiple specific sources:
python3 orchestrator.py --config config.json --sources CRM_SFDC,ORACLE_FUSION

# Process ALL sources discovered in LANDING_ZONE:
python3 orchestrator.py --config config.json --all-sources
```

---

## 7. Step 6: End-to-End Verification

Verify the ingestion results using `verify_database_and_storage.py`:

```bash
python3 verify_database_and_storage.py \
    --batch-id <BATCH_ID> \
    --source CRM_SFDC \
    --target-table SFDC_ACCOUNT_STG \
    --expected-count <N>
```

The script verifies:
1. **Storage Tier**: `LANDING_ZONE/CRM_SFDC` and `LOADING_ZONE/CRM_SFDC` are clean; full Batch Capsule is archived in `ARCHIVE_ZONE/CRM_SFDC/<YYYY-MM>/BATCH_<ID>_<TS>/`.
2. **Teradata Technical Tables**: `BATCH_RUNS` has `STATUS='SUCCESS'` and retained `PROCESS_PID`; all `BATCH_TASKS` are `SUCCESS`.
3. **Teradata Staging**: `SFDC_ACCOUNT_STG` has `<N>` rows with populated `INFA_BATCH_ID` and `INFA_LAST_REPLICATED`.
