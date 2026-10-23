# COMMON / `dataloader_core` — Shared Core SDK for DATA_LOADER

`COMMON/dataloader_core` is the centralized Python SDK shared across **Tier 1 (`BICC_INTAKE_CONTROLLER`)**, **Tier 2 (`DATA_INGESTION_ORCHESTRATOR`)**, and the **Automated Verification & Audit Suite (`TESTS/verify_database_and_storage.py`)**.

---

## 1. Purpose & Responsibilities

`dataloader_core` eliminates cross-component duplication (`DRY-01` through `DRY-09`), provides pure flat-file schema introspection with zero Teradata database dependency, prevents process lock TOCTOU race conditions (`RSK-04`), and pools Teradata Vantage connections across concurrent worker threads:

- **`schema_reader.py`**: In-memory header extraction from raw files (`.csv`, `.pecsv`, `.zip`, `.gz`) via `extract_csv_columns`, column name sanitization (`clean_column_name`), multi-chunk file selection (`select_header_chunk_file`), and data type validation (`validate_column_type`).
- **`capsule.py`**: `BatchDescriptor` data model and `CapsulePathResolver` providing canonical Batch Capsule directory management, atomic staging and publishing of queue capsules (`stage_and_publish_queue_capsule`), and strict path-segment resolution (`<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>`).
- **`exceptions.py`**: Typed domain exception hierarchy (`DataLoaderError`, `ConfigurationError`, `LockTimeoutError`, `BatchValidationError`, `SchemaSyncError`, `OrchestratorExecutionError`).
- **`config.py`**: Recursive `${VAR}` / `$VAR` expansion (`expand_env_vars`), JSON loader (`load_json_config`), and source-partitioned path resolver (`resolve_zone_path`).
- **`locking.py`**: Atomic POSIX advisory file locking (`fcntl.flock`) combined with PID metadata and active polling wait loops (`ProcessLock`, `is_pid_alive`, `wait_for_pid_completion`).
- **`db.py`**: Single source of truth for Teradata authentication (`resolve_teradata_credentials`), TPT environment construction (`build_tpt_environment`), SQL identifier validation (`validate_sql_identifier`), and thread-safe connection pooling (`TeradataConnectionManager`).
- **`mapping.py`**: `EntityRule` dataclass, in-memory `.zip`/`.gz` inner-extension inspector (`inspect_file_inner_extension`), and 2-pass `entity_mapping.csv` matcher (`EntityMapper`).
- **`manifest.py`**: Unified manifest filename parser supporting all 4 BICC/canonical conventions (`parse_manifest_filename`), delimiter-agnostic entry reader (`read_manifest_entries`), and standardized manifest writer (`write_standardized_manifest`).
- **`checksum.py`**: Streaming 64 KB block-reader for MD5 and SHA256 calculation (`compute_file_checksum`).
- **`intake/`**: Pluggable intake architecture providing `SourceIntakePlugin` (abstract contract), `PluginRegistry`, `RawBatchCandidate`, `BaseIntakeController` (reusable producer workflow), and built-in plugins (`BICCIntakePlugin`, `StandardManifestIntakePlugin`, `ManifestlessDropIntakePlugin`).
- **`locking.py`**: Atomic POSIX advisory file locking (`fcntl.flock`) combined with PID metadata and active polling wait loops (`ProcessLock`, `is_pid_alive`, `wait_for_pid_completion`), plus `UtilitySlotGovernor` for cross-process Teradata load slot regulation.
- **`logging_utils.py`**: Standardized console and Batch Capsule file logger factory (`LoggingFactory`), plus safe file handler detachment (`detach_batch_file_logger`).

---

## 2. Package Layout

```
COMMON/
├── README.md
├── docs/
│   ├── 01_dataloader_core_technical_reference.md
│   ├── 02_onboarding_new_data_sources_guide.md
│   └── 03_source_intake_controller_development_tutorial.md
└── dataloader_core/
    ├── __init__.py
    ├── capsule.py
    ├── checksum.py
    ├── config.py
    ├── db.py
    ├── exceptions.py
    ├── intake/
    │   ├── __init__.py
    │   ├── base_controller.py
    │   └── plugin.py
    ├── locking.py
    ├── logging_utils.py
    ├── manifest.py
    ├── mapping.py
    └── schema_reader.py
```

---

## 3. Documentation

Comprehensive technical, onboarding, and tutorial guides are available in the [`docs/`](docs/) directory:
- 📖 [`docs/01_dataloader_core_technical_reference.md`](docs/01_dataloader_core_technical_reference.md): Complete API specifications, class diagrams, and core SDK usage examples.
- 🚀 [`docs/02_onboarding_new_data_sources_guide.md`](docs/02_onboarding_new_data_sources_guide.md): Architectural guide and checklist for onboarding new upstream data sources.
- 🛠️ [`docs/03_source_intake_controller_development_tutorial.md`](docs/03_source_intake_controller_development_tutorial.md): Step-by-step developer tutorial implementing custom source intake controllers (`SAP_ERP` end-to-end reference).
