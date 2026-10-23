# DATA_LOADER — Phase 1 Implementation Progress & Change Log

**Specification Reference:** [`IMPROVEMENTS/PHASE_1_TPT_LOAD_PATH_AND_SCHEMA_GOVERNANCE.md`](PHASE_1_TPT_LOAD_PATH_AND_SCHEMA_GOVERNANCE.md)  
**Tracking File:** `DATA_LOADER/IMPROVEMENTS/PHASE_1_CHANGES.md`  
**Phase Goal:** Between "a validated file is ready in the loading zone" and "rows are in Teradata", ensure nothing is silently accepted, silently padded, silently dropped, or silently fabricated.

---

## 1. Item Implementation Status

| ID | Title | Severity | Files Impacted | Unit Tests / Coverage | Status |
|:---|:---|:---:|:---|:---|:---:|
| **F1.3** | Measure `has_meta` from table | Critical | `schema_guard.py`, `orchestrator_service.py` | `test_schema_guard_has_meta.py` | ✅ Complete |
| **F1.1** | Strict row rejection with explicit payload schema | Critical | `bteq_check.sh`, `generate_jobvars.sh`, `load_csv_generic.tpt.template`, `generate_tpt_job.sh`, `load_csv_generic.sh`, `run_tpt.sh` | `test_tpt_job_generation.py`, `test_tpt_file_list.py` | ✅ Complete |
| **F1.2** | Populate audit columns during load in `APPLY` statement | Critical | `generate_tpt_job.sh`, `load_csv_generic.sh` (removed `update_metadata.sh`) | `test_tpt_job_generation.py` | ✅ Complete |
| **F1.5** | Unconditional alignment check & Python header parsing | High | `bteq_check.sh`, `orchestrator_service.py`, `tpt_worker.py`, `parse_header.py` | `test_tpt_header_parse.py`, `test_orchestrator_precheck_flag.py` | ✅ Complete |
| **F1.9** | Explicit file lists (`-L`) and deterministic header modes | High | `parse_args.sh`, `pre_checks.sh`, `generate_jobvars.sh`, `load_csv_generic.tpt.template` | `test_tpt_file_list.py` | ✅ Complete |
| **F1.4** | Unlock by exact job name; never report unlock as load | Critical | `unlock_tpt_table.sh`, `parse_args.sh`, `tpt_worker.py`, `db_state.py`, `ddl_technical_tables.sql` | `test_tpt_worker_unlock.py` | ✅ Complete |
| **F1.10** | Process-group termination (`SIGKILL`) & precise lock detection | High | `tpt_worker.py` | `test_tpt_worker_process_group.py` | ✅ Complete |
| **F1.6** | Schema evolution without `DROP TABLE` (non-destructive `ALTER`) | Critical | `schema_guard.py`, `orchestrator_service.py`, `config*.json`, `exceptions.py` | `test_schema_guard_evolution.py` | ✅ Complete |
| **F1.7** | Declared row-size guard | High | `schema_guard.py`, `config*.json` | `test_schema_guard_row_size.py` | ✅ Complete |
| **F1.8** | Strict mapping validation & anchored signatures | High | `mapping.py`, `CONFIG/entity_mapping.csv`, `config*.json` | `test_core_mapping.py` | ✅ Complete |
| **F1.11** | No fabricated batch metadata in loader | High | `pre_checks.sh`, `unlock_tpt_table.sh` | `test_tpt_file_list.py` | ✅ Complete |
| **F1.12** | Safe environment construction (`TD_LOGON_USER`) | Low | `db.py`, `tpt_worker.py`, `parse_args.sh` | `test_core_db_pool.py` | ✅ Complete |

---

## 2. Detailed Change Log & Implementation Highlights

### F1.3 — Measure `has_meta` from the Table
- **Findings Addressed:** I3
- **Objective:** Eliminate hard-coded `has_meta=2` assumptions. Table inspection must dynamically measure whether audit columns exist.
- **Key Changes:**
  - `schema_guard.py`: Updated `get_teradata_table_columns` to return a 2-tuple `(payload_columns, has_meta)`.
  - Enforced audit column integrity: if a table has exactly 1 audit column (e.g. only `INFA_BATCH_ID`), it raises `SchemaSyncError` because a table must either have both audit columns (`has_meta=2`) or neither (`has_meta=0`).
  - `sync_entity_schema_if_drifted`: Now returns `(ok, has_meta)` measured directly from database catalog.
  - `orchestrator_service.py`: Passes dynamically measured `has_meta` down to `run_tpt_loader`.
- **Test Coverage:** Added `TESTS/unit/test_schema_guard_has_meta.py` validating 0, 1 (error), and 2 audit columns.

---

### F1.1 — Strict Row Rejection with an Explicit Payload Schema
- **Findings Addressed:** I1
- **Objective:** Eliminate silent row padding (`AcceptMissingColumns = 'Y'`) and missing row logging (`RecordErrorFile = ""`). Reject any broken, short, or excess rows.
- **Key Changes:**
  - `bteq_check.sh`: Introspection query on `DBC.ColumnsV` now extracts physical column types, sizes, precision, and character sets for all payload columns.
  - Replaced static `load_csv_generic.tpt` with dynamic template `load_csv_generic.tpt.template`.
  - Created `TPT_LOADER/lib/generate_tpt_job.sh`: Generates `job.tpt` with explicit `DEFINE SCHEMA PAYLOAD_SCHEMA` whose column count equals the file fields.
  - In `load_csv_generic.tpt.template`: Configured `AcceptMissingColumns = 'N'`, `AcceptExcessColumns = 'N'`, `TruncateColumnData = 'N'`.
  - `generate_jobvars.sh`: `RECORD_ERR_FILE` is unconditionally set to `${RUN_DIR}/rejected_rows.txt`.
  - `run_tpt.sh`: Checks `${RUN_DIR}/rejected_rows.txt` after `tbuild` execution, logging reject counts and failing when `ErrorLimit` is reached.
- **Test Coverage:** Added `TESTS/unit/test_tpt_job_generation.py` testing schema generation, typed declarations, and error flags.

---

### F1.2 — Populate Audit Columns During Load in `APPLY` Statement
- **Findings Addressed:** I1, I21
- **Objective:** Eliminate post-load full-table scans via BTEQ `UPDATE ... WHERE INFA_BATCH_ID IS NULL`. Audit values must be inserted atomically during the load.
- **Key Changes:**
  - `generate_tpt_job.sh`: Generates an `APPLY $INSERT` statement binding file payload columns while injecting literal audit expressions `'${BATCH_ID}'` and `TIMESTAMP '${META_TS}'`:
    ```sql
    APPLY $INSERT INTO @TargetTable ( ... , INFA_BATCH_ID, INFA_LAST_REPLICATED )
    VALUES ( :COL1, :COL2, ... , '${BATCH_ID}', TIMESTAMP '${META_TS}' );
    ```
  - Input validation: Regex validation for `${BATCH_ID}` (`^[A-Za-z0-9_.-]+$`) and `${META_TS}` (`^[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}$`).
  - Removed `TPT_LOADER/lib/update_metadata.sh` entirely from `load_csv_generic.sh`.
- **Test Coverage:** Validated via `TESTS/unit/test_tpt_job_generation.py` confirming injection of literal values and absence of `update_metadata.sh`.

---

### F1.5 — Alignment Check is Never Skipped & Python Header Parsing
- **Findings Addressed:** I13, Q11
- **Objective:** Header column sanitization and positional checks must be 100% reliable and never skipped.
- **Key Changes:**
  - Created `TPT_LOADER/lib/parse_header.py`: Uses standard Python `csv` module to parse header line 1, correctly handling quotes, delimiters, and commas inside quotes, applying `clean_column_name` in parity with `schema_reader.py`.
  - Removed bash-based `clean_column_name` from `lib/env_and_helpers.sh`.
  - `bteq_check.sh`: The query to `DBC.ColumnsV` and the payload column count check run unconditionally. When `-C` is passed, only column name string comparison is bypassed; column count mismatch halts immediately.
  - `orchestrator_service.py`: Computes `skip_precheck=guard_ran`. When Schema Guard ran and verified names against the CSV, `-C` is passed to TPT.
- **Test Coverage:** Added `TESTS/unit/test_tpt_header_parse.py` and `TESTS/unit/test_orchestrator_precheck_flag.py`.

---

### F1.9 — Explicit File Lists (`-L`) and Deterministic Header Handling
- **Findings Addressed:** I7 (wildcard part), I9 (part), §6.2
- **Objective:** Eliminate unbounded directory wildcards; support explicit file list files (`-L`) and deterministic header modes.
- **Key Changes:**
  - `parse_args.sh`: Added `-L <listfile>` CLI option, mutually exclusive with `-f`.
  - `pre_checks.sh`: Enforces mutual exclusivity of `-f` and `-L`. Removed archive decompression and temporary `.tar`/`.zip` extraction traps from TPT loader (archives are unpacked by the orchestrator).
  - Multi-file safety: If `SkipRowsEveryFile=N` and `SkipRows>0` for multi-file loads, forces `ReaderInstances=1` to prevent skipping rows across chunk boundaries out of sequence.
  - `generate_jobvars.sh` & `load_csv_generic.tpt.template`: Supports `FileList = 'Y'` and `FileName = '${FILE_LIST}'`.
  - `entity_mapping.csv`: Updated BICC rows to `HEADER_MODE=every_file` per decision D2.
- **Test Coverage:** Added `TESTS/unit/test_tpt_file_list.py`.

---

### F1.4 — Unlock by Exact Job Name; Never Report Unlock as Load
- **Findings Addressed:** I4
- **Objective:** Do not guess the job to unlock using `ls -1td` or globs. Require exact job name (`-j`) in replace mode. If unlock succeeds, retry load; do not mark the entity successful from unlock alone.
- **Key Changes:**
  - `unlock_tpt_table.sh`: In replace mode, requires `-j <job_name>`. Resumes `${WORK_DIR}/${JOB_NAME}` directly using preserved `jobvars.txt` and `job.tpt`. Removed `ls -1td` directory globbing and removed metadata backfill call.
  - `tpt_worker.py`: Generates standardized unique job name `TPT_{entity}_{ts}_{pid}` and passes `-j` to both `load_csv_generic.sh` and `unlock_tpt_table.sh`. On Error 2652, executes unlock and then retries the load rather than substituting unlock return code for load success.
  - `db_state.py` & `ddl_technical_tables.sql`: Added `TPT_JOB_NAME VARCHAR(128)` column to `BATCH_TASKS` table.
- **Test Coverage:** Added `TESTS/unit/test_tpt_worker_unlock.py` and updated `TESTS/test_phase01_units.py`.

---

### F1.10 — Process-Group Termination & Precise Lock Detection
- **Findings Addressed:** I11
- **Objective:** When a load times out or fails, terminate all child processes (`tbuild`, `bteq`) cleanly via process group signal. Do not rely on loose `"2652"` substring matching.
- **Key Changes:**
  - `tpt_worker.py`: Launches subprocesses with `start_new_session=True`. On timeout, sends `os.killpg(pgid, signal.SIGTERM)`, waits up to 5 seconds, and escalates to `os.killpg(pgid, signal.SIGKILL)` if processes remain alive.
  - Redirects stdout/stderr to disk file `${run_dir}/load_worker_{entity}.out` to avoid pipe deadlock on large volumes.
  - `_is_table_locked`: Replaced loose substring check with regex matching Teradata error patterns: `r"(?:TPT2652|RDBMS error 2652|Error 2652:)"`.
- **Test Coverage:** Added `TESTS/unit/test_tpt_worker_process_group.py`.

---

### F1.6 — Schema Evolution Without `DROP TABLE`
- **Findings Addressed:** I2
- **Objective:** Eliminate destructive `DROP TABLE` during ingestion. Support non-destructive column appends via `ALTER TABLE ... ADD`.
- **Key Changes:**
  - Added `SchemaDriftError` exception in `dataloader_core/exceptions.py`.
  - `schema_guard.py`: Removed `DROP TABLE` and `recreate_staging_table` entirely.
  - Added `create_staging_table`: Creates table when missing with `NOPI` and audit columns.
  - Added `alter_add_columns`: When CSV contains new columns appended to the end of existing columns, generates `ALTER TABLE <target> ADD <new_col> VARCHAR(4000) ...`.
  - Reordered columns, dropped columns, or type changes raise `SchemaDriftError` halting processing.
  - Updated config defaults: `"auto_migrate_ddl": false` across all shipped configuration files.
  - Test Harness Alignment: Updated `TESTS/clean_data_and_logs.sh` to recreate fresh staging tables (`ERP_MSH_USER` and `CRM_MSH_CUSTOMER`) and ensure `TPT_JOB_NAME` exists on `BATCH_TASKS`. Because `auto_migrate_ddl: false` is now strictly enforced, Schema Guard properly halts on missing tables; test harness resets now provision clean staging tables upfront to mirror governed production environments.
- **Test Coverage:** Added `TESTS/unit/test_schema_guard_evolution.py`.

---

### F1.7 — Declared Row-Size Guard
- **Findings Addressed:** Review §7
- **Objective:** Prevent Teradata Error 3933 (row length exceeds maximum allowable row length) before issuing DDL.
- **Key Changes:**
  - `schema_guard.py`: Added `declared_row_bytes(columns, character_set)` calculating row size based on charset (UNICODE: 8,000 bytes/col; LATIN: 4,000 bytes/col; audit columns: 208 bytes).
  - Added configurable `"max_row_bytes": 64000` (default 64 KB).
  - `create_staging_table` and `alter_add_columns` verify row bytes before execution; exceeding limit raises `SchemaSyncError` with explicit message instructing operator to create custom DDL with narrower columns.
- **Test Coverage:** Added `TESTS/unit/test_schema_guard_row_size.py`.

---

### F1.8 — Strict Mapping Validation & Anchored Signatures
- **Findings Addressed:** I14, I7 (part)
- **Objective:** Eliminate loose substring matching in file signatures and silent fallback defaults in mapping configuration.
- **Key Changes:**
  - `dataloader_core/mapping.py`: Signature matching regex changed to `(?:^|_)<sig>(?=-batch|\.)`. Signatures must match as distinct tokens bounded by start-of-filename or `_` and ending with `-batch` or `.`.
  - Strict mapping validation: `LOAD_MODE` must be `replace` or `append`; `HEADER_MODE` must be `first_chunk_only`, `every_file`, or `none`; `SKIP_ROWS` must be an integer $\ge 0$. Any invalid value raises `ConfigurationError`.
  - Duplicate rules for the same `(SOURCE, TARGET_TABLE)` or `(SOURCE, FILE_SIGNATURE)` raise `ConfigurationError`.
  - Corrupt or invalid zip archives raise `BatchValidationError`.
- **Test Coverage:** Expanded `TESTS/unit/test_core_mapping.py` with 9 comprehensive tests covering all validation constraints.

---

### F1.11 — No Fabricated Batch Metadata in Loader
- **Findings Addressed:** I15 (loader part)
- **Objective:** Eliminate `date +%s` fallbacks that fabricated batch IDs and timestamps when missing.
- **Key Changes:**
  - `pre_checks.sh`: When `HAS_META=2`, requires non-empty `-B` and `-T`. If either is missing, calls `die 1` immediately before invoking TPT.
  - Deleted `date +%s` fallback logic in `pre_checks.sh` and `unlock_tpt_table.sh`.
- **Test Coverage:** Added `test_missing_batch_id_with_audit_columns_fails` in `TESTS/unit/test_tpt_file_list.py`.

---

### F1.12 — Environment Construction for Loader (`TD_LOGON_USER`)
- **Findings Addressed:** Q12
- **Objective:** Prevent mutation of the caller's process login environment (`USER`).
- **Key Changes:**
  - `dataloader_core/db.py`: `build_tpt_environment` sets dedicated variable `TD_LOGON_USER` and leaves `USER` and `SID_ADM_USER` untouched.
  - `tpt_worker.py`: Passes `-u` with `TD_LOGON_USER`.
  - `parse_args.sh`: Defaults `TD_USER="${TD_LOGON_USER:-${TDENV}${SID_ADM_USER}}"`.
- **Test Coverage:** Added `test_build_tpt_environment_does_not_touch_USER` in `TESTS/unit/test_core_db_pool.py`.

---

### Phase 1 Remediation & Unit Test Suite Stabilization
Following the initial run of the test suite on Unix DEV:
1. **`test_core_db_pool.py`**: Updated assertion in `test_build_tpt_environment` to verify `env["TD_LOGON_USER"] == "DEV0SIDFINADM"` (F1.12).
2. **`test_orchestrator_precheck_flag.py`**: Updated `BatchContext` test instantiation to match canonical dataclass signature (`clean_ts`, `manifest_path`, `manifest_basename`, `active_zone`, `is_in_flight`, `batch_log_dir`, `run_log_file`).
3. **`test_schema_guard_has_meta.py` & `schema_guard.py`**: Adopted canonical parameters (`connection`, `target_db`, `target_table`) and added defensive kwargs resolution for `td_db` and `td_table`.
4. **`test_tpt_worker_unlock.py` & `tpt_worker.py`**: Handled `loading_zone is None` gracefully in `run_tpt_loader` when relative paths or mocks are used without an explicit loading zone.
5. **`test_intake_plugin_framework.py` & `test_per_entity_mapping_options.py`**: Aligned test payload filenames (`sap_gl_entry-batch7001-.csv`, `file_events-batch1001-part1.csv`, `feed-batch2001-part1.csv`) with F1.8 anchored token requirements `(?:^|_)<sig>(?=-batch|\.)`.
6. **`test_orchestrator_service.py`**: Patched `sync_entity_schema_if_drifted` in service lifecycle test so missing table checks don't fail when Teradata cursor is mocked.
7. **`TPT_LOADER/lib/env_and_helpers.sh` & `pre_checks.sh`**: Directed `die` error output to `>&2` (stderr) and defaulted `TPT_TEMPLATE="${TPT_TEMPLATE:-${LIB_DIR:-${SCRIPT_DIR}/lib}/load_csv_generic.tpt.template}"`. Updated `test_tpt_file_list.py` and `test_tpt_job_generation.py` subprocess assertions.

---

## 3. Inventory of New Unit Test Modules

The following unit tests have been created in `DATA_LOADER/TESTS/unit/` and are automatically discovered by `python3 -m unittest discover -s TESTS/unit -p "test_*.py"`:

1. [`test_schema_guard_has_meta.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_schema_guard_has_meta.py) — Validates `has_meta` measurement (0, 1 -> error, 2).
2. [`test_tpt_job_generation.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_tpt_job_generation.py) — Validates dynamic payload schema generation, typed declarations, and inline audit injection.
3. [`test_tpt_file_list.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_tpt_file_list.py) — Validates `-L` file lists, mutual exclusivity with `-f`, and missing `-B`/`-T` rejection.
4. [`test_tpt_header_parse.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_tpt_header_parse.py) — Validates Python CSV header extraction, quoting, commas, and sanitization parity.
5. [`test_orchestrator_precheck_flag.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_orchestrator_precheck_flag.py) — Validates `-C` precheck bypass flag derivation.
6. [`test_tpt_worker_unlock.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_tpt_worker_unlock.py) — Validates unique job name generation, `-j` argument passing, and retry-after-unlock semantics.
7. [`test_tpt_worker_process_group.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_tpt_worker_process_group.py) — Validates process group sessions, SIGTERM/SIGKILL escalation, and precise Error 2652 regex matching.
8. [`test_schema_guard_evolution.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_schema_guard_evolution.py) — Validates `ALTER TABLE ... ADD`, `auto_migrate_ddl=false` protection, append-mode protection, and absence of `DROP TABLE`.
9. [`test_schema_guard_row_size.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_schema_guard_row_size.py) — Validates row byte calculations for UNICODE and LATIN, and enforcement of `max_row_bytes`.
10. [`test_core_mapping.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_core_mapping.py) — Extended with tests for anchored signatures, strict enum validation, duplicate rules, and corrupt ZIP handling.
11. [`test_core_db_pool.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/unit/test_core_db_pool.py) — Extended with test verifying `USER` environment variable is untouched.
12. [`test_phase01_units.py`](file:///C:/Users/P992860/data_loader/DATA_LOADER/TESTS/test_phase01_units.py) — Updated for `-j` validation, header parsing parity, and removal of `update_metadata.sh`.

---

## 4. Architectural Invariants Verification

- **CLI Entrypoint Line Limit (< 80 lines)**:
  - `BICC_INTAKE_CONTROLLER/feeder.py`: 61 lines (OK)
  - `DATA_INGESTION_ORCHESTRATOR/orchestrator.py`: 72 lines (OK)
- **Component Mirroring**:
  - All changes made in `DATA_LOADER/PROCESSING_TOOLS/` are synchronized identically to standalone roots `COMMON/`, `TPT_LOADER/`, `DATA_INGESTION_ORCHESTRATOR/`, and `BICC_INTAKE_CONTROLLER/`.
- **Line Ending & Encoding Integrity**:
  - All shell scripts (`*.sh`) and python scripts (`*.py`) enforce POSIX LF line endings (`\n`) without UTF-8 BOM.
