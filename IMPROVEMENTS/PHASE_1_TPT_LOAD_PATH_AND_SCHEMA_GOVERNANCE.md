# Phase 1 — TPT Load Path & Schema Governance

**Scope:** `PROCESSING_TOOLS/TPT_LOADER/**`, `PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/lib/tpt_worker.py`, `PROCESSING_TOOLS/DATA_INGESTION_ORCHESTRATOR/lib/schema_guard.py`, `PROCESSING_TOOLS/COMMON/dataloader_core/mapping.py`, `PROCESSING_TOOLS/COMMON/dataloader_core/db.py`.
**Goal:** between "a validated file is ready in the loading zone" and "rows are in Teradata", nothing is silently accepted, silently padded, silently dropped or silently fabricated.
**Read first:** `IMPROVEMENTS/README.md` sections 2 and 3.

Items in this phase:

| ID | Title | Findings | Severity |
|---|---|---|---|
| F1.1 | Strict row rejection with an explicit payload schema | I1 | Critical |
| F1.2 | Populate audit columns during the load, not after | I1, I21 | Critical |
| F1.3 | Measure `has_meta` from the table | I3 | Critical |
| F1.4 | Unlock by exact job name; never report an unlock as a load | I4 | Critical |
| F1.5 | The alignment check is never skipped | I13, Q11 | High |
| F1.6 | Schema evolution without `DROP TABLE` | I2 | Critical |
| F1.7 | Declared row-size guard | Review §7 | High |
| F1.8 | Strict mapping validation and anchored signatures | I14, I7 (part) | High |
| F1.9 | Explicit file lists and deterministic header handling | I7 (part), I9 (part), §6.2 | High |
| F1.10 | Process-group termination and precise lock detection | I11 | High |
| F1.11 | No fabricated batch metadata in the loader | I15 (loader part) | High |
| F1.12 | Environment construction for the loader | Q12 | Low |

Recommended order inside the phase: F1.3 → F1.1 → F1.2 → F1.5 → F1.9 → F1.4 → F1.10 → F1.6 → F1.7 → F1.8 → F1.11 → F1.12. F1.1, F1.2 and F1.9 all change the generated TPT job; do them one after the other, on the same base.

---

## Background you need before touching the TPT loader

Read these once, fully, before starting.

1. **How the loader works today.** `load_csv_generic.sh` sources eight files from `lib/` in order: `env_and_helpers.sh` → `parse_args.sh` → `pre_checks.sh` → `bteq_check.sh` → `generate_jobvars.sh` → `run_tpt.sh` → `update_metadata.sh` → `archive_files.sh`. Each file runs top-to-bottom and uses variables set by the previous one. There is no function structure; `die <rc> <msg>` exits the whole script.
2. **How the TPT job is built today.** `lib/load_csv_generic.tpt` is a *static* script. Its schema is produced at run time by Teradata: `DEFINE SCHEMA TGT_SCHEMA FROM TABLE DELIMITED @TargetTable;` (line 42) asks the database for the column list of the target table and declares every column as `VARCHAR`. The `INSERT` is also generated: `APPLY $INSERT @TargetTable` (line 189).
3. **The core problem (I1).** Because the schema is generated from the *table*, it contains the two audit columns `INFA_BATCH_ID` and `INFA_LAST_REPLICATED`. The *file* does not contain them. So every file row is 2 fields short. The script compensates with `AcceptMissingColumns = 'Y'` (line 92), which tells TPT to pad short rows with NULLs. That also pads **genuinely broken rows** (a truncated line, a broken quote). `generate_jobvars.sh` lines 19–24 then disable `RecordErrorFile` so that the 2-field padding does not flood the disk — which also hides every real reject.
4. **The fix in one sentence.** The loader must build the schema itself from `DBC.ColumnsV`, **excluding** the audit columns, set `AcceptMissingColumns = 'N'`, always keep `RecordErrorFile`, and write the audit values as part of the `INSERT`.
5. **Generated job script.** After this phase the static `lib/load_csv_generic.tpt` is replaced by a template `lib/load_csv_generic.tpt.template` with placeholders, and each run writes its own `${RUN_DIR}/job.tpt`. This is what `tbuild -f` receives. Keep the generated file; the unlock/restart logic (F1.4) needs it.

---

### F1.1 — Strict row rejection with an explicit payload schema
Finding: I1  Severity: Critical
Files: `TPT_LOADER/lib/bteq_check.sh`, `TPT_LOADER/lib/generate_jobvars.sh`, `TPT_LOADER/lib/load_csv_generic.tpt` → `TPT_LOADER/lib/load_csv_generic.tpt.template`, new `TPT_LOADER/lib/generate_tpt_job.sh`, `TPT_LOADER/load_csv_generic.sh`, `TPT_LOADER/lib/run_tpt.sh`

**Current behaviour**
- `load_csv_generic.tpt:42` — schema generated from the whole table (includes audit columns).
- `load_csv_generic.tpt:92` — `AcceptMissingColumns = 'Y'` while the comment on lines 89–90 says the opposite.
- `generate_jobvars.sh:19-24` — `RecordErrorFile` set to empty string when `HAS_META=2`.
- `bteq_check.sh:23-27` — the pre-check already queries `DBC.ColumnsV` for column names, but only names, and only when `-C` is not given.

**Target behaviour**
- The loader always retrieves the full column definition of the target table (name, type, length, character set, decimal digits), in physical order, excluding `INFA_BATCH_ID` and `INFA_LAST_REPLICATED`.
- From that list it generates an explicit `DEFINE SCHEMA PAYLOAD_SCHEMA ( ... )` whose column count equals the number of fields in the file.
- `AcceptMissingColumns = 'N'`, `AcceptExcessColumns = 'N'`, `TruncateColumnData = 'N'`.
- `RecordErrorFileName` is **always** set to `${RUN_DIR}/rejected_rows.txt`.
- A row with the wrong number of fields is written to `rejected_rows.txt` and counted against `ErrorLimit`. With the default `ErrorLimit = 1` the job fails.

**Implementation steps**

1. **Make the column metadata query unconditional.** In `bteq_check.sh`, the `if [ "${SKIP_BTEQ_CHECK}" = "Y" ]` branch currently skips the whole BTEQ call. Restructure so that the BTEQ call *always* runs and only the *comparison* is skipped when `-C` is given. Replace the `COLNAME=` query with one that returns one line per column:

   ```sql
   SELECT 'COLDEF=' || TRIM(ColumnName) || '|' || TRIM(ColumnType) || '|'
          || TRIM(COALESCE(ColumnLength, 0)) || '|' || TRIM(COALESCE(CharType, 0)) || '|'
          || TRIM(COALESCE(DecimalTotalDigits, 0)) || '|' || TRIM(COALESCE(DecimalFractionalDigits, 0)) (TITLE '')
   FROM DBC.ColumnsV
   WHERE DatabaseName = '${TARGET_DB}' AND TableName = '${TARGET_TABLE}'
     AND ColumnName NOT IN ('INFA_BATCH_ID', 'INFA_LAST_REPLICATED')
   ORDER BY ColumnId;
   ```
   Keep the existing `NBCOL=` and `HAS_META=` queries. Write every `COLDEF=` line, without the `COLDEF=` prefix, to `${RUN_DIR}/columns.txt` (create `RUN_DIR` before the BTEQ call; today it is created in `generate_jobvars.sh` — move the `RUN_TS`/`JOB_NAME`/`RUN_DIR`/`mkdir` block to the top of `bteq_check.sh`).

2. **Create `lib/generate_tpt_job.sh`.** It is sourced after `generate_jobvars.sh` and before `run_tpt.sh`. It reads `${RUN_DIR}/columns.txt` and writes `${RUN_DIR}/job.tpt` from the template. Schema width rules (UTF8 session = 3 bytes per character):

   | `ColumnType` | Schema declaration | Width rule |
   |---|---|---|
   | `CV`, `CF` | `VARCHAR(w)` | `chars = ColumnLength / 2` if `CharType = 2` (UNICODE), else `chars = ColumnLength`; `w = chars * 3` |
   | `DA` | `VARCHAR(10)` | fixed |
   | `TS` | `VARCHAR(32)` | fixed |
   | `SZ` | `VARCHAR(40)` | fixed |
   | `AT`, `TZ` | `VARCHAR(20)` | fixed |
   | `I`, `I1`, `I2`, `I8` | `VARCHAR(21)` | fixed |
   | `D`, `N` | `VARCHAR(w)` | `w = DecimalTotalDigits + 3` (sign, point, safety) |
   | `F` | `VARCHAR(40)` | fixed |
   | anything else | **fail**: `die 1 "Unsupported column type <type> on <column>; add a rule to generate_tpt_job.sh"` | |

   Generation (normative):
   ```bash
   # lib/generate_tpt_job.sh
   TEMPLATE="${LIB_DIR}/load_csv_generic.tpt.template"
   JOB_TPT="${RUN_DIR}/job.tpt"
   [ -f "${TEMPLATE}" ] || die 1 "TPT template not found: ${TEMPLATE}"
   [ -s "${RUN_DIR}/columns.txt" ] || die 1 "No column metadata found in ${RUN_DIR}/columns.txt"

   SCHEMA_LINES=""
   INSERT_COLS=""
   INSERT_VALS=""
   while IFS='|' read -r c_name c_type c_len c_chartype c_digits c_frac; do
       case "${c_type}" in
           CV|CF) chars=$(( c_chartype == 2 ? c_len / 2 : c_len )); width=$(( chars * 3 )) ;;
           DA)    width=10 ;;
           TS)    width=32 ;;
           SZ)    width=40 ;;
           AT|TZ) width=20 ;;
           I|I1|I2|I8) width=21 ;;
           D|N)   width=$(( c_digits + 3 )) ;;
           F)     width=40 ;;
           *)     die 1 "Unsupported column type '${c_type}' on column '${c_name}' in ${FQ_TABLE}; add a rule to generate_tpt_job.sh" ;;
       esac
       SCHEMA_LINES+="        \"${c_name}\" VARCHAR(${width}),"$'\n'
       INSERT_COLS+="\"${c_name}\", "
       INSERT_VALS+=":\"${c_name}\", "
   done < "${RUN_DIR}/columns.txt"
   SCHEMA_LINES="${SCHEMA_LINES%,$'\n'}"      # remove trailing comma + newline
   INSERT_COLS="${INSERT_COLS%, }"
   INSERT_VALS="${INSERT_VALS%, }"
   PAYLOAD_COL_COUNT=$(wc -l < "${RUN_DIR}/columns.txt")
   ```
   The `INSERT_*` variables are completed in F1.2. Write the template with the two placeholders replaced. Do **not** use `sed` for the replacement (the schema contains `/` and `&` characters); use a small Python call or bash parameter substitution on the whole file content:
   ```bash
   TEMPLATE_CONTENT="$(cat "${TEMPLATE}")"
   JOB_CONTENT="${TEMPLATE_CONTENT//__PAYLOAD_SCHEMA__/${SCHEMA_LINES}}"
   JOB_CONTENT="${JOB_CONTENT//__INSERT_STATEMENT__/${INSERT_STATEMENT}}"
   printf '%s\n' "${JOB_CONTENT}" > "${JOB_TPT}" || die 1 "Cannot write ${JOB_TPT}"
   ```

3. **Convert the script into a template.** Rename `lib/load_csv_generic.tpt` to `lib/load_csv_generic.tpt.template` (git mv). Make these edits:
   - Replace line 42 with:
     ```
     DEFINE SCHEMA PAYLOAD_SCHEMA
     (
   __PAYLOAD_SCHEMA__
     );
     ```
   - Replace every `SCHEMA TGT_SCHEMA` with `SCHEMA PAYLOAD_SCHEMA`.
   - Line 92: `AcceptMissingColumns = 'N'`. Fix the comment on lines 89–90 to match.
   - Lines 187–192 (`STEP Load_Data`): replace the `APPLY $INSERT @TargetTable` line with `__INSERT_STATEMENT__` (F1.2 defines its content).
   - Remove the `TargetTdpId`, `TargetUserName`, `TargetUserPassword`, `TargetWorkingDatabase` job variables from `generate_jobvars.sh` lines 34–38: they existed only for the automatic schema generation.

4. **Always record rejects.** In `generate_jobvars.sh` delete lines 16–24 and set unconditionally:
   ```bash
   RECORD_ERR_FILE="${RUN_DIR}/rejected_rows.txt"
   ```

5. **Point `tbuild` at the generated job.** In `run_tpt.sh` line 7 replace `"${TPT_SCRIPT}"` with `"${JOB_TPT}"`. In `load_csv_generic.sh` line 69, `TPT_SCRIPT` now points to the template; rename the variable to `TPT_TEMPLATE` everywhere (`pre_checks.sh:9` checks its existence). Add `source "${LIB_DIR}/generate_tpt_job.sh"` after the `generate_jobvars.sh` line.

6. **Field-count pre-check.** After generating the schema, compare `PAYLOAD_COL_COUNT` with `HEADER_COLS` (already computed in `pre_checks.sh:136`). If they differ: `die 1 "Column count mismatch: file has ${HEADER_COLS} fields, ${FQ_TABLE} has ${PAYLOAD_COL_COUNT} payload columns"`. This check runs **even with `-C`** (see F1.5).

7. **After the job.** Log the number of lines in `rejected_rows.txt` (0 if absent). If the file is non-empty and the job still returned 0 or 4 (possible when `ErrorLimit > 1`), log a `WARN` with the path.

**Acceptance criteria**
- [ ] `grep -c AcceptMissingColumns lib/load_csv_generic.tpt.template` returns 1 and the value is `'N'`.
- [ ] `grep FROM.TABLE lib/load_csv_generic.tpt.template` returns nothing.
- [ ] After any run, `${RUN_DIR}/job.tpt`, `${RUN_DIR}/columns.txt` and `${RUN_DIR}/jobvars.txt` exist.
- [ ] `grep -c RecordErrorFile ${RUN_DIR}/jobvars.txt` returns 1 and the value is non-empty, for both `HAS_META=0` and `HAS_META=2` tables.
- [ ] On DEV, a 3-column table with 2 audit columns: a file whose second row has only 2 fields → `tbuild` exits non-zero, the row is in `rejected_rows.txt`, the table is empty (replace mode), the loader exits 3.
- [ ] Same table, a correct 3-field file → loads, `rejected_rows.txt` is absent or empty.
- [ ] A table containing a `DECIMAL(38,8)`, a `DATE`, a `TIMESTAMP(6)`, a `BIGINT` and a `VARCHAR(960) CHARACTER SET UNICODE` loads a file with matching values (reuse the 225-column DDL from Phase 3 corpus once available; until then, build a 5-column table by hand on DEV).

**Tests to add**
- `TESTS/unit/test_tpt_job_generation.py::test_schema_width_rules` — runs `generate_tpt_job.sh` through `bash` with a fixture `columns.txt` containing one line per type in the table above; asserts the generated `job.tpt` contains the expected `VARCHAR(w)` for each column and contains `AcceptMissingColumns = 'N'`. (Run the script with `RUN_DIR`, `LIB_DIR`, `FQ_TABLE` exported and `die` defined by sourcing `env_and_helpers.sh`.)
- `TESTS/unit/test_tpt_job_generation.py::test_unsupported_type_fails` — a `columns.txt` line with type `BV` makes the script exit 1 with "Unsupported column type".

**Documentation impact:** `DOCS/03_TPT_LOADER/02_functional_specification.md` section "Zero-Disk Metadata Padding" must be rewritten to describe strict rejection and the generated schema. `DOCS/03_TPT_LOADER/03_technical_manual_and_inventory.md` must list `generate_tpt_job.sh` and the template.

---

### F1.2 — Populate audit columns during the load, not after
Finding: I1, I21  Severity: Critical
Files: `TPT_LOADER/lib/generate_tpt_job.sh`, `TPT_LOADER/lib/update_metadata.sh`, `TPT_LOADER/lib/pre_checks.sh`

**Current behaviour**
- The load writes NULL into the audit columns (padding), then `update_metadata.sh` runs `UPDATE ... WHERE INFA_BATCH_ID IS NULL` over the whole table. In append mode this is a full-table scan on every load, and between the load and the update the rows have NULL audit values.

**Target behaviour**
- When `HAS_META = 2`, the `INSERT` executed by TPT lists the payload columns **and** the two audit columns, and supplies the batch ID and the extract timestamp as literals.
- `update_metadata.sh` is no longer executed in that case.
- When `HAS_META = 0`, the `INSERT` lists payload columns only.
- `HAS_META = 1` is an error (table has exactly one audit column): `die 1`.

**Step 0 — spike (do this first, 1 hour, on DEV).** TPT's Load operator (FastLoad protocol) must accept string literals in the `VALUES` list. Verify with a 2-column table `T_SPIKE (C1 VARCHAR(10), INFA_BATCH_ID VARCHAR(100))`, a 1-column file, and this `APPLY`:
```
APPLY ('INSERT INTO <db>.T_SPIKE ("C1", INFA_BATCH_ID) VALUES (:"C1", ''9001'');')
TO OPERATOR (LOAD_OPERATOR)
SELECT * FROM OPERATOR (FILE_READER);
```
Paste the `tbuild` output into `IMPROVEMENTS/DECISIONS.md` under "D3 — literals in Load operator INSERT".
- If it loads and `SELECT INFA_BATCH_ID FROM T_SPIKE` returns `9001`: implement **Variant A** below.
- If `tbuild` rejects the statement: implement **Variant B**.

**Variant A (preferred) — literals in the INSERT.** In `generate_tpt_job.sh`, after the loop from F1.1:
```bash
# Validate the literals before they are placed inside the TPT script.
[[ "${BATCH_ID}" =~ ^[A-Za-z0-9_-]{1,100}$ ]] || die 1 "BATCH_ID '${BATCH_ID}' contains characters not allowed in INFA_BATCH_ID"
[[ "${META_TS}"  =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}\ [0-9]{2}:[0-9]{2}:[0-9]{2}$ ]] || die 1 "META_TS '${META_TS}' is not YYYY-MM-DD HH:MM:SS"

if [ "${HAS_META}" -eq 2 ]; then
    INSERT_COLS+=", INFA_BATCH_ID, INFA_LAST_REPLICATED"
    INSERT_VALS+=", ''${BATCH_ID}'', ''${META_TS}''"
elif [ "${HAS_META}" -eq 1 ]; then
    die 1 "${FQ_TABLE} has exactly one of INFA_BATCH_ID / INFA_LAST_REPLICATED; it must have both or neither"
fi
INSERT_STATEMENT="APPLY ('INSERT INTO ${FQ_TABLE} (${INSERT_COLS}) VALUES (${INSERT_VALS});')
        TO OPERATOR (@ConsumerOperator [@LoadInstances])
        SELECT * FROM OPERATOR (FILE_READER [@ReaderInstances]);"
```
Then in `load_csv_generic.sh` remove the `source "${LIB_DIR}/update_metadata.sh"` line and delete `update_metadata.sh` (git rm). Also delete the `BatchId` / `Timestamp` job variables from `generate_jobvars.sh` lines 53–55 (they move into the generated INSERT).

**Variant B (fallback) — keep the post-load UPDATE.** Keep `update_metadata.sh` exactly as it is, and build `INSERT_STATEMENT` with payload columns only (no audit columns). Record in `DECISIONS.md` that I21 stays open and that a follow-up item is needed.

**The `INFA_LAST_REPLICATED` value is the extract timestamp (`META_TS`), not the load time.** Do not use `CURRENT_TIMESTAMP`.

**Acceptance criteria**
- [ ] Spike result recorded in `DECISIONS.md`.
- [ ] (Variant A) `grep -c "INFA_BATCH_ID" ${RUN_DIR}/job.tpt` is 1 for a `HAS_META=2` table and 0 for a `HAS_META=0` table.
- [ ] (Variant A) After a replace load of N rows on DEV: `SELECT COUNT(*) FROM <table> WHERE INFA_BATCH_ID = '<batch>' AND INFA_LAST_REPLICATED = TIMESTAMP '<ts>'` returns N, with no `UPDATE` executed (check `DBC.QryLogV` or simply that `update_metadata.sh` no longer exists).
- [ ] A batch ID containing a quote or a semicolon makes the loader exit 1 before `tbuild` is called.
- [ ] A table with exactly one audit column makes the loader exit 1 with the message above.

**Tests to add**
- `TESTS/unit/test_tpt_job_generation.py::test_insert_with_audit_columns` — `HAS_META=2`, asserts the generated INSERT ends with `, INFA_BATCH_ID, INFA_LAST_REPLICATED) VALUES (` … `, ''9001'', ''2026-10-16 10:00:00'');`.
- `TESTS/unit/test_tpt_job_generation.py::test_insert_without_audit_columns` — `HAS_META=0`, asserts no `INFA_` in the INSERT.
- `TESTS/unit/test_tpt_job_generation.py::test_invalid_batch_id_rejected` — `BATCH_ID="90'01"` → exit 1.

**Documentation impact:** same documents as F1.1; remove every mention of "In-Database Audit Backfill".

---

### F1.3 — Measure `has_meta` from the table
Finding: I3  Severity: Critical
Files: `DATA_INGESTION_ORCHESTRATOR/lib/schema_guard.py`, `DATA_INGESTION_ORCHESTRATOR/lib/orchestrator_service.py`, `DATA_INGESTION_ORCHESTRATOR/lib/tpt_worker.py`

**Current behaviour**
- `schema_guard.py:60-91` `get_teradata_table_columns` **removes** the audit columns from the list it returns, so nobody can tell whether they exist.
- `sync_entity_schema_if_drifted` returns the constant `2` as `has_meta` on lines 214, 218 and 236.
- `orchestrator_service.py:781` passes that constant to the worker, which passes `-M 2` to the loader.

**Target behaviour**
- `has_meta` is computed from the real column list: 2 if both audit columns exist, 1 if exactly one, 0 if none.
- The computed value is passed to the loader with `-M`.
- `has_meta == 1` is reported as a schema error (the batch fails before TPT runs).

**Implementation steps**
1. Change `get_teradata_table_columns` to return a tuple `(payload_cols: List[str], has_meta: int)`:
   ```python
   td_cols, audit_present = [], set()
   for r in rows:
       c_name = str(r[0]).strip().upper()
       if c_name in TECHNICAL_AUDIT_COLUMNS:
           audit_present.add(c_name)
       else:
           td_cols.append(c_name)
   return td_cols, len(audit_present)
   ```
   Return `(None, 0)` when the table does not exist. Update the one caller on line 205.
2. In `sync_entity_schema_if_drifted`:
   - After the call: `if has_meta == 1: raise SchemaSyncError(f"[{safe_table}] table has exactly one audit column; expected both or none")`.
   - Return the measured `has_meta` on every return path. A table created by `recreate_staging_table` (which appends both audit columns) returns 2.
3. `orchestrator_service.py:697-701` already unpacks a 4-tuple; remove the `len(res) >= 4` branch and always expect 4 values.
4. No change needed in `tpt_worker.py`; it already passes `-M {has_meta}`.

**Acceptance criteria**
- [ ] A mocked `DBC.ColumnsV` result with `A, B, INFA_BATCH_ID, INFA_LAST_REPLICATED` → `(['A','B'], 2)`.
- [ ] `A, B` → `(['A','B'], 0)`.
- [ ] `A, B, INFA_BATCH_ID` → `SchemaSyncError`.
- [ ] The literal `return ..., 2` no longer appears in `schema_guard.py` except for the created-table path.

**Tests to add**
- `TESTS/unit/test_schema_guard_has_meta.py::test_has_meta_two`, `::test_has_meta_zero`, `::test_has_meta_one_raises` — mock `connection.cursor().fetchall()` to return the three column lists above.
- Extend `TESTS/unit/test_jit_schema_guard_order.py`: assert `run_tpt_loader` is called with `has_meta` equal to the mocked value, not `2`.

**Documentation impact:** `DOCS/02_DATA_INGESTION_ORCHESTRATOR/02_functional_specification.md`, Schema Guard section.

---

### F1.4 — Unlock by exact job name; never report an unlock as a load
Finding: I4  Severity: Critical
Files: `TPT_LOADER/unlock_tpt_table.sh`, `TPT_LOADER/lib/parse_args.sh`, `TPT_LOADER/lib/bteq_check.sh` (where `JOB_NAME` is now set), `DATA_INGESTION_ORCHESTRATOR/lib/tpt_worker.py`, `DATA_INGESTION_ORCHESTRATOR/lib/db_state.py`, `DATA_INGESTION_ORCHESTRATOR/ddl_technical_tables.sql`

**Current behaviour**
- `unlock_tpt_table.sh:68` finds "the last job" with `ls -1td ".../*${TARGET_TABLE}*" | head -1`. `*ERP_MSH_USER*` also matches `TPT_ERP_MSH_USER_AK_…`.
- `tpt_worker.py:143-145`: if the unlock script exits 0 in replace mode, its result replaces the load result, and the entity is marked SUCCESS.

**Target behaviour**
- The worker decides the TPT job name, passes it to the loader (`-j`), and stores it in `BATCH_TASKS.TPT_JOB_NAME` when the task starts.
- The unlock script receives the exact job name (`-j`) and refuses to run in replace mode without it. No globbing.
- An unlock is only ever a *preparation step*. Success is decided **only** by the result of the load command that follows it.

**Implementation steps**
1. **Loader `-j <job_name>`.** In `parse_args.sh` add `j) CLI_JOB_NAME="${OPTARG}" ;;` to both `getopts` loops and the option string (`…CM:j:h`). Default `CLI_JOB_NAME=""`. Where `JOB_NAME` is set (now at the top of `bteq_check.sh`, see F1.1 step 1):
   ```bash
   if [ -n "${CLI_JOB_NAME}" ]; then
       [[ "${CLI_JOB_NAME}" =~ ^[A-Za-z0-9_]{1,120}$ ]] || die 1 "-j job name may contain only letters, digits and underscore"
       JOB_NAME="${CLI_JOB_NAME}"
   else
       JOB_NAME="TPT_${TARGET_TABLE}_${RUN_TS}"
   fi
   ```
   Update the usage block in `load_csv_generic.sh`.
2. **Unlock `-j` mandatory in replace mode.** In `unlock_tpt_table.sh` replace lines 67–75 with:
   ```bash
   [ -n "${CLI_JOB_NAME}" ] || die 1 "-j <job_name> is mandatory in replace mode (the exact TPT job name of the failed load)"
   JOB_NAME="${CLI_JOB_NAME}"
   LAST_JOB_DIR="${WORK_DIR}/${JOB_NAME}"
   [ -d "${LAST_JOB_DIR}" ] || die 1 "Job directory not found: ${LAST_JOB_DIR}"
   JOBVARS="${LAST_JOB_DIR}/jobvars.txt"
   JOB_TPT="${LAST_JOB_DIR}/job.tpt"
   [ -f "${JOBVARS}" ] && [ -f "${JOB_TPT}" ] || die 1 "jobvars.txt or job.tpt missing in ${LAST_JOB_DIR}"
   ```
   Line 84: `${TBUILD_CMD} -f "${JOB_TPT}" -v "${JOBVARS}" -j "${JOB_NAME}"`. Delete lines 90–131 (metadata backfill after resume): with F1.2 Variant A the resumed job writes the audit columns itself; with Variant B the subsequent load re-runs `update_metadata.sh`. Update the usage block.
3. **Worker computes and stores the job name.** In `tpt_worker.py`:
   ```python
   import re, time
   safe_entity = re.sub(r"[^A-Za-z0-9_]", "_", entity)
   tpt_job_name = f"TPT_{safe_entity}_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
   ```
   Add `"-j", tpt_job_name` to `cmd` and `unlock_cmd`. Change the `update_task_start` call (line 44) to `db_state.update_task_start(batch_id, entity, source=source, tpt_job_name=tpt_job_name)`.
4. **Worker never treats an unlock as success.** Replace lines 138–155 with:
   ```python
   if result.returncode not in (0, 4) and _is_table_locked(output_text):   # _is_table_locked from F1.10
       if unlock_cmd:
           logger.warning(f"[{entity}] Table lock (2652) detected. Running unlock then retrying the load once.")
           unlock_res = _run(unlock_cmd, timeout=600)          # _run from F1.10
           if unlock_res.returncode not in (0, 4):
               logger.error(f"[{entity}] Unlock failed (rc={unlock_res.returncode}); not retrying.")
           else:
               result = _run(cmd, timeout=timeout_sec)          # the load, again, in full
       else:
           logger.warning(f"[{entity}] Table lock detected but no unlock script configured.")
   ```
   Nothing else may assign `result`. The `if result.returncode in [0, 4]` block that follows stays as it is.
5. **State table.** In `db_state.py`:
   - `update_task_start(..., tpt_job_name: Optional[str] = None)`: add `TPT_JOB_NAME = ?` to both `UPDATE` statements.
   - In `ddl_technical_tables.sql` add `TPT_JOB_NAME VARCHAR(128) CHARACTER SET UNICODE NOT CASESPECIFIC` to `BATCH_TASKS`, and add the migration line `-- ALTER TABLE <TECH_DB>.BATCH_TASKS ADD TPT_JOB_NAME VARCHAR(128) CHARACTER SET UNICODE NOT CASESPECIFIC;`. Run the `ALTER` on DEV before merging. (Phase 2 F2.11 redesigns this table; keep this column in that redesign.)

**Acceptance criteria**
- [ ] `grep -n 'ls -1td' unlock_tpt_table.sh` returns nothing.
- [ ] `unlock_tpt_table.sh -t X -m replace` without `-j` exits 1 with the message above.
- [ ] In `tpt_worker.py`, the only assignments to `result` are the first `_run(cmd…)` and the retry `_run(cmd…)` after a successful unlock. `result = unlock_res` does not exist.
- [ ] On DEV: start a load, kill `tbuild` during acquisition (leaves the table locked), re-run the orchestrator for the batch → the worker logs "Running unlock then retrying", the retry succeeds, the entity is SUCCESS, and `BATCH_TASKS.TPT_JOB_NAME` holds the job name of the **retry**.
- [ ] Two entities whose names are prefixes of each other (`ERP_MSH_USER`, `ERP_MSH_USER_AK`) in one batch, with the first one locked: unlocking never touches the AK job directory.

**Tests to add**
- `TESTS/unit/test_tpt_worker_unlock.py::test_unlock_success_does_not_mark_entity_success` — mock `_run` so the first load returns rc 12 with "RDBMS error 2652" in output, the unlock returns 0, and the retry returns 12 → function returns `(entity, False)` and `update_task_end` is called with `FAILED`.
- `TESTS/unit/test_tpt_worker_unlock.py::test_unlock_then_retry_success` — same but the retry returns 0 → `(entity, True)`.
- `TESTS/unit/test_tpt_worker_unlock.py::test_job_name_passed_and_stored` — assert `-j` is in both commands and `update_task_start` received the same `tpt_job_name`.
- Extend `TESTS/test_phase01_units.py::test_tpt_worker_args` for the `-j` argument.

**Documentation impact:** `DOCS/03_TPT_LOADER/01_user_how_to_guide.md` ("Table Lock Recovery") and `DOCS/04_SYSTEM_ARCHITECTURE_AND_OPERATIONS/03_production_operations_playbook_and_faq.md`.

---

### F1.5 — The alignment check is never skipped
Finding: I13, Q11  Severity: High
Files: `TPT_LOADER/lib/bteq_check.sh`, `DATA_INGESTION_ORCHESTRATOR/lib/orchestrator_service.py`, `DATA_INGESTION_ORCHESTRATOR/lib/tpt_worker.py`

**Current behaviour**
- The orchestrator always passes `-C` (`orchestrator_service.py:782` `skip_precheck=True`), which skips the whole BTEQ alignment check in the loader.
- `_sync_schema_for_entity` (`orchestrator_service.py:668-674`) returns success without doing anything when Schema Guard is disabled or has no connection manager. In that configuration no component checks that the file matches the table.
- `bteq_check.sh:66-86` compares header names with naive `IFS` splitting.

**Target behaviour**
- `-C` is passed **only** when Schema Guard actually ran in this process and returned `IDENTICAL`, `CREATED` or `ALTERED` for this entity.
- When Schema Guard is disabled, the loader performs the full check.
- Even with `-C`, the loader still performs the cheap checks that F1.1 made unconditional: table exists, payload column count equals file field count.
- The header-name comparison parses the header with Python's `csv` module.

**Implementation steps**
1. `_sync_schema_for_entity`: when the guard is disabled or `conn_mgr is None`, return `(True, has_meta=None, guard_ran=False)`. Change its return type to a 3-tuple `(ok, has_meta, guard_ran)`. When the guard ran, `guard_ran=True`. When `has_meta is None`, the loader must measure it itself (it does: F1.1 made the `HAS_META=` query unconditional).
2. `execute_entity_tasks`: pass `skip_precheck=guard_ran` and `has_meta=has_meta` (may be `None`) to `process_entity_task`. In `tpt_worker.py:82-84`: add `-C` only if `skip_precheck`; add `-M` only if `has_meta is not None`.
3. `bteq_check.sh`: keep the BTEQ call unconditional (F1.1). Keep the `-C` branch only around the **header-name comparison**. Rewrite that comparison to use Python:
   ```bash
   mapfile -t CSV_COLS < <(python3 - "${FILES[0]}" "${DELIMITER}" <<'PY'
   import csv, re, sys
   path, delim = sys.argv[1], sys.argv[2]
   with open(path, newline="", encoding="utf-8-sig", errors="replace") as fh:
       header = next(csv.reader(fh, delimiter=delim))
   for col in header:
       c = re.sub(r"[^A-Za-z0-9_]", "_", col.strip().strip('"').strip("'"))
       c = re.sub(r"_+", "_", c).strip("_").upper()
       if c:
           print(c)
   PY
   )
   ```
   Then compare `CSV_COLS` with `DB_COLS` exactly as today (count, then position by position). Delete the `clean_column_name` Bash function from `env_and_helpers.sh` (no longer used) and the `HEADER_COLS` `awk` computation in `pre_checks.sh:136`; set `HEADER_COLS=${#CSV_COLS[@]}` instead. Note: the header check requires `SKIP_ROWS > 0`; keep that condition.
4. Document in the usage block that `-C` skips only the header-name comparison.

**Acceptance criteria**
- [ ] With `schema_guard.enabled: false` in the orchestrator config, the loader command logged by the worker does **not** contain `-C`.
- [ ] With the guard enabled and `IDENTICAL`, it does.
- [ ] A header `"USER - ID","USER_NAME, EXTRA","EMAIL"` (quoted comma) is parsed as 3 columns by the loader.
- [ ] Loading a 3-field file into a 4-payload-column table with `-C` exits 1 with "Column count mismatch".

**Tests to add**
- `TESTS/unit/test_orchestrator_precheck_flag.py::test_no_skip_when_guard_disabled` — `schema_guard.enabled=false`, mock `run_tpt_loader`, assert `skip_precheck=False`.
- `TESTS/unit/test_orchestrator_precheck_flag.py::test_skip_when_guard_identical`.
- `TESTS/unit/test_tpt_header_parse.py::test_quoted_delimiter_in_header` — runs the Python snippet (extract it into `TPT_LOADER/lib/parse_header.py` so it can be imported) on a fixture header.

---

### F1.6 — Schema evolution without `DROP TABLE`
Finding: I2  Severity: Critical
Files: `DATA_INGESTION_ORCHESTRATOR/lib/schema_guard.py`, `DATA_INGESTION_ORCHESTRATOR/config.json`, `DATA_INGESTION_ORCHESTRATOR/config_template.json`, `BICC_INTAKE_CONTROLLER/config.json`, `BICC_INTAKE_CONTROLLER/config_template.json`, `COMMON/dataloader_core/exceptions.py`

**Current behaviour**
- `schema_guard.py:235` drops and recreates the table on any drift in replace mode when `auto_migrate_ddl` is true — and it is `true` in every shipped config.

**Target behaviour**
- `DROP TABLE` never happens on an existing table. Delete the drop code path.
- `auto_migrate_ddl` is `false` in every shipped config and template.
- When `auto_migrate_ddl` is true:
  - table missing → create it (existing behaviour, keep).
  - the file's columns are the table's payload columns **plus new columns appended at the end** → `ALTER TABLE … ADD <col> <default_type> CHARACTER SET <cs>` for each new column, in order, and the action is `ALTERED`.
  - any other difference (missing column, renamed column, reordered column) → raise `SchemaDriftError` with both lists in the message. The batch fails. A DBA fixes the table.
- When `auto_migrate_ddl` is false: missing table or any drift → `SchemaDriftError`.

**Implementation steps**
1. In `exceptions.py` add `class SchemaDriftError(SchemaSyncError): """Raised when the file columns do not match the table and no safe evolution is possible."""`. Export it in `__init__.py`.
2. In `schema_guard.py`:
   - Delete `recreate_staging_table` lines 145–155 (the DROP). Rename the function `create_staging_table`; it must fail if the table exists (`CREATE TABLE` will raise 3803 — let it propagate).
   - Add:
     ```python
     def alter_add_columns(connection, target_db, target_table, new_columns, default_type, character_set):
         safe_type = validate_column_type(default_type)
         safe_cs = validate_sql_identifier(character_set).upper()
         cur = connection.cursor()
         try:
             for col in new_columns:
                 c = validate_sql_identifier(col)
                 cur.execute(f"ALTER TABLE {target_db}.{target_table} ADD {c} {safe_type} CHARACTER SET {safe_cs} NOT CASESPECIFIC")
                 logger.info(f"[{target_table}] Added column {c}")
         finally:
             cur.close()
     ```
     Note: Teradata appends new columns after the existing ones, i.e. **after** the audit columns. F1.1's schema generation orders payload columns by `ColumnId`, so a table altered this way has payload order `A, B, [INFA…], C`. The generator excludes the audit columns and keeps `A, B, C`, which matches the file. This is why the comparison below must be done on the payload list only.
   - Replace lines 216–236 of `sync_entity_schema_if_drifted` with:
     ```python
     if resolved_cols == td_cols:
         return True, "IDENTICAL", resolved_cols, has_meta
     is_pure_append = (len(resolved_cols) > len(td_cols) and resolved_cols[:len(td_cols)] == td_cols)
     drift_msg = (f"[{safe_table}] Schema drift on {safe_db}.{safe_table}: "
                  f"file columns ({len(resolved_cols)}) = {resolved_cols}; table payload columns ({len(td_cols)}) = {td_cols}")
     if not auto_migrate:
         raise SchemaDriftError(drift_msg + " — auto_migrate_ddl is disabled; a DBA must align the table")
     if not is_pure_append:
         raise SchemaDriftError(drift_msg + " — only appended new columns can be migrated automatically; a DBA must align the table")
     new_cols = resolved_cols[len(td_cols):]
     logger.warning(f"[{safe_table}] Appending {len(new_cols)} new column(s): {new_cols}")
     alter_add_columns(conn, safe_db, safe_table, new_cols, def_type, character_set)
     return False, "ALTERED", resolved_cols, has_meta
     ```
   - The `mode == "append"` prohibition (lines 230–234) is no longer needed because nothing destructive remains; remove it.
3. Set `"auto_migrate_ddl": false` in all four config files. In `orchestrator_service.py:355` change the default of `self.schema_guard_cfg.get("auto_migrate_ddl", True)` to `False`.
4. `orchestrator_service.py:704`: treat `SchemaDriftError` like `SchemaSyncError` (it is a subclass; no change needed, but add a unit test).

**Acceptance criteria**
- [ ] `grep -n "DROP TABLE" schema_guard.py` returns nothing.
- [ ] `git grep '"auto_migrate_ddl": true'` returns nothing.
- [ ] Table `A,B` + file `A,B,C`, auto_migrate true → one `ALTER TABLE … ADD C …`, action `ALTERED`.
- [ ] Table `A,B` + file `A,C` → `SchemaDriftError`, no SQL executed.
- [ ] Table `A,B` + file `B,A` → `SchemaDriftError`.
- [ ] Table `A,B,C` + file `A,B` → `SchemaDriftError`.
- [ ] Missing table, auto_migrate false → `SchemaDriftError`.

**Tests to add**
- `TESTS/unit/test_schema_guard_evolution.py` with one test per acceptance bullet; mock the cursor and record executed SQL.
- Update `TESTS/unit/test_jit_schema_guard_order.py` if it asserts on `RECREATED` (it currently mocks `sync_entity_schema_if_drifted`, so probably not).
- Scenario 08 part B still passes (it tests `auto_migrate_ddl=false` blocking).

**Documentation impact:** all Schema Guard sections; `02_deployment_and_installation_guide.md` must state that `auto_migrate_ddl` is false in production and that the DBA owns structural changes other than appended columns.

---

### F1.7 — Declared row-size guard
Finding: Review §7  Severity: High
Files: `DATA_INGESTION_ORCHESTRATOR/lib/schema_guard.py`, config files

**Current behaviour**
- `generate_staging_ddl` declares every payload column `VARCHAR(4000) CHARACTER SET UNICODE` (8,000 bytes each). A 225-column table declares ~1.8 MB per row. Teradata rejects table definitions whose maximum possible row size exceeds the system limit (error 3933). Nothing checks this before trying.

**Target behaviour**
- Before any `CREATE TABLE` or `ALTER TABLE ADD`, compute the declared maximum row size in bytes. If it exceeds `schema_guard.max_row_bytes` (new config key, default `64000`), raise `SchemaDriftError` with a message that states the computed size, the limit, the column count and the instruction to create the table by hand with proper types.
- **Never shrink column widths to fit.** Column widths are a data contract, not a tuning knob.

**Implementation steps**
1. Add to `schema_guard.py`:
   ```python
   def declared_row_bytes(columns, default_type, character_set, has_meta_cols=2):
       width = int(re.match(r"^VARCHAR\((\d+)\)$", validate_column_type(default_type)).group(1))
       per_char = 2 if character_set.upper() == "UNICODE" else 1
       payload = len(columns) * (width * per_char + 2)          # +2 bytes VARCHAR length indicator
       audit = (4 + 2) + (100 * per_char + 2) if has_meta_cols else 0   # TIMESTAMP(0)=? use 10; VARCHAR(100)
       return payload + 10 + (100 * per_char + 2)
   ```
   (Use `10` bytes for `TIMESTAMP(0)`.) Keep the arithmetic simple and over-estimate rather than under-estimate.
2. Call it in `create_staging_table` and in `alter_add_columns` (for the *resulting* column list). On exceeding the limit:
   `raise SchemaDriftError(f"[{table}] Declared row size {size} bytes exceeds max_row_bytes={limit} for {n} columns of {default_type} {cs}. Create the table manually with appropriate column types, or raise schema_guard.max_row_bytes if the system supports large rows.")`
3. Read `max_row_bytes` from `schema_guard` config, default 64000. Add the key to the two orchestrator config files with value `64000` and a comment-equivalent entry in the deployment guide.

**Acceptance criteria**
- [ ] 7 columns `VARCHAR(4000) UNICODE` → allowed (≈56 KB). 8 columns → `SchemaDriftError`.
- [ ] Message contains the computed size and the limit.
- [ ] No code path changes `default_type` based on the column count.

**Tests to add**
- `TESTS/unit/test_schema_guard_row_size.py::test_within_limit`, `::test_exceeds_limit`, `::test_alter_add_exceeds_limit`.

**Documentation impact:** deployment guide (new key), Schema Guard functional spec (explicit statement that wide PVOs need hand-written DDL).

---

### F1.8 — Strict mapping validation and anchored signatures
Finding: I14, I7 (matching part)  Severity: High
Files: `COMMON/dataloader_core/mapping.py`, `CONFIG/entity_mapping.csv`

**Current behaviour**
- `mapping.py:160-162` turns any `LOAD_MODE` other than `replace`/`append` into `replace`. Lines 170–178 do the same for `HEADER_MODE`. Lines 164–168 turn a non-numeric `SKIP_ROWS` into 1.
- `mapping.py:249` matches `rule.signature in fn_lower` — a substring anywhere in the filename.

**Target behaviour**
- Any invalid value in `entity_mapping.csv` raises `ConfigurationError` naming the row, the column and the value, when the file is loaded. The process stops before any file is touched.
- A signature matches only when it is a complete token of the filename: it must be immediately preceded by `_` or the start of the name, and immediately followed by `-batch` or `.`.
- Duplicate `(SOURCE, FILE_SIGNATURE, INNER_EXTENSION)` rows are a `ConfigurationError`.

**Implementation steps**
1. In `load_rules`, replace the three coercions:
   ```python
   if lmode not in ("replace", "append"):
       raise ConfigurationError(f"entity_mapping.csv row {reader.line_num}: LOAD_MODE '{lmode}' is invalid (replace|append)")
   ```
   Same pattern for `HEADER_MODE` (`first_chunk_only|every_file|none`) and `SKIP_ROWS` (non-negative integer). Import `ConfigurationError` from `.exceptions`.
2. Add a duplicate check after the loop: build a set of `(source.upper(), signature, inner_extension)`; raise on a repeat.
3. Replace the substring test in both passes of `match_file`:
   ```python
   def _signature_matches(filename_lower: str, signature: str) -> bool:
       pattern = r"(?:^|_)" + re.escape(signature) + r"(?=-batch|\.)"
       return re.search(pattern, filename_lower) is not None
   ```
   Use it instead of `rule.signature in fn_lower`. Real BICC names look like `file_<am>_<am>_<pvo>-batch<id>-<ts>.csv`, so the PVO name is always preceded by `_` and followed by `-batch`.
4. `inspect_file_inner_extension` returns `.zip` for an unreadable zip (line 82 only logs a warning). Make it raise `BatchValidationError` instead: a corrupt archive must stop the batch, not fall into the pass-2 fallback.

**Acceptance criteria**
- [ ] `LOAD_MODE=apend` → `ConfigurationError` mentioning `apend`.
- [ ] `file_x_userpvo-batch1-20260101_000000.csv` matches signature `userpvo`.
- [ ] `file_x_supplieruserpvo-batch1-20260101_000000.csv` does **not** match `userpvo`.
- [ ] `file_x_userpvo.csv` matches; `file_x_userpvo_extra-batch1-.csv` does not.
- [ ] A zip that is not a zip → `BatchValidationError`.
- [ ] The shipped `CONFIG/entity_mapping.csv` still loads without error.

**Tests to add**
- `TESTS/unit/test_core_mapping.py::test_invalid_load_mode_raises`, `::test_invalid_header_mode_raises`, `::test_invalid_skip_rows_raises`, `::test_duplicate_rule_raises`, `::test_signature_is_anchored` (the four filename cases above), `::test_corrupt_zip_raises`.
- Review the existing tests in that file: any that relied on substring matching must be updated to anchored filenames.

**Documentation impact:** `DOCS/00_COMMON_CORE_SDK/02_onboarding_new_data_sources_guide.md` — the signature rules.

---

### F1.9 — Explicit file lists and deterministic header handling
Finding: I7 (wildcard part), I9 (part), §6.2  Severity: High
Files: `TPT_LOADER/lib/parse_args.sh`, `TPT_LOADER/lib/pre_checks.sh`, `TPT_LOADER/lib/generate_jobvars.sh`, `TPT_LOADER/lib/load_csv_generic.tpt.template`

**Current behaviour**
- The loader receives either one file or a wildcard (`-f`). The orchestrator passes `*{signature}*{ext}`, which TPT resolves over the whole directory.
- Header handling for multi-file loads relies on in-place stripping (Phase 2 removes it).

**Target behaviour**
- New option `-L <listfile>`: a text file with one absolute file path per line, in load order. Mutually exclusive with `-f`. The loader passes it to TPT with `FileList = 'Y'` and `FileName = <listfile>`. TPT reads exactly those files, in that order.
- `-f` remains for standalone use.
- Header modes map to TPT attributes as follows and nothing else:

  | Mode | `SkipRows` | `SkipRowsEveryFile` | `ReaderInstances` |
  |---|---|---|---|
  | `first_chunk_only` | `<skip_rows>` | `N` | forced to **1** (so "first file" is deterministic) |
  | `every_file` | `<skip_rows>` | `Y` | as requested |
  | `none` | `0` | `N` | as requested |

- The default `HEADER_MODE` for BICC rows in `entity_mapping.csv` depends on **decision D2**: if every split file has a header → `every_file`; otherwise `first_chunk_only`. Set it in the CSV once D2 is recorded.

**Implementation steps**
1. `parse_args.sh`: add `L) FILE_LIST="${OPTARG}" ;;` (option string `…L:`). Default `FILE_LIST=""`. In `pre_checks.sh`, replace the "Expand the file spec" block (lines 26–38) with:
   ```bash
   if [ -n "${FILE_LIST}" ] && [ -n "${FILE_SPEC}" ]; then die 1 "-f and -L are mutually exclusive"; fi
   if [ -n "${FILE_LIST}" ]; then
       [ -s "${FILE_LIST}" ] || die 1 "File list not found or empty: ${FILE_LIST}"
       mapfile -t FILES < <(tr -d '\r' < "${FILE_LIST}")
       for f in "${FILES[@]}"; do
           [[ "${f}" = /* ]] || die 1 "File list entries must be absolute paths: ${f}"
           [ -s "${f}" ] || die 1 "File is empty or unreadable: ${f}"
       done
       USE_FILE_LIST="Y"
   else
       [ -n "${FILE_SPEC}" ] || { usage; die 1 "-f <file|pattern> or -L <listfile> is mandatory"; }
       # existing glob expansion code, unchanged
       USE_FILE_LIST="N"
   fi
   ```
   Archive decompression (lines 40–89) must be **removed** from the loader: the orchestrator extracts archives (Phase 2 F2.4) and standalone users pass extracted files. Delete the block and the `trap`.
2. `generate_jobvars.sh`: when `USE_FILE_LIST=Y` write `FileList = 'Y'` and `FileName = '<path of the list file>'`, and `DirectoryPath = ''`. Otherwise write `FileList = 'N'` and the current `DirectoryPath`/`FileName`. Add `VARCHAR FileList = @FileList,` to the `FILE_READER` operator in the template.
3. Header mode: the orchestrator already translates header modes into `-S` and `-Y` (`orchestrator_service.py:180-217`). After Phase 2 F2.3 removes the stripping branch, those values follow the table above. In the loader, force `READER_INSTANCES=1` when `SKIP_ROWS_EVERY_FILE=N` and `SKIP_ROWS > 0` and more than one file is loaded, with a `log INFO` explaining why.
4. The `MultipleReaders` rule in `pre_checks.sh:103-109` stays: `Y` only for a single file with `READER_INSTANCES > 1`.

**Acceptance criteria**
- [ ] `-L` with 3 files loads exactly those 3 files even if a 4th matching file sits in the same directory (verify on DEV: put a stray `file_x_userpvo-batch999-.csv` beside the listed files; its rows must not be in the table).
- [ ] `-L` with a relative path in the list → exit 1.
- [ ] `-f` and `-L` together → exit 1.
- [ ] `first_chunk_only` with 3 files: `jobvars.txt` has `SkipRows = 1`, `SkipRowsEveryFile = 'N'`, `ReaderInstances = 1`; the loaded row count equals total data rows (header of file 1 skipped, files 2 and 3 fully loaded).
- [ ] `every_file` with 3 files, each with a header: loaded row count equals total minus 3.
- [ ] No `unzip` or `gzip` call remains in `pre_checks.sh`.

**Tests to add**
- `TESTS/unit/test_tpt_file_list.py::test_mutually_exclusive`, `::test_relative_path_rejected`, `::test_jobvars_filelist_mode` (run `parse_args.sh` + `pre_checks.sh` + `generate_jobvars.sh` via `bash -c` with `tbuild`/`bteq` stubbed on `PATH`, following the pattern already used by the loader's own dry-run tests if present; otherwise create `TESTS/unit/helpers/stub_bin/` with stub `tbuild` and `bteq` scripts).

**Documentation impact:** TPT loader user guide (new `-L` option, removed archive handling), onboarding guide (header-mode table).

---

### F1.10 — Process-group termination and precise lock detection
Finding: I11  Severity: High
Files: `DATA_INGESTION_ORCHESTRATOR/lib/tpt_worker.py`

**Current behaviour**
- `subprocess.run(cmd, capture_output=True, timeout=…)`: on timeout only the Bash wrapper is killed; `tbuild` keeps running, keeps the table lock, and the utility slot is released anyway.
- The lock test is `"2652" in stdout_str` — any number 2652 in the output triggers it.
- All output is held in memory.

**Target behaviour**
- The loader runs in its own session; on timeout the whole process group gets `SIGTERM`, then `SIGKILL` after 30 s.
- Output is streamed to `<work_dir>/<job_name>.out` (not kept in memory); the last 50 lines are stored in `BATCH_TASKS.ERROR_MESSAGE` on failure.
- Lock detection uses a regex on error lines only.

**Implementation steps**
1. Add to `tpt_worker.py`:
   ```python
   import signal, subprocess, re
   from dataclasses import dataclass

   _LOCK_RE = re.compile(r"\b(?:RDBMS error|Error)\s+2652\b|\bis being Loaded\b|\bis being MLoaded\b", re.IGNORECASE)

   @dataclass
   class RunResult:
       returncode: int
       output_path: str
       def tail(self, n=50):
           try:
               with open(self.output_path, "r", encoding="utf-8", errors="replace") as fh:
                   return "".join(fh.readlines()[-n:])
           except OSError:
               return ""

   def _is_table_locked(text: str) -> bool:
       return _LOCK_RE.search(text) is not None

   def _run(cmd, env, timeout, output_path, grace_seconds=30) -> RunResult:
       with open(output_path, "a", encoding="utf-8") as out:
           proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, env=env, start_new_session=True)
           try:
               rc = proc.wait(timeout=timeout)
           except subprocess.TimeoutExpired:
               logger.error(f"Timeout after {timeout}s; terminating process group {proc.pid}")
               os.killpg(proc.pid, signal.SIGTERM)
               try:
                   rc = proc.wait(timeout=grace_seconds)
               except subprocess.TimeoutExpired:
                   os.killpg(proc.pid, signal.SIGKILL)
                   rc = proc.wait()
               rc = -1 if rc == 0 else rc       # a timeout is never a success
       return RunResult(rc, output_path)
   ```
2. Replace every `subprocess.run(...)` in `run_tpt_loader` with `_run(...)`. `output_path = os.path.join(work_dir, f"{tpt_job_name}.out")` (same file for the load, the unlock and the retry — they append).
3. Replace `("2652" in stdout_str …)` with `_is_table_locked(result.tail(500))`.
4. On failure, `err_msg = result.tail(50)`.
5. Keep the slot-governor `with` block around the whole sequence (it already is, in `process_entity_task`). Because the process group is dead when `_run` returns, the slot is released only after `tbuild` is gone.

**Acceptance criteria**
- [ ] A loader stub that `exec`s `sleep 600` with `timeout_seconds=5`: `run_tpt_loader` returns within ~40 s, no `sleep` process remains (`pgrep -f "sleep 600"` is empty), `update_task_end` called with `FAILED` and a message containing "Timeout".
- [ ] Output containing "Rows sent: 2652" is **not** detected as a lock; "RDBMS error 2652" is.
- [ ] `capture_output` no longer appears in `tpt_worker.py`.

**Tests to add**
- `TESTS/unit/test_tpt_worker_process_group.py::test_timeout_kills_group` (uses a real `bash -c 'sleep 600 & wait'` stub; skip on Windows).
- `TESTS/unit/test_tpt_worker_process_group.py::test_lock_regex_positive_negative`.

---

### F1.11 — No fabricated batch metadata in the loader
Finding: I15 (loader part)  Severity: High
Files: `TPT_LOADER/lib/pre_checks.sh`, `TPT_LOADER/unlock_tpt_table.sh`

**Current behaviour**
- `pre_checks.sh:126-133`: when no batch ID or timestamp is given or extracted, the loader invents them (`date +%s`, `date +…`). The same fallback exists in `unlock_tpt_table.sh:107-112`.

**Target behaviour**
- When the target table has audit columns (`HAS_META = 2`), both `-B` and `-T` (or the `-b`/`-c` extraction patterns producing non-empty values) are mandatory. Missing → `die 1`.
- When `HAS_META = 0`, `-B`/`-T` are ignored with a `log INFO`.
- No `date`-based fallback anywhere.

**Implementation steps**
1. Move the metadata block (`pre_checks.sh:111-133`) **after** the BTEQ call (it needs `HAS_META`). Replace lines 126–133 with:
   ```bash
   if [ "${HAS_META}" -eq 2 ]; then
       [ -n "${BATCH_ID}" ] || die 1 "${FQ_TABLE} has audit columns: -B <batch_id> (or -b pattern) is mandatory"
       [ -n "${META_TS}"  ] || die 1 "${FQ_TABLE} has audit columns: -T <timestamp> (or -c pattern) is mandatory"
   fi
   ```
2. Delete lines 107–112 of `unlock_tpt_table.sh` (they are removed anyway by F1.4 step 2).

**Acceptance criteria**
- [ ] `grep -n "date '+%s'" pre_checks.sh unlock_tpt_table.sh` returns nothing.
- [ ] Loader on a `HAS_META=2` table without `-B` → exit 1 before `tbuild`.

**Tests to add**
- `TESTS/unit/test_tpt_file_list.py::test_missing_batch_id_with_audit_columns_fails` (same stub harness as F1.9).

---

### F1.12 — Environment construction for the loader
Finding: Q12  Severity: Low
Files: `COMMON/dataloader_core/db.py`

**Current behaviour**
- `build_tpt_environment` lines 119–127 set `SID_ADM_USER` and `USER` to the already-prefixed user. `USER` is the OS login variable and should not be changed.

**Target behaviour**
- The function sets one dedicated variable `TD_LOGON_USER` with the fully-qualified user and leaves `USER` and `SID_ADM_USER` untouched.
- `tpt_worker.py` passes `-u tpt_env["TD_LOGON_USER"]`.

**Implementation steps**
1. Replace lines 119–127 with `tpt_env["TD_LOGON_USER"] = str(user)` (after computing `user` as today).
2. `tpt_worker.py:99-100` and `120-121`: use `TD_LOGON_USER`.
3. In `parse_args.sh` line 9, default `TD_USER="${TD_LOGON_USER:-${TDENV}${SID_ADM_USER}}"`.

**Acceptance criteria**
- [ ] `build_tpt_environment({"user": "DEV0X"})` returns an env where `USER` equals the caller's `USER` and `TD_LOGON_USER == "DEV0X"`.

**Tests to add**
- `TESTS/unit/test_core_db_pool.py::test_build_tpt_environment_does_not_touch_USER`.

---

## Phase 1 exit checklist (technical lead)

- [ ] All 12 items merged with their tests.
- [ ] On DEV, the Phase 3 realistic corpus (or, until it exists, a hand-built 225-column typed table) loads end-to-end through the orchestrator with `rejected_rows.txt` empty, audit columns populated, and `BATCH_TASKS.TPT_JOB_NAME` filled.
- [ ] On DEV, a deliberately truncated row is rejected and visible in `rejected_rows.txt`.
- [ ] `DECISIONS.md` contains D2 and D3.
- [ ] Documentation listed under "Documentation impact" updated.
