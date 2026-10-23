# Phase 3 — Security Hygiene, Tests, Packaging & Refactoring

**Scope:** repository settings and history, `TESTS/**`, Python packaging, dead code, plugin wiring, module structure, documentation.
**Goal:** the repository exposes nothing it should not; the test suite can detect the classes of defect found in the review; the code base has one source of truth, one copy of every artefact, and no module nobody can maintain.
**Read first:** `IMPROVEMENTS/README.md` sections 2 and 3.

Items in this phase:

| ID | Title | Findings | Severity |
|---|---|---|---|
| **S** | Repository privacy and scrubbing — **do today** | S1, S2, S3 | Critical |
| F3.1 | Realistic test corpus | Tests | High |
| F3.2 | Fault-injection and integrity scenarios | Tests | High |
| F3.3 | Value-level database assertions and coverage gates | Tests | High |
| F3.4 | Single source of truth: monorepo, one config, one doc tree | A1, A2 | Medium |
| F3.5 | Python packaging; remove `sys.path` manipulation | Q1 | Medium |
| F3.6 | Dead code removal | Code quality | Low |
| F3.7 | Plugin hooks wired; registry fails on unknown names | A5 | Medium |
| F3.8 | Small code-quality fixes | Q2–Q7, Q9, Q10 | Low |
| F3.9 | Split `orchestrator_service.py` | Code quality | Medium |
| F3.10 | Documentation accuracy and tone | Docs | Medium |

Recommended order: **S immediately**, then F3.1 → F3.3 → F3.2 (tests first, so Phases 1–2 can be verified against them) → F3.4 → F3.5 → F3.6 → F3.7 → F3.8 → F3.9 → F3.10.

---

## S — Repository privacy and scrubbing (today, technical lead)
Finding: S1, S2, S3  Severity: Critical

**Facts**
- The repository can be cloned without credentials.
- Script headers carry the client's acronym. Commits carry an author address on the client's domain.
- Documentation and the committed archive `TESTS/OUTPUTS/all_test_outputs_latest.tar.gz` contain the production deployment path, the development Teradata host name, service-account and database names.
- No password is present (only wallet references). Test data is synthetic.

**Steps — in this order**
1. **GitHub → Settings → General → Danger Zone → Change visibility → Private**, for `DATA_LOADER` and for the four component repositories mentioned in the response document. Take a screenshot of each confirmation for the ticket.
2. Remove the archive from version control (keep a copy outside git if needed for reference):
   ```bash
   git rm --cached TESTS/OUTPUTS/all_test_outputs_latest.tar.gz
   ```
   In `.gitignore` replace the two lines `TESTS/OUTPUTS/*` / `!TESTS/OUTPUTS/all_test_outputs_latest.tar.gz` with `TESTS/OUTPUTS/*` and `!TESTS/OUTPUTS/.gitkeep` only. In `TESTS/archive_outputs.sh` and `TESTS/README.md`, stop referring to a committed "baseline archive".
3. Replace the client acronym in the header block of `PROCESSING_TOOLS/TPT_LOADER/load_csv_generic.sh`, `lib/load_csv_generic.tpt` (or `.template`) and `unlock_tpt_table.sh` with `DATA_LOADER Framework`.
4. In every file under `DOCS/`, `PROCESSING_TOOLS/*/docs/`, `PROCESSING_TOOLS/*/README.md`, `README.md`, `TESTS/README.md`, `DATA_LOADER_REVIEW_RESPONSE.md`: replace the absolute deployment path with `<DATA_LOADER_HOME>`, the host name with `<TDPID>`, service accounts with `<TDENV><SERVICE_ACCOUNT>`, database names with `<TDENV>SIDFIN<LAYER>` where the layer suffix is generic. Use `git grep -n` with the real values to find every occurrence, then `git grep` again to prove zero remain. Do not paste the real values into the commit message.
5. Set the commit identity for this repository to the company address: `git config user.email <company address>`.
6. Add `TESTS/tools/check_no_identifiers.sh`: reads regular expressions, one per line, from the file named by `DL_FORBIDDEN_PATTERNS_FILE` (kept **outside** the repository, maintained by the technical lead), runs `git grep -I -n -E -f` against the tree, exits 1 on any hit. Call it from `TESTS/run_all_tests.sh` as step 0 and from the PR checklist.
7. History: the identifiers remain in the git history. Decide with the organisation's security contact whether a history rewrite (`git filter-repo`) is required. If yes, do it on all five repositories at once and force-push; every developer re-clones afterwards. Record the decision in `DECISIONS.md` (D5).

**Acceptance criteria**
- [ ] `git clone https://github.com/<owner>/DATA_LOADER.git` from a machine with no credentials fails.
- [ ] `git ls-files | grep -c tar.gz` is 0.
- [ ] `TESTS/tools/check_no_identifiers.sh` exits 0 on `main`.
- [ ] `git log -1 --format=%ae` on the scrubbing commit shows the company domain.

---

### F3.1 — Realistic test corpus
Finding: Tests  Severity: High
Files: new `TESTS/tools/generate_corpus.py`, new `TESTS/DATASETS/CORPUS/**`, new `TESTS/DATASETS/DDL/**`

**Current behaviour**
- Nine datasets, each a 3-column, 1–3-row, unquoted CSV with a pre-standardized manifest. None of the defects found in the review can be triggered by them.

**Target behaviour**
- A deterministic generator (fixed random seed `20261023`) produces the datasets below plus, for each, an `EXPECTED.json` with the exact values the staging table must contain. Datasets are generated into `TESTS/DATASETS/CORPUS/` and committed (they are synthetic). The generator is committed so the corpus can be regenerated identically.
- Column names are generic (`COL_001` … or descriptive synthetic names). No real PVO names, no real values.

**Datasets (each is one batch directory with its manifest):**

| Name | Content | Purpose |
|---|---|---|
| `WIDE_TYPED_225` | 225 columns; 1,000 rows; column types in the companion DDL: `BIGINT` ×20, `DECIMAL(38,8)` ×40, `DATE` ×20, `TIMESTAMP(6)` ×20, `INTEGER` ×10, rest `VARCHAR(n) CHARACTER SET UNICODE` with n in {30, 150, 240, 960, 4000}; every field double-quoted; ~10 % of values empty; values include `é`, `ü`, `ß`, `日本語`, emoji; some VARCHAR values contain `,` and `""` (doubled quotes) and `\n` inside quotes. | F1.1/F1.2 end to end; TPT quoting; UTF-8; schema width rules |
| `WIDE_TYPED_225_ZIP` | same payload inside one `.zip` | F2.4 |
| `WIDE_TYPED_225_GZ` | same payload as `.csv.gz` | F2.4 |
| `MULTIPART_3` | one entity split in 3 files (`-batch<id>-<ts>` names with increasing `<ts>`), headers in every part **or** only in part 1 according to **D2** (generate both variants: `MULTIPART_3_HEADER_EVERY`, `MULTIPART_3_HEADER_FIRST`) | F1.9, F2.3 |
| `PECSV_KEYS` | a `.csv` data file and a `.pecsv` key file for the same signature, with their two mapping rows | inner-extension routing |
| `BICC_SHAPED` | a manifest named `MANIFEST-<YYYYMMDD_HHMMSS>.MF` with a `PLV_KEY=…` first line and `;`-separated entries (field layout according to **D1**), files named `file_<am>_<am>_<pvo>-batch<id>-<ts>.zip` | F2.5, F2.6, plugin parsing |
| `TRUNCATED_ROW` | `WIDE_TYPED_225` with row 500 cut after 100 fields | F1.1 rejection |
| `BROKEN_QUOTE` | row 200 with an unbalanced `"` | F1.1 rejection |
| `DUPLICATE_DELIVERY` | two identical copies of `WIDE_TYPED_225` with the same manifest name | F2.1 |
| `SIGNATURE_COLLISION` | files `…_userpvo-batch…` and `…_supplieruserpvo-batch…` in one batch, with mapping rows for both | F1.8, F2.2 |

**Implementation steps**
1. Write `generate_corpus.py` (standard library only: `csv`, `random`, `zipfile`, `gzip`, `hashlib`, `json`, `datetime`). One function per dataset; a `main()` that regenerates everything; `--only <name>`.
2. For each dataset also write `TESTS/DATASETS/DDL/<name>.sql` — the typed `CREATE MULTISET TABLE <TDENV>SIDFIN<STG>.<table>` with the two audit columns last — and `EXPECTED.json`: `{"row_count": N, "sample_rows": {"<key value>": {"<column>": "<value as string>", ...}}}` for 10 keys.
3. Manifests: standardized `MANIFEST_<SRC>_<TS>_<ID>.MF` with real MD5s (compute from the generated bytes), except `BICC_SHAPED`.
4. Add a mapping file `TESTS/DATASETS/CORPUS/entity_mapping.csv` with the rows the corpus needs; scenarios copy it over `CONFIG/entity_mapping.csv` in a sandbox config.

**Acceptance criteria**
- [ ] `python3 TESTS/tools/generate_corpus.py` twice produces byte-identical output (`git status` clean after the second run).
- [ ] `md5sum` of each payload equals the manifest entry.
- [ ] `WIDE_TYPED_225` has exactly 225 header fields when parsed with Python `csv`, and at least 3 rows contain an embedded newline.

**Tests to add**
- `TESTS/unit/test_generate_corpus.py::test_deterministic`, `::test_manifest_checksums_match`.

---

### F3.3 — Value-level database assertions and coverage gates
Finding: Tests  Severity: High
Files: `TESTS/verify_database_and_storage.py`, new `TESTS/run_unit_with_coverage.sh`, `TESTS/unit/test_orchestrator_service.py`

**Target behaviour**
- `verify_database_and_storage.py` accepts `--expected-values <EXPECTED.json>` and `--key-column <col>`: for every key in `sample_rows`, it selects the row and compares every listed column value (as string, trimmed) with the expected one; any difference is a `[FAIL]` with column, expected and actual. It also fails if `row_count` differs or if `rejected_rows.txt` for the batch is non-empty when `expect_rejects` is absent.
- Unit coverage is measured and gated: `dataloader_core` ≥ 80 % lines, `DATA_INGESTION_ORCHESTRATOR/lib` ≥ 75 %, `BICC_INTAKE_CONTROLLER/lib` ≥ 75 %. Below the gate, the script exits 1.
- The test `test_orchestrator_entrypoint_line_count_under_80` is deleted (it asserts a line count, not behaviour).

**Implementation steps**
1. Implement the comparison in `audit_batch`; keep the existing checks.
2. `run_unit_with_coverage.sh`:
   ```bash
   pip install --quiet coverage
   python3 -m coverage run --source=PROCESSING_TOOLS -m unittest discover -s TESTS/unit -t TESTS
   python3 -m coverage run -a --source=PROCESSING_TOOLS TESTS/test_phase01_units.py
   python3 -m coverage report --fail-under=75 --include='PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/lib/*'
   python3 -m coverage report --fail-under=80 --include='PROCESSING_TOOLS/COMMON/dataloader_core/*'
   python3 -m coverage report --fail-under=75 --include='PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER/lib/*'
   ```
   Call it from `run_all_tests.sh` scenario 09 instead of the plain `unittest` call.
3. Delete the line-count test.

**Acceptance criteria**
- [ ] Changing one expected value in `EXPECTED.json` makes scenario 17 (F3.2) fail with the column name in the message.
- [ ] `run_unit_with_coverage.sh` exits 1 when a threshold is not met (verify once by temporarily lowering a threshold to 99).

---

### F3.2 — Fault-injection and integrity scenarios
Finding: Tests  Severity: High
Files: new `TESTS/scenarios/12_…` to `17_…`, `TESTS/run_all_tests.py`, `TESTS/run_all_tests.sh`, `TESTS/README.md`

All scenarios follow the structure of `01_test_nominal_pipeline.sh` (trap → clean → inject → run → assert → archive outputs). Every assertion must `exit 1` on failure; a `[WARNING]` is not an assertion. Each scenario uses a **sandbox config** (copy of `config.json` with `auto_migrate_ddl: false`, the corpus mapping, and a dedicated technical database if available) created by a shared helper `TESTS/scenarios/lib/sandbox_config.sh`.

| # | Name | Steps | Assertions |
|---|---|---|---|
| 12 | `12_test_kill_tbuild_mid_load.sh` | Inject `WIDE_TYPED_225`; start the orchestrator in background; wait until `pgrep -f tbuild` is non-empty; `kill -9` the `tbuild` PID; wait for the orchestrator to exit; run the orchestrator again. | First run exits non-zero; `BATCH_TASKS` shows FAILED then, after the second run, SUCCESS for attempt 2; the table is unlocked (a `SELECT COUNT(*)` works); row count equals `EXPECTED.json`; no slot file under `.utility_slots` is held (`flock -n` on each succeeds). |
| 13 | `13_test_upload_in_progress.sh` | Copy the manifest first, then stream the payload with `pv -L 50k` (or `dd` in a loop with `sleep`) so the file grows during the feeder's settling window. | Feeder exits non-zero with "size changed during settling window"; nothing published to LANDING; a second feeder run after the copy completes succeeds. |
| 14 | `14_test_strict_rejects.sh` | Inject `TRUNCATED_ROW`, then `BROKEN_QUOTE`. | Each run exits non-zero; `rejected_rows.txt` for the entity is non-empty and contains the offending row number; the target table is empty (replace mode) and `BATCH_RUNS` is FAILED. |
| 15 | `15_test_duplicate_delivery.sh` | Inject `DUPLICATE_DELIVERY` (first copy, run feeder; second copy, run feeder). | First copy loaded; second copy under `DROP_ZONE/<SRC>/QUARANTINE/*/` with `REASON.txt`; the archived capsule of the first copy is unchanged (compare `ls -li` before/after). |
| 16 | `16_test_crash_during_archive.sh` | Run with `DL_TEST_FAULT=before_archive_rename` exported (add a test-only hook in the archive step: `if os.environ.get("DL_TEST_FAULT") == "before_archive_rename": os._exit(137)` immediately before `os.replace`); then run again without the variable. | After run 1 the batch directory is still in LOADING with `.work` removed; run 2 archives it without re-running TPT (log contains "already loaded"); archive payload MD5s match the manifest. |
| 17 | `17_test_wide_typed_end_to_end.sh` | Create the typed table from `DDL/WIDE_TYPED_225.sql`; inject `WIDE_TYPED_225`, then `_ZIP`, then `_GZ`, then `MULTIPART_3_*`, then `PECSV_KEYS`, then `BICC_SHAPED`. | For each: exit 0; `verify_database_and_storage.py --expected-values … --key-column …` passes; `rejected_rows.txt` empty; audit columns equal the batch id and extract timestamp. |

Also extend scenario 01 so that a missing `SUCCESS` in the logs is a failure, and scenario 07 so that it calls the verifier with `--expected-values`.

**Implementation steps**
1. Add the `DL_TEST_FAULT` hook (one `if`, documented as test-only, default inert).
2. Write the six scripts and the helper; register them in `run_all_tests.py` `SCENARIOS` and `run_all_tests.sh`.
3. Update `TESTS/README.md` with a table of scenarios and what each proves.

**Acceptance criteria**
- [ ] `./run_all_tests.sh` runs 17 scenarios on DEV and all pass.
- [ ] Reverting any one of F1.1, F1.4, F2.1, F2.2 or F2.4 on a throwaway branch makes at least one of scenarios 12–17 fail (do this check once per item and note the result in the PR).

---

### F3.4 — Single source of truth: monorepo, one config, one doc tree
Finding: A1, A2  Severity: Medium
Files: `sync_components.sh`, `PROCESSING_TOOLS/*/docs/`, `PROCESSING_TOOLS/COMMON/docs/`, `PROCESSING_TOOLS/*/entity_mapping*.csv`, `BICC_INTAKE_CONTROLLER/config*.json`, `DATA_INGESTION_ORCHESTRATOR/orchestrator.py`

**Target behaviour**
- `DATA_LOADER` is the only repository where code changes. The four component repositories are archived read-only on GitHub with a `README` pointing here. `sync_components.sh` is deleted.
- Documentation exists only under `DOCS/`. The copies under `PROCESSING_TOOLS/*/docs/` and `PROCESSING_TOOLS/COMMON/docs/` are deleted; each component `README.md` keeps a one-paragraph summary and links to `DOCS/`.
- `CONFIG/entity_mapping.csv` is the only mapping file. Delete `BICC_INTAKE_CONTROLLER/entity_mapping.csv`, `DATA_INGESTION_ORCHESTRATOR/entity_mapping.csv` and `entity_mapping_template.csv`; keep one template as `CONFIG/entity_mapping_template.csv`.
- The feeder config loses its `schema_guard` block. The `DL_AUTO_MIGRATE_DDL` environment override is removed from `base_controller.py` (lines 322–324), `intake_service.py` (97–99) and `orchestrator_service.py` (349–355). The orchestrator's own config decides; a CLI flag `--auto-migrate-ddl` / `--no-auto-migrate-ddl` on `orchestrator.py` overrides the config for one run (used by scenario 08).

**Implementation steps**
1. `git rm sync_components.sh`; add a `MAINTENANCE.md` at the root stating that components are edited here.
2. `git rm -r` the duplicate docs directories; fix links in component READMEs (`grep -rn "docs/" PROCESSING_TOOLS/*/README.md`).
3. `git rm` the duplicate mapping files; `grep -rn "entity_mapping" PROCESSING_TOOLS TESTS` and fix every path to `CONFIG/entity_mapping.csv` (the configs already point there; the `EntityMapper` default argument `"entity_mapping.csv"` in `base_controller.py:95` must become the CONFIG path).
4. Feeder config/template: delete the `schema_guard` object. `orchestrator.py`: add the two mutually exclusive flags with `argparse` (`parser.add_mutually_exclusive_group()`), pass `auto_migrate_override: Optional[bool]` to `OrchestratorService`. Scenario 08 part B passes `--no-auto-migrate-ddl` instead of editing the config.

**Acceptance criteria**
- [ ] `find . -name "*.md" -not -path "./.git/*" | xargs md5sum | awk '{print $1}' | sort | uniq -d` prints nothing (no duplicate documents).
- [ ] `git ls-files | grep -c entity_mapping` is 2 (`CONFIG/entity_mapping.csv`, `CONFIG/entity_mapping_template.csv`) plus the corpus mapping.
- [ ] `git grep DL_AUTO_MIGRATE_DDL` returns nothing.

---

### F3.5 — Python packaging; remove `sys.path` manipulation
Finding: Q1  Severity: Medium
Files: new `PROCESSING_TOOLS/COMMON/pyproject.toml`, every Python module with a `sys.path.insert` block

**Target behaviour**
- `dataloader_core` is an installable package: `pip install -e PROCESSING_TOOLS/COMMON`. The `BICC_INTAKE_CONTROLLER/lib` and `DATA_INGESTION_ORCHESTRATOR/lib` packages import it normally.
- No `sys.path.insert` anywhere under `PROCESSING_TOOLS/`. The only path manipulation allowed is in `TESTS/unit/__init__.py` (one place), and only until the CI installs the package.

**Implementation steps**
1. `pyproject.toml`:
   ```toml
   [build-system]
   requires = ["setuptools>=61"]
   build-backend = "setuptools.build_meta"
   [project]
   name = "dataloader-core"
   version = "2.1.0"
   requires-python = ">=3.8"
   dependencies = ["teradatasql>=20.0"]
   [tool.setuptools.packages.find]
   include = ["dataloader_core*"]
   ```
2. Delete the `sys.path` blocks in: `feeder.py:15-20`, `lib/intake_service.py:24-29`, `lib/manifest_factory.py:18-20`, `lib/scanner.py:19-21`, `orchestrator.py` (top), `lib/orchestrator_service.py:23-28`, `lib/sensor.py:18-20`, `lib/schema_guard.py`, `lib/post_tasks.py:17-19`, `lib/db_state.py` (top). For the `lib.` imports inside each component, make `lib/` a proper package (it needs an `__init__.py`) and run the entrypoints with the component directory as working directory, as the launchers already do (`cd PROCESSING_TOOLS/<component>`), or convert `from lib.x import y` to relative imports `from .x import y` and run with `python3 -m`. Choose the first (fewer changes) and document it in the deployment guide.
3. Deployment guide: add `pip install -e <DATA_LOADER_HOME>/PROCESSING_TOOLS/COMMON` to the installation steps.
4. `TESTS/unit/__init__.py`: a single `sys.path.insert` for `PROCESSING_TOOLS/COMMON` and the two component directories, with a comment that it disappears once CI installs the package.

**Acceptance criteria**
- [ ] `git grep -n "sys.path.insert" PROCESSING_TOOLS` returns nothing.
- [ ] After `pip install -e PROCESSING_TOOLS/COMMON`, `python3 -c "import dataloader_core"` works from any directory.
- [ ] All unit tests pass.

---

### F3.6 — Dead code removal
Finding: vulture results  Severity: Low

Delete, after confirming with `git grep` that nothing references them:
- `BICC_INTAKE_CONTROLLER/lib/scanner.py` (entire file) and `lib/manifest_factory.py` functions `vault_raw_manifest`, `transfer_batch_to_landing_zone`, `create_standardized_manifest`, `compute_file_md5` (keep `stage_batch_capsule_to_landing_zone` only if still called; otherwise delete the file).
- `intake_service.py`: the aliases `process_batch`, `enqueue_batch_capsule`; the `mapper_or_conn` / `maybe_mapper` compatibility parameters of `process_single_batch`; all unused imports.
- `schema_guard.py`: `load_entity_mappings`, `match_target_table_for_file`.
- `orchestrator_service.py`: `execute_entity_workload`, `finalize_and_archive` aliases (after F2.10 removed the others).
- `db.py`: the `TeradataConnectionManager.resolve_credentials` / `build_tpt_env` / `validate_identifier` static aliases if unused.
- Every unused import reported by `python3 -m pyflakes PROCESSING_TOOLS TESTS`.

**Acceptance criteria**
- [ ] `python3 -m pyflakes PROCESSING_TOOLS TESTS` prints nothing.
- [ ] `vulture PROCESSING_TOOLS --min-confidence 60` reports only `__exit__` parameters.

---

### F3.7 — Plugin hooks wired; registry fails on unknown names
Finding: A5  Severity: Medium
Files: `COMMON/dataloader_core/intake/base_controller.py`, `COMMON/dataloader_core/intake/plugin.py`

**Implementation steps**
1. In `BaseIntakeController.run`, after `self.verify_payload_stability(candidate)` and before `self.stage_and_publish_batch(candidate)`, call `self.plugin.preprocess_candidate(candidate, self.drop_zone)`.
2. In `stage_and_publish_batch`, replace the direct `declared_files=` move with `payload_files=self.plugin.prepare_payload_files(candidate, self.drop_zone)` (the capsule publisher already accepts `(src, dst)` pairs under `payload_files`). The default implementation keeps today's behaviour.
3. `PluginRegistry.get_plugin`: delete the alias blocks (lines 274–281); unknown key → `raise ConfigurationError(f"Unknown intake_plugin '{name_or_source}'. Registered: {sorted(cls._registry)}")`. Register the aliases explicitly with `PluginRegistry.register(...)` at module end instead.

**Acceptance criteria**
- [ ] A plugin subclass overriding `prepare_payload_files` to rename files produces a capsule with the renamed files.
- [ ] `intake_plugin: "bicc_typo"` → `ConfigurationError` at start-up.

**Tests to add**
- `TESTS/unit/test_intake_plugin_framework.py::test_hooks_are_invoked`, `::test_unknown_plugin_raises`.

---

### F3.8 — Small code-quality fixes
Finding: Q2–Q7, Q9, Q10  Severity: Low

| Item | File | Change |
|---|---|---|
| Q2 | `capsule.py`, `manifest.py` | Remove alias keys from `to_dict` (`extract_timestamp`, `created_at_utc`, `manifest_filename`, `raw_timestamp`); remove alias properties; remove `**kwargs` from `BatchDescriptor.__init__` and `stage_and_publish_queue_capsule`. Update callers (`git grep` each removed name). |
| Q3 | `capsule.py` | Replace `CapsulePublishResult(str)` with `@dataclass class CapsulePublishResult: path: str; descriptor: BatchDescriptor`. Callers that unpack `capsule_dir, descriptor = …` become `result = …; result.path, result.descriptor`. |
| Q4 | `capsule.py` | Make `BatchDescriptor` a plain `@dataclass` with field defaults; delete the hand-written `__init__`. |
| Q5 | `capsule.py` | Add `manifest_checksum` to `to_dict` and `from_dict`. |
| Q6 | `capsule.py`, `db_state.py`, plugins | Use `datetime.now(timezone.utc)` for `intake_timestamp_iso` and name the field accordingly; store Teradata timestamps as before (server local) but document it. |
| Q7 | `plugin.py` | Extract `_discover_manifest_candidates(self, drop_zone, extensions)` into `SourceIntakePlugin`; BICC and Standard plugins call it with `(".MF",)` and `(".MF", ".CTL")`. |
| Q9 | `orchestrator_service.py`, `base_controller.py` | Every `logger.critical`/`logger.error` inside an `except Exception` gets `exc_info=True`. |
| Q10 | `locking.py` | Move `atexit.register(self.release)` to `__init__`. |

**Acceptance criteria**
- [ ] `git grep -n "kwargs" COMMON/dataloader_core/capsule.py` returns nothing.
- [ ] All unit tests pass after updating them for the removed aliases.

---

### F3.9 — Split `orchestrator_service.py`
Finding: maintainability index 4.4, CC up to 56  Severity: Medium
Files: `DATA_INGESTION_ORCHESTRATOR/lib/**`

**Target structure** (names are mandatory):

| Module | Responsibility | Comes from |
|---|---|---|
| `lib/queue_discovery.py` | `QueuedBatchItem`, `scan_landing_queue`, in-flight listing | `sensor.py` (rename), `check_inflight_batch` |
| `lib/batch_preparation.py` | dequeue (`os.replace`), descriptor loading, `verify_descriptor_batch`, `prepare_entity_work_area`, `extract_archive_members` | `prepare_batch_from_queued_item`, `sensor.py` verifiers, F2.2/F2.4 code |
| `lib/entity_dispatch.py` | `process_entity_task`, the `ThreadPoolExecutor` loop, slot-governor usage, header-mode mapping | `process_entity_task`, `execute_entity_tasks` |
| `lib/batch_lifecycle.py` | state initialisation, completeness barrier, post-task invocation, receipt update, archive rename | `run_completeness_barrier_and_archive` |
| `lib/orchestrator_service.py` | configuration, lock, pre-flight, the `run` loop calling the four modules; **≤ 250 lines** | the rest |

**Rules**
- No function with cyclomatic complexity above 15 (`radon cc -n C PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/lib` must print nothing).
- No module above 400 lines.
- `BatchContext` moves to `lib/models.py` and gains `active_zone: str` as the batch directory and `already_loaded: bool`.
- Public function signatures used by tests (`run_tpt_loader`, `process_entity_task`, `OrchestratorService.run`) keep their names; imports in tests are updated to the new modules.

Do this item **after** F2.x is merged, never in parallel with it.

**Acceptance criteria**
- [ ] `wc -l lib/orchestrator_service.py` ≤ 250.
- [ ] `radon cc -n C lib/` prints nothing; `radon mi -n B lib/` prints nothing (every module ≥ 20).
- [ ] All unit tests and scenarios pass unchanged in behaviour.

---

### F3.10 — Documentation accuracy and tone
Finding: Docs  Severity: Medium
Files: `DOCS/**`, `README.md`

**Rules for every document**
1. One tree (`DOCS/`), after F3.4.
2. First line after the title: `_Last verified against commit <sha> on <date>._` — updated by whoever changes the behaviour described.
3. Banned words and phrases (replace with the plain fact): `wire-speed`, `enterprise-grade`, `O(1)`, `100% PASS`, `100% success`, `zero-leak`, `bulletproof`, `guarantee` (unless followed by the exact mechanism that guarantees it), `atomically` (unless the operation is one `rename`/`os.replace`).
4. Placeholders only (see S step 4). No real hosts, accounts, paths.
5. Mermaid edge labels containing parentheses or special characters are quoted: `-->|"label (x)"|`.

**Specific corrections**
- Orchestrator functional spec: zone lifecycle rewritten for F2.2; remove "In-Memory Padding", "fast-path O(1)" unless describing the explicit `false` configuration; add the duplicate-delivery and QUARANTINE sections; add the same-filesystem requirement.
- TPT loader guide/spec: generated job script, `-L`, `-j`, strict rejection, audit columns in the INSERT, removal of archive handling and of the post-load UPDATE (if Variant A).
- Architecture spec: state honestly that the design is single-host, what the hostname check does, and what the operator must do for a foreign-host `RUNNING` row.
- Intake spec §6: "Integrity" rewritten to say exactly what is verified at each step and what is not (upstream checksums only when declared).
- `README.md`: remove the "100% PASS" badge-like statements; replace the "11 scenarios" count with a link to `TESTS/README.md`.
- `TESTS/README.md`: scenario table from F3.2.

**Acceptance criteria**
- [ ] `git grep -n -i -E "wire.speed|enterprise.grade|O\(1\)|100% PASS|zero.leak|bulletproof" DOCS README.md` returns nothing.
- [ ] Every file under `DOCS/` has the "Last verified" line.
- [ ] A reviewer reading only `DOCS/` can predict the behaviour tested by scenarios 12–17 without opening the code (spot-check by the technical lead on three scenarios).

---

## Phase 3 exit checklist (technical lead)

- [ ] Section S completed on day 1; D5 recorded.
- [ ] 17 scenarios pass on DEV; coverage gates pass; `pyflakes` and `shellcheck` clean.
- [ ] One repository, one config, one doc tree; `sync_components.sh` gone; component repos archived.
- [ ] `orchestrator_service.py` ≤ 250 lines; no function above CC 15.
- [ ] `DECISIONS.md` complete (D1–D5).
