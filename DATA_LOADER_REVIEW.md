# DATA_LOADER — Code, Architecture, Documentation & Test Review

**Repository:** `github.com/manisadegh/DATA_LOADER` (2 commits: `fddedfe`, `a43cd4e`)
**Local clone:** `C:\Users\ms250192\Projects\generic_tpt_script\DATA_LOADER`
**Review date:** 23 Oct 2026

**Method:**
- Full read of the Python core, the BICC controller, the orchestrator and the TPT loader (Bash + `.tpt`).
- Static analysis with pyflakes, radon and vulture.
- Unit tests executed locally with coverage.
- Inspection of the 9 datasets and of the committed test-output archive (225 files).
- Spot-checks of documentation claims against the code.

Everything not listed in section 7 was verified by reading the code or running it.

## Executive summary

DATA_LOADER is an ambitious and conceptually well-structured framework. It has three tiers (intake → orchestrator → TPT) and uses a filesystem queue with atomic publish, solid POSIX locking and Teradata state tracking. The engineering intent is visible throughout.

However, several **data-integrity defects** mean it is not yet production-safe. Some paths silently load malformed rows without trace. Some silently drop governed staging tables. One can mark an entity as loaded when it wasn't. Integrity checks are weaker than the documentation states.

The test suite passes, but it runs entirely on 3-column toy data that cannot exercise these failure modes. The "100% PASS" claim is accurate but says little about production readiness.

Separately, **the repository is public and contains client-identifying information**. This needs immediate action.

Severity scale used below: **Critical** = silent data loss or corruption, or a wrong success status; **High** = likely production failure or a strong integrity gap; **Medium** = robustness or maintainability issue; **Low** = hygiene.

---

## 0. Confidentiality — immediate action

| # | Finding | Evidence |
|---|---|---|
| S1 | The repo is **publicly accessible** (it can be cloned anonymously). | `git clone` without credentials |
| S2 | It contains client identifiers. | `FDJ` in the headers of `load_csv_generic.sh`, `load_csv_generic.tpt` and `unlock_tpt_table.sh`; commit author email `@lfdj.com` |
| S3 | It exposes internal infrastructure. | Dev host `tdadev`, service account `DEV0SIDFINADM`, DBs `DEV0SIDFIN*`, path `/sg/local/sid/home/Dsidadm/DATA_LOADER`. These appear in the docs and in 16 committed `jobvars.txt` files inside `TESTS/OUTPUTS/all_test_outputs_latest.tar.gz`. |
| S4 | No passwords leaked. | All committed `UserPassword` values are `"$tdwallet(DEV0SIDFINADM)"` references. Test data is synthetic. |

**Recommended actions:**
- Make the repo private, or move it to the client's or Teradata's internal Git.
- Treat its history as already exposed.
- Remove the output tarball from version control.

---

## 1. What works well

- **Clear tier separation.** The intake controller never touches Teradata. The orchestrator owns state. The TPT loader is a reusable CLI. The `BatchDescriptor` contract between tiers is a good idea.
- **Atomic publish into the queue.** Capsules are built in `.staging_BATCH_*` and published with `os.replace`. This is the correct pattern.
- **Locking is genuinely well engineered.** `ProcessLock` uses `flock`, re-checks the inode after acquiring, and unlinks the file while still holding the lock. `UtilitySlotGovernor` caps concurrent `tbuild` jobs across processes.
- **SQL hygiene is good.** Statements are parameterised throughout `db_state.py`. Identifiers are validated by `validate_sql_identifier`, with a Bash mirror in `validate_identifier`.
- **Secrets handling is sound by default.** Wallet references are used. Job-variable files get `chmod 600` and their directories `chmod 700`. Credentials are never passed on the command line.
- **There is a typed exception hierarchy** (`DataLoaderError` and subclasses), rather than `sys.exit` calls buried in business logic.
- **The DAT-02 guard is sound.** In append mode the load refuses to proceed if NULL audit rows exist, which prevents duplicate appends after a partial failure.
- **Zip extraction is safe.** Members are extracted by `basename`, so there is no zip-slip path traversal.
- **The tests are real.** 39 Python tests pass. 11 scenarios were run against a real DEV environment on 2026-10-21, with archived evidence.
- **Hygiene is good overall.** pyflakes reports **no undefined names**.

---

## 2. Architecture

| # | Sev. | Finding |
|---|---|---|
| A1 | High | **This repo is a downstream mirror.** `sync_components.sh` copies code from sibling repositories (`../COMMON`, `../TPT_LOADER`, …) that are not in this repo. The real source of truth isn't versioned here, and edits made here will be overwritten by the next sync. |
| A2 | Medium | **Massive duplication.** There are 43 Markdown files but only 28 are unique. `entity_mapping.csv` exists in **4 identical copies**. The feeder config carries a `schema_guard` block that the feeder never uses, except to override the orchestrator through the `DL_AUTO_MIGRATE_DDL` environment variable. That is a hidden cross-config coupling. |
| A3 | Medium | **Two sources of truth for batch state.** The filesystem (zones, manifests, marker files) and Teradata (`BATCH_RUNS` / `BATCH_TASKS`) are not reconciled transactionally. Several of the Critical findings below come from this gap. |
| A4 | Medium | **The legacy "flat batch" path roughly doubles the complexity** of the queue and recovery logic. It also carries a live bug (I19). |
| A5 | Medium | **The plugin architecture is partly fictional.** `SourceIntakePlugin.preprocess_candidate` and `prepare_payload_files` are never called by `BaseIntakeController`. Payload handling is hard-coded. In addition, unknown plugin names silently fall back to BICC. |
| A6 | Medium | **There is an implicit single-host assumption.** Liveness is checked with host-local PIDs (`is_pid_alive`), and a dead PID causes the batch to be marked FAILED. Running on two hosts, or after a PID is reused, would misclassify batches. |
| A7 | Medium | **FAIL_STOP coupling is very wide.** One failing source halts the multi-source sweep. One failing dbt test anywhere in the project blocks all ingestion (see I12). |

---

## 3. Code quality

**Metrics:**
- **Complexity hotspots (radon):**
  - `run_tpt_loader`: CC **56**
  - `scan_landing_queue`: CC **43**
  - `stage_and_publish_queue_capsule`: CC 39
  - `process_entity_task`: CC 32
  - `run_completeness_barrier_and_archive`: CC 32
- **Maintainability:** `orchestrator_service.py` (1,087 lines) has a maintainability index of **4.4/100**. Every other module scores above 30.
- **pyflakes:** 51 findings, all unused imports or variables. `intake_service.py` alone imports 14 unused names.
- **Dead code (vulture):** `scanner.py`, most of `manifest_factory.py`, the two plugin hooks above, `transition_to_loading_zone`, two schema-guard helpers and `sensor.scan_landing_zone`.

**Code smells:**

| # | Sev. | Finding | Location |
|---|---|---|---|
| Q1 | Medium | `sys.path.insert` appears in every module instead of proper packaging. | All Python modules |
| Q2 | Medium | Backward-compatibility churn: aliases (`process_batch = …`, `finalize_and_archive = …`), duplicated dict keys (`extract_timestamp` / `_raw` / `_iso` / `raw_timestamp`), and `**kwargs` that silently swallow typos. | `capsule.py`, `manifest.py`, service classes |
| Q3 | Medium | `CapsulePublishResult` subclasses `str` and overrides `__iter__`, so iterating the path yields 2 items instead of characters. | `capsule.py:23` |
| Q4 | Low | `@dataclass` is combined with a hand-written `__init__`, so the dataclass fields are decorative. | `capsule.py:40` |
| Q5 | Low | `manifest_checksum` is lost in a `to_dict` / `from_dict` round trip. | `capsule.py:111-147` |
| Q6 | Low | `created_at_utc` is an alias for local `datetime.now()`, not UTC. | `capsule.py`, `db_state.py` |
| Q7 | Medium | The BICC and Standard intake plugins are near-identical copy-paste. | `plugin.py:94-195` |
| Q8 | Medium | The connection pool returns connections to the queue even after errors, with no health check, so a dead session is reused indefinitely. | `db.py:210-228` |
| Q9 | Low | Unhandled exceptions are logged without stack traces. | `orchestrator_service.py:1082`, `:795` |
| Q10 | Low | `atexit.register(self.release)` runs on every lock acquisition. | `locking.py:215` |
| Q11 | Low | The claim that Python and Bash header parsing "match 100%" is false. Python uses the `csv` module; Bash uses naive `IFS` splitting. | `schema_reader.py:34` vs `bteq_check.sh:68` |
| Q12 | Low | `build_tpt_environment` overwrites `$USER` and `SID_ADM_USER` with the already-prefixed user. This is latent (callers pass `-u`), but it could produce a double `TDENV` prefix for future callers. | `db.py:119-127` |

---

## 4. Correctness & data-integrity anomalies

### Critical

**I1 — Malformed rows are loaded silently.**
- The TPT script sets `AcceptMissingColumns = 'Y'`. The comment directly above it says *"Strict: a row with the wrong number of columns … stops the job instead of being silently fixed."* The code does the opposite of its comment.
- When `HAS_META=2` (the orchestrator default), `RecordErrorFile` is disabled.
- As a result, a truncated row or a broken quote is padded with NULLs and loaded, and nothing is written to disk.
- The padding also assumes the two audit columns are physically last in the table. The name-order check excludes them, so a table where they sit elsewhere would shift data without any error.
- Location: `load_csv_generic.tpt:89-92`, `generate_jobvars.sh:19-24`.

**I2 — Governed staging tables can be dropped.**
- `auto_migrate_ddl` is `true` in **both** shipped configs.
- Any name or order drift in `replace` mode triggers `DROP TABLE` followed by a recreate as all-`VARCHAR(4000)` NOPI.
- A hand-written typed DDL (such as the original FDJ table, with its `DELETED_TS` column) would be replaced on the first run. Grants, statistics and constraints are lost.
- Location: `schema_guard.py:230-236`.

**I3 — `has_meta` is never measured.**
- Schema Guard returns `2` on every code path.
- A table without the audit columns is reported `IDENTICAL` with `has_meta=2`. The loader then disables reject logging and fails on the metadata `UPDATE`.
- Location: `schema_guard.py:214, 218, 236`.

**I4 — The unlock script can resume the wrong job, and the entity is then marked SUCCESS.**
- `ls -1td …/*${TARGET_TABLE}*` matches `ERP_MSH_USER_AK` when unlocking `ERP_MSH_USER`. The two run concurrently in the same batch, and the shipped mapping contains both pairs.
- The script resumes the AK job and returns 0.
- `tpt_worker` then records the *original* entity as SUCCESS, even though that table was never loaded and is still locked.
- Location: `unlock_tpt_table.sh:68`, `tpt_worker.py:143-145`.

**I5 — Integrity checks are weaker than documented.**
- The checksums declared in the BICC manifest are **never verified**.
- The feeder computes its own MD5s into a new manifest.
- The default orchestrator path checks **file sizes only**, because `verify_checksum_on_queued_capsule` defaults to `False`.
- The unit tests use `checksum=dummy`.
- Location: `base_controller.py:247-251`, `orchestrator_service.py:578-586`.

**I6 — A re-delivered batch destroys the queued one.**
- `stage_and_publish_queue_capsule` calls `shutil.rmtree(final_dir)` when a capsule with the same timestamp and ID already exists.
- This happens even if that capsule is still queued, or is being unpacked by the orchestrator at that moment.
- Location: `capsule.py:447-449`.

**I7 — Data from other entities, or from earlier batches, can be loaded into the wrong table.**
- For multi-chunk entities, TPT receives the wildcard `*{signature}*{ext}` and evaluates it over the whole `LOADING_ZONE/<SOURCE>/`, not over the validated file list.
- Signatures are matched as substrings, first match wins (for example `userpvo` would also match `…supplieruserpvo…`).
- The default fast path (`verify_descriptor_batch`) performs **no orphan-file check**. The OPS-01 rule exists only on the legacy manifest path.
- Location: `orchestrator_service.py:189`, `mapping.py:249`, `sensor.py:382-445`.

**I8 — The archive step is not atomic and moves the manifest first.**
- The manifest is exactly the marker that `check_inflight_batch` uses to detect an interrupted batch.
- A crash mid-archive therefore leaves payload files orphaned in `LOADING_ZONE` with no in-flight marker.
- The next batch is unpacked on top of them, where I7's wildcard can pick them up.
- Location: `orchestrator_service.py:895-921`.

### High

- **I9 — In-place header stripping mutates the payload that gets archived.** For multi-chunk raw CSVs, chunk 1's header is stripped in place. The archived file then no longer matches its manifest MD5. Location: `orchestrator_service.py:87-109`.
- **I10 — A truncated zip member can be reused on retry.** If a member already exists on disk, it is reused with no integrity check. A crash mid-extraction leaves a truncated file that is loaded as-is. Location: `orchestrator_service.py:155`.
- **I11 — `tbuild` can outlive its own timeout.**
  - On timeout, `subprocess.run` kills only the Bash wrapper. A grandchild `tbuild` can keep running and holding the table lock after its utility slot has been released.
  - Lock detection is a substring match on `"2652"` anywhere in the output.
  - Location: `tpt_worker.py:133-138`.
- **I12 — Post-tasks are heavy and unbounded.**
  - `dbt run` and `dbt test` run on the **whole project**, with no selector and no timeout. Any failing test blocks the queue, and a hung dbt holds the orchestrator lock.
  - Post-tasks are at-least-once on recovery.
  - With `--skip-post-tasks`, a multi-batch drain in `replace` mode leaves only the last batch in staging.
- **I13 — Alignment is not checked at all in some configurations.** The orchestrator always passes `-C` (skip pre-check). `_sync_schema_for_entity` fails open when Schema Guard is disabled or has no connection manager. Location: `orchestrator_service.py:668-674`.
- **I14 — Invalid configuration values are silently coerced.** An invalid `LOAD_MODE` (for example a typo like `apend`) becomes `replace`, i.e. a truncating load. `HEADER_MODE` is coerced the same way. Location: `mapping.py:160-178`.
- **I15 — Timestamps are fabricated silently.** Several fallbacks stamp `datetime.now()` as the *extract* timestamp, which then flows into archive partitioning and run metadata. Location: `manifest.py:98-223`, `capsule.py:197`, `pre_checks.sh:128-133`.
- **I16 — Recovery is the least validated path.**
  - It runs with `verify_checksum=False` and `allow_orphan_files=True`.
  - It picks `os.listdir()[0]` when several capsules exist, so FIFO is not guaranteed on recovery.
  - Orphaned `.staging_BATCH_*` directories are never recovered, even though their payload has already left the drop zone.
- **I17 — The pre-flight database check can be skipped silently.** `wait_or_recover_active_db_batch` swallows any non-domain exception at DEBUG level, so an unreachable database simply skips the check. Location: `orchestrator_service.py:416`.

### Medium

- **I18 — The audit trail is weak.**
  - `BATCH_TASKS` is keyed per file, but every update is issued per entity, so per-file tracking is effectively fictional.
  - Re-ingesting a batch that already succeeded overwrites its run row and deletes its task history.
- **I19 — Legacy flat-batch bug.** When several flat manifests coexist with capsules, every flat batch receives the **same** list of all flat data files. Location: `sensor.py:211-240`.
- **I20 — Batch identity is arbitrary.** It comes from the *first* `-batchNNN-` filename in the manifest. Real BICC extracts mix batch numbers: an earlier sample had `.csv` at `batch1736238000` and `.pecsv` at `batch558766085`.
- **I21 — The metadata UPDATE scales poorly.** `UPDATE … WHERE INFA_BATCH_ID IS NULL` runs after every load. In append mode this is a full scan of a growing table. Location: `update_metadata.sh`.

---

## 5. Tests

**Unit tests (Python):**
- 39 tests pass locally: 35 unit tests across 13 files, plus 4 "phase01" tests. Every Teradata interaction is mocked.
- Line coverage is **66%** overall and **51%** for `orchestrator_service.py`.
- Critical paths are thinly covered: `check_inflight_batch` **15%**, `strip_header_in_place` **7%**, `run_all_sources` **2%**, `ProcessLock.acquire` 49%.
- One of only two orchestrator-service tests asserts the entrypoint's *line count* (`< 80`), not behaviour.
- The Bash/TPT layer has **no** unit coverage.

**Scenario tests (Bash):**
- All 11 scenarios passed against real DEV (`TDENV=DEV0`, `TDPID=tdadev`) on 2026-10-21.

**Datasets — the core weakness:**
- All 9 batches are 3-column, 1–3-row, unquoted CSVs with pre-standardized manifests.
- There is no real BICC manifest (`MANIFEST-YYYYMMDD_HHMMSS.MF` with `PLV_KEY` and `;`).
- There are no quoted fields, embedded delimiters or newlines, no zip/gz, no `.pecsv`, no multi-chunk extract, no typed columns and no wide tables.
- The filenames (`file_userpvo-batch9001-.csv`) don't follow BICC naming.

**Assertion strength:**
- Scenario 01 ("nominal end-to-end") checks only filesystem artefacts. A missing `SUCCESS` in the logs is only a *warning*.
- Scenario 04 ("crash recovery") stages a clean flat batch plus a dead PID file. No crash during TPT, unpacking or archiving is simulated.
- Scenario 07 is the **only** check of database contents: a row count of 3 and non-null audit columns, with no value comparison.

**Conclusion:** none of findings I1–I17 can be detected by the current suite.

---

## 6. Documentation

**Strengths:**
- The documentation is extensive: 18 guides plus indexes, about 5,300 lines in `DOCS/`.
- It is well organised per tier (user guide, functional spec, technical manual, QA).
- It includes Mermaid diagrams.
- It is candid in places. For example, it states that recovery bypasses checksum validation.

**Weaknesses:**
- **15 byte-identical copies** of documents, kept in sync by script. This is a drift risk and doubles review cost.
- **Inflated tone.** About 80 strong or absolute claims ("wire-speed", "O(1)", "enterprise-grade", "guarantee", "100% PASS").
- **Inaccurate claims:**
  - "Atomically shifts data payloads from LANDING to LOADING" — false; the move is file by file.
  - "Total physical and logical isolation" between sources — overstated, given the shared slot governor, the project-wide dbt run and the sweep-wide FAIL_STOP.
- **`AcceptMissingColumns='Y'` is presented as a feature** ("Zero-Disk Metadata Padding") without stating its consequence: short rows are no longer rejected.
- **Environment details are hard-coded.** Absolute production paths appear throughout, which also feeds into S3.

---

## 7. Not verified / limits of this review

- **Row-size limit for auto-DDL (likely High).** 225 × `VARCHAR(4000) CHARACTER SET UNICODE` declares about 1.8 MB per row. That exceeds Teradata's maximum row size (1 MB on large-row systems), so `CREATE TABLE` should fail with error 3933 for the very PVO this project started with. An attempt to confirm this on the sandpit failed because the sandpit is unreachable (driver error 444); nothing was created there. One `CREATE` on DEV would settle it.
- **BICC multi-part headers.** If BICC repeats the header in each split file (believed to be the case), the default `first_chunk_only` mode loads N−1 header rows as data into all-VARCHAR tables, without any error. This needs a real multi-part extract to confirm.
- **BICC manifest column layout.** The second field is believed to be the UCM document ID rather than an MD5, which matters as soon as checksum verification is enabled. This needs confirmation against a real manifest.
- **Not covered in this pass:**
  - shellcheck was installed but not run.
  - Scenarios 02, 03, 05, 06, 08, 10 and 11 were reviewed only through their archived outputs.
  - The 855-line developer tutorial and the operations playbook were spot-checked, not fully read.

---

## 8. Prioritised recommendations

**P0 — now:**
- Make the repo private. Remove the test-output tarball and the client identifiers.
- Set `auto_migrate_ddl: false` everywhere until Schema Guard can never `DROP` a table. Replace `DROP` with `ALTER … ADD` or with a hard failure.

**P1 — before any production run:**
- **Fix silent row acceptance (I1).** Set `AcceptMissingColumns='N'` and supply the audit columns through job variables in the `APPLY` statement instead of padding. Re-enable `RecordErrorFile`. This also removes the post-load `UPDATE` (I21).
- **Measure `has_meta` instead of hard-coding it (I3).**
- **Fix the unlock job lookup (I4).** Persist the exact TPT job name per task in `BATCH_TASKS` and never glob for it.
- **Close the integrity gaps (I5).**
  - Verify the BICC-declared checksums at intake.
  - Enable checksum verification on capsules by default.
  - Fail on any orphan file in the fast path.
- **Never delete an existing capsule (I6).** Refuse the duplicate, or version it.
- **Remove the shared wildcard (I7).** Give TPT an explicit file list or a per-entity subdirectory. Use anchored signature matching.
- **Make archiving atomic (I8).** Move the whole capsule directory in one rename, with the marker removed last.
- **Kill the whole process group on timeout (I11),** so `tbuild` can't outlive its utility slot.
- **Fail fast on invalid configuration values (I14)** instead of coercing them.

**P2 — confidence:**
- Build a BICC-realistic test corpus: 225 columns, quoted fields, embedded commas and newlines, UTF-8, zip, multi-part, `.pecsv`, typed tables.
- Add fault-injection tests: kill the process during TPT, unpacking and archiving.
- Assert on database *values*, not only counts.

**P3 — maintainability:**
- Make this repo the source of truth, or package the core properly, and drop `sys.path` manipulation.
- Delete the dead code and the legacy flat path.
- Split `orchestrator_service.py` into smaller units.
- Keep a single copy of each document.
