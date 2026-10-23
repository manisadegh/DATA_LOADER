# DATA_LOADER — Remediation Programme

**Status:** Approved for implementation
**Date:** 23 October 2026
**Inputs:** `DATA_LOADER_REVIEW.md` (external review) and `DATA_LOADER_REVIEW_RESPONSE.md` (engineering response)

This directory contains the technical specifications the development team must implement. Nothing in the code base has been changed yet. Every change described here must be implemented exactly as written. If a specification is unclear, ambiguous or seems wrong, **stop and ask the technical lead** before writing code. Do not improvise.

---

## 1. The three phases

The work is split by **component layer**, not by priority. Each phase is a coherent body of work with its own tests and its own acceptance review.

| Phase | Document | Layer | What it covers |
|---|---|---|---|
| **1** | [`PHASE_1_TPT_LOAD_PATH_AND_SCHEMA_GOVERNANCE.md`](PHASE_1_TPT_LOAD_PATH_AND_SCHEMA_GOVERNANCE.md) | `TPT_LOADER`, `tpt_worker.py`, `schema_guard.py`, `mapping.py` | Everything between "a validated file is ready" and "rows are in Teradata": strict row rejection, audit columns, schema evolution without DROP, measured `has_meta`, exact unlock, process-group kill, strict configuration validation, row-size guard, no fabricated metadata. |
| **2** | [`PHASE_2_ORCHESTRATION_LIFECYCLE_AND_RECOVERY.md`](PHASE_2_ORCHESTRATION_LIFECYCLE_AND_RECOVERY.md) | `dataloader_core/capsule.py`, `intake/`, `orchestrator_service.py`, `sensor.py`, `db_state.py`, `post_tasks.py` | Everything that moves batches between zones and tracks their state: per-batch loading directories, explicit file lists, atomic archive, no payload mutation, safe extraction, duplicate handling, checksum verification, recovery ordering, state reconciliation, post-task scoping, state-table redesign. |
| **3** | [`PHASE_3_SECURITY_TESTS_PACKAGING_AND_REFACTORING.md`](PHASE_3_SECURITY_TESTS_PACKAGING_AND_REFACTORING.md) | Repository, `TESTS/`, packaging, documentation | Repository privacy and scrubbing, realistic test corpus, fault-injection scenarios, value-level database assertions, Python packaging, dead-code removal, plugin wiring, splitting `orchestrator_service.py`, documentation consolidation. |

**One exception to "not by priority":** section S of Phase 3 (make the repositories private, remove the test-output archive) must be done **today**, before any other work. It takes less than one hour. The technical lead owns it.

### Dependencies between phases

- Phase 2 item **F2.2** (per-batch loading directories and explicit file lists) changes how the TPT loader receives its input. Phase 1 item **F1.9** (`-L` file-list option) must be finished first.
- Phase 2 item **F2.11** (state-table redesign) adds the `TPT_JOB_NAME` column that Phase 1 item **F1.4** (exact unlock) writes. Implement **F2.11 step 1** (the DDL migration) together with F1.4.
- Phase 3 tests exercise Phase 1 and Phase 2 behaviour. Write each phase's own unit tests as part of that phase (every item lists them); the Phase 3 corpus and scenarios are the end-to-end layer on top.

---

## 2. How each item is written

Every item in the phase documents follows the same template:

```
### F<phase>.<n> — <Title>
Finding: <IDs from the review>            Severity: <Critical|High|Medium|Low>
Files: <exact paths>
Current behaviour: <what the code does today, with line numbers>
Target behaviour:  <what the code must do after the change>
Implementation steps: <numbered, exact>
Acceptance criteria: <checkable statements, each must be true>
Tests to add: <exact test names and what they assert>
```

Line numbers refer to the code **as of commit `ae11519`**. If the file has changed since, find the same code by its content.

Code blocks in the specifications are **normative**: implement them as written unless the block is labelled `Illustration`. Variable, function, option and column names given in the specifications are mandatory. Other teams and tests depend on them.

---

## 3. Working rules for the development team

### 3.1 Branching and commits
- One branch per item: `fix/F1.3-measure-has-meta`, `fix/F2.6-atomic-archive`, etc. The item ID is mandatory in the branch name.
- One pull request per item. Do not combine items.
- Commit message format: `<type>(<scope>): <summary> [F<phase>.<n>]`, e.g. `fix(schema_guard): measure has_meta from DBC.ColumnsV [F1.3]`.
- Never push directly to `main`. Every PR needs one review from the technical lead.

### 3.2 Definition of done — all boxes must be ticked
- [ ] Every step in the item's **Implementation steps** is done.
- [ ] Every statement in **Acceptance criteria** has been checked by hand and is true.
- [ ] Every test listed in **Tests to add** exists, has the exact name given, and passes.
- [ ] The whole existing test suite still passes (`python3 -m unittest discover -s TESTS/unit -t TESTS` and `python3 TESTS/test_phase01_units.py`).
- [ ] `python3 -m pyflakes PROCESSING_TOOLS TESTS` reports no new findings on the files you touched.
- [ ] `shellcheck` reports no new findings on any `.sh` file you touched (install with `apt install shellcheck` or `pip install shellcheck-py`).
- [ ] Documentation that describes the changed behaviour is updated in the same PR (see the "Documentation impact" line on each item).
- [ ] The PR description lists the item ID, the finding IDs, and a copy of the acceptance criteria with each one ticked.

### 3.3 Things you must never do
- Never change behaviour that is not covered by an item. If you notice something else that looks wrong, write it down and tell the technical lead. Do not fix it.
- Never delete or weaken an existing test to make it pass. If a test fails because the specification changes behaviour, the item's **Tests to add** section tells you which assertions to change.
- Never commit `config.json` changes other than the ones specified.
- Never commit anything under `DATA/`, `LOGS/` or `TESTS/OUTPUTS/`.
- Never put a password, a hostname, a service-account name or an absolute production path in code, tests, documentation or commit messages. Use the placeholders `<TDPID>`, `<TDENV>`, `<SERVICE_ACCOUNT>`, `<DATA_LOADER_HOME>`.

### 3.4 Environments
- All unit tests run with mocked Teradata (see existing tests for the pattern).
- Scenario tests run on the DEV Unix host against the DEV Teradata system. Never run them against anything else.
- When an item says "verify on DEV", that means running the exact command given, on DEV, and pasting the output into the PR.

---

## 4. Open decisions (technical lead)

Two facts about Oracle BICC extracts are **not known for certain** and affect Phase 1 and Phase 2. The technical lead must settle them with real files before the dependent items start. Each item below says what to do in either case.

| # | Question | How to settle it | Affects |
|---|---|---|---|
| D1 | What fields does a real BICC `MANIFEST-*.MF` line contain? One of: `filename;ucm_doc_id` or `filename;ucm_doc_id;md5`. | Open one real manifest from the DROP_ZONE on DEV. Count the `;`-separated fields on a data line. If the last field is 32 hexadecimal characters, it is an MD5. | F2.7 |
| D2 | When BICC splits a large extract into several files, does **every** file start with a header row, or only the first? | Find one real multi-part extract on DEV. Run `head -1` on each part. | F1.9, F2.3 |

Record the answers in `IMPROVEMENTS/DECISIONS.md` (create the file) with the date and the files examined. Keep the files themselves out of git.

---

## 5. Glossary

| Term | Meaning |
|---|---|
| Capsule | A `BATCH_<TS>_<ID>/` directory containing one batch: payload files, `MANIFEST_*.MF`, `batch_descriptor.json`, `RAW/`. |
| Entity | One target staging table and the files that feed it. |
| Audit columns | `INFA_BATCH_ID` and `INFA_LAST_REPLICATED`, the two technical columns appended to staging tables. |
| `has_meta` | 2 if a table has both audit columns, 1 if it has exactly one, 0 if none. |
| Replace / append | `replace` empties the table then loads with the TPT Load operator (FastLoad protocol). `append` keeps rows and loads with the Update operator (MultiLoad protocol). |
| FAIL_STOP | On any failure, stop processing the queue so that no newer batch is loaded ahead of a failed older batch. |
| In-flight batch | A batch that was moved into `LOADING_ZONE` but did not reach `ARCHIVE_ZONE`. |
| FIFO | Oldest extract timestamp first. |
