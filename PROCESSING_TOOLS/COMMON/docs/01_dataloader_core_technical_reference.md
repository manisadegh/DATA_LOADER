# `dataloader_core` — Shared Core SDK Technical Reference

## 1. Architectural Overview

`dataloader_core` (deployed under `PROCESSING_TOOLS/COMMON/dataloader_core/`) provides the foundational infrastructure and domain services shared by `BICC_INTAKE_CONTROLLER` (Tier 1), `DATA_INGESTION_ORCHESTRATOR` (Tier 2), and the verification test suite.

```mermaid
classDiagram
    class ConfigLoader {
        +load_json_config(config_path: str, env: Optional[dict]) dict
        +expand_env_vars(data: Any, env: Optional[dict]) Any
        +resolve_path(base_dir: str, configured_path: str, source: Optional[str], ensure_exists: bool) str
    }
    class ProcessLock {
        +lock_file: str
        +poll_interval_sec: float
        +timeout_sec: float
        +is_pid_alive(pid: int) bool
        +wait_for_pid(pid: int, poll_interval_sec: float, timeout_sec: float, logger: Logger, context_label: str) None
        +acquire() ProcessLock
        +release() None
        +__enter__() ProcessLock
        +__exit__() None
    }
    class TeradataConnectionManager {
        +max_connections: int
        +total_connections_created: int
        +resolve_credentials(td_cfg: dict) dict
        +build_tpt_env(td_cfg: dict, base_env: dict) dict
        +validate_identifier(identifier: str) str
        +acquire_connection() ContextManager~TeradataConnection~
        +cursor() ContextManager~Cursor~
        +close_all() None
    }
    class EntityMapper {
        +load_rules(mapping_file: str, source: Optional[str]) List~EntityRule~
        +inspect_inner_extension(file_path: str) str
        +match_file(filename: str, file_dir: Optional[str], source: Optional[str]) Optional~EntityRule~
    }
    class UtilitySlotGovernor {
        +slot_dir: str
        +max_slots: int
        +timeout_sec: float
        +acquire_slot(entity_name: str, logger: Logger) Tuple~int, int~
        +release_slot(slot_idx: int, fd: int, entity_name: str, logger: Logger) None
        +slot(entity_name: str, logger: Logger) ContextManager
    }
    class SourceIntakePlugin {
        <<abstract>>
        +source_name: str
        +discover_batches(drop_dir: str) List~RawBatchCandidate~
        +extract_batch_metadata(drop_dir: str, candidate: RawBatchCandidate) RawBatchCandidate
        +verify_payload_files(drop_dir: str, candidate: RawBatchCandidate) bool
    }
    class PluginRegistry {
        +register(name: str) Callable
        +get_plugin(name: str) SourceIntakePlugin
        +list_plugins() List~str~
    }
    class BaseIntakeController {
        +run() int
        +process_batch(candidate: RawBatchCandidate) bool
    }
    class ManifestHandler {
        +parse_filename(filename_or_path: str, default_source: str, custom_regex: Optional[str], strict: bool) ManifestMetadata
        +read_entries(manifest_path: str, require_non_empty: bool) List~ManifestEntry~
        +write_standardized_manifest(output_dir: str, source: str, extract_timestamp: str, batch_id: str, file_checksum_pairs: list) str
        +compute_file_checksum(file_path: str, algorithm: str) str
    }
    class SchemaReader {
        +clean_column_name(col_raw: str) str
        +extract_csv_columns(file_path: str, delimiter: str) List~str~
        +select_header_chunk_file(files: List~str~) str
        +validate_column_type(col_name: str, inferred_type: str) bool
    }
    class CapsulePathResolver {
        +normalize_timestamp_token(ts: str) str
        +normalize_iso_timestamp(ts: str) str
        +get_year_month(ts: str) str
        +get_capsule_folder_name(batch_id: str, ts: str) str
        +get_archive_capsule_dir(archive_base: str, source: str, batch_id: str, ts: str, ensure_exists: bool) str
        +get_queue_capsule_dir(landing_base: str, source: str, batch_id: str, ts: str, ensure_exists: bool) str
        +get_raw_vault_dir(archive_base: str, source: str, batch_id: str, ts: str, ensure_exists: bool) str
        +get_log_capsule_dir(logs_base: str, source: str, batch_id: str, ts: str, ensure_exists: bool) str
        +stage_and_publish_queue_capsule(staging_dir: str, final_capsule_dir: str) str
    }
    class LoggingFactory {
        +setup_feeder_logger(logs_dir: str, source: Optional[str]) Logger
        +setup_orchestrator_console_logger() Logger
        +attach_batch_file_logger(logger: Logger, capsule_or_logs_dir: str, source: str, extract_timestamp: str, batch_id: str) str
        +detach_batch_file_logger(logger: Logger, handler_ref: Any) None
    }
```

---

## 2. Module Specifications & Contracts

### 2.1 `dataloader_core.exceptions`
Defines typed domain exceptions so service classes (`IntakeControllerService`, `OrchestratorService`) raise structured exceptions rather than invoking `sys.exit()` inside internal methods:
- `DataLoaderError(Exception)`: Base exception.
- `ConfigurationError(DataLoaderError)`: Missing or malformed JSON configuration or required keys.
- `LockTimeoutError(DataLoaderError)`: Active PID or `fcntl.flock` wait exceeded `lock_timeout_seconds`.
- `BatchValidationError(DataLoaderError, ValueError)`: Missing/empty files, checksum mismatch, unmapped entity, or `OPS-01` single-batch/orphan violation.
- `SchemaSyncError(DataLoaderError, RuntimeError)`: Schema drift blocked by `auto_migrate_ddl=False` or `load_mode='append'`, or DDL execution failure.
- `OrchestratorExecutionError(DataLoaderError)`: Subprocess delegation or entity worker execution failure.

### 2.2 `dataloader_core.schema_reader`
Pure in-memory schema introspection utilities with **zero database dependencies**:
- `clean_column_name(col_raw: str) -> str`: Normalizes column names (`[^A-Za-z0-9_]` $\rightarrow$ `_`, collapses repeated underscores, strips leading/trailing underscores, converts to uppercase). Maintains 100% parity with bash `clean_column_name` and Teradata column naming rules.
- `extract_csv_columns(file_path: str, delimiter: str = ",") -> List[str]`: Reads line 1 from raw files, transparently decompressing `.zip` or `.gz` streams in memory without writing temporary files to disk. Returns sanitized column names.
- `select_header_chunk_file(files: List[str]) -> str`: Sorts chunk filenames deterministically and selects the file containing the header line (typically chunk 1).
- `validate_column_type(col_name: str, inferred_type: str = "VARCHAR") -> bool`: Validates column data types and identifiers.

### 2.3 `dataloader_core.config` (`ConfigLoader`)
- `expand_env_vars(data, env=None)`: Recursively expands `${VAR}` and `$VAR` across nested strings, dicts, and lists. Supports explicit `env` dictionary expansion without mutating global `os.environ`.
- `resolve_zone_path(base_dir, configured_path, source=None, ensure_exists=True)`: Resolves relative paths against `base_dir` and appends `<SOURCE>` using exact terminal segment matching (`os.path.basename`).
- `load_json_config(config_path, env=None)`: Loads JSON config and applies `expand_env_vars`.

### 2.4 `dataloader_core.locking` (`ProcessLock`, `UtilitySlotGovernor`)
- **`ProcessLock`**:
  - Combines POSIX advisory locking (`fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`) with PID liveness verification (`os.kill(pid, 0)`) and inode verification (`os.fstat(fd).st_ino == os.stat(lock_file).st_ino`).
  - Prevents TOCTOU race conditions when concurrent cron jobs start simultaneously while preserving active-wait polling logs and automatic stale-PID recovery on crashed runs.
- **`UtilitySlotGovernor`**:
  - Regulates concurrent Teradata load utility sessions (FastLoad, MultiLoad) across all processes and sources via bounded OS lock files (`.utility_slots/slot_01.lock` .. `slot_N.lock`).
  - Implements bounded token acquisition via non-blocking `fcntl.flock`. If all slots are busy, sleeps for `poll_interval_sec` up to `timeout_sec`.
  - Zero-leak guarantee: because lock tokens are held by open file descriptors in the Linux kernel process table, if an orchestrator process or TPT child crashes or receives `SIGKILL`, the kernel releases the slot lock instantly. No stale lock cleanup is ever needed.

### 2.5 `dataloader_core.db` (`TeradataConnectionManager`)
- **Credential Precedence**:
  1. Explicit `key_file` & `pass_file` $\rightarrow$ `ENCRYPTED_PASSWORD(file:<key>,file:<pass>)`
  2. Explicit `password` in `teradata` config block
  3. Auto-detected `~/.dbt/{user}_Key.properties` & `{user}_Pass.properties` (or `$DBT_PROFILE_DIR`)
  4. `TD_PASSWORD` environment variable
- **Thread-Safe Connection Pooling**:
  - Maintains a `queue.Queue` pool of reusable `teradatasql` connections (default `max_connections=6`, configurable via `teradata.connection_pool_size`).
  - Worker threads in `ThreadPoolExecutor` borrow connections via `with conn_mgr.acquire_connection() as conn:` or `with conn_mgr.cursor() as cur:`, eliminating per-query TCP logon/logoff overhead.

### 2.6 `dataloader_core.mapping` (`EntityMapper`, `EntityRule`)
- Loads and caches `entity_mapping.csv` into `EntityRule` dataclasses (with full backward-compatible dict-like item access `rule['TARGET_TABLE']`).
- **Extended 9-Column Architecture**:
  - Legacy 5 columns: `SOURCE`, `TARGET_TABLE`, `FILE_SIGNATURE`, `EXTENSION`, `INNER_EXTENSION`.
  - Extended optional columns: `DELIMITER` (default `,`), `LOAD_MODE` (default `replace`), `SKIP_ROWS` (default `1` for single chunk), `HEADER_MODE` (default `first_chunk_only`).
  - `HEADER_MODE` supports 3 operational modes:
    - `first_chunk_only`: Solution A behavior (strips chunk 1 header, TPT skips 0, `-Y N`).
    - `every_file`: Retains headers in all files and instructs TPT to skip headers natively (`-S N -Y Y`).
    - `none`: Pure data payload without header (`-S 0 -Y N`).
- Inspects `.zip` archives in memory (`inspect_file_inner_extension`) to distinguish `.csv` data payloads from `.pecsv` primary-key delete extracts.
- Executes the 2-pass matching algorithm (Pass 1: `source` + `signature` + `extension` + `inner_extension`; Pass 2: fallback without `inner_extension`).

### 2.7 `dataloader_core.manifest` (`ManifestHandler`) & `dataloader_core.checksum`
- Supports all 4 manifest filename conventions:
  1. `MANIFEST_<SOURCE>_<YYYYMMDD_HHMMSS>_<BATCH_ID>.MF`
  2. `*MANIFEST-<YYYYMMDD_HHMMSS>.MF`
  3. `MANIFEST-batch<ID>-.MF`
  4. `MANIFEST_<TOKEN>.MF`
- Parses `;`, `\t`, and `,` delimited manifest bodies and computes 64 KB streaming MD5/SHA256 digests.

### 2.8 `dataloader_core.capsule` (`CapsulePathResolver`, `BatchDescriptor`)
- `BatchDescriptor`: Dataclass capturing batch metadata (`batch_id`, `source`, `extract_timestamp`), payload file manifests, entities, and pre-extracted column headers. Serializes to/from `batch_descriptor.json`.
- `CapsulePathResolver`:
  - `get_queue_capsule_dir(landing_base, source, batch_id, ts)`: Builds path `LANDING_ZONE/<SOURCE>/BATCH_<CLEAN_TS>_<BATCH_ID>/`.
  - `get_archive_capsule_dir(archive_base, source, batch_id, ts)`: Builds path `ARCHIVE_ZONE/<SOURCE>/<YYYY-MM>/BATCH_<ID>_<TS>/`.
  - `stage_and_publish_queue_capsule(staging_dir, final_capsule_dir)`: Atomically renames temporary staging directory to published capsule destination.

### 2.9 `dataloader_core.logging_utils` (`LoggingFactory`)
- `setup_feeder_logger(logs_dir, source)`: Configures rotating feeder log handler.
- `setup_orchestrator_console_logger()`: Configures console log stream.
- `attach_batch_file_logger(logger, capsule_or_logs_dir, source, extract_timestamp, batch_id)`: Creates batch-specific file logger.
- `detach_batch_file_logger(logger, handler_ref)`: Flushes, closes, and removes file handlers from logger to prevent resource leaks and cross-test contamination.

### 2.10 `dataloader_core.intake` (`SourceIntakePlugin`, `PluginRegistry`, `BaseIntakeController`)
- **`RawBatchCandidate`**: Dataclass representing an identified raw candidate in `DROP_ZONE` prior to ingestion staging:
  - `batch_id`: Extracted batch identifier.
  - `extract_timestamp`: Extracted raw timestamp.
  - `manifest_file`: Optional path to manifest file (if source uses manifests).
  - `payload_files`: List of raw data payload filenames.
  - `metadata`: Arbitrary dictionary of source-specific metadata.
- **`SourceIntakePlugin`**: Abstract base class defining the contract for discovering and unpacking upstream data feeds:
  - `discover_batches(drop_dir: str) -> List[RawBatchCandidate]`: Finds batch candidates in the drop zone.
  - `extract_batch_metadata(drop_dir: str, candidate: RawBatchCandidate) -> RawBatchCandidate`: Parses manifest or file naming conventions to resolve timestamps and payload lists.
  - `verify_payload_files(drop_dir: str, candidate: RawBatchCandidate) -> bool`: Verifies file stability and existence before staging.
- **`PluginRegistry`**: Singleton registry supporting `@PluginRegistry.register("name")`, `PluginRegistry.get_plugin("name")`, and dynamic fallback. Built-in plugins:
  - `"bicc"` (`BICCIntakePlugin`): Oracle Fusion BICC exports with `MANIFEST-batch<id>-.MF` or timestamped manifests.
  - `"standard_manifest"` (`StandardManifestIntakePlugin`): Generic manifests matching `MANIFEST_<SOURCE>_<TIMESTAMP>_<BATCH_ID>.MF`.
  - `"manifestless"` (`ManifestlessDropIntakePlugin`): Manifestless directory arrivals where files are grouped by timestamp or naming pattern.
- **`BaseIntakeController`**: Generic intake controller engine implementing the end-to-end Producer lifecycle:
  - Concurrency locking with active polling wait via `ProcessLock`.
  - Invokes plugin discovery and strictly enforces chronological ascending FIFO order.
  - Verifies file stability over settling window (`file_stability_window_seconds`).
  - Performs pure in-memory column extraction via `schema_reader` with **zero database connectivity**.
  - Computes streaming MD5 hashes, generates `batch_descriptor.json`, raw receipt, and canonical manifest.
  - Atomically stages and publishes batch capsule to `LANDING_ZONE/<SOURCE>/BATCH_<TS>_<ID>/`.
  - Invokes Orchestrator with live log streaming and enforces `FAIL_STOP` on non-zero exit codes.
