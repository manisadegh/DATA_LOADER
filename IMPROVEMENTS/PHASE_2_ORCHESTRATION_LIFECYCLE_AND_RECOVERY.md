# Phase 2 — Orchestration Lifecycle, Recovery & State

**Scope:** `PROCESSING_TOOLS/COMMON/dataloader_core/{capsule.py,manifest.py,db.py,intake/*}`, `PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/{orchestrator.py,lib/orchestrator_service.py,lib/sensor.py,lib/db_state.py,lib/post_tasks.py,ddl_technical_tables.sql}`, `PROCESSING_TOOLS/BICC_INTAKE_CONTROLLER/**`.
**Goal:** a batch moves between zones as **one directory, in one rename**, is never modified, is never silently overwritten, is recovered in order after any crash, and its state in Teradata is a faithful history.
**Read first:** `IMPROVEMENTS/README.md` sections 2 and 3, and Phase 1 items F1.9 and F1.4 (this phase depends on them).

Items in this phase:

| ID | Title | Findings | Severity |
|---|---|---|---|
| F2.1 | Duplicate deliveries are refused and quarantined | I6 | Critical |
| F2.2 | One directory per batch; atomic zone transitions; explicit file lists | I7, I8 | Critical |
| F2.3 | The payload is never modified | I9 | High |
| F2.4 | Safe archive extraction | I10 | High |
| F2.5 | Checksum verification end to end | I5, D1 | Critical |
| F2.6 | Deterministic batch identity and timestamps | I15, I20 | High |
| F2.7 | Deterministic recovery and orphan handling | I16 | High |
| F2.8 | Pre-flight errors stop the run; host-aware liveness; state reconciliation | I17, A6, A3 | High |
| F2.9 | Post-tasks scoped, bounded and isolated per source | I12, A7 | High |
| F2.10 | Remove the legacy flat-batch path | A4, I19 | Medium |
| F2.11 | State tables keep history | I18 | Medium |
| F2.12 | Connection pool health check | Q8 | Medium |

Recommended order: F2.10 → F2.2 → F2.3 → F2.4 → F2.1 → F2.7 → F2.6 → F2.5 → F2.11 → F2.8 → F2.9 → F2.12. F2.10 first because deleting the legacy path removes code that F2.2 would otherwise have to change twice.

---

## Background you need before touching the orchestrator

1. **Zones today.** The feeder publishes `LANDING_ZONE/<SRC>/BATCH_<TS>_<ID>/`. The orchestrator **unpacks** that directory file by file into the flat root `LOADING_ZONE/<SRC>/` (`orchestrator_service.py:541-555`), runs TPT against that root, then moves files one by one into `ARCHIVE_ZONE/<SRC>/<YYYY-MM>/BATCH_<ID>_<TS>/` (`:895-921`) and deletes whatever is left in the root (`:927-938`). The "in-flight batch" detector looks for a `.MF` file in the root (`:445-449`).
2. **Why that is fragile.** Every transition is many small operations. A crash in the middle leaves a half-state nobody can interpret, and the manifest — the only in-flight marker — is the first thing moved during archiving. Because all entities of a batch share one flat directory, TPT wildcards can see other entities' files and leftovers from previous batches.
3. **The fix in one sentence.** A batch is a directory. It is moved from LANDING to LOADING with one `os.replace`, worked on *inside* that directory, and moved from LOADING to ARCHIVE with one `os.replace`. Its presence in LOADING **is** the in-flight marker.
4. **`os.replace` is atomic only on the same filesystem.** `DATA/LANDING_ZONE`, `DATA/LOADING_ZONE` and `DATA/ARCHIVE_ZONE` must be on one filesystem. F2.2 adds a startup check.

Target layout after this phase:

```
LOADING_ZONE/<SRC>/
  .orchestrator.pid
  .utility_slots/                       (unchanged, at LOADING_ZONE/.utility_slots in multi-source mode)
  BATCH_<TS>_<ID>/                      <- the capsule, moved here as-is
    MANIFEST_<SRC>_<TS>_<ID>.MF
    batch_descriptor.json
    RAW/
    <payload files exactly as delivered: .csv / .zip / .gz / .pecsv>
    .work/                              <- created by the orchestrator, deleted before archiving
      <ENTITY>/
        files.lst                       <- absolute paths, load order, one per line
        <plain data files: hard links to the payload, or extracted archive members>
        .extract_tmp/                   <- transient, see F2.4
ARCHIVE_ZONE/<SRC>/<YYYY-MM>/BATCH_<ID>_<TS>/   <- the same directory, renamed, without .work/
```

---

### F2.10 — Remove the legacy flat-batch path
Finding: A4, I19  Severity: Medium
Files: `lib/sensor.py`, `lib/orchestrator_service.py`

Do this first; it deletes code the other items would otherwise modify.

**Implementation steps**
1. `sensor.py`: delete `scan_landing_zone` (lines 52–98). In `scan_landing_queue`, delete the "legacy flat batch files" block (lines 202–248) and the `orphan_files` variable. After the capsule loop, add: any regular file in `landing_zone` whose name does not start with `.` is an error → return `"ERROR_UNEXPECTED_FILES", []` and log the list.
2. `orchestrator_service.py`: in `prepare_batch_from_queued_item` delete the `else:` legacy branch (lines 556–564). In `check_inflight_batch` delete the flat-manifest detection (lines 444–497); F2.2 rewrites this method. Delete `detect_and_validate_batch` and `acquire_guards_and_detect_batch` (lines 627–652) and `transition_to_loading_zone` (654–656). In `run`, replace the two `ERROR_MISSING_MANIFEST` / `ERROR_MULTIPLE_MANIFESTS` branches (lines 1048–1056) with one `ERROR_UNEXPECTED_FILES` branch raising `BatchValidationError`.
3. `QueuedBatchItem`: `capsule_dir` becomes mandatory (`str`); remove the `is_capsule` property and the `data_files` field.
4. Remove the imports that become unused (`glob` in `sensor.py`, `scan_landing_zone` in `orchestrator_service.py`).

**Acceptance criteria**
- [ ] `grep -n "legacy\|flat" lib/sensor.py lib/orchestrator_service.py` returns nothing (case-insensitive).
- [ ] A stray `foo.csv` at `LANDING_ZONE/<SRC>/` root makes `scan_landing_queue` return `ERROR_UNEXPECTED_FILES`.

**Tests to add / change**
- `TESTS/unit/test_multi_batch_queue_sensor.py`: delete tests that create flat manifests; add `test_unexpected_root_file_is_error`.
- `TESTS/unit/test_orchestrator_service.py`: remove any use of `detect_and_validate_batch`.

**Documentation impact:** remove "legacy flat" mentions from the orchestrator user guide and functional spec.

---

### F2.2 — One directory per batch; atomic zone transitions; explicit file lists
Finding: I7, I8  Severity: Critical
Files: `lib/orchestrator_service.py`, `lib/sensor.py`, `COMMON/dataloader_core/capsule.py`, `lib/tpt_worker.py`
Depends on: Phase 1 F1.9 (`-L`).

**Current behaviour**
- Described in the background above. Additionally `prepare_batch_from_queued_item` deletes anything in the loading root that has the same name as a capsule entry (`:546-550`), and the archive step `rmtree`s an existing `RAW` in the archive (`:913-914`).

**Target behaviour**
- **Dequeue:** `os.replace(LANDING/<SRC>/BATCH_x, LOADING/<SRC>/BATCH_x)`. If the destination exists → `BatchValidationError` (a batch with this identity is already in flight; see F2.1).
- **Work area:** for each entity, the orchestrator creates `BATCH_x/.work/<ENTITY>/`, places the plain data files there (hard link for plain files, extraction for archives — F2.4), and writes `files.lst` (absolute paths, sorted by file name, one per line).
- **TPT input:** `run_tpt_loader` receives the path of `files.lst` and passes `-L <files.lst>` to the loader. No wildcards anywhere.
- **Archive:** delete `BATCH_x/.work/`, then `os.replace(LOADING/<SRC>/BATCH_x, ARCHIVE/<SRC>/<YYYY-MM>/BATCH_<ID>_<TS>)`. If the destination exists → do **not** overwrite: rename the existing one to `BATCH_<ID>_<TS>.previous_<epoch>` first and log a WARNING.
- **In-flight detection:** every `BATCH_*` directory in `LOADING/<SRC>/`.
- **Startup checks:** the three zones share one filesystem (`st_dev`), and the loading root contains no regular files other than `.orchestrator.pid`.

**Implementation steps**
1. **Startup filesystem check** in `OrchestratorService.__init__`, after the zone paths are resolved:
   ```python
   devs = {os.stat(p).st_dev for p in (self.landing_zone, self.loading_zone, self.archive_zone)}
   if len(devs) != 1:
       raise ConfigurationError("LANDING_ZONE, LOADING_ZONE and ARCHIVE_ZONE must be on the same filesystem (atomic directory moves are required).")
   ```
2. **`prepare_batch_from_queued_item`**: replace lines 538–568 with:
   ```python
   batch_dir = os.path.join(self.loading_zone, os.path.basename(item.capsule_dir))
   if os.path.exists(batch_dir):
       raise BatchValidationError(f"Batch directory already in LOADING_ZONE: {batch_dir}")
   os.replace(item.capsule_dir, batch_dir)
   ctx_active_zone = batch_dir
   manifest_in_loading = os.path.join(batch_dir, item.manifest_basename)
   desc_in_loading = os.path.join(batch_dir, "batch_descriptor.json")
   raw_in_loading = os.path.join(batch_dir, "RAW") if os.path.isdir(os.path.join(batch_dir, "RAW")) else None
   ```
   Every later use of `self.loading_zone` as "where the batch files are" must become `ctx.active_zone` (the batch directory). `BatchContext.active_zone` already exists; set it to `batch_dir`. Audit each occurrence: `verify_descriptor_batch(self.loading_zone, …)` → `(batch_dir, …)`; `_sync_schema_for_entity` sample path; `process_entity_task` `loading_zone`; archive step; receipt update; `CURRENT_MANIFEST` env.
3. **Work area and file lists.** Add to `orchestrator_service.py`:
   ```python
   def prepare_entity_work_area(batch_dir: str, entity: str, payload_files: List[str]) -> str:
       """Creates BATCH_x/.work/<ENTITY>/ with plain data files and files.lst; returns the list path."""
       work_dir = os.path.join(batch_dir, ".work", entity)
       if os.path.isdir(work_dir):
           shutil.rmtree(work_dir)            # idempotent on retry
       os.makedirs(work_dir)
       plain_files: List[str] = []
       for fname in sorted(payload_files):
           src = os.path.join(batch_dir, fname)
           lower = fname.lower()
           if lower.endswith(".zip") or lower.endswith(".gz"):
               plain_files.extend(extract_archive_members(src, work_dir))      # F2.4
           else:
               dst = os.path.join(work_dir, fname)
               try:
                   os.link(src, dst)
               except OSError:
                   shutil.copy2(src, dst)
               plain_files.append(dst)
       plain_files.sort()
       list_path = os.path.join(work_dir, "files.lst")
       with open(list_path, "w", encoding="utf-8", newline="\n") as fh:
           fh.write("\n".join(plain_files) + "\n")
       return list_path
   ```
   Call it at the top of `process_entity_task` (which receives `batch_dir` via `orch_config["active_zone"]`, set in `prepare_batch_from_queued_item`). Replace everything between the `pending_tasks` lookup and the header-mode block (lines 142–178) with that call. `target_spec` becomes `list_path`.
4. **Worker.** `run_tpt_loader(entity, file_list_path, …)`: replace the `-f actual_file_path` pair in `cmd` with `-L file_list_path`. Delete the `/tmp` / `//` special cases (lines 63–66).
5. **Archive.** Replace lines 889–938 with:
   ```python
   batch_archive_dir = CapsulePathResolver.get_archive_capsule_dir(self.archive_zone, ctx.source, ctx.batch_id, ctx.clean_ts, ensure_exists=False)
   os.makedirs(os.path.dirname(batch_archive_dir), exist_ok=True)
   work_root = os.path.join(ctx.active_zone, ".work")
   if os.path.isdir(work_root):
       shutil.rmtree(work_root)
   if os.path.exists(batch_archive_dir):
       aside = f"{batch_archive_dir}.previous_{int(time.time())}"
       self.logger.warning(f"Archive capsule already exists; moving it aside to {aside}")
       os.replace(batch_archive_dir, aside)
   os.replace(ctx.active_zone, batch_archive_dir)
   ```
   The receipt update (lines 869–887) runs **before** this block, on `ctx.active_zone/RAW`.
6. **In-flight detection** (`check_inflight_batch`): return the list of `BATCH_*` directories in `self.loading_zone`, sorted by name (names are `BATCH_<TS>_<ID>`, so lexical order is chronological), each turned into a `BatchContext` by reading its `batch_descriptor.json` (mandatory; missing → `BatchValidationError`) and validating with `verify_descriptor_batch(batch_dir, descriptor, verify_checksum=False)`. Return type becomes `List[BatchContext]`; `run` iterates it before scanning the landing queue.
7. **Startup root check**: in `run`, after acquiring the lock, if `self.loading_zone` contains a regular file other than `.orchestrator.pid` → `BatchValidationError` listing the files. (A leftover from a pre-F2.2 crash must be cleaned by an operator; see runbook.)
8. **Capsule publish** (`capsule.py:446-449`): delete the `rmtree`; F2.1 defines the replacement.

**Acceptance criteria**
- [ ] After dequeue, `LANDING/<SRC>/BATCH_x` no longer exists and `LOADING/<SRC>/BATCH_x` contains exactly the files the capsule had.
- [ ] `grep -n "shutil.move\|rmtree" lib/orchestrator_service.py` shows `rmtree` only for `.work` and for `prepare_entity_work_area`, and no `shutil.move`.
- [ ] The loader command logged by the worker contains `-L …/BATCH_x/.work/<ENTITY>/files.lst` and no `-f`.
- [ ] A stray matching file placed in `LOADING/<SRC>/BATCH_x/` but not declared is **not** loaded (it is not in `files.lst`).
- [ ] Kill the orchestrator (`kill -9`) during TPT; restart → it finds `BATCH_x` in LOADING, re-runs pending tasks, archives. The payload files in the archive are byte-identical to the delivered ones.
- [ ] Kill the orchestrator between `rmtree(.work)` and `os.replace` → on restart the batch is found in LOADING with all tasks SUCCESS, the completeness barrier passes and the archive happens. (Verify by inserting a `time.sleep(30)` between the two calls in a throwaway branch.)
- [ ] Zones on different filesystems → `ConfigurationError` at startup.

**Tests to add**
- `TESTS/unit/test_batch_directory_lifecycle.py::test_dequeue_is_single_rename` (patch `os.replace`, assert called once with the right pair), `::test_work_area_and_file_list` (hard links or copies exist, `files.lst` sorted, absolute), `::test_archive_is_single_rename`, `::test_existing_archive_moved_aside`, `::test_inflight_sorted_oldest_first`, `::test_stray_root_file_blocks_run`, `::test_different_filesystem_rejected` (patch `os.stat`).

**Documentation impact:** orchestrator functional spec (zone lifecycle, in-flight marker), architecture spec (same-filesystem requirement), operations playbook (what to do with stray root files).

---

### F2.3 — The payload is never modified
Finding: I9  Severity: High
Files: `lib/orchestrator_service.py`

**Current behaviour**
- `strip_header_in_place` (lines 87–109) rewrites chunk 1 of a multi-chunk entity and writes a `.header_stripped` marker; the archive then contains a modified file.

**Target behaviour**
- Delete `strip_header_in_place` and every reference to `.header_stripped`. Header handling is done by TPT (`SkipRows`/`SkipRowsEveryFile`, F1.9) over the ordered `files.lst`.
- The header-mode block (lines 180–217) collapses to:
  ```python
  if header_mode == "none":
      skip_rows, skip_rows_every_file = 0, "N"
  elif header_mode == "every_file":
      skip_rows, skip_rows_every_file = entity_skip_rows, "Y"
  else:  # first_chunk_only
      skip_rows, skip_rows_every_file = entity_skip_rows, "N"
  ```
- The orchestrator never opens a payload file for writing. The only writes inside `BATCH_x` are under `.work/` and `RAW/RECEIPT_*.json`.

**Acceptance criteria**
- [ ] `grep -rn "header_stripped\|strip_header" PROCESSING_TOOLS TESTS` returns nothing.
- [ ] `md5sum` of each payload file after archiving equals the value in the standardized manifest (verify on DEV with a 3-part entity).

**Tests to add**
- `TESTS/unit/test_batch_directory_lifecycle.py::test_payload_untouched` — compute hashes before and after a mocked full run; equal.

---

### F2.4 — Safe archive extraction
Finding: I10  Severity: High
Files: `lib/orchestrator_service.py` (new function `extract_archive_members`)

**Current behaviour**
- Lines 143–175: members are extracted into the shared root; an existing file is reused without any check; name collisions are silently skipped.

**Target behaviour**
- Extraction goes to `<work_dir>/.extract_tmp/`, every member is verified (size equals `ZipInfo.file_size`; for gzip, decompression completes without error and the output is non-empty), then moved into `<work_dir>` with `os.replace`. `.extract_tmp` is deleted at the end and at the start (retry restarts from scratch).
- A member name that already exists in `<work_dir>` → `BatchValidationError` (two archives in one entity must not contain the same member name).
- Only members ending in `.csv` / `.pecsv` (case-insensitive) are extracted; directory entries are skipped; member paths are reduced to `basename` (keep the existing zip-slip protection).

**Implementation (normative)**
```python
def extract_archive_members(archive_path: str, work_dir: str) -> List[str]:
    tmp = os.path.join(work_dir, ".extract_tmp")
    if os.path.isdir(tmp):
        shutil.rmtree(tmp)
    os.makedirs(tmp)
    produced: List[str] = []
    lower = archive_path.lower()
    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(archive_path) as zf:
                for info in zf.infolist():
                    name = os.path.basename(info.filename)
                    if info.is_dir() or not name.lower().endswith((".csv", ".pecsv")):
                        continue
                    out_tmp = os.path.join(tmp, name)
                    with zf.open(info) as src, open(out_tmp, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1024 * 1024)
                    if os.path.getsize(out_tmp) != info.file_size:
                        raise BatchValidationError(f"Extracted size mismatch for {name} in {archive_path}")
                    produced.append(name)
        elif lower.endswith(".gz"):
            base = os.path.basename(archive_path)[:-3]
            if not base.lower().endswith((".csv", ".pecsv")):
                base += ".csv"
            out_tmp = os.path.join(tmp, base)
            with gzip.open(archive_path, "rb") as src, open(out_tmp, "wb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
            if os.path.getsize(out_tmp) == 0:
                raise BatchValidationError(f"Empty gzip payload: {archive_path}")
            produced.append(base)
        else:
            raise BatchValidationError(f"Unsupported archive: {archive_path}")
        final_paths = []
        for name in produced:
            dst = os.path.join(work_dir, name)
            if os.path.exists(dst):
                raise BatchValidationError(f"Duplicate member name '{name}' across archives of the same entity")
            os.replace(os.path.join(tmp, name), dst)
            final_paths.append(dst)
        return final_paths
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
```
`zipfile.BadZipFile`, `gzip.BadGzipFile`, `EOFError` and `OSError` raised inside must be caught in `prepare_entity_work_area` and re-raised as `BatchValidationError` with the archive path.

**Acceptance criteria**
- [ ] A zip truncated with `truncate -s 1000 x.zip` → `BatchValidationError`, no file left in `<work_dir>`.
- [ ] Two zips each containing `data.csv` → `BatchValidationError`.
- [ ] Re-running after a failure extracts from scratch (no `.extract_tmp` left over).

**Tests to add**
- `TESTS/unit/test_archive_extraction.py::test_zip_ok`, `::test_zip_truncated`, `::test_gz_ok`, `::test_gz_corrupt`, `::test_duplicate_member`, `::test_tmp_cleaned`.

---

### F2.1 — Duplicate deliveries are refused and quarantined
Finding: I6  Severity: Critical
Files: `COMMON/dataloader_core/capsule.py`, `COMMON/dataloader_core/intake/base_controller.py`

**Current behaviour**
- `capsule.py:447-449`: an existing `BATCH_<TS>_<ID>` in LANDING is deleted (`rmtree`) and replaced.

**Target behaviour**
- If the final capsule directory already exists in LANDING, **or** a directory with the same name exists in `LOADING_ZONE/<SRC>/`, **or** an archive capsule for the same `(source, batch_id, ts)` exists, the feeder does not publish. It moves the raw manifest and the declared files from DROP_ZONE to `DROP_ZONE/<SRC>/QUARANTINE/<YYYYMMDD_HHMMSS>_<batch_id>/`, writes `REASON.txt` there, logs an ERROR, and continues with the **next** candidate (a duplicate is not a reason to block newer data; it is not "older data failing").
- The staging directory (`.staging_BATCH_*`) is removed if it was created.

**Implementation steps**
1. `stage_and_publish_queue_capsule` gains a parameter `conflict_check_dirs: List[str]` (LOADING and ARCHIVE roots for the source). Before creating `staging_dir`:
   ```python
   conflicts = [final_dir] + [os.path.join(d, final_folder) for d in conflict_check_dirs]
   archive_dir = cls.get_archive_capsule_dir(archive_root, clean_src, clean_batch, clean_ts)   # pass archive_root separately
   conflicts.append(archive_dir)
   existing = [p for p in conflicts if os.path.exists(p)]
   if existing:
       raise BatchValidationError(f"Batch {clean_batch}@{clean_ts} already exists: {existing}")
   ```
   Delete lines 447–448 (`if os.path.exists(final_dir): shutil.rmtree(final_dir)`). Keep `os.replace(staging_dir, final_dir)`; if it raises `FileExistsError`/`OSError` because the target appeared in the meantime, remove `staging_dir` and raise `BatchValidationError`.
2. `BaseIntakeController.run` (lines 375–396): wrap the per-candidate body so that a `BatchValidationError` whose message starts with `"Batch "` and contains `"already exists"` triggers quarantine and `continue`; every other `BatchValidationError` keeps today's FAIL_STOP behaviour (return 1). Implement quarantine as `self.quarantine_candidate(candidate, reason)`:
   ```python
   q_dir = os.path.join(self.drop_zone, "QUARANTINE", f"{time.strftime('%Y%m%d_%H%M%S')}_{CapsulePathResolver.sanitize_token(candidate.batch_id)}")
   os.makedirs(q_dir)
   for fname in candidate.declared_files + ([os.path.basename(candidate.manifest_path)] if candidate.manifest_path else []):
       src = os.path.join(self.drop_zone, fname)
       if os.path.exists(src):
           shutil.move(src, os.path.join(q_dir, fname))
   with open(os.path.join(q_dir, "REASON.txt"), "w", encoding="utf-8") as fh:
       fh.write(reason + "\n")
   self.logger.error(f"Batch {candidate.batch_id} quarantined to {q_dir}: {reason}")
   ```
   The `QUARANTINE` directory must be ignored by the plugins' `discover_raw_batches` (they list files only, so a directory is already ignored; add an explicit `os.path.isfile` check in `BICCIntakePlugin` and `StandardManifestIntakePlugin` anyway).
3. Pass `conflict_check_dirs=[<loading_zone>/<SRC>]` and the archive root from the controller. The controller knows `orchestrator.landing_zone`; add `orchestrator.loading_zone` and `orchestrator.archive_zone` to the feeder config (`BICC_INTAKE_CONTROLLER/config.json` and template) with values `../../DATA/LOADING_ZONE` and `../../DATA/ARCHIVE_ZONE`.

**Acceptance criteria**
- [ ] `grep -n rmtree COMMON/dataloader_core/capsule.py` returns nothing.
- [ ] Publishing the same batch twice: the first capsule is untouched (same inode, same mtime), the second delivery is under `DROP_ZONE/<SRC>/QUARANTINE/…/` with `REASON.txt`, the feeder exits 0 and the orchestrator is still triggered.
- [ ] A capsule already in LOADING or ARCHIVE blocks publishing the same way.

**Tests to add**
- `TESTS/unit/test_core_manifest_and_capsule.py::test_publish_refuses_existing_capsule`, `::test_publish_refuses_inflight_capsule`, `::test_publish_refuses_archived_capsule`.
- `TESTS/unit/test_intake_service.py::test_duplicate_is_quarantined_and_run_continues`.

**Documentation impact:** intake controller functional spec §6 (add "Duplicate deliveries"), operations playbook (how to handle QUARANTINE).

---

### F2.7 — Deterministic recovery and orphan handling
Finding: I16  Severity: High
Files: `lib/orchestrator_service.py`, `COMMON/dataloader_core/intake/base_controller.py`

**Current behaviour**
- Recovery takes `capsule_dirs[0]` from an unordered `os.listdir`; recovery validation allows orphan files; `.staging_BATCH_*` directories are never looked at.

**Target behaviour**
- Recovery processes **all** `BATCH_*` directories in LOADING, oldest first (name order), **before** touching the landing queue (F2.2 step 6 implements the listing).
- Recovery validation uses the same `verify_descriptor_batch` as normal processing (orphan check included — see F2.5 step 4).
- At feeder start-up, every `.staging_BATCH_*` directory in `LANDING/<SRC>/` is moved to `LANDING/<SRC>/QUARANTINE/<name>_<epoch>/` with an ERROR log line stating that the payload inside must be re-delivered or restored by an operator. The feeder then continues normally.

**Implementation steps**
1. `BaseIntakeController.run`, immediately after acquiring the lock: list `LANDING/<SRC>/.staging_BATCH_*`; for each, `os.replace` into `LANDING/<SRC>/QUARANTINE/` (create it). Log with `self.logger.error`.
2. `scan_landing_queue` must ignore the `QUARANTINE` directory (it does not start with `BATCH_`, so it is already ignored; add a test).
3. Recovery ordering: covered by F2.2 step 6; add the test here.

**Acceptance criteria**
- [ ] Two in-flight directories `BATCH_20261016_100200_9003` and `BATCH_20261016_100100_9002` → 9002 processed first.
- [ ] A `.staging_BATCH_…` left in LANDING is in `QUARANTINE/` after the next feeder run, with its contents intact.

**Tests to add**
- `TESTS/unit/test_recovery_ordering.py::test_inflight_processed_oldest_first`, `::test_staging_dir_quarantined`.

**Documentation impact:** operations playbook (QUARANTINE handling).

---

### F2.6 — Deterministic batch identity and timestamps
Finding: I15, I20  Severity: High
Files: `COMMON/dataloader_core/manifest.py`, `COMMON/dataloader_core/intake/plugin.py`, `COMMON/dataloader_core/capsule.py`

**Current behaviour**
- `manifest.py`: four of five parsing paths stamp `datetime.now()` as the extract timestamp (lines 98–103, 155–159, 188–195, 203–210, 214–223). `capsule.py:197` does the same.
- `plugin.py:119-121`: the batch ID is the `-batch<id>-` token of the **first** declared file. Different files in one BICC manifest can carry different tokens.

**Target behaviour**
- No code path invents a timestamp. If a timestamp cannot be determined from the manifest name or the payload names, the candidate is a `BatchValidationError`.
- For BICC: `extract_timestamp_raw` = the `YYYYMMDD_HHMMSS` token of the manifest name (`MANIFEST-<TS>.MF`), else the `-<YYYYMMDD_HHMMSS>.` token shared by the payload file names (all files must agree), else error.
- For BICC: `batch_id` = the manifest timestamp token when the manifest name has one (it uniquely identifies one BICC run), else the common `-batch<id>-` token when all declared files share it, else error. Each file's own `-batch<id>-` token is recorded in `batch_descriptor.json` as `entities[<E>].files[i].source_batch_token` so nothing is lost.
- For standard manifests (`MANIFEST_<SRC>_<TS>_<ID>.MF`): source, timestamp and batch ID come from the name; nothing else is accepted (`strict=True` becomes the only mode).
- `parse_manifest_filename` patterns 3, 4 and 5 (legacy `MANIFEST-batch<ID>-.MF`, single token, generic fallback) are deleted.
- `CapsulePathResolver.normalize_iso_timestamp`: unparseable input → `ValueError`.

**Implementation steps**
1. `manifest.py`: delete `_raw_ts_to_iso_and_epoch`'s `except` fallback (raise `ValueError`); delete patterns 3–5 and the corresponding blocks; make the function raise `ValueError` when nothing matches. Remove the `strict` parameter (always strict). Keep `custom_regex` support.
2. `plugin.py` `BICCIntakePlugin.discover_raw_batches`: after reading `declared_files`:
   ```python
   ts_tokens = {m.group(1) for f in declared_files if (m := re.search(r"-(\d{8}_\d{6})\.", f))}
   batch_tokens = [extract_batch_id_from_filenames([f]) for f in declared_files]
   if meta.extract_timestamp_raw:                     # MANIFEST-<TS>.MF
       extract_ts, b_id = meta.extract_timestamp_raw, meta.extract_timestamp_raw
   elif len(ts_tokens) == 1 and len(set(batch_tokens)) == 1 and batch_tokens[0]:
       extract_ts, b_id = ts_tokens.pop(), batch_tokens[0]
   else:
       logger.error(f"Cannot determine a unique extract timestamp / batch id for manifest '{f}': ts_tokens={ts_tokens}, batch_tokens={set(batch_tokens)}")
       raise BatchValidationError(f"Manifest '{f}': ambiguous or missing timestamp/batch tokens")
   ```
   Store `batch_tokens` in `candidate.metadata["file_batch_tokens"]` (a dict filename → token) and copy them into the descriptor in `BaseIntakeController.stage_and_publish_batch` (`file_entry["source_batch_token"]`). Delete the `mtime` fallback (lines 123–127). Apply the same change to `StandardManifestIntakePlugin` (where the name always carries everything) and `ManifestlessDropIntakePlugin` (keep mtime there — it is the only information available — but write `metadata["timestamp_source"] = "mtime"` and log a WARNING per batch).
3. `capsule.py:195-197`: `raise ValueError(f"Unparseable timestamp: {ts!r}")`.
4. `pre_checks.sh` fabrication is handled by Phase 1 F1.11.

**Decision D4 (technical lead):** confirm with a real BICC manifest whether all files of one extract share one `-batch<id>-` token. If they do, change the rule to "batch_id = the shared token" and keep the manifest timestamp as `extract_timestamp_raw`. Record in `DECISIONS.md`. The code above works in both cases; only the preferred source of `b_id` changes.

**Acceptance criteria**
- [ ] `grep -n "datetime.now" COMMON/dataloader_core/manifest.py COMMON/dataloader_core/capsule.py COMMON/dataloader_core/intake/plugin.py` shows only the `ManifestlessDropIntakePlugin` use and the `intake_timestamp` write in `capsule.py`.
- [ ] `MANIFEST-20261005_132810.MF` listing files with two different batch tokens → candidate with `batch_id = "20261005_132810"`, both tokens in the descriptor.
- [ ] `MANIFEST.MF` (no tokens anywhere) → `BatchValidationError`.
- [ ] `MANIFEST_ORACLE_FUSION_20261016_100000_9001.MF` → unchanged behaviour.

**Tests to add**
- `TESTS/unit/test_core_manifest_and_capsule.py::test_no_timestamp_fabrication` (parametrised over the deleted patterns → `ValueError`), `::test_bicc_identity_from_manifest_timestamp`, `::test_bicc_identity_from_payload_tokens`, `::test_bicc_ambiguous_raises`, `::test_normalize_iso_timestamp_raises`.

**Documentation impact:** intake functional spec (batch identity rules), onboarding guide.

---

### F2.5 — Checksum verification end to end
Finding: I5, D1  Severity: Critical
Files: `COMMON/dataloader_core/manifest.py`, `COMMON/dataloader_core/intake/base_controller.py`, `lib/orchestrator_service.py`, `lib/sensor.py`, `DATA_INGESTION_ORCHESTRATOR/config.json` + template

**Current behaviour**
- Intake computes MD5s but never compares them with anything delivered.
- The orchestrator's default path verifies sizes only (`verify_checksum_on_queued_capsule` defaults to `False`, `orchestrator_service.py:579`).
- `verify_descriptor_batch` performs no orphan check.
- `read_manifest_entries` treats field 2 as the checksum whatever it is.

**Target behaviour**
- `ManifestEntry` gains `ucm_doc_id: Optional[str]`. Parsing of `;`-separated lines: 2 fields → `(filename, X)` where `X` is the checksum if it is 32 hex characters (MD5) or 64 (SHA-256), otherwise `ucm_doc_id`; 3 fields → `(filename, ucm_doc_id, checksum)`. `,`-separated standardized manifests keep `(filename, checksum)`.
- Intake verifies every declared checksum that exists (`BatchValidationError` on mismatch). If no checksum is declared (D1 says BICC has none), intake logs one INFO line per batch: "No upstream checksum declared; integrity from this point is guaranteed by the intake MD5 only."
- `verify_checksum_on_queued_capsule` defaults to **`true`** and is set to `true` in both config files. The fast path (sizes only) exists only when explicitly configured `false`.
- `verify_descriptor_batch` enforces the orphan rule: any regular file in `batch_dir` that is not a declared payload file, the manifest, `batch_descriptor.json`, or under `RAW/` or `.work/` → `ValueError("Boundary violation (OPS-01) …")`.

**Implementation steps**
1. `manifest.py`: add `ucm_doc_id` to `ManifestEntry`; implement the field rules in `read_manifest_entries` (`_HEX32 = re.compile(r"^[0-9a-f]{32}$", re.I)`, `_HEX64` likewise). The `"=" in line_str` skip rule becomes `re.match(r"^[A-Z_]+=", line_str)` (only `KEY=VALUE` metadata lines).
2. `base_controller.py` `stage_and_publish_batch`: keep a dict `declared_checksums = {e.filename: e.checksum for e in entries if e.checksum}` on the candidate (`candidate.metadata["declared_checksums"]`, filled by the plugins). In the MD5 loop (lines 247–264): if `fname in declared_checksums` and `md5 != declared_checksums[fname].lower()` → `BatchValidationError(f"Checksum mismatch for {fname}: declared {…}, computed {…}")`. Record `"upstream_checksum_verified": bool` per file in the receipt payload.
3. `orchestrator_service.py:579`: default `True`; config files: `"verify_checksum_on_queued_capsule": true`.
4. `sensor.py` `verify_descriptor_batch`: add the orphan check described above, after the per-file loop.
5. Unit tests that use `checksum=dummy` must be changed to real MD5s of the fixture content (`hashlib.md5(open(p,'rb').read()).hexdigest()`).

**Acceptance criteria**
- [ ] A BICC line `file.zip;123456;<md5>` → `ManifestEntry(filename, checksum=<md5>, ucm_doc_id="123456")`; `file.zip;123456` → `checksum=None, ucm_doc_id="123456"`; `file.zip;<md5>` → `checksum=<md5>`.
- [ ] A declared MD5 that does not match → feeder FAIL_STOP with "Checksum mismatch".
- [ ] A payload byte changed between LANDING and LOADING → orchestrator `BatchValidationError` (default config).
- [ ] An undeclared `extra.csv` inside the batch directory → `Boundary violation`.
- [ ] `git grep "dummy" TESTS/unit` returns nothing.

**Tests to add**
- `TESTS/unit/test_core_manifest_and_capsule.py::test_manifest_field_rules` (the three line shapes), `::test_intake_verifies_declared_checksum`.
- `TESTS/unit/test_multi_batch_queue_sensor.py::test_descriptor_batch_orphan_file_rejected`, `::test_descriptor_batch_checksum_mismatch`.

**Documentation impact:** orchestrator functional spec (integrity section — remove "fast path O(1)" wording unless `false` is configured), intake spec.

---

### F2.11 — State tables keep history
Finding: I18  Severity: Medium
Files: `ddl_technical_tables.sql`, `lib/db_state.py`, `lib/orchestrator_service.py`, `TESTS/verify_database_and_storage.py`
Depends on: Phase 1 F1.4 (`TPT_JOB_NAME`).

**Current behaviour**
- `BATCH_RUNS` has one row per `(BATCH_ID, SOURCE)`; a re-run overwrites it. `BATCH_TASKS` has one row per file, but every update is per entity. A re-run of a SUCCESS batch deletes its task rows.

**Target behaviour**
- `BATCH_RUNS`: one row per **attempt**. New columns `RUN_ATTEMPT INTEGER NOT NULL`, `PROCESS_HOST VARCHAR(255)`. Primary index `(BATCH_ID, SOURCE)` stays (non-unique). Rows are never updated except `STATUS`/`END_TIME` of the current attempt; never deleted.
- `BATCH_TASKS`: one row per **(attempt, entity)**. Columns: `BATCH_ID, SOURCE, RUN_ATTEMPT, ENTITY_NAME, FILE_COUNT INTEGER, STATUS, START_TIME, END_TIME, RETRY_COUNT, TPT_JOB_NAME, ERROR_MESSAGE`. `FILE_NAME` is dropped; the file names live in the descriptor.
- "Current attempt" = `MAX(RUN_ATTEMPT)` for the batch and source.

**Implementation steps**
1. Write `ddl_technical_tables.sql` version 3.0 with the two tables above, plus a migration block (commented) for existing environments:
   ```sql
   -- ALTER TABLE <TECH_DB>.BATCH_RUNS  ADD RUN_ATTEMPT INTEGER DEFAULT 1 NOT NULL;
   -- ALTER TABLE <TECH_DB>.BATCH_RUNS  ADD PROCESS_HOST VARCHAR(255) CHARACTER SET UNICODE NOT CASESPECIFIC;
   -- CREATE TABLE <TECH_DB>.BATCH_TASKS_V3 (...);
   -- INSERT INTO <TECH_DB>.BATCH_TASKS_V3 SELECT BATCH_ID, SOURCE, 1, ENTITY_NAME, COUNT(*), MIN(STATUS), MIN(START_TIME), MAX(END_TIME), MAX(RETRY_COUNT), MIN(TPT_JOB_NAME), MIN(ERROR_MESSAGE) FROM <TECH_DB>.BATCH_TASKS GROUP BY 1,2,3,4;
   -- RENAME TABLE <TECH_DB>.BATCH_TASKS TO <TECH_DB>.BATCH_TASKS_V2_BACKUP; RENAME TABLE <TECH_DB>.BATCH_TASKS_V3 TO <TECH_DB>.BATCH_TASKS;
   ```
   Run the migration on DEV before merging.
2. `db_state.py`:
   - `initialize_batch(batch_id, source, extract_timestamp, entity_file_counts: Dict[str, int])`:
     `attempt = (SELECT COALESCE(MAX(RUN_ATTEMPT),0)+1 …)`; `INSERT` the run row with `RUN_ATTEMPT=attempt, PROCESS_PID, PROCESS_HOST=socket.gethostname()`; `INSERT` one task row per entity with `STATUS='PENDING'`. **If the previous attempt is `RUNNING` with a live PID on this host → raise `DataLoaderError`** (another process owns it; the lock should have prevented this). If the previous attempt has tasks in `SUCCESS`, copy them as `SUCCESS` into the new attempt (so a recovery does not reload entities that already loaded). Return `attempt`.
   - Every other method takes `run_attempt` (store it on the `TeradataStateDB` instance after `initialize_batch` to avoid threading it through every call: `self.current_attempt[(batch_id, source)] = attempt`).
   - Remove the `file_name` parameter from `update_task_start`/`update_task_end`; add `tpt_job_name` to `update_task_start` (F1.4).
   - `get_pending_tasks` returns `(ENTITY_NAME, RETRY_COUNT)` for the current attempt.
   - `get_batch_summary(batch_id, expected_entity_count, source)` compares the count of `SUCCESS` tasks of the current attempt with the number of entities.
   - `finish_batch`, `mark_batch_failed`: `WHERE … AND RUN_ATTEMPT = <current>`.
   - `get_active_batch_run(source)`: latest attempt with `STATUS='RUNNING'` → include `process_host`.
3. `orchestrator_service.py`: `execute_entity_tasks` builds `entity_file_counts` instead of `tasks_list`; `run_completeness_barrier_and_archive` passes `len(ctx.entities_workload)`.
4. `TESTS/verify_database_and_storage.py`: query the current attempt; assert `PROCESS_HOST` is not null.

**Acceptance criteria**
- [ ] Running the same batch twice produces two `BATCH_RUNS` rows (`RUN_ATTEMPT` 1 and 2) and the attempt-1 rows are unchanged.
- [ ] `grep -n "DELETE FROM" lib/db_state.py` returns nothing.
- [ ] A recovery run copies previously `SUCCESS` entities and only re-runs the others.

**Tests to add**
- `TESTS/unit/test_db_state_history.py::test_second_attempt_inserts_not_updates`, `::test_success_entities_carried_over`, `::test_no_delete_statements` (inspect executed SQL).

**Documentation impact:** technical manual (table definitions), operations playbook (how to read attempts).

---

### F2.8 — Pre-flight errors stop the run; host-aware liveness; state reconciliation
Finding: I17, A6, A3  Severity: High
Files: `lib/orchestrator_service.py`, `COMMON/dataloader_core/locking.py`

**Current behaviour**
- `wait_or_recover_active_db_batch` (lines 383–417) catches every non-domain exception and logs at DEBUG.
- PID liveness is host-local.

**Target behaviour**
- Database errors during pre-flight (`teradatasql.OperationalError`, `teradatasql.DatabaseError`, connection failures) are re-raised as `DataLoaderError` → exit 1 with a CRITICAL log. The orchestrator never starts a batch when it cannot read its own state.
- Liveness: a `RUNNING` attempt whose `PROCESS_HOST` differs from `socket.gethostname()` is **never** reclassified by this process; the orchestrator logs CRITICAL and exits 1 (an operator must decide). Same-host dead PID → `FAILED` as today.
- Reconciliation at start-up, after the lock: for every `BATCH_*` directory in LOADING, look up the latest attempt: `SUCCESS` → all entities are already loaded; run the completeness barrier and archive only; `RUNNING` with dead same-host PID or `FAILED` → recovery (F2.2 step 6); no row → treat as never started.
- `ProcessLock` writes `"<hostname>:<pid>"` into the lock file; `read_pid_file` parses both the old and the new format; liveness is checked only when the host matches, otherwise the lock is considered held (wait until timeout).

**Implementation steps**
1. `wait_or_recover_active_db_batch`: replace the generic `except Exception` with `except Exception as exc: raise DataLoaderError(f"Pre-flight state check failed: {exc}") from exc`. Add the host comparison using `active_db_batch["process_host"]` (F2.11).
2. `locking.py`: `os.write(fd, f"{socket.gethostname()}:{os.getpid()}\n")`; `read_pid_file` returns `(host, pid)`; update `wait_for_pid_completion` and `ProcessLock.acquire/release` accordingly.
3. Reconciliation: implement in `check_inflight_batch` by consulting `db.get_latest_attempt(batch_id, source)` (add this method to `db_state.py`) and setting `ctx.already_loaded = True` when `SUCCESS`; `run` skips `execute_entity_tasks` for such contexts.

**Acceptance criteria**
- [ ] With Teradata unreachable, `orchestrator.py` exits 1 and logs CRITICAL; nothing is moved.
- [ ] A `RUNNING` row with `PROCESS_HOST='otherhost'` → exit 1 with CRITICAL, status unchanged.
- [ ] Lock file content matches `^[^:]+:\d+$`; an old-format file containing only a PID is still parsed.

**Tests to add**
- `TESTS/unit/test_orchestrator_preflight.py::test_db_error_is_fatal`, `::test_foreign_host_running_is_fatal`, `::test_success_inflight_only_archives`.
- `TESTS/unit/test_core_locking.py::test_lock_file_has_host_and_pid`, `::test_legacy_pid_only_format`.

---

### F2.9 — Post-tasks scoped, bounded and isolated per source
Finding: I12, A7  Severity: High
Files: `lib/post_tasks.py`, `lib/orchestrator_service.py`, `DATA_INGESTION_ORCHESTRATOR/config.json` + template

**Current behaviour**
- `dbt run`/`dbt test` run on the whole project; no timeout on any task; output buffered; a failing task fails the batch and, through FAIL_STOP, the whole queue and (in `--all-sources`) all other sources.
- With `--skip-post-tasks`, draining several queued batches of one source in `replace` mode leaves only the last batch in staging.

**Target behaviour**
- Every task has `timeout_seconds` (default 3600); a `dbt` task **must** have `select` (a dbt selector string); missing → `ConfigurationError` at start-up (validate all post-tasks in `OrchestratorService.__init__`, before any batch is touched).
- Task output is streamed to `<batch_log_dir>/POST_TASKS/<n>_<type>.log` and the last 50 lines are logged on failure.
- Multi-source sweep: a failure in one source halts **that source's queue only**; the sweep continues with the other sources and exits 1 at the end if any source failed.
- `--skip-post-tasks` with more than one queued batch for the source and any entity in `replace` mode: process only the **first** batch, log a WARNING naming the batches left queued, exit 0. New config key `orchestration.allow_replace_drain_without_post_tasks` (default `false`) disables this protection.

**Implementation steps**
1. `post_tasks.py`: add `validate_post_tasks(tasks) -> None` (type in `{dbt, shell, python}`; `dbt` requires `project_dir`, `profiles_dir`, `select`; `timeout_seconds` integer > 0 if present). Replace the three `subprocess.run(..., capture_output=True)` calls with a helper that opens the log file, uses `start_new_session=True`, `proc.wait(timeout)`, and kills the process group on timeout (same shape as Phase 1 F1.10 `_run`). `dbt` commands: `["dbt","run","--select",select,"--project-dir",…,"--profiles-dir",…]` and the same for `dbt test`.
2. `orchestrator_service.py`: call `validate_post_tasks` on config and file tasks in `__init__`/`run` before the lock; pass `batch_log_dir` to `run_post_tasks`.
3. `run_all_sources`: collect `rc` per source; `continue` instead of `return rc`; final `return 1 if any(rc != 0) else 0`; log a summary table.
4. `run`: before the queue loop, if `self.skip_post_tasks and len(queued_items) > 1 and not allow_drain`: check whether any entity in the first item's descriptor has `load_mode == "replace"`; if yes, truncate `queued_items` to the first item and log the WARNING.

**Acceptance criteria**
- [ ] A `dbt` task without `select` → `ConfigurationError` before any batch moves.
- [ ] A shell task `sleep 100` with `timeout_seconds: 2` → batch FAILED within ~35 s, no `sleep` left running.
- [ ] `--all-sources` with source A failing and source B fine → B is processed, exit code 1, summary logged.
- [ ] `--skip-post-tasks` with 3 queued replace-mode batches → one processed, two left queued, WARNING logged, exit 0.

**Tests to add**
- `TESTS/unit/test_post_tasks.py::test_dbt_requires_select`, `::test_timeout_kills_group`, `::test_output_streamed_to_file`.
- `TESTS/unit/test_orchestrator_sweep.py::test_sweep_continues_after_source_failure`, `::test_skip_post_tasks_drain_protection`.

**Documentation impact:** orchestrator user guide (post-task configuration, new key), operations playbook.

---

### F2.12 — Connection pool health check
Finding: Q8  Severity: Medium
Files: `COMMON/dataloader_core/db.py`

**Target behaviour**
- A connection borrowed from the idle pool is validated with `SELECT 1` before being handed out; on failure it is closed, removed from `_all_connections`, and a new one is created.
- A connection returned after an exception inside the `with` block is closed and discarded, not re-queued.

**Implementation steps**
1. In `acquire_connection`, after `conn = self._idle_pool.get_nowait()`:
   ```python
   if not self._is_healthy(conn):
       self._discard(conn); conn = None
   ```
   with `_is_healthy` executing `SELECT 1` on a cursor inside `try/except Exception: return False`, and `_discard` closing and removing from `_all_connections` under `self._lock`.
2. Wrap `yield conn` in `try/except BaseException: self._discard(conn); raise` so a failing borrower's connection is not reused; the `finally` must then skip `put_nowait` for discarded connections (track with a local flag).

**Acceptance criteria**
- [ ] A connection whose `cursor().execute` raises is not returned by the next `acquire_connection`.
- [ ] `total_connections_created` increases by one after a discard.

**Tests to add**
- `TESTS/unit/test_core_db_pool.py::test_unhealthy_connection_replaced`, `::test_connection_discarded_after_borrower_error`.

---

## Phase 2 exit checklist (technical lead)

- [x] All 12 items merged with their tests; Phase 1 fully merged before F2.2 starts.
- [x] On DEV: deliver three batches, `kill -9` the orchestrator during the second one's TPT, restart → batches finish in order, archives contain byte-identical payloads, `BATCH_RUNS` shows attempt 2 for the killed batch.
- [x] On DEV: deliver the same batch twice → second copy in `QUARANTINE`, first copy loaded normally.
- [x] `DECISIONS.md` contains D1 and D4 (both settled).
- [x] Documentation listed under "Documentation impact" updated; operations playbook has a "QUARANTINE" section and a "stray files in LOADING_ZONE root" section.
